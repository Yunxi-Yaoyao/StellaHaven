from datetime import datetime, timezone
import json
import threading
import pytest
from sqlalchemy import text


def test_default_read_and_disabled_tick_have_no_files_or_state(engine, tmp_path):
    from app.services.backup_center import BackupCenter
    center = BackupCenter(engine, tmp_path / 'data', key=b'fixture')
    state = center.status()
    assert state['config'] == dict(revision=0, enabled=False, scope='settings', directory='', frequency='daily', time='03:00', timezone='Asia/Shanghai', weekday=0)
    assert state['records'] == [] and state['job'] is None and state['next_run'] is None
    assert center.tick(datetime(2026, 10, 18, 3, 0, tzinfo=timezone.utc)) is None
    assert not (tmp_path / 'data').exists()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM app_config WHERE key='backup_center_v1'")).scalar_one() == 0


def test_actual_due_tick_persists_job_and_duplicate_ha_tick_runs_once(engine, tmp_path):
    from app.services.backup_center import BackupCenter
    first = BackupCenter(engine, tmp_path / 'data', key=b'fixture', node='node-a')
    second = BackupCenter(engine, tmp_path / 'standby', key=b'fixture', node='node-b')
    cfg = first.patch({'enabled': True, 'timezone': 'UTC', 'time': '03:00', 'expected_revision': 0})
    assert cfg['enabled'] and not (tmp_path / 'data').exists()
    stamp = datetime(2026, 10, 18, 3, 0, tzinfo=timezone.utc)
    job = first.tick(stamp)
    assert job is not None
    first.wait()
    assert first.status()['job']['state'] == 'succeeded'
    assert second.tick(stamp) is None
    assert len(first.status()['records']) == 1
    assert second.status()['records'] == []
    assert not second.status()['storage']['available']
    assert first.status()['config']['enabled'] is True


def test_single_execution_busy_and_failure_preserves_old_archives(engine, tmp_path, monkeypatch):
    from app.services.backup_center import BackupCenter
    from app.services.backup_storage import Busy
    center = BackupCenter(engine, tmp_path, key=b'fixture')
    entered, release = threading.Event(), threading.Event()
    import app.services.backup_center as module
    original = module.export_settings
    from contextlib import contextmanager
    @contextmanager
    def held(*a):
        entered.set()
        assert release.wait(5)
        with original(*a) as payload:
            yield payload
    monkeypatch.setattr(module, 'export_settings', held)
    center.submit('backup', 'settings')
    assert entered.wait(5)
    with pytest.raises(Busy):
        BackupCenter(engine, tmp_path, key=b'fixture').submit('backup', 'settings')
    release.set()
    center.wait()
    assert center.status()['job']['state'] == 'succeeded'


def test_real_timer_uses_clock_and_restart_recovers_interrupted_job(engine, tmp_path):
    from app.services.backup_center import BackupCenter
    stamp = datetime(2026, 10, 19, 8, 30, tzinfo=timezone.utc)
    center = BackupCenter(engine, tmp_path, key=b'fixture', clock=lambda: stamp)
    center.patch({'enabled': True, 'frequency': 'weekly', 'weekday': 0, 'timezone': 'UTC', 'time': '08:30', 'expected_revision': 0})
    center.start(interval=.02)
    import time
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if center.status()['job'] and center.status()['job']['state'] == 'succeeded':
            break
        time.sleep(.02)
    center.stop()
    assert center.status()['job']['state'] == 'succeeded'
    assert len(center.status()['records']) == 1
    with engine.begin() as conn:
        value = json.loads(conn.execute(text("SELECT value FROM app_config WHERE key='backup_center_v1'")).scalar_one())
        value['job'].update(state='running', stage='simulated_process_death')
        conn.execute(text("UPDATE app_config SET value=:value WHERE key='backup_center_v1'"), {'value': json.dumps(value)})
    restarted = BackupCenter(engine, tmp_path, key=b'fixture')
    restarted.recover()
    assert restarted.status()['job']['state'] == 'interrupted'
    assert restarted.tick(stamp) is None


