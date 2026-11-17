"""Mandatory owned TCP/main/lifespan/PG proof of periodic bootstrap timeouts.

The runner must admit a nonce database and either a read-only-host sandbox
or its nonprivileged CI job-private overlay/internal sidecar network. No clock, expiry, lease, ACK, authorization or worker code is replaced.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4

import httpx
import pytest
import uvicorn


@pytest.mark.parametrize('endpoint', ['/agent/files/config', '/agent/identity'])
def test_active_upload_survives_periodic_network_timeout(tmp_path, monkeypatch, endpoint):
    from tests_agent_unified.conftest import require_os_fixture
    require_os_fixture()
    assert not Path('.env').exists()
    nonce = os.environ['NODE_FILES_AUTO_NONCE']
    receipt = json.loads(Path(os.environ['NODE_FILES_AUTO_RECEIPT']).read_text())
    assert receipt == {'nonce': nonce, 'database': 'nodefiles_' + nonce}
    def guard(event, args):
        if event == 'socket.connect' and isinstance(args[1], tuple):
            assert args[1][0] in ('127.0.0.1', '::1'), 'unknown destination'
    sys.addaudithook(guard)
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    origin = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    for key, value in {
        'STELLA_MAIN_ORIGIN': origin, 'STELLA_TRUSTED_ORIGINS': origin,
        'STELLA_COOKIE_SECURE': 'false', 'STELLA_NODE_FILES_ENABLED': '1',
        'STELLA_NODE_FILE_STATE': str(tmp_path / 'spool'),
        'STELLA_BACKUP_DATA_ROOT': str(tmp_path / 'backup-data'),
        'STELLA_BACKUP_DIRECTORY': str(tmp_path / 'backups'),
        'STELLA_BACKUP_RECEIPT_DIR': str(tmp_path / 'receipts'),
    }.items():
        monkeypatch.setenv(key, value)
    from app.database import Base, engine, sessionLocal
    import main
    from app.models import User, AuthSession, Node
    from app.models.config import AppConfig
    from app.models.node_file import FileAgent, FileJob
    from app.services import admin_security
    from app.security import make_access_token
    from sqlalchemy import delete, text
    from agent import stella_agent as module
    with engine.begin() as conn:
        assert conn.execute(text('SELECT current_database(),current_user')).one() == (receipt['database'], receipt['database'])
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
        Base.metadata.create_all(conn)
    uid, sid = uuid4(), uuid4()
    node_id = 930000 + (1 if endpoint.endswith('config') else 2)
    token = 'synthetic-refresh-' + uuid4().hex
    monkeypatch.setenv('STELLA_OWNER_ID', str(uid))
    with sessionLocal() as db:
        # CI runs both parameters in one process on its fresh owned database.
        assert db.get(Node, node_id) is None
        db.add(User(id=uid, username='refresh-' + uid.hex, display_name='owned fixture')); db.flush()
        db.add(AuthSession(id=sid, user_id=uid, refresh_hash=uuid4().hex))
        db.add(Node(id=node_id, name='owned refresh', platform='linux', host='synthetic', status='online', token=token))
        db.add(AppConfig(key=admin_security.STATE_KEY, value=json.dumps({'owner_id': str(uid)})))
        db.commit()
    upload_entered, upload_release = threading.Event(), threading.Event()
    refresh_entered, refresh_release = threading.Event(), threading.Event()
    controls = {'active_upload': None, 'delay_refresh': False}
    wire, notices, preps = [], [], []
    async def controlled_wire(scope, receive, send):
        import asyncio
        method, path = scope.get('method'), scope.get('path')
        if method == 'GET' and path == controls['active_upload']:
            upload_entered.set()
            while not upload_release.is_set(): await asyncio.sleep(.01)
        elif method == 'GET' and path == endpoint and controls['delay_refresh']:
            refresh_entered.set()
            while not refresh_release.is_set(): await asyncio.sleep(.01)
        async def observed_send(message):
            if message['type'] == 'http.response.start':
                wire.append({'method': method, 'path': path, 'status': message['status']})
            await send(message)
        return await main.app(scope, receive, observed_send)
    server = uvicorn.Server(uvicorn.Config(controlled_wire, log_level='warning', lifespan='on'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True); thread.start()
    until = time.monotonic() + 8
    while not server.started and time.monotonic() < until: time.sleep(.025)
    assert server.started, 'real main lifespan startup failed'
    evidence = Path(os.environ['NODE_FILES_EVIDENCE'])
    tag = endpoint.rsplit('/', 1)[1]
    events = {'endpoint': endpoint, 'notices': notices, 'wire': wire, 'preparations': preps}
    stderr = open(evidence / ('child-' + tag + '.log'), 'w')
    real_popen = subprocess.Popen
    def observed_popen(argv, *args, **kwargs):
        if isinstance(argv, list) and any(x in argv for x in ('--file-prepare', '--file-child')):
            kwargs['stderr'] = stderr
        child = real_popen(argv, *args, **kwargs)
        if isinstance(argv, list) and '--file-prepare' in argv: preps.append(child)
        return child
    monkeypatch.setattr(subprocess, 'Popen', observed_popen)
    supervisor = None
    try:
        with httpx.Client(base_url=origin, headers={'Origin': origin}, cookies={'stella_at': make_access_token(str(uid), str(sid))}, timeout=10) as client:
            identity = httpx.get(origin + '/agent/identity', headers={'Authorization': 'Bearer ' + token}).json()
            supervisor = module._FileSupervisor(lambda: {'origin': origin, 'token': token, 'binding': identity, 'legacy': None, 'store': str(tmp_path / 'packages')}, allow_loopback=True)
            supervisor._notice = notices.append
            until = time.monotonic() + 15
            while time.monotonic() < until:
                supervisor.tick()
                if supervisor.worker and client.get('/node-files/nodes').status_code == 200:
                    # Actual child claim registers FileAgent; a real list proves readiness.
                    nodes = client.get('/node-files/nodes').json()
                    if any(n['id'] == node_id and n['online'] for n in nodes): break
                time.sleep(.025)
            else: pytest.fail('no verified managed worker')
            oldworker = supervisor.worker
            def submit(op, path, **extra):
                response = client.post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': node_id, 'root': 'system', 'op': op, 'path': str(path).lstrip('/'), **extra})
                assert response.status_code == 201, response.text
                return response.json()
            def state(job):
                response = client.get('/node-files/requests/' + job['id'])
                assert response.status_code == 200, response.text
                return response.json()
            def complete(job):
                until = time.monotonic() + 15
                while time.monotonic() < until:
                    supervisor.tick(); value = state(job)
                    if value['state'] in ('done', 'failed', 'unknown', 'cancelled'):
                        assert value['state'] == 'done', value
                        return value
                    time.sleep(.025)
                pytest.fail('bounded completion timeout; never replay')
            target = tmp_path / 'upload.txt'
            data = b'stdlib isolated upload 32 bytes!'
            job = submit('upload', target, size=len(data), sha256=hashlib.sha256(data).hexdigest())
            controls['active_upload'] = '/agent/files/requests/' + job['id'] + '/upload'
            assert client.put('/node-files/requests/' + job['id'] + '/upload', params={'offset': 0}, content=data).status_code == 200
            assert client.post('/node-files/requests/' + job['id'] + '/seal').status_code == 200
            assert upload_entered.wait(6), 'real upload GET never blocked'
            before = state(job); assert before['state'] == 'running', before
            with sessionLocal() as db:
                row = db.get(FileJob, job['id']); assert row.lease and row.state == 'running'
                events.update(job=job['id'], expires=row.expires, claimed=True, old_worker_pid=oldworker.pid)
            controls['delay_refresh'] = True
            # Keep production refresh=5 and socket timeout=3; no synthetic time.
            until = time.monotonic() + 9
            refresh_child = None
            while time.monotonic() < until:
                supervisor.tick()
                if refresh_entered.is_set():
                    if refresh_child is None: refresh_child = supervisor.preparing
                    if refresh_child is not None and refresh_child.poll() is not None:
                        supervisor.tick(); break
                time.sleep(.02)
            assert refresh_entered.is_set() and refresh_child is not None
            assert refresh_child.poll() is not None, 'no actual preparation timeout'
            events.update(refresh_returncode=refresh_child.returncode, same_worker=supervisor.worker is oldworker, old_worker_returncode=oldworker.poll(), target_absent_while_blocked=not target.exists())
            controls['delay_refresh'] = False; refresh_release.set(); upload_release.set()
            if oldworker.poll() is not None:
                # RED records the real deadline/unknown consequence without replay,
                # manual expires changes, fabricated ACK or clock acceleration.
                until = time.monotonic() + 68
                while time.monotonic() < until:
                    supervisor.tick(); final = state(job)
                    if final['state'] == 'unknown': break
                    time.sleep(.1)
                events.update(red_final=final['state'], red_target_absent=not target.exists())
                assert final['state'] == 'unknown', final
            assert supervisor.worker is oldworker and oldworker.poll() is None, events
            assert refresh_child.returncode == 75
            assert 'temporary configuration network timeout; verified worker retained' in notices
            assert supervisor.next_prepare > time.monotonic()
            assert not target.exists() or target.read_bytes() == data
            result = complete(job)
            assert target.read_bytes() == data
            assert hashlib.sha256(target.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()
            preview = complete(submit('preview', target)); assert preview['result']['text'].encode() == data
            download = complete(submit('download', target))
            response = client.get('/node-files/requests/' + download['id'] + '/download')
            assert response.status_code == 200 and response.content == data
            assert supervisor.worker is oldworker and oldworker.poll() is None
            prefix = '/agent/files/requests/' + job['id']
            for method, suffix in [('GET', ''), ('POST', '/admit'), ('POST', '/result')]:
                assert any(e['method'] == method and e['path'] == prefix + suffix and e['status'] == 200 for e in wire), (method, suffix, wire)
            with sessionLocal() as db:
                row = db.get(FileJob, job['id']); assert row.state == 'done' and row.error is None
            until = time.monotonic() + 10
            while time.monotonic() < until:
                supervisor.tick()
                if preps[-1] is not refresh_child and preps[-1].poll() == 0 and supervisor.preparing is None: break
                time.sleep(.025)
            else: pytest.fail('bounded refresh did not recover')
            assert supervisor.worker is oldworker and oldworker.poll() is None
            events['refresh_recovered'] = True
            events.update(final=result['state'], disk_sha256=hashlib.sha256(target.read_bytes()).hexdigest(), preview_download=True, same_worker_after_complete=True, middleware=[m.cls.__name__ for m in main.app.user_middleware], real_lifespan=True, uid=os.getuid())
    finally:
        refresh_release.set(); upload_release.set()
        events['preparations'] = [{'pid': p.pid, 'returncode': p.poll()} for p in preps]
        (evidence / ('full-main-' + tag + '.json')).write_text(json.dumps(events, indent=2, default=str))
        try:
            if supervisor: supervisor.close()
        finally:
            stderr.close(); server.should_exit = True; thread.join(8)
            with sessionLocal() as db:
                db.execute(delete(FileJob).where(FileJob.node_id == node_id))
                db.execute(delete(FileAgent).where(FileAgent.node_id == node_id))
                db.execute(delete(Node).where(Node.id == node_id))
                db.execute(delete(AuthSession).where(AuthSession.user_id == uid))
                db.execute(delete(User).where(User.id == uid))
                db.execute(delete(AppConfig).where(AppConfig.key == admin_security.STATE_KEY))
                db.commit()
            engine.dispose()
        assert not thread.is_alive()
