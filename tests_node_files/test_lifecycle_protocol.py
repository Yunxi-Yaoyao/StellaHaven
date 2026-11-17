"""Real independent installed worker + HTTP + nonce PG; systemd is an adapter fixture."""
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def real_identity_transport(system, tmp_path, monkeypatch):
    import httpx
    import uvicorn
    from fastapi import FastAPI
    from app.routers.monitor import agent_router as main_agent_router
    from app.routers.node_files import agent_router
    from app.services import oidc
    owned = tmp_path / 'oidc'
    monkeypatch.setattr(oidc, 'OIDC_DIR', owned)
    monkeypatch.setattr(oidc, 'PRIVATE_KEY_PATH', owned / 'private.json')
    monkeypatch.setattr(oidc, 'CLIENT_FILE', owned / 'clients.json')
    app = FastAPI()
    app.include_router(agent_router)
    # Actual existing identity endpoint only; no resident key paths/lifespan.
    route = next(r for r in main_agent_router.routes if getattr(r, 'path', '') == '/agent/identity')
    app.router.routes.append(route)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    url = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.02)
        assert server.started
        with httpx.Client(trust_env=False) as client:
            response = client.get(url + '/agent/identity', headers={'Authorization': 'Bearer ' + system['token']})
            assert response.status_code == 200, response.text
            system['lifecycle_center'] = response.json()['center_id']
        system['lifecycle_url'] = url
        yield app
    finally:
        server.should_exit = True
        thread.join(5)
        assert not thread.is_alive()
        assert owned.is_dir()


class OwnedSystemd:
    """Executes real unit ExecStart children, NOT a real systemd restart claim."""
    def __init__(self, unit_dir, service):
        self.unit_dir, self.service = unit_dir, service
        self.process = None
        self.enabled = False
        self.status = ''
        self.restarts = 0
        self.logs = []
        self.events = []
        self.uid = self.gid = None

    def halt(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=15)
        self.status = ''

    def info(self, service):
        assert service == self.service
        live = self.process is not None and self.process.poll() is None
        return {'ActiveState': 'active' if live else 'inactive', 'SubState': 'running' if live else 'dead', 'MainPID': str(self.process.pid) if live else '0', 'UnitFileState': 'enabled' if self.enabled else 'disabled', 'StatusText': self.status if live else '', 'FragmentPath': str(self.unit_dir / service) if (self.unit_dir / service).exists() else ''}

    def call(self, *args, check=True):
        self.events.append(list(args))
        if args[0] in ('enable', 'disable'):
            self.enabled = args[0] == 'enable'
        elif args[0] == 'stop':
            self.halt()
        elif args[0] == 'restart':
            self.halt()
            text = (self.unit_dir / self.service).read_text()
            lines = text.splitlines()
            argv = shlex.split(next(x.removeprefix('ExecStart=') for x in lines if x.startswith('ExecStart=')))
            env = {'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'}
            for line in lines:
                if line.startswith('Environment='):
                    key, value = line.removeprefix('Environment=').split('=', 1)
                    env[key] = value
                if line.startswith('EnvironmentFile='):
                    for item in Path(line.removeprefix('EnvironmentFile=')).read_text().splitlines():
                        if not item or item.startswith('#'):
                            continue
                        key, value = item.split('=', 1)
                        # Installer's JSON double-quoted systemd environment values.
                        env[key] = json.loads(value) if value.startswith('"') else value
            address = '\0nfl-' + uuid4().hex
            env['NOTIFY_SOCKET'] = '@' + address[1:]
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notify:
                notify.bind(address)
                notify.settimeout(.05)
                log = self.unit_dir / ('child-' + str(self.restarts) + '.log')
                self.logs.append(log)
                self.restarts += 1
                with log.open('wb') as output:
                    from agent.node_files_lifecycle import demote
                    self.process = subprocess.Popen(argv, cwd='/', env=env, stdout=output, stderr=output, preexec_fn=demote(self.uid, self.gid))
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise RuntimeError('actual child startup failed: ' + log.read_text())
                    try:
                        message = notify.recv(8192).decode()
                    except socket.timeout:
                        continue
                    assert 'READY=1' in message
                    self.status = next(x.removeprefix('STATUS=') for x in message.splitlines() if x.startswith('STATUS='))
                    break
                else:
                    self.halt()
                    raise RuntimeError('actual authenticated claim timeout: ' + log.read_text())
        return SimpleNamespace(returncode=0)


