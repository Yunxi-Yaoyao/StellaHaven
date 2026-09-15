"""Real PG + loopback HTTP, isolated per-test schema; never main/conftest."""
import asyncio
import hashlib
import io
import os
import socket
import threading
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
import uvicorn


@pytest.fixture
def live(tmp_path, monkeypatch):
    dsn = os.getenv('STELLA_CACHE_TEST_DSN')
    if not dsn:
        pytest.skip('STELLA_CACHE_TEST_DSN required (exact guarded test PG only)')
    from tests_ha.testdb_guard import build_test_engine, select_test_url, IDENTITY_SQL, verify_identity
    guard_env = dict(os.environ, STELLA_TEST_DATABASE_URL=dsn)
    select_test_url(dsn, guard_env)  # Fail before application imports or any connection.
    monkeypatch.setenv('STELLA_BLOB_STORAGE', 'postgres')
    monkeypatch.setenv('STELLA_BLOB_CACHE', str(tmp_path/'cache'))
    monkeypatch.setenv('STELLA_SECRET_KEY', 'cache-regression-only-not-production-key-123456')
    from fastapi import FastAPI
    from app.database import get_db
    from app.models import User, AuthSession, Workspace, Document, Attachment, BlobObject, BlobChunk
    from app.routers.attachment import router
    from app.routers.dynamic_assets import router as assets
    from app.security import make_access_token
    from app.services import blob_store
    schema = 'cache_test_' + uuid4().hex
    admin = build_test_engine(dsn, guard_env)
    def verify(conn):
        url, address, revalidate = admin._stella_test_identity
        revalidate()
        verify_identity(conn.execute(text(IDENTITY_SQL)).one(), url, address)
    with admin.begin() as conn:
        verify(conn)
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    def schema_engine(url, connect_args):
        connect_args = dict(connect_args)
        connect_args['options'] += f' -csearch_path={schema} -capplication_name={schema}'
        return create_engine(url, connect_args=connect_args)
    engine = build_test_engine(dsn, guard_env, factory=schema_engine)
    tables = (User, AuthSession, Workspace, Document, Attachment, BlobObject, BlobChunk)
    for model in tables:
        model.__table__.create(engine)
    payload = b'http-pg-cache-regression-'*65536
    with Session(engine) as db:
        user = User(username='cachetest', display_name='Cache')
        db.add(user); db.flush()
        auth = AuthSession(user_id=user.id, refresh_hash=uuid4().hex)
        ws = Workspace(user_id=user.id, name='Test')
        db.add_all([auth, ws]); db.flush()
        doc = Document(workspace_id=ws.id, title='Cache test', file_path='test', content_hash='test')
        db.add(doc); db.flush()
        att = Attachment(doc_id=doc.id, filename='private.bin', mime='application/octet-stream', size=len(payload))
        db.add(att); db.flush()
        att_id = att.id
        token = make_access_token(str(user.id), str(auth.id))
        blob_store.put(db, 'attachments/'+str(att.id), io.BytesIO(payload), att.mime, len(payload))
        blob_store.put(db, 'avatars/test.bin', io.BytesIO(payload), att.mime, len(payload))
        db.commit()
    app = FastAPI()
    def get_test_db():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = get_test_db
    app.include_router(router); app.include_router(assets)
    started, release = threading.Event(), threading.Event()
    state = {'slow':False, 'checkedout':None}
    class Gate:
        async def __call__(self, scope, receive, send):
            async def gated(message):
                if state['slow'] and message['type']=='http.response.body' and message.get('body'):
                    state['checkedout'] = engine.pool.checkedout()
                    started.set()
                    while not release.is_set():
                        await asyncio.sleep(.01)
                await send(message)
            await app(scope, receive, gated)
    sock = socket.socket(); sock.bind(('127.0.0.1',0)); sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(Gate(), log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets':[sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic()+5
    while not server.started and time.monotonic()<deadline:
        time.sleep(.01)
    assert server.started
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', cookies={'stella_at':token}, timeout=10) as client:
            yield client, engine, att_id, payload, tmp_path/'cache', state, started, release
    finally:
        release.set(); server.should_exit=True; thread.join(5); sock.close()
        engine.dispose()
        with admin.begin() as conn:
            verify(conn)
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()


def test_real_attachment_head_private_and_public(live):
    client, engine, aid, payload, cache, *_ = live
    path = '/attachments/'+str(aid)
    head = client.head(path)
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(payload))
    assert head.headers['cache-control'] == 'no-store'
    print(f'HTTP_EVIDENCE HEAD={head.status_code} body_bytes={len(head.content)} content_length={head.headers["content-length"]} cache_control={head.headers["cache-control"]}')
    result = client.get(path)
    assert result.content == payload and result.headers['cache-control'] == 'no-store'
    assert result.headers['etag'] == '"'+hashlib.sha256(payload).hexdigest()+'"'
    for headers, status in [({'Range':'bytes=1-9'},206), ({'Range':'bytes=999999999-'},416), ({'If-None-Match':result.headers['etag']},304)]:
        response = client.get(path, headers=headers)
        assert response.status_code == status
        assert response.headers['cache-control'] == 'no-store'
    public = client.get('/assets/avatars/test.bin')
    assert public.content == payload and 'cache-control' not in public.headers
    assert len(list(cache.glob('*.bin'))) == 1
    assert client.head('/attachments/'+str(uuid4())).status_code == 404


