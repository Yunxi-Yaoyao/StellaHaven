"""Real TCP FastAPI + real file worker; only seeded synthetic identity/node."""
import hashlib
import json
import os
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


@pytest.fixture(autouse=True)
def renew_owned_file_worker_presence(request):
    # The session fixture has no continuously running Agent except inside each
    # browser journey. Builds/ACL probes can legitimately outlast the 15s TTL.
    # Renew with the actual worker protocol before the next independent case;
    # never change the product clock, online TTL, or offline/session assertions.
    if 'system' in request.fixturenames:
        system = request.getfixturevalue('system')
        system['worker'].tick()


@pytest.fixture(scope='session')
def system(tmp_path_factory):
    assert os.environ['POSTGRES_DB'].startswith('nodefiles_')
    assert os.environ['POSTGRES_HOST'] == '127.0.0.1'
    assert not Path('.env').exists()
    root = tmp_path_factory.mktemp('owned-node-root')
    (root / 'hello.txt').write_text('节点文件 · 真实 worker\n')
    binary = bytes(range(256)) * 1400
    (root / 'download.bin').write_bytes(binary)
    (root / '.hidden').write_text('hidden')
    (root / 'folder').mkdir()
    (root / 'escape').symlink_to('/etc')
    with engine.begin() as conn:
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
        Base.metadata.create_all(conn)
    uid, sid = uuid4(), uuid4()
    token = 'synthetic-file-node-' + uuid4().hex
    with sessionLocal() as db:
        db.add(User(id=uid, username='file-fixture', display_name='节点文件验收'))
        db.flush()
        db.add(AuthSession(id=sid, user_id=uid, refresh_hash=uuid4().hex))
        db.add(Node(id=930001, name='隔离文件节点', platform='linux', host='synthetic', status='online', token=token))
        db.commit()
    policy = root.parent / 'policy.json'
    policy.write_text(json.dumps({'930001': {'fixture': {'owners': [str(uid)], 'label': '验收目录', 'write': True}}}))
    os.environ['STELLA_NODE_FILE_POLICY'] = str(policy)
    os.environ['STELLA_NODE_FILE_STATE'] = str(root.parent / 'center-spool')
    app = FastAPI()
    app.include_router(router)
    app.include_router(agent_router)
    import socket
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(.02)
    assert server.started
    url = f'http://127.0.0.1:{port}'
    client = httpx.Client(base_url=url, cookies={'stella_at': make_access_token(str(uid), str(sid))})
    worker = FileWorker(url, token, Sandbox({'fixture': {'path': str(root), 'write': True}}))
    worker.tick()
    value = {'client': client, 'worker': worker, 'root': root, 'uid': uid, 'sid': sid, 'url': url, 'app': app, 'token': token, 'binary': binary, 'policy': policy}
    yield value
    client.close()
    server.should_exit = True
    thread.join(5)
    assert not thread.is_alive()
    engine.dispose()