def make_fixture(system, tmp_path, monkeypatch):
    from agent import node_files_lifecycle as lc
    iid = uuid4().hex[:24]
    code_base, config_base, units = [tmp_path / name for name in ('code', 'config', 'units')]
    code, config = code_base / iid, config_base / iid
    for path in (code, config, units):
        path.mkdir(parents=True, mode=0o700)
    (code / 'stella_agent.py').write_bytes((Path(lc.__file__).parent / 'stella_agent.py').read_bytes())
    (code / 'stella_agent.py').chmod(0o700)
    binding = {'format': 1, 'instance_id': iid, 'center_id': system['lifecycle_center'], 'node_id': 930001, 'service': 'stella-agent-' + iid, 'slot': 'owned'}
    (config / 'instance.json').write_text(json.dumps(binding))
    env = {'STELLA_URL': system['lifecycle_url'], 'STELLA_TOKEN': system['token'], 'STELLA_INSTANCE_ID': iid, 'STELLA_INSTANCE_MANIFEST': str(config / 'instance.json')}
    (config / 'agent.env').write_text(''.join(k + '=' + json.dumps(v) + '\n' for k, v in env.items()))
    (config / 'agent.env').chmod(0o600)
    main_unit = units / (binding['service'] + '.service')
    main_unit.write_text(f'User=sta{iid}\nEnvironmentFile={config}/agent.env\nExecStart=/usr/bin/env python3 {code}/stella_agent.py\n')
    account = lc.pwd.getpwuid(os.geteuid())
    monkeypatch.setattr(lc.pwd, 'getpwnam', lambda name: account if name == 'sta' + iid else (_ for _ in ()).throw(KeyError(name)))
    adapter = OwnedSystemd(units, 'stella-files-' + iid + '.service')
    lifecycle = lc.Lifecycle(iid, code_base=code_base, config_base=config_base, unit_base=units, systemd=adapter, allow_loopback=True)
    return lc, lifecycle, adapter, main_unit, env


