"""Explicit Linux-only companion installer. No generic Agent updater or root grants.

Run this reviewed helper as root against an ALREADY bound instance; package and
canonical release pins are both mandatory. Dependency probes/staging run as its UID.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import types

if sys.platform == 'linux':
    import fcntl
    import pwd

PACKAGE_FILES = ('manifest.json', 'stella_agent.py', 'node_files.py', 'node_files_delivery.py', 'node_files_lifecycle.py')
MAX_PACKAGE = 8 * 1024 * 1024


class LifecycleError(ValueError):
    pass


def delivery():
    module = types.ModuleType('_node_files_delivery')
    module.__file__ = str(Path(__file__).with_name('node_files_delivery.py'))
    exec(compile(Path(module.__file__).read_bytes(), module.__file__, 'exec'), module.__dict__)
    return module


def digest(body):
    return hashlib.sha256(body).hexdigest()


def build_package(source, target):
    source, target = Path(source), Path(target)
    d = delivery()
    manifest, bodies = d.build_release(source)
    bodies['manifest.json'] = d.canonical(manifest)
    for name in ('node_files_delivery.py', 'node_files_lifecycle.py'):
        bodies[name] = (source / name).read_bytes()
        compile(bodies[name], name, 'exec')
    metadata = {'format': 1, 'mode': 'linux-companion', 'platforms': ['linux'], 'release': d.release_id(manifest),
                'files': {name: {'size': len(body), 'sha256': digest(body)} for name, body in bodies.items()}}
    bodies['package.json'] = d.canonical(metadata)
    with tarfile.open(target, 'w', format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(bodies):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(bodies[name]), 0o600, 0
            archive.addfile(info, io.BytesIO(bodies[name]))
    body = target.read_bytes()
    result = {'sha256': digest(body), 'size': len(body), 'release': metadata['release']}
    assert read_package(target, result['sha256'], result['release']) == bodies
    return result


def read_package(path, expected, release):
    for pin in (expected, release):
        if not isinstance(pin, str) or not re.fullmatch('[a-f0-9]{64}', pin):
            raise LifecycleError('invalid_package_pin')
    with Path(path).open('rb') as stream:
        body = stream.read(MAX_PACKAGE + 1)
    if len(body) > MAX_PACKAGE or digest(body) != expected:
        raise LifecycleError('package_hash_size_mismatch')
    bodies = {}
    with tarfile.open(fileobj=io.BytesIO(body), mode='r:') as archive:
        for item in archive:
            if item.name not in (*PACKAGE_FILES, 'package.json') or item.name in bodies or not item.isfile() or not 0 < item.size <= 2 * 1024 * 1024:
                raise LifecycleError('invalid_package_member')
            bodies[item.name] = archive.extractfile(item).read()
    if set(bodies) != set(PACKAGE_FILES) | {'package.json'}:
        raise LifecycleError('incomplete_package')
    d = delivery()
    meta = json.loads(bodies['package.json'])
    if set(meta) != {'format', 'mode', 'platforms', 'release', 'files'} or type(meta['format']) is not int or meta['format'] != 1 or meta['mode'] != 'linux-companion' or meta['platforms'] != ['linux'] or meta['release'] != release or set(meta['files']) != set(PACKAGE_FILES):
        raise LifecycleError('invalid_package_manifest')
    for name in PACKAGE_FILES:
        if meta['files'][name] != {'size': len(bodies[name]), 'sha256': digest(bodies[name])}:
            raise LifecycleError('package_member_hash_mismatch')
        if name.endswith('.py'):
            compile(bodies[name], name, 'exec')
    manifest = d.validate_manifest(json.loads(bodies['manifest.json']))
    if d.release_id(manifest) != release:
        raise LifecycleError('package_release_pin_mismatch')
    for name in d.FILES:
        d.verify_body(name, manifest['files'][name], bodies[name])
    return bodies


def clean_env():
    return {'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'}


def demote(uid, gid):
    def apply():
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    return apply if uid is not None and os.geteuid() == 0 else None


def dependency_probe(python, uid=None, gid=None):
    if not Path(python).is_absolute():
        raise LifecycleError('absolute_private_python_required')
    try:
        result = subprocess.run([str(python), '-I', '-B', '-c', 'import httpx,json,sys; print(json.dumps({"httpx":httpx.__version__,"prefix":sys.prefix}))'], env=clean_env(), cwd='/', preexec_fn=demote(uid, gid), capture_output=True, timeout=15, check=True)
        return json.loads(result.stdout)
    except Exception:
        raise LifecycleError('httpx_preflight_failed_use_explicit_instance_venv') from None


def safe_path(path, owner=0, private=False, directory=False):
    path = Path(path)
    for ancestor in path.parents:
        if ancestor.is_symlink():
            raise LifecycleError('symlink_ancestor_refused')
    info = path.lstat()
    if path.is_symlink() or info.st_uid != owner or info.st_mode & (0o077 if private else 0o022):
        raise LifecycleError('untrusted_path_owner_mode')
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
        raise LifecycleError('invalid_path_type')
    return info


def atomic(path, body, mode=0o600, uid=0, gid=0):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.files-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, mode)
        os.chown(temporary, uid, gid)
        os.replace(temporary, path)
        delivery().fsync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def unit_text(iid, code, config, python, runtime, allow_loopback=False):
    # Spaces/specifiers are rejected before interpolation; no shell is used.
    return f'''[Unit]
Description=Stella file companion {iid}
After=network-online.target
Wants=network-online.target
ConditionPathExists={config}/instance.json
[Service]
Type=notify
NotifyAccess=main
User=sta{iid}
ExecStart={python} -I -B {runtime}/node_files_lifecycle.py worker --instance {iid} --code-root {code} --config-root {config}{' --allow-loopback' if allow_loopback else ''}
EnvironmentFile={config}/agent.env
Environment=STELLA_FILE_ROOTS={{}}
EnvironmentFile={config}/files.env
WorkingDirectory={code}/files
Restart=on-failure
RestartSec=5
TimeoutStartSec=25
TimeoutStopSec=20
UMask=0077
NoNewPrivileges=yes
CapabilityBoundingSet=
RestrictSUIDSGID=yes
[Install]
WantedBy=multi-user.target
'''


class Systemd:
    def __init__(self):
        self.exe = '/usr/bin/systemctl'
        if not Path(self.exe).exists():
            self.exe = '/usr/sbin/systemctl'

    def call(self, *args, check=True):
        return subprocess.run([self.exe, *args], env=clean_env(), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45, check=check)

    def info(self, service):
        result = self.call('show', service, '--property=ActiveState,SubState,MainPID,UnitFileState,StatusText,FragmentPath', check=False)
        if result.returncode:
            raise LifecycleError('systemd_status_unavailable')
        return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


class Lifecycle:
    def __init__(self, iid, *, code_base=Path('/opt/stella-agents'), config_base=Path('/etc/stella-agents'), unit_base=Path('/etc/systemd/system'), systemd=None, allow_loopback=False):
        if sys.platform != 'linux':
            raise LifecycleError('linux_only_windows_unsupported')
        if os.geteuid() != 0 or not re.fullmatch('[a-f0-9]{24}', iid):
            raise LifecycleError('root_and_bound_instance_required')
        self.iid, self.code, self.config = iid, Path(code_base) / iid, Path(config_base) / iid
        self.service = 'stella-files-' + iid + '.service'
        self.unit = Path(unit_base) / self.service
        self.systemd = systemd or Systemd()
        self.allow_loopback = allow_loopback
        for path in (self.code, self.config, self.unit.parent):
            if not path.is_absolute() or re.search(r'[\s%\\\x00-\x1f]', str(path)):
                raise LifecycleError('unsafe_installation_path')
        for ancestor in (*reversed(self.config.parents), self.config):
            safe_path(ancestor, directory=True)
        safe_path(self.config, directory=True)
        safe_path(self.config / 'instance.json')
        self.binding = json.loads((self.config / 'instance.json').read_bytes())
        expected = {'format', 'center_id', 'node_id', 'instance_id', 'service', 'slot'}
        b = self.binding
        if set(b) != expected or b['format'] != 1 or b['instance_id'] != iid or b['service'] != 'stella-agent-' + iid or not re.fullmatch('[a-f0-9]{64}', b['center_id']) or type(b['node_id']) is not int or b['node_id'] <= 0:
            raise LifecycleError('instance_binding_mismatch')
        user = pwd.getpwnam('sta' + iid)
        self.uid, self.gid = user.pw_uid, user.pw_gid
        safe_path(self.code, self.uid, directory=True)
        safe_path(self.code / 'stella_agent.py', self.uid)
        safe_path(self.config / 'agent.env', private=True)
        agent_env = dict(line.split('=', 1) for line in (self.config / 'agent.env').read_text().splitlines() if '=' in line)
        if json.loads(agent_env.get('STELLA_INSTANCE_ID', 'null')) != iid or json.loads(agent_env.get('STELLA_INSTANCE_MANIFEST', 'null')) != str(self.config / 'instance.json'):
            raise LifecycleError('credential_binding_mismatch')
        self.origin, self.token = json.loads(agent_env['STELLA_URL']), json.loads(agent_env['STELLA_TOKEN'])
        delivery().checked_origin(self.origin, allow_loopback=allow_loopback)
        if not self.token or any(c in self.token for c in '\r\n\x00'):
            raise LifecycleError('invalid_instance_token')
        # Companion mode must not coexist with the main optional module.
        if (self.code / 'node_files.py').exists() or (self.code / 'node_files.py').is_symlink() or 'STELLA_FILE_ROOTS' in agent_env:
            raise LifecycleError('embedded_file_mode_conflict')
        main_unit = self.unit.parent / (b['service'] + '.service')
        safe_path(main_unit)
        text = main_unit.read_text()
        for value in ('User=sta' + iid + '\n', 'EnvironmentFile=' + str(self.config / 'agent.env') + '\n', 'ExecStart=/usr/bin/env python3 ' + str(self.code / 'stella_agent.py') + '\n'):
            if value not in text:
                raise LifecycleError('main_unit_binding_mismatch')
        self.base = self.code / 'files'
        self.state_path = self.config / 'files-state.json'

    @contextlib.contextmanager
    def locked(self):
        handles = []
        try:
            for path, owner in ((self.config.parent / ('.' + self.iid + '.lock'), 0), (self.code / '.update.lock', self.uid)):
                try:
                    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                    os.fchown(fd, owner, self.gid if owner else 0)
                except FileExistsError:
                    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
                handles.append(fd)
                if os.fstat(fd).st_uid != owner or os.fstat(fd).st_mode & 0o077 or os.fstat(fd).st_nlink != 1:
                    raise LifecycleError('unsafe_instance_lock')
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            for fd in reversed(handles):
                os.close(fd)

    def state(self):
        if not self.state_path.exists():
            return None
        safe_path(self.state_path, private=True)
        state = json.loads(self.state_path.read_bytes())
        if state['binding'] != self.binding:
            raise LifecycleError('lifecycle_binding_mismatch')
        return state

    def status(self):
        state = self.state()
        info = self.systemd.info(self.service)
        if not state:
            if self.unit.exists() or self.unit.is_symlink() or info.get('FragmentPath') or info.get('ActiveState') != 'inactive' or info.get('MainPID') != '0':
                raise LifecycleError('orphan_or_foreign_companion_recovery_unknown')
            return {'installed': False, 'mode': 'linux-companion', 'roots_granted': False, 'systemd': info}
        if state.get('recovery_unknown'):
            self.owned_unit(state, info)
            return {'installed': True, 'mode': 'linux-companion', 'recovery_unknown': True, 'manual_intervention_required': True, 'roots_granted': None, 'authenticated_ready': False, 'release': state['release'], 'package_sha256': state['package_sha256'], 'systemd': info}
        safe_path(self.unit)
        if digest(self.unit.read_bytes()) != state['unit_sha256']:
            raise LifecycleError('foreign_companion_unit')
        pointer = self.base / 'releases/current.json'
        safe_path(pointer, self.uid, private=True)
        selected = json.loads(pointer.read_bytes())['release']
        try:
            verified = subprocess.run([state['python'], '-I', '-B', str(Path(state['runtime']) / 'node_files_delivery.py'), 'check', '--store', str(self.base / 'releases')], env=clean_env(), cwd='/', preexec_fn=demote(self.uid, self.gid), capture_output=True, timeout=15)
            integrity = verified.returncode == 0 and json.loads(verified.stdout)['release'] == selected
        except Exception:
            integrity = False
        return {'installed': True, 'mode': 'linux-companion', 'release': selected, 'package_sha256': state['package_sha256'], 'integrity': integrity, 'consistent': integrity and selected == state['release'], 'authenticated_ready': integrity and info.get('ActiveState') == 'active' and info.get('StatusText') == 'authenticated release ' + state['release'], 'readiness_scope': 'authenticated_startup_claim_not_live_center_health', 'systemd': info}

    def owned_unit(self, state, info):
        # Never signal a numeric PID. Only the exact root-owned bound unit may
        # be stopped, and the manager must resolve that same fragment.
        expected = state.get('recovery_unknown', {}).get('owned_unit_sha256', state['unit_sha256'])
        if expected is None:
            if self.unit.exists() or info.get('FragmentPath') or info.get('ActiveState') != 'inactive' or info.get('MainPID') != '0':
                raise LifecycleError('foreign_companion_unit')
            return
        safe_path(self.unit)
        if digest(self.unit.read_bytes()) != expected or info.get('FragmentPath') != str(self.unit):
            raise LifecycleError('foreign_companion_unit')

    def confirmed_stop(self, state):
        self.owned_unit(state, self.systemd.info(self.service))
        result = self.systemd.call('stop', self.service, check=False)
        if result.returncode != 0:
            raise LifecycleError('stop_failed_recovery_unknown')
        info = self.systemd.info(self.service)
        self.owned_unit(state, info)
        if info.get('ActiveState') != 'inactive' or info.get('MainPID') != '0':
            raise LifecycleError('stop_readback_recovery_unknown')

    def restore_activation(self, recovery, restart_previous=False):
        candidate = recovery['candidate']
        restore = [candidate['python'], '-I', '-B', str(Path(candidate['runtime']) / 'node_files_lifecycle.py'), 'restore', '--store', str(self.base / 'releases')]
        if recovery['old_pointer'] is not None:
            restore += ['--release', json.loads(recovery['old_pointer'])['release']]
        result = subprocess.run(restore, env=clean_env(), cwd='/', preexec_fn=demote(self.uid, self.gid), capture_output=True, timeout=30)
        if result.returncode:
            raise LifecycleError('pointer_rollback_failed_manual_intervention_required')
        if recovery['old_unit'] is None:
            self.unit.unlink(missing_ok=True)
        else:
            atomic(self.unit, recovery['old_unit'].encode(), 0o644)
        self.systemd.call('daemon-reload')
        old_info = recovery['old_info']
        self.systemd.call('enable' if restart_previous and old_info.get('UnitFileState') == 'enabled' else 'disable', self.service)
        if restart_previous and recovery['old_unit'] is not None and old_info.get('ActiveState') == 'active':
            self.systemd.call('restart', self.service)
            restored = self.systemd.info(self.service)
            if restored.get('StatusText') != old_info.get('StatusText') or restored.get('ActiveState') != 'active':
                raise LifecycleError('rollback_recovery_failed_manual_intervention_required')
        # Keep the recovery record until all restoration calls succeed.
        if recovery['previous'] is None:
            self.state_path.unlink(missing_ok=True)
            delivery().fsync_directory(self.state_path.parent)
        else:
            atomic(self.state_path, delivery().canonical(recovery['previous']))

    def stage(self, state):
        result = subprocess.run([state['python'], '-I', '-B', str(Path(state['runtime']) / 'node_files_lifecycle.py'), 'stage', '--store', str(self.base / 'releases'), '--runtime', state['runtime'], '--release', state['release']], env=clean_env(), cwd='/', preexec_fn=demote(self.uid, self.gid), capture_output=True, timeout=30)
        if result.returncode:
            raise LifecycleError('stage_or_dependency_preflight_failed')

    def activate(self, candidate, bodies=None):
        """Caller holds both existing instance locks. Restore exact unit/pointer/state."""
        previous = self.state()
        if previous and previous.get('recovery_unknown'):
            raise LifecycleError('recovery_unknown_stop_required_no_business_retry')
        old_unit = self.unit.read_bytes() if self.unit.exists() else None
        if old_unit is not None:
            safe_path(self.unit)
            if not previous or digest(old_unit) != previous['unit_sha256']:
                raise LifecycleError('foreign_companion_unit')
        elif previous:
            raise LifecycleError('missing_owned_unit')
        old_info = self.systemd.info(self.service)
        if previous is None and (old_info.get('FragmentPath') or old_info.get('MainPID', '0') != '0'):
            raise LifecycleError('foreign_companion_service')
        for path in (self.base, self.base / 'releases'):
            if path.exists() or path.is_symlink():
                safe_path(path, self.uid, private=True, directory=True)
        runtime_base = self.config / 'files-runtime'
        runtime_base.mkdir(mode=0o755, exist_ok=True)
        safe_path(runtime_base, directory=True)
        os.chmod(runtime_base, 0o755)
        runtime = Path(candidate['runtime'])
        if bodies is not None:
            if not runtime.exists():
                stage = Path(tempfile.mkdtemp(prefix='.stage-', dir=runtime_base))
                try:
                    for name, body in bodies.items():
                        atomic(stage / name, body, 0o644)
                    os.chmod(stage, 0o755)
                    delivery().fsync_directory(stage)
                    os.rename(stage, runtime)
                    delivery().fsync_directory(runtime_base)
                finally:
                    if stage.exists():
                        shutil.rmtree(stage)
            safe_path(runtime, directory=True)
            if {p.name for p in runtime.iterdir()} != set(bodies):
                raise LifecycleError('runtime_package_members_changed')
            for name, body in bodies.items():
                safe_path(runtime / name)
                if (runtime / name).read_bytes() != body:
                    raise LifecycleError('runtime_package_changed')
        dependency_probe(candidate['python'], self.uid, self.gid)
        pointer = self.base / 'releases/current.json'
        old_pointer = pointer.read_bytes() if pointer.exists() else None
        files_env = self.config / 'files.env'
        if files_env.exists():
            safe_path(files_env, private=True)
        else:
            atomic(files_env, b'STELLA_FILE_ROOTS={}\n')
        text = unit_text(self.iid, self.code, self.config, Path(candidate['python']), runtime, self.allow_loopback).encode()
        candidate = dict(candidate, binding=self.binding, unit_sha256=digest(text))
        if previous and all(candidate[k] == previous[k] for k in ('package_sha256', 'release', 'python', 'runtime', 'unit_sha256')) and self.status()['authenticated_ready']:
            return self.status()
        candidate['previous'] = {k: v for k, v in previous.items() if k != 'previous'} if previous else None
        try:
            self.stage(candidate)
            atomic(self.unit, text, 0o644)
            self.systemd.call('daemon-reload')
            self.systemd.call('enable', self.service)
            self.systemd.call('restart', self.service)
            info = self.systemd.info(self.service)
            if info.get('ActiveState') != 'active' or info.get('StatusText') != 'authenticated release ' + candidate['release']:
                raise LifecycleError('authenticated_worker_not_ready')
            atomic(self.state_path, delivery().canonical(candidate))
            return self.status()
        except BaseException:
            # Persist candidate + exact old identities BEFORE trying a stop.
            # A nonzero/timeout/unknown stop never licenses destructive cleanup.
            owned_hash = candidate['unit_sha256'] if self.unit.exists() and self.unit.read_bytes() == text else (previous['unit_sha256'] if previous else None)
            recovery = {'operation': 'activation', 'candidate': candidate, 'previous': previous,
                        'old_unit': old_unit.decode() if old_unit is not None else None,
                        'old_pointer': old_pointer.decode() if old_pointer is not None else None,
                        'old_info': old_info, 'owned_unit_sha256': owned_hash}
            pending = dict(candidate, recovery_unknown=recovery)
            atomic(self.state_path, delivery().canonical(pending))
            try:
                self.confirmed_stop(pending)
            except Exception:
                raise LifecycleError('stop_failed_recovery_unknown_manual_intervention_required') from None
            self.restore_activation(recovery, restart_previous=True)
            raise

    def install(self, package, package_sha256, release, python):
        bodies = read_package(package, package_sha256, release)
        if not Path(python).is_absolute() or re.search(r'[\s%\\\x00-\x1f]', str(python)):
            raise LifecycleError('unsafe_python_path')
        candidate = {'package_sha256': package_sha256, 'release': release, 'python': str(python), 'runtime': str(self.config / 'files-runtime' / package_sha256)}
        with self.locked():
            return self.activate(candidate, bodies)

    def stop(self):
        with self.locked():
            state = self.state()
            if not state:
                return self.status()  # Orphan/foreign/unknown is never a no-op success.
            self.owned_unit(state, self.systemd.info(self.service))
            if not state.get('recovery_unknown'):
                state = dict(state, recovery_unknown={'operation': 'stop', 'candidate': state,
                             'previous': state.get('previous'), 'owned_unit_sha256': state['unit_sha256']})
                atomic(self.state_path, delivery().canonical(state))
            try:
                self.systemd.call('disable', self.service)
                self.confirmed_stop(state)
            except Exception:
                raise LifecycleError('stop_failed_recovery_unknown_manual_intervention_required') from None
            recovery = state['recovery_unknown']
            if recovery['operation'] == 'activation':
                # Explicit stop recovers metadata but never restarts old business work.
                self.restore_activation(recovery)
            else:
                atomic(self.state_path, delivery().canonical(recovery['candidate']))
            result = self.status()
            if result['systemd'].get('ActiveState') != 'inactive' or result['systemd'].get('MainPID') != '0' or result['systemd'].get('UnitFileState') == 'enabled':
                raise LifecycleError('stop_readback_failed')
            return result

    def rollback(self):
        with self.locked():
            state = self.state()
            if not state or not state.get('previous'):
                raise LifecycleError('no_previous_complete_release')
            return self.activate(state['previous'])


def notify_ready(release):
    name = os.environ.get('NOTIFY_SOCKET')
    if not name:
        return
    address = '\0' + name[1:] if name.startswith('@') else name
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.connect(address)
        sock.sendall(('READY=1\nSTATUS=authenticated release ' + release).encode())


def verify_center_identity(origin, token, binding, allow_loopback=False):
    import httpx
    origin = delivery().checked_origin(origin, allow_loopback)
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client:
        with client.stream('GET', origin + '/agent/identity', headers={'Authorization': 'Bearer ' + token}) as response:
            if response.status_code != 200:
                raise LifecycleError('worker_identity_authentication_refused')
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 8192:
                    raise LifecycleError('worker_identity_response_limit')
    identity = json.loads(body)
    if set(identity) != {'center_id', 'node_id', 'source_version', 'source_sha256', 'source_size'} or type(identity['node_id']) is not int or identity['node_id'] != binding['node_id'] or identity['center_id'] != binding['center_id']:
        raise LifecycleError('worker_center_node_identity_mismatch')


def worker(iid, code, config, allow_loopback=False):
    if sys.platform != 'linux' or not re.fullmatch('[a-f0-9]{24}', iid):
        raise LifecycleError('linux_bound_worker_required')
    # Root-owned privateConfig holds executable bootstrap bytes. Generations are
    # instance-UID-owned. Main Agent stays at its fixed binding path.
    runtime = Path(__file__).resolve().parent
    code, config = Path(code), Path(config)
    if not code.is_absolute() or not config.is_absolute() or runtime.parent != config / 'files-runtime' or os.environ.get('STELLA_INSTANCE_MANIFEST') != str(config / 'instance.json'):
        raise LifecycleError('worker_installation_path_mismatch')
    binding = json.loads((config / 'instance.json').read_bytes())
    if binding['instance_id'] != iid or os.environ.get('STELLA_INSTANCE_ID') != iid or code.name != iid:
        raise LifecycleError('worker_binding_mismatch')
    safe_path(config / 'instance.json')
    if (code / 'node_files.py').exists() or (code / 'node_files.py').is_symlink():
        raise LifecycleError('embedded_file_mode_conflict')
    meta = json.loads((runtime / 'package.json').read_bytes())
    for name in PACKAGE_FILES:
        if digest((runtime / name).read_bytes()) != meta['files'][name]['sha256']:
            raise LifecycleError('worker_runtime_changed')
    base = code / 'files'
    fd = os.open(base / '.worker.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Remove unrelated inherited env before any network client can start.
        kept = {k: v for k, v in os.environ.items() if k in ('STELLA_TOKEN', 'STELLA_URL', 'STELLA_FILE_ROOTS', 'NOTIFY_SOCKET')}
        os.environ.clear()
        os.environ.update(clean_env(), **kept)
        d = delivery()
        store = d.ReleaseStore(base / 'releases')
        if store.current().name != meta['release']:
            raise LifecycleError('worker_generation_package_mismatch')
        verify_center_identity(os.environ['STELLA_URL'], os.environ['STELLA_TOKEN'], binding, allow_loopback)
        def bound():
            safe_path(config / 'instance.json')
            if json.loads((config / 'instance.json').read_bytes()) != binding or not (code / 'stella_agent.py').is_file() or (code / 'node_files.py').exists() or (code / 'node_files.py').is_symlink():
                raise LifecycleError('main_instance_removed_changed_or_embedded_mode_conflict')
        d.run_worker(store, os.environ['STELLA_URL'], os.environ['STELLA_TOKEN'], allow_loopback=allow_loopback, on_ready=lambda: notify_ready(meta['release']), before_tick=bound)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description='Explicit opt-in existing Linux instance companion lifecycle (not generic updater)')
    parser.add_argument('action', choices=('install', 'update', 'status', 'stop', 'rollback', 'worker', 'stage', 'restore', 'build'))
    parser.add_argument('--instance')
    parser.add_argument('--package')
    parser.add_argument('--package-sha256')
    parser.add_argument('--release')
    parser.add_argument('--python')
    parser.add_argument('--source')
    parser.add_argument('--store')
    parser.add_argument('--runtime')
    parser.add_argument('--code-root')
    parser.add_argument('--config-root')
    parser.add_argument('--allow-loopback', action='store_true', help='Explicit isolated local HTTP fixture transport only')
    args = parser.parse_args()
    if sys.platform != 'linux':
        raise LifecycleError('linux_only_windows_unsupported')
    if args.action == 'build':
        print(json.dumps(build_package(args.source, args.package)))
    elif args.action == 'stage':
        d = delivery()
        runtime = Path(args.runtime)
        manifest = d.validate_manifest(json.loads((runtime / 'manifest.json').read_bytes()))
        if d.release_id(manifest) != args.release:
            raise LifecycleError('stage_release_pin_mismatch')
        Path(args.store).parent.mkdir(mode=0o700, exist_ok=True)
        d.ReleaseStore(args.store).install(manifest, lambda name, _: (runtime / name).read_bytes())
    elif args.action == 'restore':
        d = delivery()
        store = d.ReleaseStore(args.store)
        pointer = store.root / 'current.json'
        if args.release:
            if not re.fullmatch('[a-f0-9]{64}', args.release):
                raise LifecycleError('invalid_restore_pin')
            store.verify(store.root / args.release, args.release)
            store._atomic(pointer, d.canonical({'release': args.release}))
        else:
            pointer.unlink(missing_ok=True)
            d.fsync_directory(store.root)
    elif args.action == 'worker':
        worker(args.instance, args.code_root, args.config_root, args.allow_loopback)
    else:
        lifecycle = Lifecycle(args.instance, allow_loopback=args.allow_loopback)
        if args.action in ('install', 'update'):
            result = lifecycle.install(args.package, args.package_sha256, args.release, args.python)
        else:
            result = getattr(lifecycle, args.action)()
        print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # No exception text/argv/env: credentials and filesystem grants stay local.
        print(json.dumps({'event': 'lifecycle_refused', 'kind': type(exc).__name__}), file=sys.stderr)
        raise SystemExit(1)
