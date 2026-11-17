"""Real stdlib Agent transport against the owned TCP FastAPI/PostgreSQL fixture."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from agent.node_files import FileWorker, Sandbox
from agent.stella_agent import _FileHTTPClient
from test_pipeline import submit, complete
from test_write_pipeline import upload
from test_auto_config import auto  # Reuse the nonce-admitted automatic-root fixture.


def test_stdlib_automatic_root_roundtrip(auto, tmp_path, monkeypatch):
    """Run every original real-UID0/chroot assertion with only transport swapped."""
    from test_auto_config import test_default_config_real_root_worker_reads_and_writes_fabricated_root
    original = subprocess.Popen
    def stdlib_child(argv, *args, **kwargs):
        argv = list(argv)
        for index, value in enumerate(argv):
            if str(value).endswith('/tests_node_files/auto_root_worker.py'):
                argv[index] = str(Path(__file__).with_name('stdlib_root_worker.py'))
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', stdlib_child)
    test_default_config_real_root_worker_reads_and_writes_fabricated_root(auto, tmp_path)


def test_stdlib_real_http_file_roundtrip(system):
    s = dict(system)
    client = _FileHTTPClient({'origin': s['url'], 'token': s['token'], 'allow_loopback': True})
    s['worker'] = FileWorker(s['url'], s['token'], Sandbox({'fixture': {'path': str(s['root']), 'write': True}}), client=client)
    try:
        assert complete(s, submit(s, 'list'))['state'] == 'done'
        assert complete(s, submit(s, 'mkdir', 'stdlib-roundtrip'))['state'] == 'done'
        data = b'stdlib isolated upload 32 bytes!'
        assert len(data) == 32
        result = upload(s, 'upload', 'stdlib-roundtrip/body.txt', data)
        assert result['state'] == 'done', result
        assert (s['root'] / 'stdlib-roundtrip/body.txt').read_bytes() == data
        preview = complete(s, submit(s, 'preview', 'stdlib-roundtrip/body.txt'))
        assert preview['state'] == 'done', preview
        assert preview['result']['text'].encode() == data
        edited = 'stdlib 编辑完成\n'.encode()
        assert upload(s, 'edit', 'stdlib-roundtrip/body.txt', edited, etag=preview['result']['etag'])['state'] == 'done'
        result = complete(s, submit(s, 'download', 'stdlib-roundtrip/body.txt'))
        assert result['state'] == 'done', result
        response = s['client'].get('/node-files/requests/' + result['id'] + '/download')
        assert response.status_code == 200
        assert response.content == edited
        assert response.headers['x-file-sha256'] == hashlib.sha256(edited).hexdigest()
    finally:
        client.close()


@pytest.mark.parametrize('size', [0, 32, 65536, 65537, 153600, 358400])
def test_stdlib_subprocess_http_roundtrip(system, size):
    s = system
    repo = Path(__file__).resolve().parents[1]
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR', 'PYTHONPATH')}
    env.update(PYTHONDONTWRITEBYTECODE='1', NODE_FILE_WORKER_URL=s['url'], NODE_FILE_WORKER_TOKEN=s['token'], STELLA_FILE_ROOTS=json.dumps({'fixture': {'path': str(s['root']), 'write': True}}))
    child = subprocess.Popen([sys.executable, '-B', str(repo / 'tests_node_files/stdlib_worker.py')], env=env, cwd=s['root'].parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    def finish(job):
        until = time.monotonic() + 15
        while time.monotonic() < until:
            assert child.poll() is None, 'child exited; first exception traceback is in teardown output'
            result = s['client'].get('/node-files/requests/' + job['id'])
            assert result.status_code == 200, result.text
            result = result.json()
            if result['state'] in ('done', 'failed', 'unknown', 'cancelled'):
                assert result['state'] == 'done', result
                return result
            time.sleep(.02)
        pytest.fail('stdlib child did not finish; no write is replayed')
    def send(op, path, data, **kwargs):
        job = submit(s, op, path, size=len(data), sha256=hashlib.sha256(data).hexdigest(), **kwargs)
        for offset in range(0, len(data), 65536):
            r = s['client'].put('/node-files/requests/' + job['id'] + '/upload', params={'offset': offset}, content=data[offset:offset + 65536])
            assert r.status_code == 200, r.text
        assert s['client'].post('/node-files/requests/' + job['id'] + '/seal').status_code == 200
        return finish(job)
    try:
        assert finish(submit(s, 'list'))['result']['entries']
        directory = 'stdlib-child-' + str(size)
        finish(submit(s, 'mkdir', directory))
        path = directory + '/body.txt'
        data = b'a' * size
        send('upload', path, data)
        assert (s['root'] / path).read_bytes() == data
        # Preview has a separate protocol limit; download validates the complete
        # body for every transfer boundary, including >preview-limit payloads.
        preview = finish(submit(s, 'preview', path)) if size <= 65536 else None
        if preview is not None:
            assert preview['result']['text'].encode() == data
            data = '独立 stdlib 子进程编辑\n'.encode()
            send('edit', path, data, etag=preview['result']['etag'])
            assert (s['root'] / path).read_bytes() == data
        download = finish(submit(s, 'download', path))
        response = s['client'].get('/node-files/requests/' + download['id'] + '/download')
        assert response.status_code == 200
        assert response.content == data
        assert response.headers['x-file-sha256'] == hashlib.sha256(data).hexdigest()
    finally:
        if child.poll() is None:
            child.terminate()
        out, errors = child.communicate(timeout=15)
        evidence = Path(os.environ['NODE_FILES_EVIDENCE'])
        # Synthetic credentials only; complete native traceback is retained.
        (evidence / ('stdlib-child-' + str(size) + '.log')).write_text(out + errors)
        assert child.returncode == 0, out + errors
        started = json.loads(out.splitlines()[0])
        assert started['pid'] != os.getpid() and started['uid'] == 0
        assert not started['app_imported'] and not started['postgres_environment_present'] and not started['httpx_imported']


def test_managed_stdlib_child_upload(system, tmp_path):
    """Actual immutable-package prepare/child/parent-death protocol, no fake tick."""
    from agent import stella_agent as module
    from fastapi import Depends, HTTPException
    from app.security import agent_token
    s = system
    identity = {'center_id': 'f' * 64, 'node_id': 930001}
    def fixture_identity(token=Depends(agent_token)):
        if token != s['token']:
            raise HTTPException(401, 'invalid_agent')
        return identity
    routes = list(s['app'].router.routes)
    s['app'].add_api_route('/agent/identity', fixture_identity, methods=['GET'])
    legacy = json.dumps({'fixture': {'path': str(s['root']), 'write': True}})
    supervisor = module._FileSupervisor(lambda: {'origin': s['url'], 'token': s['token'], 'binding': identity, 'legacy': legacy, 'store': str(tmp_path / 'owned-packages')}, allow_loopback=True, refresh=.15)
    def finish(job):
        until = time.monotonic() + 15
        while time.monotonic() < until:
            supervisor.tick()
            result = s['client'].get('/node-files/requests/' + job['id']).json()
            if result['state'] in ('done', 'failed', 'unknown', 'cancelled'):
                assert result['state'] == 'done', result
                return result
            time.sleep(.03)
        pytest.fail('managed stdlib child did not finish; never replay write')
    def send(op, path, data, **extra):
        job = submit(s, op, path, size=len(data), sha256=hashlib.sha256(data).hexdigest(), **extra)
        for offset in range(0, len(data), 65536):
            response = s['client'].put('/node-files/requests/' + job['id'] + '/upload', params={'offset': offset}, content=data[offset:offset + 65536])
            assert response.status_code == 200, response.text
        assert s['client'].post('/node-files/requests/' + job['id'] + '/seal').status_code == 200
        return finish(job)
    try:
        finish(submit(s, 'list'))
        finish(submit(s, 'mkdir', 'managed-stdlib'))
        data = b'stdlib isolated upload 32 bytes!'
        send('upload', 'managed-stdlib/body.txt', data)
        assert (s['root'] / 'managed-stdlib/body.txt').read_bytes() == data
        preview = finish(submit(s, 'preview', 'managed-stdlib/body.txt'))
        assert preview['result']['text'].encode() == data
        edited = 'managed 子进程保存\n'.encode()
        send('edit', 'managed-stdlib/body.txt', edited, etag=preview['result']['etag'])
        result = finish(submit(s, 'download', 'managed-stdlib/body.txt'))
        response = s['client'].get('/node-files/requests/' + result['id'] + '/download')
        assert response.status_code == 200 and response.content == edited
        assert supervisor.worker is not None and supervisor.worker.poll() is None
        assert supervisor.worker.args[1:3] == ['-I', '-B']
    finally:
        supervisor.close()
        s['app'].router.routes[:] = routes
