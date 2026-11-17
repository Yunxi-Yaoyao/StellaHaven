"""Real TCP FastAPI + real file worker; only seeded synthetic identity/node."""
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy import text
from app.database import Base, engine, sessionLocal
from app.models import User, AuthSession, Node
from app.models.node_file import FileAgent, FileJob
from app.routers.node_files import router, agent_router
from app.security import make_access_token
from agent.node_files import Sandbox, FileWorker



def submit(s, op, path='', **extra):
    response = s['client'].post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': 930001, 'root': 'fixture', 'op': op, 'path': path, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def complete(s, job):
    s['worker'].tick()
    response = s['client'].get('/node-files/requests/' + job['id'])
    assert response.status_code == 200, response.text
    return response.json()


def test_real_worker_list_preview_stream_download(system):
    s = system
    nodes = s['client'].get('/node-files/nodes').json()
    assert nodes[0]['online'] and nodes[0]['roots'][0]['id'] == 'fixture'
    result = complete(s, submit(s, 'list'))
    assert result['state'] == 'done'
    assert 'hello.txt' in [x['name'] for x in result['result']['entries']]
    assert '.hidden' not in [x['name'] for x in result['result']['entries']]
    preview = complete(s, submit(s, 'preview', 'hello.txt'))
    assert preview['result']['text'] == (s['root'] / 'hello.txt').read_text()
    with sessionLocal() as db:
        persisted = db.get(FileJob, preview['id'])
        assert 'text' not in persisted.result, 'file body must not persist in the durable task/audit JSON'
    job = complete(s, submit(s, 'download', 'download.bin'))
    assert job['state'] == 'done'
    with s['client'].stream('GET', '/node-files/requests/' + job['id'] + '/download') as response:
        chunks = list(response.iter_bytes(65536))
        assert len(chunks) > 1 and b''.join(chunks) == s['binary']
        assert response.headers['x-file-sha256'] == hashlib.sha256(s['binary']).hexdigest()


def test_path_root_token_and_late_cancel(system):
    s = system
    for path in ['../etc/passwd', '/etc/passwd', 'x/../hello.txt']:
        r = s['client'].post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': 930001, 'root': 'fixture', 'op': 'preview', 'path': path})
        assert r.status_code == 422
    denied = complete(s, submit(s, 'preview', 'escape/passwd'))
    assert denied['state'] == 'failed'
    job = submit(s, 'list')
    other = httpx.get(s['url'] + '/agent/files/requests/' + job['id'], params={'lease': 'x' * 48}, headers={'Authorization': 'Bearer wrong'})
    assert other.status_code == 401
    s['client'].post('/node-files/requests/' + job['id'] + '/cancel').raise_for_status()
    assert complete(s, job)['state'] == 'cancelled'
    with sessionLocal() as db:
        row = db.get(FileJob, job['id'])
        assert row.lease is None  # cancelled before claim cannot be executed late


def test_agent_entry_optional_hook(system, monkeypatch, tmp_path):
    from agent import stella_agent as module  # pyright: ignore[reportAttributeAccessIssue]
    from fastapi import Depends, HTTPException
    from app.security import agent_token
    s = system
    # The owning fixture mounts only the file router. Supply its independent
    # synthetic center identity; actual file config/release/jobs stay unmodified.
    identity = {'center_id': 'f' * 64, 'node_id': 930001}
    def fixture_identity(token=Depends(agent_token)):
        if token != s['token']:
            raise HTTPException(401, 'invalid_agent')
        return identity
    prior_routes = list(s['app'].router.routes)
    s['app'].add_api_route('/agent/identity', fixture_identity, methods=['GET'])
    legacy = json.dumps({'fixture': {'path': str(s['root']), 'write': True}})
    monkeypatch.setenv('STELLA_FILE_ROOTS', legacy)
    agent = object.__new__(module.Agent)
    agent.url, agent.token = s['url'], s['token']
    monkeypatch.setattr(agent, '_file_snapshot', lambda: {
        'origin': s['url'], 'token': s['token'], 'binding': identity,
        'legacy': legacy, 'store': str(tmp_path / 'owned-releases')})
    original = module._FileSupervisor
    monkeypatch.setattr(module, '_FileSupervisor', lambda snapshot: original(snapshot, allow_loopback=True, refresh=.15))
    job = submit(s, 'preview', 'hello.txt')
    try:
        deadline = time.monotonic() + 15
        result = {'state': 'pending'}
        while time.monotonic() < deadline:
            agent._file_tick()
            result = s['client'].get('/node-files/requests/' + job['id']).json()
            if result['state'] == 'done':
                break
            time.sleep(.03)
        assert result['state'] == 'done'
        assert agent._file_supervisor.worker is not None
        assert not hasattr(agent, '_file_worker')  # no synchronous inline fallback
    finally:
        if hasattr(agent, '_file_supervisor'):
            agent._file_supervisor.close()
        s['app'].router.routes[:] = prior_routes