def test_download_releases_db_before_body_and_delete(live):
    client, engine, aid, payload, cache, state, started, release = live
    from app.models import Attachment
    from app.services import blob_store
    state['slow'] = True
    result = {}
    worker = threading.Thread(target=lambda:result.update(response=client.get('/attachments/'+str(aid))))
    worker.start()
    try:
        assert started.wait(5)
        assert state['checkedout'] == 0
        with Session(engine) as db:
            idle = db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE application_name=current_setting('application_name') AND pid<>pg_backend_pid() AND state LIKE 'idle in transaction%'")).scalar_one()
            assert idle == 0
            db.execute(text("SET LOCAL lock_timeout='500ms'"))
            before = time.monotonic()
            blob_store.delete(db, 'attachments/'+str(aid))
            db.delete(db.get(Attachment, aid)); db.commit()
            print(f'PG_EVIDENCE idle_in_transaction={idle} body_checkedout={state["checkedout"]} delete_seconds={time.monotonic()-before:.6f}')
    finally:
        release.set(); worker.join(10)
    assert hashlib.sha256(result['response'].content).digest() == hashlib.sha256(payload).digest()
    print('HTTP_EVIDENCE slow_download_sha256='+hashlib.sha256(result['response'].content).hexdigest())
    assert client.get('/attachments/'+str(aid)).status_code == 404


def test_head_does_not_need_cache_capacity(live, monkeypatch):
    client, engine, aid, payload, cache, *_ = live
    monkeypatch.setenv('STELLA_BLOB_CACHE_MAX_BYTES', '0')
    response = client.head('/attachments/'+str(aid))
    assert response.status_code == 200
    assert response.headers['content-length'] == str(len(payload))
    assert not list(cache.glob('*.bin'))
    assert client.get('/attachments/'+str(aid)).status_code == 503


def test_public_download_releases_db_before_body(live):
    client, engine, aid, payload, cache, state, started, release = live
    state['slow'] = True
    result = {}
    worker = threading.Thread(target=lambda:result.update(response=client.get('/assets/avatars/test.bin')))
    worker.start()
    try:
        assert started.wait(5)
        assert state['checkedout'] == 0
    finally:
        release.set(); worker.join(10)
    assert result['response'].content == payload