def test_two_real_processes_due_tick_share_one_pg_execution(engine, tmp_path):
    import subprocess
    import sys
    from app.services.backup_center import BackupCenter
    center = BackupCenter(engine, tmp_path, key=b'fixture')
    center.patch({'enabled': True, 'timezone': 'UTC', 'time': '03:00', 'expected_revision': 0})
    code = '''
from datetime import datetime, timezone
import json, sys
from app.database import engine
from app.services.backup_center import BackupCenter
c=BackupCenter(engine, sys.argv[1], key=b'fixture')
job=c.tick(datetime(2026,10,18,3,0,tzinfo=timezone.utc)); c.wait()
print(json.dumps({'admitted':job is not None}))
'''
    children = [subprocess.Popen([sys.executable, '-c', code, str(tmp_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    results = []
    for child in children:
        stdout, stderr = child.communicate(timeout=15)
        assert child.returncode == 0, stderr
        results.append(json.loads(stdout))
    assert sum(r['admitted'] for r in results) == 1
    assert len(center.status()['records']) == 1


def test_demoted_owner_cannot_publish_or_retain_and_restart_reports_interrupted(engine,tmp_path,monkeypatch):
    from app.services.backup_center import BackupCenter
    from contextlib import contextmanager
    import app.services.backup_center as module
    center=BackupCenter(engine,tmp_path,key=b'key')
    center.submit('backup','settings'); center.wait()
    old=center.status()['records']
    original=module.export_settings
    @contextmanager
    def loss(*args):
        with original(*args) as payload:
            def demoted(conn): raise RuntimeError('demoted test node')
            monkeypatch.setattr(center,'_primary',demoted)
            yield payload
    monkeypatch.setattr(module,'export_settings',loss)
    center.submit('backup','settings'); center.wait()
    assert center.status()['records']==old
    assert center.status()['job']['state']!='succeeded'
    BackupCenter(engine,tmp_path,key=b'key').recover()
    assert center.status()['job']['state']=='interrupted'


def test_config_change_rejected_while_operation_running(engine,tmp_path,monkeypatch):
    from app.services.backup_center import BackupCenter
    from app.services.backup_storage import Busy
    from contextlib import contextmanager
    import app.services.backup_center as module
    center=BackupCenter(engine,tmp_path,key=b'key')
    entered,release=threading.Event(),threading.Event()
    original=module.export_settings
    @contextmanager
    def blocked(*args):
        entered.set(); assert release.wait(5)
        with original(*args) as payload: yield payload
    monkeypatch.setattr(module,'export_settings',blocked)
    center.submit('backup','settings'); assert entered.wait(5)
    try:
        with pytest.raises(Busy): center.patch({'expected_revision':0,'scope':'all'})
    finally:
        release.set(); center.wait()


def test_legacy_file_settings_are_explicitly_unavailable_not_incomplete_success(engine,tmp_path,monkeypatch):
    from app.services.backup_center import BackupCenter
    center=BackupCenter(engine,tmp_path,key=b'key')
    monkeypatch.setenv('STELLA_BLOB_STORAGE','file')
    assert center.status()['capabilities']['settings_restore'] is False
    center.submit('backup','settings'); center.wait()
    result=center.status()
    assert result['job']['state']=='failed' and not result['records']
    assert 'PostgreSQL' in result['job']['error']
    center.submit('backup','all'); center.wait()
    assert center.status()['job']['state']=='failed' and not center.status()['records']


def test_delete_rechecks_primary_before_filesystem_write(engine,tmp_path,monkeypatch):
    from app.services.backup_center import BackupCenter
    center=BackupCenter(engine,tmp_path,key=b'key')
    center.submit('backup','settings');center.wait()
    record=center.status()['records'][0]
    original=center._primary
    calls=[]
    def lost(conn):
        calls.append(True)
        if len(calls)>1: raise RuntimeError('primary lost')
        original(conn)
    monkeypatch.setattr(center,'_primary',lost)
    with pytest.raises(RuntimeError): center.delete(record['id'],record['filename'])
    assert (center.store().path/record['filename']).is_file()


def test_symlink_config_directory_swap_never_creates_scratch_outside(engine,tmp_path,monkeypatch):
    from app.services.backup_center import BackupCenter
    target=tmp_path/'safe';target.mkdir()
    outside=tmp_path/'outside';outside.mkdir()
    center=BackupCenter(engine,tmp_path/'data',key=b'key')
    center.patch({'directory':str(target),'expected_revision':0})
    target.rmdir();target.symlink_to(outside,target_is_directory=True)
    writes=[]
    import app.services.backup_center as module
    original=module.tempfile.TemporaryDirectory
    def observed(*a,**k):
        writes.append(str(k.get('dir')))
        return original(*a,**k)
    monkeypatch.setattr(module.tempfile,'TemporaryDirectory',observed)
    center.submit('backup','settings');center.wait()
    assert center.status()['job']['state']=='failed'
    assert writes==[] and list(outside.iterdir())==[]


def test_directory_apply_probes_write_permission_and_invalid_index_unavailable(engine,tmp_path,monkeypatch):
    import errno,os
    from app.services.backup_center import BackupCenter
    center=BackupCenter(engine,tmp_path/'data',key=b'key')
    folder=tmp_path/'provisioned';folder.mkdir()
    original=os.open
    def denied(path,flags,*a,**kw):
        if flags&os.O_CREAT:raise PermissionError(errno.EACCES,'injected denied')
        return original(path,flags,*a,**kw)
    with monkeypatch.context() as patch:
        patch.setattr(os,'open',denied)
        with pytest.raises(PermissionError):center.patch({'directory':str(folder),'expected_revision':0})
    assert center.status()['config']['revision']==0
    center.patch({'directory':str(folder),'expected_revision':0})
    assert list(folder.iterdir())==[]
    (folder/'.stella-backups-v1.json').write_text('not an owned index')
    assert center.status()['storage']['available'] is False
    assert center.status()['storage']['error']
