"""Unmodified historical updaters against real owned-loopback release routes.

The .15 fixture is byte-identical to the live Nyarch file at diagnosis time.
The .12 fixture is historical; unreachable HK has NOT been fingerprint-verified.
No production credential, service, path or network is used.
"""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest
import uvicorn
from starlette.responses import JSONResponse, Response

from test_agent_rollout_compat import ROOT, release_app

FIXTURES = ROOT / 'tests_isolated/fixtures/agent_rollout'
PROVENANCE = json.loads((FIXTURES / 'provenance.json').read_text())
LABELS = tuple(PROVENANCE)


@pytest.fixture(params=LABELS)
def legacy(request, tmp_path):
    row = PROVENANCE[request.param]
    body = gzip.decompress((FIXTURES / row['fixture']).read_bytes())
    assert hashlib.sha256(body).hexdigest() == row['sha256']
    assert len(body) == row['size']
    path = tmp_path / 'stella_agent.py'
    path.write_bytes(body)
    path.chmod(0o640)
    spec = importlib.util.spec_from_file_location('owned_legacy', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path, body


@pytest.fixture
def center(monkeypatch):
    app = release_app()
    state = {'seen': [], 'manifest': None, 'body': None, 'status': 200}

    @app.middleware('http')
    async def observe(request, call_next):
        state['seen'].append(request.url.path)
        if request.url.path == '/agent/version' and state['manifest'] is not None:
            return JSONResponse(state['manifest'])
        if request.url.path == '/agent/script' and (state['body'] is not None or state['status'] != 200):
            return Response(state['body'] or b'', status_code=state['status'], headers={'Location': '/unexpected'})
        return await call_next(request)

    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    worker.start()
    deadline = time.monotonic() + 5
    while not server.started and worker.is_alive() and time.monotonic() < deadline:
        time.sleep(.01)
    assert server.started
    # Guard all Python socket clients in this process, including the real old
    # HTTP clients. Only this fixture's exact listening endpoint is allowed.
    original_connect = socket.socket.connect
    def connect(client, address):
        assert address == ('127.0.0.1', port), ('non-owned connection', address)
        return original_connect(client, address)
    monkeypatch.setattr(socket.socket, 'connect', connect)
    try:
        yield 'http://127.0.0.1:' + str(port), state
    finally:
        server.should_exit = True
        worker.join(5)
        sock.close()
        assert not worker.is_alive()


def instance(legacy, center, fallback):
    module, path, body = legacy
    if fallback:
        module.httpx = None
    else:
        assert module.httpx is not None, 'httpx transport must actually run'
    return module.Agent(center[0], 'owned-fixture-only')


@pytest.mark.parametrize('pin', ['0.6.11', '0.6.15'])
@pytest.mark.parametrize('fallback', [False, True], ids=['httpx', 'urllib'])
def test_parked_pin_never_downloads_or_restarts_even_for_older_12(legacy, center, monkeypatch, fallback, pin):
    monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION', pin)
    agent = instance(legacy, center, fallback)
    module, path, body = legacy
    with patch.object(module.os, 'execv') as execute:
        agent.check_update()
    assert path.read_bytes() == body
    execute.assert_not_called()
    assert center[1]['seen'] == ['/agent/version']


@pytest.mark.parametrize('fallback', [False, True], ids=['httpx', 'urllib'])
def test_exact_18_source_upgrades_old_full_script_without_service_restart(legacy, center, monkeypatch, fallback):
    monkeypatch.delenv('STELLA_AGENT_ROLLOUT_VERSION', raising=False)
    agent = instance(legacy, center, fallback)
    module, path, body = legacy
    real_run = subprocess.run
    probes = []
    def run(argv, **kw):
        assert argv[0] == sys.executable and argv[1:3] == ['-B', '-c']
        assert Path(argv[-2]).parent == path.parent
        probes.append(argv[-2])
        return real_run(argv, **kw)
    with patch.object(module.os, 'execv') as execute, patch.object(module.subprocess, 'run', run):
        agent.check_update()
    assert path.read_bytes() == (ROOT / 'agent/stella_agent.py').read_bytes()
    assert path.stat().st_mode & 0o777 == 0o640
    assert len(probes) == 2 and probes[1] == str(path)
    execute.assert_called_once_with(sys.executable, [sys.executable, str(path)] + sys.argv[1:])
    assert center[1]['seen'] == ['/agent/version', '/agent/script']


@pytest.mark.parametrize('failure', ['missing', 'hash', 'size', 'same_version', 'older_version', 'malformed_version', 'payload_version', 'syntax', 'redirect', 'http503'])
@pytest.mark.parametrize('fallback', [False, True], ids=['httpx', 'urllib'])
def test_old_updaters_reject_invalid_metadata_or_payload(legacy, center, monkeypatch, failure, fallback):
    monkeypatch.delenv('STELLA_AGENT_ROLLOUT_VERSION', raising=False)
    agent = instance(legacy, center, fallback)
    module, path, body = legacy
    payload = (ROOT / 'agent/stella_agent.py').read_bytes()
    manifest = dict(version='0.6.20', sha256=hashlib.sha256(payload).hexdigest(), size=len(payload))
    state = center[1]
    state['manifest'] = manifest
    if failure == 'missing': manifest.pop('sha256')
    elif failure == 'hash': manifest['sha256'] = '0' * 64
    elif failure == 'size': manifest['size'] += 1
    elif failure == 'same_version': manifest['version'] = module.AGENT_VERSION
    elif failure == 'older_version': manifest['version'] = '0.6.11'
    elif failure == 'malformed_version': manifest['version'] = '0.6.018'
    elif failure in ('payload_version', 'syntax'):
        assert payload.count(b'AGENT_VERSION = "0.6.20"') == 1
        payload = payload.replace(b'AGENT_VERSION = "0.6.20"', b'AGENT_VERSION = "0.6.18"', 1) if failure == 'payload_version' else b'def broken(:\n'
        state['body'] = payload
        manifest.update(sha256=hashlib.sha256(payload).hexdigest(), size=len(payload))
    else:
        state['status'] = 302 if failure == 'redirect' else 503
    with patch.object(module.os, 'execv') as execute:
        agent.check_update()
    assert path.read_bytes() == body
    assert path.stat().st_mode & 0o777 == 0o640
    execute.assert_not_called()
    assert not list(path.parent.glob('.stella-*'))
    assert '/unexpected' not in state['seen']


def test_actual_relocated_exec_to_real_18_help_leaves_exact_old_backup(legacy, center, monkeypatch):
    monkeypatch.delenv('STELLA_AGENT_ROLLOUT_VERSION', raising=False)
    module, path, body = legacy
    # The exact full old module executes the exact full new source. --help exits
    # before new main can create an Agent or contact any service.
    code = ('import runpy,sys; p=sys.argv[1]; m=runpy.run_path(p,run_name="owned_old"); '
            'sys.argv=[p,"--help"]; m["Agent"](sys.argv_url,"owned-fixture-only").check_update()')
    code = code.replace('sys.argv_url', repr(center[0]))
    env = {k: os.environ[k] for k in ('PATH', 'TMPDIR') if k in os.environ}
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(path)],
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert '--url' in result.stdout and '--token' in result.stdout
    assert path.read_bytes() == (ROOT / 'agent/stella_agent.py').read_bytes()
    backups = list(path.parent.glob('.stella-rollback-*.py'))
    assert len(backups) == 1 and backups[0].read_bytes() == body
    assert backups[0].stat().st_mode & 0o777 == 0o640
    assert center[1]['seen'] == ['/agent/version', '/agent/script']