def test_installer_lifecycle_real_workers_empty_roots_update_failure_and_rollback(system, tmp_path, monkeypatch):
    lc, lifecycle, adapter, main_unit, env = make_fixture(system, tmp_path, monkeypatch)
    protected = {p: p.read_bytes() for p in (main_unit, lifecycle.config / 'agent.env', lifecycle.config / 'instance.json', lifecycle.code / 'stella_agent.py')}
    source = Path(lc.__file__).parent
    package_path = tmp_path / 'package.tar'
    first = lc.build_package(source, package_path)
    assert lifecycle.status()['installed'] is False
    assert adapter.restarts == 0 and not lifecycle.unit.exists()
    try:
        old_umask = os.umask(0o077)
        try:
            status = lifecycle.install(package_path, first['sha256'], first['release'], sys.executable)
        finally:
            os.umask(old_umask)
        assert (Path(lifecycle.state()['runtime']).stat().st_mode & 0o777) == 0o755
        assert (Path(lifecycle.state()['runtime']).parent.stat().st_mode & 0o777) == 0o755
        assert status['authenticated_ready'] and status['consistent']
        assert Path(lifecycle.state()['runtime']).is_relative_to(lifecycle.config), 'privileged runtime writes must stay under root-owned privateConfig, never UID-writable code ancestry'
        from app.database import sessionLocal
        from app.models.node_file import FileAgent
        with sessionLocal() as db:
            assert db.get(FileAgent, 930001).roots == {}
        before = {p.name: p.read_bytes() for p in system['root'].iterdir() if p.is_file() and not p.is_symlink()}
        denied = system['client'].post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': 930001, 'root': 'fixture', 'op': 'create', 'path': 'not-granted'})
        assert denied.status_code in (403, 409) and not (system['root'] / 'not-granted').exists()
        assert before == {p.name: p.read_bytes() for p in system['root'].iterdir() if p.is_file() and not p.is_symlink()}
        current_pid = adapter.process.pid
        lifecycle.install(package_path, first['sha256'], first['release'], sys.executable)
        assert adapter.process.pid == current_pid and adapter.restarts == 1
        import fcntl
        with lifecycle.locked():
            with pytest.raises(BlockingIOError):
                lifecycle.install(package_path, first['sha256'], first['release'], sys.executable)
        # A fully pinned candidate imports fine but refuses actual worker startup.
        changed = tmp_path / 'candidate'
        changed.mkdir()
        for name in ('stella_agent.py', 'node_files.py', 'node_files_delivery.py', 'node_files_lifecycle.py'):
            body = (source / name).read_bytes()
            if name == 'node_files.py':
                body = body.replace(b"FILE_MODULE_VERSION = '1.0.0'", b"FILE_MODULE_VERSION = '1.0.1'")
                body += b'\nclass FileWorker:\n    def __init__(self,*a,**k): raise RuntimeError("owned start failure")\n'
            (changed / name).write_bytes(body)
        failed_path = tmp_path / 'failed.tar'
        failed = lc.build_package(changed, failed_path)
        pointer = lifecycle.base / 'releases/current.json'
        saved_pointer, saved_unit, saved_state = pointer.read_bytes(), lifecycle.unit.read_bytes(), lifecycle.state_path.read_bytes()
        with pytest.raises(RuntimeError, match='actual child startup failed'):
            lifecycle.install(failed_path, failed['sha256'], failed['release'], sys.executable)
        assert pointer.read_bytes() == saved_pointer and lifecycle.unit.read_bytes() == saved_unit and lifecycle.state_path.read_bytes() == saved_state
        assert lifecycle.status()['authenticated_ready']
        # Successful explicit update, then explicit complete rollback.
        for name in ('node_files.py',):
            (changed / name).write_bytes((source / name).read_bytes().replace(b"FILE_MODULE_VERSION = '1.0.0'", b"FILE_MODULE_VERSION = '1.0.2'"))
        second_path = tmp_path / 'second.tar'
        second = lc.build_package(changed, second_path)
        assert lifecycle.install(second_path, second['sha256'], second['release'], sys.executable)['release'] == second['release']
        assert lifecycle.rollback()['release'] == first['release']
        # Fixture-only explicit authorized writable root; never a real root.
        lifecycle.stop()
        (lifecycle.config / 'files.env').write_text('STELLA_FILE_ROOTS=' + json.dumps(json.dumps({'fixture': {'path': str(system['root']), 'write': True}})) + '\n')
        assert lifecycle.install(package_path, first['sha256'], first['release'], sys.executable)['authenticated_ready']
        response = system['client'].post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': 930001, 'root': 'fixture', 'op': 'create', 'path': 'lifecycle-created'})
        assert response.status_code == 201, response.text
        for _ in range(120):
            result = system['client'].get('/node-files/requests/' + response.json()['id']).json()
            if result['state'] in ('done', 'failed', 'unknown'):
                break
            time.sleep(.05)
        assert result['state'] == 'done', result
        assert (system['root'] / 'lifecycle-created').read_bytes() == b''
        (system['root'] / 'lifecycle-created').unlink()
        lifecycle.stop()
        # Fail closed before a claim when installed module is lost; no fallback.
        module = lifecycle.base / 'releases' / first['release'] / 'node_files.py'
        module.unlink()
        worker_argv = [sys.executable, '-I', '-B', str(lifecycle.config / 'files-runtime' / first['sha256'] / 'node_files_lifecycle.py'), 'worker', '--instance', lifecycle.iid, '--code-root', str(lifecycle.code), '--config-root', str(lifecycle.config), '--allow-loopback']
        process = subprocess.run(worker_argv, env={**env, 'STELLA_FILE_ROOTS': '{}'}, cwd='/', capture_output=True, timeout=15)
        assert process.returncode == 1 and b'"event": "start"' not in process.stdout
        assert lifecycle.status()['integrity'] is False and lifecycle.status()['authenticated_ready'] is False
        assert all(p.read_bytes() == body for p, body in protected.items())
        events = []
        for log in adapter.logs:
            events.append({'log': log.name, 'events': [json.loads(line) for line in log.read_text().splitlines() if line.startswith('{')]})
        evidence = Path(os.environ['NODE_FILES_EVIDENCE'])
        (evidence / 'lifecycle-workers.json').write_text(json.dumps({'boundary': 'fixture systemd adapter; real independent ExecStart workers, HTTP and owned PG', 'first': first, 'failed': failed, 'second': second, 'rollback_pointer_unit_state_exact': True, 'default_empty_root_zero_writes': True, 'synthetic_authorized_create': True, 'missing_module_exit': process.returncode, 'events': events, 'protected_unchanged': [p.name for p in protected]}, indent=2))
    finally:
        adapter.halt()