def test_owner_node_root_and_deadline_fences(system):
    s = system
    job = submit(s, 'list')
    claim = s['worker'].client.post('/agent/files/claim', json={'roots': {'fixture': True}}).json()
    assert claim['id'] == job['id']
    # A distinct authenticated synthetic node cannot consume another node's lease.
    with sessionLocal() as db:
        db.add(Node(id=930002, name='other-synthetic', platform='linux', host='synthetic-other', status='online', token='synthetic-other-token'))
        db.commit()
    denied = httpx.get(s['url'] + '/agent/files/requests/' + job['id'], params={'lease': claim['lease']}, headers={'Authorization': 'Bearer synthetic-other-token'})
    assert denied.status_code == 404
    # Lease alone is not authority for a different session, even for the same uid.
    new_sid = uuid4()
    with sessionLocal() as db:
        db.add(AuthSession(id=new_sid, user_id=s['uid'], refresh_hash=uuid4().hex))
        db.commit()
    with httpx.Client(base_url=s['url'], cookies={'stella_at': make_access_token(str(s['uid']), str(new_sid))}) as other:
        assert other.get('/node-files/requests/' + job['id']).status_code == 404
    s['client'].post('/node-files/requests/' + job['id'] + '/cancel').raise_for_status()
    late = s['worker'].client.post('/agent/files/requests/' + job['id'] + '/result', json={'lease': claim['lease'], 'result': {'entries': []}})
    assert late.status_code == 409
    assert s['client'].get('/node-files/requests/' + job['id']).json()['state'] == 'cancelled'
    timeout = submit(s, 'preview', 'hello.txt')
    with sessionLocal() as db:
        db.get(FileJob, timeout['id']).expires = time.time() - 1
        db.commit()
    assert complete(s, timeout)['state'] == 'cancelled'
    original = s['policy'].read_text()
    try:
        s['policy'].write_text('{}')
        denied = s['client'].post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': 930001, 'root': 'fixture', 'op': 'list'})
        assert denied.status_code == 404
    finally:
        s['policy'].write_text(original)


def test_offline_and_revoked_session_no_execution(system):
    s = system
    with sessionLocal() as db:
        db.get(Node, 930001).status = 'offline'
        db.commit()
    denied = s['client'].post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': 930001, 'root': 'fixture', 'op': 'list'})
    assert denied.status_code == 409 and denied.json()['detail'] == 'node_offline'
    with sessionLocal() as db:
        db.get(Node, 930001).status = 'online'
        db.commit()
    job = submit(s, 'list')
    with sessionLocal() as db:
        db.get(AuthSession, s['sid']).revoked = True
        db.commit()
    s['worker'].tick()
    assert s['client'].get('/node-files/requests/' + job['id']).status_code == 401
    with sessionLocal() as db:
        assert db.get(FileJob, job['id']).state == 'cancelled'
        db.get(AuthSession, s['sid']).revoked = False
        db.commit()