def test_real_http_disconnect_releases_pin(live):
    import fcntl
    client, engine, aid, payload, cache, state, started, release = live
    state['slow'] = True
    with client.stream('GET', '/attachments/'+str(aid)) as response:
        assert response.status_code == 200 and started.wait(5)
        path = next(cache.glob('*.bin'))
        fd = os.open(path, os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
    # Real TCP close triggers the response's disconnect watcher, not a test
    # cancellation and not completion of the artificially stalled body send.
    fd = os.open(path, os.O_RDONLY)
    try:
        deadline = time.monotonic()+3
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                assert time.monotonic()<deadline, 'lease survived TCP disconnect'
                time.sleep(.01)
    finally:
        os.close(fd)
    assert engine.pool.checkedout() == 0


def test_real_http_enospc_is_503_and_recovers(live, monkeypatch):
    import errno
    client, engine, aid, payload, cache, *_ = live
    def full(*args):
        raise OSError(errno.ENOSPC, 'injected real-filesystem allocation failure')
    with monkeypatch.context() as scoped:
        scoped.setattr(os, 'posix_fallocate', full)
        response = client.get('/attachments/'+str(aid))
        assert response.status_code == 503
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['retry-after'] == '5'
    assert not list(cache.glob('.fill-*')) and not list(cache.glob('*.bin'))
    assert engine.pool.checkedout() == 0
    assert client.get('/attachments/'+str(aid)).content == payload


def test_snapshot_concurrent_delete_and_caller_state(live, monkeypatch):
    from app.services import blob_store
    from app.models import User
    from starlette.requests import Request
    client, engine, aid, payload, cache, *_ = live
    key = 'attachments/'+str(aid)
    original = blob_store.read_range
    checked = []
    def deleting_reader(snapshot, key, start, size):
        for number, chunk in enumerate(original(snapshot, key, start, size)):
            if number == 0:
                checked.append(snapshot.execute(text('SHOW transaction_isolation')).scalar())
                checked.append(snapshot.execute(text('SHOW transaction_read_only')).scalar())
                with Session(engine) as writer:
                    writer.execute(text("SET LOCAL lock_timeout='500ms'"))
                    blob_store.delete(writer, key); writer.commit()
            yield chunk
    monkeypatch.setattr(blob_store, 'read_range', deleting_reader)
    with Session(engine) as caller:
        user = caller.query(User).one()
        user.display_name = 'pending-not-committed'
        response = blob_store.response(caller, key, Request({'type':'http','method':'GET','headers':[]}))
        try:
            assert user in caller.dirty
            with Session(engine) as other:
                assert other.query(User).one().display_name == 'Cache'
            assert response.lease.path.read_bytes() == payload
        finally:
            response.lease.close()
        caller.rollback()
    assert checked == ['repeatable read', 'on']
    assert client.get('/attachments/'+str(aid)).status_code == 404


def test_real_http_capacity_includes_active_download(live, monkeypatch):
    from app.services import blob_store
    client, engine, aid, payload, cache, state, started, release = live
    # One payload allocation fits; an active one must not be evicted to fill
    # a second object. Completed leases become eligible without a process restart.
    block = os.statvfs(cache.parent).f_frsize
    cap = ((len(payload)+block-1)//block)*block
    monkeypatch.setenv('STELLA_BLOB_CACHE_MAX_BYTES', str(cap))
    second = b'Z'*len(payload)
    with Session(engine) as db:
        blob_store.put(db, 'avatars/second.bin', io.BytesIO(second), 'application/octet-stream', len(second))
        db.commit()
    state['slow'] = True
    result = {}
    worker = threading.Thread(target=lambda:result.update(response=client.get('/attachments/'+str(aid))))
    worker.start()
    try:
        assert started.wait(5)
        # Avoid blocking a 503 JSON body in the artificial slow-send gate.
        state['slow'] = False
        blocked = client.get('/assets/avatars/second.bin')
        assert blocked.status_code == 503
        assert sum(p.stat().st_blocks*512 for p in cache.glob('*.bin')) <= cap
        assert not list(cache.glob('.fill-*'))
    finally:
        release.set(); worker.join(10)
    assert result['response'].content == payload
    assert client.get('/assets/avatars/second.bin').content == second
    assert len(list(cache.glob('*.bin'))) == 1