def test_failed_authentication_never_reports_ready_and_leaves_no_installed_service(system, tmp_path, monkeypatch):
    lc, lifecycle, adapter, main_unit, env = make_fixture(system, tmp_path, monkeypatch)
    env['STELLA_TOKEN'] = 'synthetic-invalid-' + uuid4().hex
    (lifecycle.config / 'agent.env').write_text(''.join(k + '=' + json.dumps(v) + '\n' for k, v in env.items()))
    package = tmp_path / 'package.tar'
    info = lc.build_package(Path(lc.__file__).parent, package)
    try:
        with pytest.raises(RuntimeError, match='actual child startup failed'):
            lifecycle.install(package, info['sha256'], info['release'], sys.executable)
        assert not lifecycle.unit.exists() and not lifecycle.state_path.exists()
        assert not (lifecycle.base / 'releases/current.json').exists()
        assert lifecycle.status()['installed'] is False
        assert not adapter.enabled and adapter.info(lifecycle.service)['ActiveState'] == 'inactive'
    finally:
        adapter.halt()


@pytest.mark.parametrize('fault', ['credential-mode', 'identity', 'embedded-module', 'main-unit', 'symlink-base'])
def test_foreign_or_unsafe_instance_refused_without_start(system, tmp_path, monkeypatch, fault):
    lc, lifecycle, adapter, main_unit, env = make_fixture(system, tmp_path, monkeypatch)
    if fault == 'credential-mode':
        (lifecycle.config / 'agent.env').chmod(0o644)
    elif fault == 'identity':
        value = json.loads((lifecycle.config / 'instance.json').read_bytes())
        value['instance_id'] = 'f' * 24
        (lifecycle.config / 'instance.json').write_text(json.dumps(value))
    elif fault == 'embedded-module':
        (lifecycle.code / 'node_files.py').write_text('# optional embedded module')
    elif fault == 'main-unit':
        main_unit.write_text('User=root\n')
    else:
        lifecycle.base.symlink_to(tmp_path / 'unrelated')
        (tmp_path / 'unrelated').mkdir()
    with pytest.raises((lc.LifecycleError, OSError)):
        second = lc.Lifecycle(lifecycle.iid, code_base=lifecycle.code.parent, config_base=lifecycle.config.parent, unit_base=lifecycle.unit.parent, systemd=adapter, allow_loopback=True)
        package = tmp_path / 'package.tar'
        info = lc.build_package(Path(lc.__file__).parent, package)
        second.install(package, info['sha256'], info['release'], sys.executable)
    assert adapter.restarts == 0 and not lifecycle.unit.exists()


