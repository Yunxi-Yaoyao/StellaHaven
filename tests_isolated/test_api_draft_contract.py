"""Real draft services/routes/auth on disposable SQLite; no production bootstrap.

Run alone with --noconftest. SQLite verifies transaction/readback behavior, NOT
PostgreSQL row-lock serialization (that requires the separate PG acceptance).
"""
import asyncio
import importlib
import importlib.abc
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import JSON, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session
from starlette.websockets import WebSocket

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env(tmp_path, monkeypatch):
    previous = {k: v for k, v in sys.modules.items() if k == 'app' or k.startswith('app.')}
    for key in previous:
        del sys.modules[key]
    monkeypatch.setenv('STELLA_SECRET_KEY', 'draft-fixture-signing-key-not-production-000000')
    monkeypatch.delenv('STELLA_OWNER_ID', raising=False)

    class BlockBootstrap(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname in {'main', 'app.main', 'app.config', 'app.database'}:
                raise AssertionError(f'Forbidden production import: {fullname}')

    guard = BlockBootstrap()
    sys.meta_path.insert(0, guard)
    engine = None
    try:
        for name in ['app', 'app.routers', 'app.services', 'app.repositories', 'app.schemas']:
            package = types.ModuleType(name)
            package.__path__ = [str(ROOT.joinpath(*name.split('.')))]
            sys.modules[name] = package
            if '.' in name:
                parent, attr = name.rsplit('.', 1)
                setattr(sys.modules[parent], attr, package)
        database = types.ModuleType('app.database')
        class Base(DeclarativeBase):
            pass
        database.Base = Base
        def get_db():
            raise AssertionError('Dependency override required')
        database.get_db = get_db
        sys.modules['app.database'] = database
        sys.modules['app'].database = database
        models = importlib.import_module('app.models')
        svc = importlib.import_module('app.services.document')
        auth = importlib.import_module('app.routers.auth')
        ws = importlib.import_module('app.routers.ws')
        notify = importlib.import_module('app.routers.notify_ws')
        routes = importlib.import_module('app.routers.document')
        security = importlib.import_module('app.security')
        engine = create_engine(f'sqlite:///{tmp_path / "draft.sqlite"}', connect_args={'check_same_thread': False})
        @event.listens_for(engine, 'connect')
        def sqlite_fk(conn, record):
            conn.execute('PRAGMA foreign_keys=ON')
        monkeypatch.setattr(models.Document.__table__.c.frontmatter, 'type', JSON())
        Base.metadata.create_all(engine, tables=[m.__table__ for m in [models.User, models.AuthSession, models.AppConfig, models.Workspace, models.Document]])
        uid, sid, wid, did = [uuid4() for _ in range(4)]
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with Session(engine) as db:
            db.add(models.User(id=uid, username='fixture', display_name='fixture'))
            db.flush()
            db.add(models.AuthSession(id=sid, user_id=uid, refresh_hash='fixture', created_at=now, last_seen=now))
            db.add(models.AppConfig(key='security.owner_admin.v1', value=json.dumps({'owner_id': str(uid)})))
            db.add(models.Workspace(id=wid, user_id=uid, name='fixture'))
            db.flush()
            db.add(models.Document(id=did, workspace_id=wid, title='fixture', file_path='/fixture.md', content='body', content_hash='original', draft_content='old draft', draft_updated_at=datetime.now(), draft_device='old device'))
            db.commit()
        app = FastAPI()
        app.include_router(routes.router)
        app.include_router(auth.router)
        app.include_router(notify.router)  # Exact notifications path precedes UUID route.
        app.include_router(ws.router)
        def isolated_db():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[get_db] = isolated_db
        # Direct ASGI socket harness does not need the unrelated broadcast workers.
        ws._worker_started = notify._worker_started = True
        token = security.make_access_token(str(uid), str(sid))
        with TestClient(app) as client:
            client.cookies.set('stella_at', token)
            yield types.SimpleNamespace(engine=engine, models=models, svc=svc, auth=auth,
                ws=ws, notify=notify, routes=routes, client=client, uid=uid, sid=sid,
                wid=wid, did=did, token=token, now=now)
    finally:
        if engine is not None:
            engine.dispose()
        sys.meta_path.remove(guard)
        for key in list(sys.modules):
            if key == 'app' or key.startswith('app.'):
                del sys.modules[key]
        sys.modules.update(previous)


def change(env, model, key, **values):
    with Session(env.engine) as db:
        row = db.get(model, key)
        for name, value in values.items():
            setattr(row, name, value)
        db.commit()


def snapshot(env):
    with Session(env.engine) as db:
        doc = db.get(env.models.Document, env.did)
        return (doc.draft_content, doc.draft_updated_at, doc.draft_device, doc.content, doc.updated_at)


def test_save_rejects_deleted_even_with_stale_identity_map(env):
    before = snapshot(env)
    with Session(env.engine, expire_on_commit=False) as db:
        stale = db.get(env.models.Document, env.did)
        db.commit()
        change(env, env.models.Document, env.did, deleted_at=datetime.now())
        assert stale.deleted_at is None
        assert env.svc.save_draft(db, env.did, 'must not persist', 'device') is None
        assert not db.in_transaction()
    assert snapshot(env) == before


def test_deleted_draft_is_hidden_by_service_and_http_without_clearing(env):
    before = snapshot(env)
    with Session(env.engine, expire_on_commit=False) as db:
        stale = db.get(env.models.Document, env.did)
        db.commit()
        change(env, env.models.Document, env.did, deleted_at=datetime.now())
        assert stale.deleted_at is None
        assert env.svc.get_fresh_draft(db, env.did) is None
    assert env.client.get(f'/documents/{env.did}/draft').status_code == 404
    assert snapshot(env) == before
    # The global ownership guard intentionally still permits trash operations.
    with Session(env.engine) as db:
        assert env.auth.require_doc_owner(db, env.did, db.get(env.models.User, env.uid))
    change(env, env.models.Document, env.did, deleted_at=None)
    response = env.client.get(f'/documents/{env.did}/draft')
    assert response.status_code == 200
    assert response.json()['content'] == before[0]


class Idle:
    def __init__(self, action=lambda: None):
        self.action = action


def socket_run(env, monkeypatch, steps=(), *, kind='document', device='fixture', on_send=None, prepare_db=None):
    """Real Starlette socket + real route; only time/ASGI transport are synthetic.

    Every DB mutation uses a distinct session/connection. No TestClient thread
    shares the socket session, and no auth/service decision is mocked.
    """
    steps = list(steps)
    output, timeouts = [], []
    module = env.notify if kind == 'notify' else env.ws
    scope = {'type': 'websocket', 'path': '/fixture', 'headers': [(b'cookie', f'stella_at={env.token}'.encode())], 'query_string': b''}
    connected = False
    async def receive():
        nonlocal connected
        if not connected:
            connected = True
            return {'type': 'websocket.connect'}
        if not steps:
            return {'type': 'websocket.disconnect', 'code': 1000}
        step = steps.pop(0)
        if callable(step):
            step = step()
        if isinstance(step, dict):
            return step
        return {'type': 'websocket.receive', 'text': step}
    async def send(message):
        output.append(message)
        if on_send:
            on_send(message)
    async def wait_for(awaitable, timeout):
        timeouts.append(timeout)
        assert timeout == 15
        if steps and isinstance(steps[0], Idle):
            awaitable.close()
            steps.pop(0).action()
            raise asyncio.TimeoutError
        return await asyncio.wait_for(awaitable, timeout)
    proxy = types.SimpleNamespace(**{name: getattr(asyncio, name) for name in dir(asyncio)})
    proxy.wait_for = wait_for
    monkeypatch.setattr(module, 'asyncio', proxy)
    async def run():
        with Session(env.engine) as db:
            if prepare_db:
                prepare_db(db)
            socket = WebSocket(scope, receive, send)
            if kind == 'document':
                await module.document_ws(socket, env.did, device=device, db=db)
            elif kind == 'list':
                await module.list_ws(socket, env.wid, db=db)
            else:
                await module.notifications_ws(socket, db=db)
            assert not db.in_transaction(), 'socket retained a DB transaction'
    asyncio.run(run())
    assert not env.ws.connections and not env.notify._clients
    return output, timeouts


def close_codes(output):
    return [message['code'] for message in output if message['type'] == 'websocket.close']


@pytest.mark.parametrize('request_id', [None, 'x' * 128, '界' * 42 + 'ab'], ids=['legacy', 'ascii-boundary', 'utf8-boundary'])
def test_ack_is_committed_and_matches_readback(env, monkeypatch, request_id):
    from hashlib import sha256
    before = snapshot(env)
    content = '草稿🙂\n' + 'x' * (256 * 1024)
    payload = {'type': 'draft', 'content': content}
    if request_id is not None:
        payload['request_id'] = request_id
    observed = []
    def on_send(message):
        if message['type'] != 'websocket.send':
            return
        receipt = json.loads(message['text'])
        stored = snapshot(env)  # Independent connection, BEFORE the next receive.
        assert stored[0] == content
        assert receipt == {'type': 'draft_ack', 'request_id': request_id,
            'draft_updated_at': stored[1].isoformat(),
            'content_hash': sha256(content.encode('utf-8')).hexdigest(),
            'base_updated_at': before[4].isoformat()}
        observed.append(receipt)
    output, _ = socket_run(env, monkeypatch, [
        json.dumps({'type': 'future-message', 'nested': {'ok': [1]}}),
        json.dumps(payload),
    ], on_send=on_send)
    assert len(observed) == 1
    assert close_codes(output) == []
    after = snapshot(env)
    assert after[2] == 'fixture'
    assert after[3:] == before[3:]
    response = env.client.get(f'/documents/{env.did}/draft')
    assert response.status_code == 200
    assert response.json()['content'] == content
    assert response.json()['updated_at'] == observed[0]['draft_updated_at']


@pytest.mark.parametrize('raw', [
    '[]', 'null', '1', '"text"', 'true', '{broken',
    '{}', '{"type": null}', '{"type": []}', '{"type": 1}',
    '{"type": "draft"}', '{"type": "draft", "content": null}',
    '{"type": "draft", "content": []}', '{"type": "draft", "content": 1}',
    json.dumps({'type': 'draft', 'content': 'ok', 'request_id': None}),
    json.dumps({'type': 'draft', 'content': 'ok', 'request_id': 1}),
    json.dumps({'type': 'draft', 'content': 'ok', 'request_id': ''}),
    json.dumps({'type': 'draft', 'content': 'ok', 'request_id': 'x' * 129}),
    json.dumps({'type': 'draft', 'content': 'ok', 'request_id': '界' * 43}),
    json.dumps({'type': 'draft', 'content': '\ud800'}),
    '[' * 1500 + '0' + ']' * 1500,
    '1' * 5000,
    {'type': 'websocket.receive', 'bytes': b'binary'},
], ids=[
    'array', 'null', 'number', 'string', 'boolean', 'malformed',
    'missing-type', 'null-type', 'array-type', 'number-type',
    'missing-content', 'null-content', 'array-content', 'number-content',
    'null-id', 'number-id', 'empty-id', 'long-id', 'utf8-id',
    'surrogate-content', 'deep-json', 'huge-integer', 'binary',
])
def test_invalid_draft_message_closes_without_writes(env, monkeypatch, raw):
    before = snapshot(env)
    output, _ = socket_run(env, monkeypatch, [raw])
    assert close_codes(output) == [1008]
    assert not any(m['type'] == 'websocket.send' for m in output)
    assert snapshot(env) == before


@pytest.mark.parametrize('device', [None, [], 1, '\ud800'])
def test_invalid_device_closes_without_writes(env, monkeypatch, device):
    before = snapshot(env)
    output, _ = socket_run(env, monkeypatch, [json.dumps({'type': 'draft', 'content': 'new'})], device=device)
    assert close_codes(output) == [1008]
    assert not any(m['type'] == 'websocket.send' for m in output)
    assert snapshot(env) == before


@pytest.mark.parametrize('failure', ['flush', 'commit'])
def test_database_failure_rolls_back_and_never_acknowledges(env, monkeypatch, failure):
    from sqlalchemy.exc import OperationalError
    before = snapshot(env)
    def prepare(db):
        if failure == 'commit':
            @event.listens_for(db, 'before_commit')
            def fail_commit(session):
                raise OperationalError('fixture', {}, RuntimeError('synthetic failure'))
        else:
            @event.listens_for(db, 'after_flush')
            def fail_flush(session, flush_context):
                raise OperationalError('fixture', {}, RuntimeError('synthetic failure'))
    output, _ = socket_run(env, monkeypatch, [json.dumps({'type': 'draft', 'content': 'not committed'})], prepare_db=prepare)
    assert close_codes(output) == [1011]
    assert not any(m['type'] == 'websocket.send' for m in output)
    assert snapshot(env) == before


def test_service_failure_ends_transaction(env):
    from sqlalchemy.exc import OperationalError
    before = snapshot(env)
    with Session(env.engine) as db:
        @event.listens_for(db, 'before_commit')
        def fail_commit(session):
            raise OperationalError('fixture', {}, RuntimeError('synthetic failure'))
        with pytest.raises(OperationalError):
            env.svc.save_draft(db, env.did, 'not committed', 'fixture')
        assert not db.in_transaction()
    assert snapshot(env) == before


def test_delete_after_socket_auth_is_rechecked_at_write(env, monkeypatch):
    before = snapshot(env)
    checks = []
    def prepare(db):
        @event.listens_for(db, 'after_rollback')
        def after_auth(session):
            checks.append(True)
            if len(checks) == 2:
                change(env, env.models.Document, env.did, deleted_at=datetime.now())
    output, _ = socket_run(env, monkeypatch, [json.dumps({'type': 'draft', 'content': 'forbidden'})], prepare_db=prepare)
    assert close_codes(output) == [1008]
    assert not any(m['type'] == 'websocket.send' for m in output)
    assert snapshot(env) == before


@pytest.mark.parametrize('kind', ['document', 'list', 'notify'])
@pytest.mark.parametrize('stage', ['connect', 'message', 'idle'])
@pytest.mark.parametrize('failure', ['revoked', 'expired', 'disabled'])
def test_socket_session_revalidation(env, monkeypatch, kind, stage, failure):
    def invalidate():
        if failure == 'disabled':
            change(env, env.models.User, env.uid, is_active=False)
        else:
            values = {'revoked': True} if failure == 'revoked' else {'last_seen': env.now - timedelta(hours=1)}
            change(env, env.models.AuthSession, env.sid, **values)
        return json.dumps({'type': 'future-message'})
    if stage == 'connect':
        invalidate()
        steps = []
    else:
        steps = [Idle(invalidate) if stage == 'idle' else invalidate]
    output, timeouts = socket_run(env, monkeypatch, steps, kind=kind)
    assert close_codes(output) == [1008]
    if stage == 'idle':
        assert timeouts == [15]


@pytest.mark.parametrize('kind', ['document', 'list', 'notify'])
def test_polling_never_extends_session(env, monkeypatch, kind):
    output, timeouts = socket_run(env, monkeypatch, [Idle(), Idle(), json.dumps({'type': 'future-message'})], kind=kind)
    assert len(timeouts) == 4
    assert close_codes(output) == []
    with Session(env.engine) as db:
        session = db.get(env.models.AuthSession, env.sid)
        assert session.last_seen == session.created_at == env.now
        assert not session.revoked


def test_ack_snapshot_survives_another_write_after_commit(env, monkeypatch):
    from hashlib import sha256
    expected = {}
    def prepare(db):
        @event.listens_for(db, 'before_commit')
        def capture(session):
            doc = session.get(env.models.Document, env.did)
            expected.update(draft_updated_at=doc.draft_updated_at.isoformat(), base_updated_at=doc.updated_at.isoformat())
        @event.listens_for(db, 'after_commit')
        def later_write(session):
            change(env, env.models.Document, env.did, draft_content='later writer', draft_updated_at=datetime.now())
    output, _ = socket_run(env, monkeypatch, [json.dumps({'type': 'draft', 'content': 'own write', 'request_id': 'own'})], prepare_db=prepare)
    receipt, = [json.loads(m['text']) for m in output if m['type'] == 'websocket.send']
    assert receipt == {'type': 'draft_ack', 'request_id': 'own', 'content_hash': sha256(b'own write').hexdigest(), **expected}
    assert snapshot(env)[0] == 'later writer'


def test_ack_delivery_loss_does_not_undo_commit(env, monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    def drop(message):
        if message['type'] == 'websocket.send':
            raise WebSocketDisconnect(1006)
    socket_run(env, monkeypatch, [json.dumps({'type': 'draft', 'content': 'committed anyway'})], on_send=drop)
    assert env.client.get(f'/documents/{env.did}/draft').json()['content'] == 'committed anyway'


def test_real_sqlalchemy_write_requests_pg_row_lock(env):
    from sqlalchemy.dialects.postgresql import dialect
    statements = []
    with Session(env.engine) as db:
        @event.listens_for(db, 'do_orm_execute')
        def inspect_statement(state):
            statements.append(str(state.statement.compile(dialect=dialect())))
        receipt = env.svc.save_draft(db, env.did, '', 'fixture')
        assert receipt is not None
        assert not db.in_transaction()
    # Lifecycle locks now look up workspace before locking the fresh document.
    # Keep the behavioral lock assertion without requiring one total SELECT.
    locked = [statement for statement in statements if 'FOR UPDATE' in statement]
    assert len(locked) == 1
    assert 'FROM documents' in locked[0]
    assert statements[-1] == locked[0]
    assert snapshot(env)[0] == ''


@pytest.mark.parametrize('state', ['missing', 'expired', 'foreign'])
def test_get_draft_retains_404_contract(env, state):
    before = snapshot(env)
    target = env.did
    if state == 'missing':
        target = uuid4()
    elif state == 'expired':
        change(env, env.models.Document, env.did, draft_updated_at=datetime.now() - timedelta(seconds=601))
    else:
        foreign_uid = uuid4()
        with Session(env.engine) as db:
            db.add(env.models.User(id=foreign_uid, username='foreign', display_name='foreign'))
            db.commit()
        change(env, env.models.Workspace, env.wid, user_id=foreign_uid)
    response = env.client.get(f'/documents/{target}/draft')
    assert response.status_code == 404
    assert snapshot(env)[0] == before[0]


def test_router_roundtrip_and_logout_closes_existing_notification_socket(env, monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    with env.client.websocket_connect(f'/ws/{env.did}?device=browser') as socket:
        socket.send_json({'type': 'draft', 'content': 'real routed draft', 'request_id': 'roundtrip'})
        receipt = socket.receive_json()
        assert receipt['type'] == 'draft_ack'
        assert receipt['request_id'] == 'roundtrip'
        assert snapshot(env)[0] == 'real routed draft'
        socket.send_json([])
        with pytest.raises(WebSocketDisconnect) as disconnected:
            socket.receive_json()
        assert disconnected.value.code == 1008
    def logout():
        response = env.client.post('/auth/logout')
        assert response.status_code == 200
        assert any('stella_at=' in cookie and 'Max-Age=0' in cookie for cookie in response.headers.get_list('set-cookie'))
    output, _ = socket_run(env, monkeypatch, [Idle(logout)], kind='notify')
    assert close_codes(output) == [1008]
    with Session(env.engine) as db:
        session = db.get(env.models.AuthSession, env.sid)
        assert session.revoked
        assert session.last_seen == env.now


@pytest.mark.parametrize('stage', ['connect', 'message', 'idle'])
def test_document_socket_rechecks_deleted_state(env, monkeypatch, stage):
    before = snapshot(env)
    def delete():
        change(env, env.models.Document, env.did, deleted_at=datetime.now())
        return json.dumps({'type': 'draft', 'content': 'forbidden'})
    if stage == 'connect':
        delete()
        steps = []
    else:
        steps = [Idle(delete) if stage == 'idle' else delete]
    output, timeouts = socket_run(env, monkeypatch, steps)
    assert close_codes(output) == [1008]
    if stage == 'connect':
        assert not any(m['type'] == 'websocket.accept' for m in output)
    assert snapshot(env) == before
