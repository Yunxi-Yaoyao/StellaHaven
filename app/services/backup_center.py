"""Durable single-slot jobs and PG-fenced node-local backup execution."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import errno
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import uuid
from zoneinfo import ZoneInfo
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.schemas.backups import Config, ConfigPatch
from app.services.backup_storage import BackupDirectory, Busy, directory_fd, ensure_private_directory
from app.services.backup_projection import export_settings, restore_settings, settings_supported, UnsupportedSettingsMode
from app.services.backup_postgres import export_all
from app.services.backup_archive import InvalidArchive
from app.backup_diagnostics import BackupFailure, REASON_CODES, STAGES

logger = logging.getLogger(__name__)

KEY = 'backup_center_v1'
STATE_LOCK = 1937006962
EXEC_LOCK = 1937006963


class Conflict(ValueError):
    pass


def next_run(config, now):
    if not config['enabled']:
        return None
    zone = ZoneInfo(config['timezone'])
    local = now.astimezone(zone)
    hour, minute = map(int, config['time'].split(':'))
    for day in range(9):
        date = local.date() + timedelta(days=day)
        if config['frequency'] == 'weekly' and date.weekday() != config['weekday']:
            continue
        candidate = datetime(date.year, date.month, date.day, hour, minute, tzinfo=zone)
        utc = candidate.astimezone(timezone.utc)
        if utc > now and utc.astimezone(zone).replace(tzinfo=None) == candidate.replace(tzinfo=None):
            return utc.isoformat()
    return None


def failure_reason(exc):
    if isinstance(exc, (InvalidArchive, BackupFailure)):
        return exc.reason_code if exc.reason_code in REASON_CODES else 'operation_failed'
    if isinstance(exc, UnsupportedSettingsMode):
        return 'settings_mode_unsupported'
    if isinstance(exc, subprocess.TimeoutExpired):
        return 'operation_timeout'
    if isinstance(exc, SQLAlchemyError):
        return 'database_unavailable'
    if isinstance(exc, ValidationError):
        return 'configuration_invalid'
    if isinstance(exc, OSError):
        return {errno.ENOSPC: 'storage_full', errno.EACCES: 'storage_permission_denied',
                errno.EROFS: 'storage_read_only'}.get(exc.errno, 'storage_unavailable')
    return 'operation_failed'


def safe_error(exc):
    if isinstance(exc, UnsupportedSettingsMode):
        return '备份/原子设置恢复需要 PostgreSQL blob 与 shared state 模式；旧文件模式尚不支持，不会生成不完整成功包'
    if isinstance(exc, OSError):
        return {errno.ENOSPC: '空间不足，旧备份保留', errno.EACCES: '目录权限不足，旧备份保留',
                errno.EROFS: '目录只读，旧备份保留'}.get(exc.errno, '目录或资源不可用，旧备份保留')
    return '备份操作未完成，旧备份保留；请提供任务编号、失败阶段和原因代码以定位'


def default_directory_capacity(path):
    """Read-only no-follow probe of the nearest parent; never creates files.

    This is an admission hint, not a reserved directory. Creation still checks
    the primary/lock and real filesystem permissions at execution time.
    """
    candidate = Path(path)
    while candidate != Path('/'):
        try:
            with directory_fd(candidate) as fd:
                info = os.fstatvfs(fd)
                if info.f_flag & os.ST_RDONLY or not os.access(
                        f'/proc/self/fd/{fd}', os.W_OK | os.X_OK, effective_ids=True):
                    raise PermissionError(errno.EACCES, 'default parent not writable')
                return info.f_bavail * info.f_frsize
        except FileNotFoundError:
            candidate = candidate.parent
    raise ValueError('no safe owned default parent')


class BackupCenter:
    def __init__(self, engine, data_root, *, key, node=None, clock=None, default_directory=None):
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.engine = engine
        self.data_root = Path(data_root)
        # Persistent output is independently provisioned; never reinterpret the
        # resource input root merely to escape a read-only deployment bundle.
        if default_directory is not None and not os.fspath(default_directory):
            raise ValueError('operator default directory must be an absolute nonempty path')
        self.default_directory = (Path(Config(directory=os.fspath(default_directory)).directory)
                                  if default_directory is not None else self.data_root / 'backups')
        self.key = key
        self.node = node or socket.gethostname()
        self.worker = None
        self.stop_event = threading.Event()
        self.timer = None

    def _read(self, conn):
        value = conn.execute(text('SELECT value FROM app_config WHERE key=:key'), {'key': KEY}).scalar_one_or_none()
        return json.loads(value) if value else {'config': Config().model_dump(), 'job': None, 'last_slot': None}

    def _write(self, conn, state):
        conn.execute(text('INSERT INTO app_config (key,value) VALUES (:key,:value) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value'),
                     {'key': KEY, 'value': json.dumps(state)})

    def _edit(self, conn):
        conn.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': STATE_LOCK})
        return self._read(conn)

    def _primary(self, conn):
        if self.engine.dialect.name != 'postgresql':
            raise RuntimeError('backup execution requires PostgreSQL')
        if os.getenv('STELLA_HA_MODE') == 'primary-only':
            import httpx
            with httpx.Client(trust_env=False, timeout=1) as client:
                response = client.get(os.getenv('STELLA_PATRONI_URL', 'http://127.0.0.1:8008').rstrip('/') + '/primary')
            if response.status_code != 200 or response.json().get('role') not in ('primary', 'master'):
                raise BackupFailure('not_writable_primary')
        if conn.execute(text("SELECT NOT pg_is_in_recovery() AND current_setting('transaction_read_only')='off'" )).scalar_one() is not True:
            raise BackupFailure('not_writable_primary')

    def directory(self, config):
        return Path(config['directory']) if config['directory'] else self.default_directory

    def store(self, config=None, fence=lambda: None):
        if config is None:
            with self.engine.connect() as conn:
                config = self._read(conn)['config']
        return BackupDirectory(self.directory(config), self.key, fence)

    def status(self, now=None):
        now = now or self.clock()
        with self.engine.connect() as conn:
            state = self._read(conn)
        config = Config.model_validate(state['config']).model_dump()
        storage = dict(node=self.node, available=False, free_bytes=None, error=None, can_initialize_default=False)
        records = []
        try:
            with directory_fd(self.directory(config)) as fd:
                info = os.fstatvfs(fd)
                storage.update(available=True, free_bytes=info.f_bavail * info.f_frsize)
            records = self.store(config).records()
        except FileNotFoundError:
            if not config['directory']:
                try:
                    capacity = default_directory_capacity(self.directory(config))
                    storage.update(can_initialize_default=True, free_bytes=capacity,
                                   error='默认目录尚未创建；仅在手动或已启用的计划执行时创建')
                except (OSError, ValueError):
                    pass
            if not storage['can_initialize_default']:
                storage['error'] = '当前执行节点的目录不存在或无法创建，请指定可写目录'
        except (OSError, ValueError, KeyError, TypeError):
            storage['available'] = False
            storage['error'] = '当前执行节点的目录不可达或归属校验失败；不会假定其他节点本地盘共享'
        return dict(config=config, records=records, job=state.get('job'), storage=storage,
                    next_run=next_run(config, now), capabilities={'settings_restore': settings_supported(), 'full_restore': 'maintenance_cli'})

    def patch(self, fields):
        patch = ConfigPatch.model_validate(fields)
        changes = patch.model_dump(exclude_unset=True, exclude={'expected_revision'})
        if any(v is None for v in changes.values()):
            raise ValueError('null configuration field')
        with self.engine.begin() as conn:
            self._primary(conn)
            if not conn.execute(text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': EXEC_LOCK}).scalar_one():
                raise Busy('backup operation busy')
            state = self._edit(conn)
            if state['config']['revision'] != patch.expected_revision:
                raise Conflict('configuration revision changed')
            merged = Config.model_validate(state['config'] | changes).model_dump()
            if merged['directory']:
                with directory_fd(self.directory(merged)) as fd:
                    if 'directory' in changes:
                        name = '.stella-probe-' + uuid.uuid4().hex + '.tmp'
                        self._primary(conn)
                        probe = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                        try:
                            os.write(probe, b'backup-directory-probe')
                            os.fsync(probe)
                        finally:
                            os.close(probe)
                            os.unlink(name, dir_fd=fd)
            merged['revision'] += 1
            state['config'] = merged
            self._write(conn, state)
        return merged

    def _execution_fence(self, conn):
        self._primary(conn)
        held = conn.execute(text('SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype=\'advisory\' AND pid=pg_backend_pid() AND objid=:key AND granted)'), {'key': EXEC_LOCK}).scalar_one()
        if not held:
            raise BackupFailure('execution_lock_lost')
        conn.commit()

    def _fence(self, conn, identity):
        self._execution_fence(conn)
        state = self._read(conn)
        if not state.get('job') or state['job']['id'] != identity:
            raise BackupFailure('job_ownership_lost')
        conn.commit()

    def _job(self, conn, identity, **fields):
        self._fence(conn, identity)
        state = self._edit(conn)
        if state['job']['id'] != identity:
            raise BackupFailure('job_ownership_lost')
        if state['job']['state'] in ('succeeded', 'failed', 'interrupted'):
            return  # never rewrite a persisted terminal or manufacture a new one
        state['job'].update(fields)
        self._write(conn, state)
        terminal = state['job']['state'] in ('succeeded', 'failed')
        if terminal and state['job']['kind'] == 'backup':
            from app.services.result_notifications import stage_result
            job = state['job']
            ok = job['state'] == 'succeeded'
            # Only static text and the closed reason-code vocabulary, never
            # exception strings, SQL, archive names or arbitrary stored errors.
            reason = job.get('reason_code')
            reason = reason if reason in REASON_CODES else 'operation_failed'
            scope = '所有设置' if job['scope'] == 'settings' else '全部备份'
            stage_result(conn, source='backup', operation_id=identity,
                         outcome='success' if ok else 'failure',
                         title='备份完成' if ok else '备份失败',
                         body=f'{scope} ZIP 已生成并发布；不代表完成恢复演练。' if ok else f'备份未完成，旧备份保留。原因代码：{reason}')
        conn.commit()
        if terminal:
            from app.services.result_notifications import deliver_pending
            deliver_pending(self.engine)

    def submit(self, kind, scope, record_id=None, *, slot=None, confirm=None):
        if kind not in ('backup', 'verify', 'restore') or scope not in ('settings', 'all'):
            raise ValueError('invalid operation')
        conn = self.engine.connect()
        owned = False
        try:
            self._primary(conn)
            owned = conn.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': EXEC_LOCK}).scalar_one()
            if not owned:
                raise Busy('backup operation busy')
            conn.commit()
            state = self._edit(conn)
            config = deepcopy(state['config'])
            if slot is not None and (not config['enabled'] or state.get('last_slot') == slot):
                conn.rollback()
                return None
            if record_id:
                with self.store(config).open_record(record_id, verify=False) as (record, stream):
                    if kind == 'restore' and (scope != 'settings' or record['scope'] != 'settings'):
                        raise Conflict('maintenance_required')
                    if kind == 'restore' and confirm != record['filename']:
                        raise ValueError('confirmation mismatch')
            identity = uuid.uuid4().hex
            job = dict(id=identity, kind=kind, scope=scope, state='queued', stage='admitted',
                       error=None, record_id=record_id, reason_code=None, failed_stage=None)
            state.update(job=job, executor={'node': self.node, 'id': identity})
            if slot is not None:
                state['last_slot'] = slot
            self._write(conn, state)
            conn.commit()
            self.worker = threading.Thread(target=self._run, args=(conn, identity, config), daemon=True,
                                           name='stella-backup-' + identity[:8])
            self.worker.start()
            conn = None
            return deepcopy(job)
        finally:
            if conn is not None:
                if owned:
                    conn.rollback()
                    conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': EXEC_LOCK})
                    conn.commit()
                conn.close()

    def _run(self, conn, identity, config):
        fence = lambda: self._fence(conn, identity)
        stage = 'preparing'
        try:
            self._job(conn, identity, state='running', stage='preparing')
            job = self._read(conn)['job']
            conn.commit()
            fence()
            if not config['directory']:
                ensure_private_directory(self.directory(config), fence)
            store = self.store(config, fence)
            if job['kind'] == 'backup':
                self._job(conn, identity, stage='exporting')
                stage = 'exporting'
                with directory_fd(self.directory(config)) as fd:
                    scratch = Path(f'/proc/self/fd/{fd}')  # anonymous TemporaryFiles; nothing large survives a kill
                    with self.engine.connect().execution_options(isolation_level='REPEATABLE READ', postgresql_readonly=True) as snapshot:
                        method = export_settings(snapshot, scratch) if job['scope'] == 'settings' else export_all(snapshot, scratch, self.data_root, backup_directory=self.directory(config))
                        with method as payload:
                            fence()
                            self._job(conn, identity, stage='validating_publishing')
                            stage = 'validating_publishing'
                            record = store.create(job['scope'], payload.entries, payload.warnings)
                self._job(conn, identity, record_id=record['id'])
            elif job['kind'] == 'verify':
                self._job(conn, identity, stage='verifying_zip_not_restore')
                stage = 'verifying_zip_not_restore'
                with store.open_record(job['record_id']):
                    fence()
                store.mark_verified(job['record_id'], True)
            else:
                self._job(conn, identity, stage='restoring_settings')
                stage = 'restoring_settings'
                with store.open_record(job['record_id']) as (record, stream):
                    fence()
                    restore_settings(self.engine, stream, fence=fence)
                    fence()
            self._job(conn, identity, state='succeeded', stage='completed')
        except Exception as exc:
            reason = failure_reason(exc)
            # Emit even if a disconnected/demoted owner cannot persist its job.
            # No traceback, class name, exception string, path or payload.
            logger.warning('backup_job_failed job_id=%s reason_code=%s failed_stage=%s', identity, reason, stage)
            try:
                conn.rollback()
                if 'job' in locals() and job['kind'] == 'verify':
                    self.store(config, fence).mark_verified(job['record_id'], False)
            except Exception:
                pass
            try:
                conn.rollback()
                self._job(conn, identity, state='failed', stage='failed', error=safe_error(exc),
                          reason_code=reason, failed_stage=stage)
            except Exception:
                # A demoted/disconnected owner must not write a success or clean as leader.
                pass
        finally:
            try:
                conn.rollback()
                conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': EXEC_LOCK})
                conn.commit()
            except Exception:
                conn.invalidate()
            conn.close()

    def delete(self, identity, confirmation):
        with self.engine.connect() as conn:
            self._primary(conn)
            owned = conn.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': EXEC_LOCK}).scalar_one()
            if not owned:
                raise Busy('backup operation busy')
            try:
                config = self._read(conn)['config']
                conn.commit()
                self.store(config, lambda: self._execution_fence(conn)).delete(identity, confirmation)
            finally:
                conn.rollback()
                conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': EXEC_LOCK})
                conn.commit()

    def wait(self):
        if self.worker:
            self.worker.join(190)
            if self.worker.is_alive():
                raise RuntimeError('backup worker did not finish within bound')

    def recover(self):
        with self.engine.connect() as conn:
            self._primary(conn)
            if not conn.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': EXEC_LOCK}).scalar_one():
                return
            try:
                state = self._edit(conn)
                if state.get('job') and state['job']['state'] in ('queued', 'running'):
                    previous = state['job'].get('stage')
                    state['job'].update(state='interrupted', stage='owner_lost', error='执行者已中断；未标记成功，请校验现有备份后重试',
                                        reason_code='executor_interrupted', failed_stage=previous if previous in STAGES else None)
                    self._write(conn, state)
                conn.commit()
                if state.get('job') and state['job']['state'] in ('interrupted', 'failed'):
                    try:
                        self.store(state['config'], lambda: self._execution_fence(conn)).recover()
                    except FileNotFoundError:
                        pass  # node-local directory can be absent after failover
            finally:
                conn.rollback()
                conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': EXEC_LOCK})
                conn.commit()

    def tick(self, now=None):
        now = now or self.clock()
        with self.engine.connect() as conn:
            config = self._read(conn)['config']
        if not config['enabled']:
            return None
        local = now.astimezone(ZoneInfo(config['timezone']))
        if local.strftime('%H:%M') != config['time'] or (config['frequency'] == 'weekly' and local.weekday() != config['weekday']):
            return None
        slot = config['timezone'] + ':' + local.strftime('%Y-%m-%dT%H:%M')
        try:
            return self.submit('backup', config['scope'], slot=slot)
        except Busy:
            return None

    def start(self, interval=15):
        def loop():
            while not self.stop_event.is_set():
                try:
                    self.recover()
                    self.tick()
                    # Reuse existing maintenance cadence even with backups OFF.
                    # Pending terminal summaries survive process death and do
                    # not depend on a frontend status/list refresh.
                    from app.services.result_notifications import deliver_pending
                    deliver_pending(self.engine)
                except Exception:
                    pass  # no secrets, no filesystem fallback; persisted job remains honest
                self.stop_event.wait(interval)
        self.timer = threading.Thread(target=loop, daemon=True, name='stella-backup-timer')
        self.timer.start()

    def stop(self):
        self.stop_event.set()
        if self.timer:
            self.timer.join(2)
        self.wait()