def test_inflight_authenticated_worker_renews_file_presence(system):
    s = system
    job = submit(s, 'list')
    claim = s['worker'].client.post('/agent/files/claim', json={'roots': {'fixture': True}}).json()
    with sessionLocal() as db:
        db.get(FileAgent, 930001).seen = time.time() - 16
        db.commit()
    alive = s['worker'].client.get('/agent/files/requests/' + job['id'], params={'lease': claim['lease']})
    assert alive.status_code == 200 and alive.json()['state'] == 'running'
    s['client'].post('/node-files/requests/' + job['id'] + '/cancel').raise_for_status()


def test_native_vue_browser(system):
    run_native_browser(system, 'browser.mjs')


def test_draft_scope_browser(system):
    run_native_browser(system, 'draft_scope.mjs')


def run_native_browser(system, script):
    import subprocess
    repo = Path(__file__).resolve().parents[1]
    assert (repo / 'tests_node_files/worker.py').is_file(), 'independent file-worker process entry missing'
    s = system
    evidence = Path(os.environ['NODE_FILES_EVIDENCE'])
    cfg = {'backend': s['url'], 'cookie': s['client'].cookies.get('stella_at'), 'root': str(s['root']), 'evidence': str(evidence), 'sha256': hashlib.sha256(s['binary']).hexdigest(), 'bytes': len(s['binary'])}
    config = s['root'].parent / 'browser-private.json'
    config.write_text(json.dumps(cfg))
    script_prefix = 'F2' if script == 'browser.mjs' else 'draft'
    worker_env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'PYTHONPATH')}
    # Browser-only synthetic choices exercise actual Dropdown value changes,
    # without changing the production root/scope protocol or any real node.
    readonly = s['root'].parent / 'browser-readonly-root'
    readonly.mkdir(exist_ok=True)
    (readonly / 'read-only.txt').write_text('真实只读允许根回读\n')
    policy = json.loads(s['policy'].read_text())
    policy['930001']['readonly'] = {'owners': [str(s['uid'])], 'label': '只读目录', 'write': False}
    policy['930003'] = {'fixture': {'owners': [str(s['uid'])], 'label': '离线目录', 'write': False}}
    s['policy'].write_text(json.dumps(policy))
    with sessionLocal() as db:
        if not db.get(Node, 930003):
            db.add(Node(id=930003, name='离线文件节点', platform='linux', host='synthetic-dropdown-offline', status='offline', token='synthetic-dropdown-offline-' + uuid4().hex))
            db.commit()
    worker_env.update({'NODE_FILE_WORKER_URL': s['url'], 'NODE_FILE_WORKER_TOKEN': s['token'], 'STELLA_FILE_ROOTS': json.dumps({'fixture': {'path': str(s['root']), 'write': True}, 'readonly': {'path': str(readonly), 'write': False}}), 'PYTHONDONTWRITEBYTECODE': '1'})
    worker = subprocess.Popen([sys.executable, str(repo / 'tests_node_files/worker.py')], cwd=s['root'].parent, env=worker_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        node = os.environ.get('STELLA_CI_NODE', '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node')
        result = subprocess.run([node, str(repo / 'tests_node_files' / script), str(config)], capture_output=True, text=True, timeout=120, env={**os.environ, 'NODE_ENV': '', 'PLAYWRIGHT_BROWSERS_PATH': '/root/.cache/ms-playwright'})
        (evidence / (script_prefix + '-browser.log')).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        assert worker.poll() is None, 'independent worker exited before browser completion'
    finally:
        worker.terminate()
        output, errors = worker.communicate(timeout=15)
        (evidence / (script_prefix + '-independent-worker.log')).write_text(output + errors)
        assert worker.returncode == 0, output + errors
        events = [json.loads(line) for line in output.splitlines()]
        assert events[0]['event'] == 'start' and events[0]['pid'] != os.getpid()
        assert not events[0]['app_imported'] and not events[0]['postgres_environment_present']
        assert not any(event['event'] == 'worker_error' for event in events), events
        assert events[-1]['event'] == 'stop' and events[-1]['ticks'] > 0