def test_missing_httpx_never_changes_resident_generation_or_service(system, tmp_path, monkeypatch):
    lc, lifecycle, adapter, main_unit, env = make_fixture(system, tmp_path, monkeypatch)
    package = tmp_path / 'package.tar'
    info = lc.build_package(Path(lc.__file__).parent, package)
    wrapper = tmp_path / 'python-without-site'
    wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -S "$@"\n')
    wrapper.chmod(0o755)
    with pytest.raises(lc.LifecycleError, match='httpx_preflight'):
        lifecycle.install(package, info['sha256'], info['release'], wrapper)
    assert not lifecycle.unit.exists() and not lifecycle.state_path.exists()
    assert not (lifecycle.base / 'releases/current.json').exists()
    assert adapter.restarts == 0


def test_main_instance_identity_removal_stops_existing_companion_before_more_claims(system, tmp_path, monkeypatch):
    lc, lifecycle, adapter, main_unit, env = make_fixture(system, tmp_path, monkeypatch)
    package = tmp_path / 'package.tar'
    info = lc.build_package(Path(lc.__file__).parent, package)
    try:
        assert lifecycle.install(package, info['sha256'], info['release'], sys.executable)['authenticated_ready']
        (lifecycle.config / 'instance.json').unlink()
        try:
            adapter.process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            pytest.fail('companion kept running after main instance identity removal')
        assert adapter.process.returncode == 1
        events = [json.loads(line) for line in adapter.logs[-1].read_text().splitlines()]
        assert events[-2]['event'] == 'stop' and events[-1]['event'] == 'lifecycle_refused'
    finally:
        adapter.halt()


def test_partial_bootstrap_copy_can_be_retried_without_foreign_partial_generation(system, tmp_path, monkeypatch):
    lc, lifecycle, adapter, main_unit, env = make_fixture(system, tmp_path, monkeypatch)
    package = tmp_path / 'package.tar'
    info = lc.build_package(Path(lc.__file__).parent, package)
    original = lc.atomic
    def fail_copy(path, body, *args, **kwargs):
        if Path(path).name == 'node_files_delivery.py':
            raise OSError('owned interrupted copy')
        return original(path, body, *args, **kwargs)
    monkeypatch.setattr(lc, 'atomic', fail_copy)
    with pytest.raises(OSError, match='owned interrupted copy'):
        lifecycle.install(package, info['sha256'], info['release'], sys.executable)
    assert not lifecycle.unit.exists() and adapter.restarts == 0
    monkeypatch.setattr(lc, 'atomic', original)
    try:
        assert lifecycle.install(package, info['sha256'], info['release'], sys.executable)['authenticated_ready']
    finally:
        adapter.halt()


def test_center_without_file_protocol_never_becomes_ready(system, tmp_path, monkeypatch, real_identity_transport):
    app = real_identity_transport
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, 'path', '') == '/agent/identity']
    lc, lifecycle, adapter, main_unit, env = make_fixture(system, tmp_path, monkeypatch)
    package = tmp_path / 'package.tar'
    info = lc.build_package(Path(lc.__file__).parent, package)
    try:
        with pytest.raises(RuntimeError, match='authenticated claim timeout'):
            lifecycle.install(package, info['sha256'], info['release'], sys.executable)
        assert not lifecycle.unit.exists() and not lifecycle.state_path.exists()
        assert not (lifecycle.base / 'releases/current.json').exists()
        assert adapter.info(lifecycle.service)['ActiveState'] == 'inactive'
    finally:
        adapter.halt()


def test_valid_token_for_different_node_cannot_claim_as_bound_instance(system, tmp_path, monkeypatch):
    lc, lifecycle, adapter, main_unit, env = make_fixture(system, tmp_path, monkeypatch)
    binding = json.loads((lifecycle.config / 'instance.json').read_bytes())
    binding['node_id'] = 930002
    (lifecycle.config / 'instance.json').write_text(json.dumps(binding))
    package = tmp_path / 'package.tar'
    info = lc.build_package(Path(lc.__file__).parent, package)
    try:
        with pytest.raises(RuntimeError, match='actual child startup failed'):
            lifecycle.install(package, info['sha256'], info['release'], sys.executable)
        assert not lifecycle.unit.exists() and not lifecycle.state_path.exists()
        assert adapter.info(lifecycle.service)['ActiveState'] == 'inactive'
    finally:
        adapter.halt()
