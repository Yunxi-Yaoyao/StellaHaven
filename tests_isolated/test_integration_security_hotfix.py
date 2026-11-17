"""Run separately with --noconftest from scratch cwd, never in a PG suite.
Actual main ASGI/middleware/auth; private SQLite; real loopback HTTP and WS.
"""
import os
os.environ.update(STELLA_SECRET_KEY='hotfix-synthetic-signing-key-only-000000000', STELLA_COOKIE_SECURE='false', POSTGRES_HOST='127.0.0.1', POSTGRES_PORT='1', POSTGRES_DB='stella_test_hotfix', POSTGRES_USER='hotfix_fixture', POSTGRES_PASSWORD='synthetic-only', STELLA_TRUSTED_ORIGINS='https://stella.xiya.live', STELLA_MAIN_ORIGIN='https://stella.xiya.live')
import json
import time
import socket
import threading
from uuid import UUID
import pytest
import uvicorn
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from app.database import get_db, engine as unused_pg
from app.models.user import User, AuthSession, Invite, EmailCode
from app.models.config import AppConfig
from app.services import integrations as store, integrations_sessions as sessions
from app.routers.integrations_host import IntegrationsHostMiddleware
from tests_isolated.test_owner_admin_security import DAILY, ADMIN

@event.listens_for(unused_pg, 'do_connect')
def forbid_pg(*a, **kw):
    raise AssertionError('Hotfix tests must not connect application PG')

@pytest.fixture
def upstream():
    app = FastAPI()
    seen = []
    @app.api_route('/{path:path}', methods=['GET','HEAD','POST','PUT','PATCH','DELETE'])
    async def echo(path: str, request: Request):
        seen.append((request.method, path))
        return {'synthetic': True, 'cookie': request.headers.get('cookie',''), 'auth': request.headers.get('authorization','')}
    @app.websocket('/socket')
    async def ws_echo(ws: WebSocket):
        await ws.accept()
        while True:
            e = await ws.receive()
            if e['type'] == 'websocket.disconnect': break
            if e.get('text') is not None: await ws.send_text(e['text'])
            if e.get('bytes') is not None: await ws.send_bytes(e['bytes'])
    sock = socket.socket(); sock.bind(('127.0.0.1',0))
    server = uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread = threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    thread.start()
    deadline = time.monotonic()+5
    while not server.started and thread.is_alive() and time.monotonic()<deadline: time.sleep(.01)
    assert server.started
    yield f'http://127.0.0.1:{sock.getsockname()[1]}/', seen
    server.should_exit=True; thread.join(5); sock.close()
    assert not thread.is_alive()

@pytest.fixture
def integration_env(monkeypatch, upstream):
    monkeypatch.delenv('STELLA_OWNER_ID',raising=False)
    monkeypatch.delenv('STELLA_HA_MODE',raising=False)
    import main
    main.app.middleware_stack = None
    eng = create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    for t in [User.__table__,AuthSession.__table__,Invite.__table__,EmailCode.__table__,AppConfig.__table__]: t.create(eng)
    factory = sessionmaker(eng,expire_on_commit=False)
    for m in main.app.user_middleware:
        if m.cls is IntegrationsHostMiddleware: monkeypatch.setitem(m.kwargs,'db_factory',factory)
    def db_dep():
        with factory() as db:
            try: yield db
            finally: db.rollback()
    main.app.dependency_overrides[get_db] = db_dep
    c = TestClient(main.app,base_url='https://stella.xiya.live')
    response=c.post('/auth/register',json={'username':'owner','password':DAILY})
    assert response.status_code==201,response.text
    uid=UUID(response.json()['id'])
    assert c.post('/auth/admin/setup',json={'user_password':DAILY,'new_password':ADMIN}).status_code==410
    assert c.post('/auth/admin/unlock',json={'password':ADMIN}).status_code==410
    mid='a'*32; origin='https://app-'+mid+'.xiya.live'; root,seen=upstream
    with factory() as db:
        sid=str(db.query(AuthSession).filter(AuthSession.user_id==uid,AuthSession.revoked==False).one().id)
        state=store.empty_state()
        state['targets']['target']=dict(id='target',name='synthetic',upstream_url=root,allowed_ips=['127.0.0.1'],controlled=True,headers={'authorization':'SYNTHETIC-TARGET'})
        state['modules'][mid]=dict(id=mid,name='synthetic',icon='globe',mode='isolated_proxy',adapter='generic',browser_url='',target_id='target',initial_path='/',origin=origin,enabled=True,injection={'active':None,'draft':None,'previous':None})
        db.add(AppConfig(key=store.KEY,value=json.dumps(state))); db.commit()
    launch=c.post('/external-modules/'+mid+'/launch')
    assert launch.status_code==200,launch.text
    info=launch.json()
    boot=c.post(info['url'],data=info['fields'],headers={'Origin':'https://stella.xiya.live'},follow_redirects=False)
    assert boot.status_code==303,boot.text
    cookie=boot.headers['set-cookie'].split(';')[0]
    yield c, factory, main.app, uid, sid, mid, origin, cookie, seen
    c.close(); main.app.dependency_overrides.pop(get_db,None); main.app.middleware_stack=None; eng.dispose()

@pytest.mark.parametrize('first',['stella.xiya.live','attacker.invalid','app-'+('a'*32)+'.xiya.live'])
def test_duplicate_host_cannot_dispatch_integration(integration_env,first):
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    r=c.get(origin+'/echo',headers=[('Host',first),('Host',origin.removeprefix('https://')),('Cookie',cookie)])
    assert r.status_code==421,r.text
    assert seen==[]


@pytest.mark.parametrize('host',[
    'app-'+('a'*32)+'.xiya.live:', 'stella.xiya.live:',
    'app-'+('a'*32)+'.xiya.live:0443', 'app-'+('a'*32)+'.xiya.live:0',
    'app-'+('a'*32)+'.xiya.live:65536', 'app-'+('a'*32)+'.xiya.live.',
    'user@app-'+('a'*32)+'.xiya.live', 'app-'+('a'*32)+'.xiya.live/path',
    'app-'+('a'*32)+'.xiya.live?x=1', 'app-'+('a'*32)+'.xiya.live#x',
    ' app-'+('a'*32)+'.xiya.live', 'app-'+('a'*32)+'.xiya.live,stella.xiya.live',
])
def test_malformed_authority_rejected_at_outer_dispatch(integration_env,host):
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    r=c.get(origin+'/echo',headers={'Host':host,'Cookie':cookie})
    assert r.status_code==421,r.text
    assert seen==[]


def test_real_nonowner_main_session_cannot_use_integration_grant(integration_env):
    from app.security import make_access_token
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    with f() as db:
        user=User(username='legacy-other',display_name='legacy',is_active=True,is_admin=True)
        db.add(user);db.flush()
        session=AuthSession(user_id=user.id,refresh_hash='synthetic-other',remember=True)
        db.add(session);db.flush()
        raw='SYNTHETIC-NONOWNER-GRANT'
        cfg=db.get(AppConfig,store.KEY);state=json.loads(cfg.value)
        state['grants'][sessions.digest(raw)]=dict(id=mid,origin=origin,sid=str(session.id),expires=time.time()+900)
        cfg.value=json.dumps(state);db.commit()
        at=make_access_token(str(user.id),str(session.id))
    assert c.get('/auth/me',headers={'Cookie':'stella_at='+at}).status_code==403
    r=c.get(origin+'/echo',headers={'Cookie':sessions.COOKIE+'='+raw})
    assert r.status_code==401,r.text
    assert seen==[]


def change_identity(factory, uid, sid, mode):
    from datetime import datetime, timedelta, timezone
    from app.services.admin_security import STATE_KEY
    with factory() as db:
        if mode=='revoked': db.get(AuthSession,UUID(sid)).revoked=True
        elif mode=='expired': db.get(AuthSession,UUID(sid)).created_at=datetime.now(timezone.utc)-timedelta(days=99)
        elif mode=='inactive': db.get(User,uid).is_active=False
        elif mode=='grant_expired':
            row=db.get(AppConfig,store.KEY);state=json.loads(row.value)
            for g in state['grants'].values(): g['expires']=0
            row.value=json.dumps(state)
        else:
            row=db.get(AppConfig,STATE_KEY);state=json.loads(row.value)
            if mode=='owner_changed':
                replacement=User(username='replacement',display_name='new',is_active=True)
                db.add(replacement);db.flush();state['owner_id']=str(replacement.id)
            elif mode=='pin_missing': state.pop('owner_id')
            elif mode=='pin_invalid': state['owner_id']='not-a-uuid'
            elif mode=='state_invalid': state=[]
            row.value=json.dumps(state)
        db.commit()


@pytest.mark.parametrize('mode',['owner_changed','revoked','expired','inactive','pin_missing','pin_invalid','state_invalid','grant_expired'])
def test_persisted_grant_tracks_owner_and_session_from_new_db_session(integration_env,mode):
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    assert c.get(origin+'/echo',headers={'Cookie':cookie}).status_code==200
    seen.clear()
    change_identity(f,uid,sid,mode)
    r=c.get(origin+'/echo',headers={'Cookie':cookie})
    assert r.status_code==401,r.text
    assert seen==[]


def test_lock_preserves_same_sid_iframe_and_reads_are_readonly(integration_env):
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    assert c.post('/auth/admin/lock').status_code==410
    with f() as db: before=db.get(AppConfig,store.KEY).value
    statements=[]
    def record_sql(conn,cursor,statement,params,ctx,many): statements.append(statement.lower())
    engine=f.kw['bind'];event.listen(engine,'before_cursor_execute',record_sql)
    try:
        # Both middleware and service read fresh sessions, without current_user override.
        r=c.get(origin+'/echo',headers={'Cookie':cookie+'; stella_at=NEVER-FORWARD; app_session=fixture'})
        assert r.status_code==200,r.text
        assert r.json()['cookie']=='app_session=fixture'
        assert r.json()['auth']=='SYNTHETIC-TARGET'
        with f() as db:
            grant=sessions.authorize(db,mid,origin,cookie.split('=',1)[1])
            assert grant['sid']==sid
            assert db.get(AppConfig,store.KEY).value==before
    finally: event.remove(engine,'before_cursor_execute',record_sql)
    assert statements
    assert not any(any(word in sql for word in ['for update','advisory','insert ','update ','delete ']) for sql in statements)


@pytest.mark.parametrize('host',['app-'+('f'*32)+'.xiya.live','app-unknown.xiya.live','app-'+('a'*32)+'.xiya.live:444'])
def test_unknown_app_host_never_falls_through_to_main(integration_env,host):
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    r=c.get('https://'+host+'/auth/me',headers={'Cookie':cookie})
    assert r.status_code==404,r.text
    assert seen==[]


@pytest.mark.parametrize('mode',['owner_changed','revoked','expired'])
def test_real_websocket_rechecks_owner_every_five_seconds(integration_env,mode):
    from starlette.websockets import WebSocketDisconnect
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    with c.websocket_connect(origin.replace('https:','wss:')+'/socket',headers={'Cookie':cookie,'Origin':origin}) as ws:
        ws.send_text('real synthetic echo');assert ws.receive_text()=='real synthetic echo'
        ws.send_bytes(b'\x00\xff');assert ws.receive_bytes()==b'\x00\xff'
        assert c.post('/auth/admin/lock').status_code==410
        ws.send_text('still ordinary iframe');assert ws.receive_text()=='still ordinary iframe'
        start=time.monotonic();change_identity(f,uid,sid,mode)
        with pytest.raises(WebSocketDisconnect) as err: ws.receive_text()
        assert err.value.code==1008
        assert time.monotonic()-start<7


def test_websocket_duplicate_host_rejected_before_upstream(integration_env):
    from starlette.websockets import WebSocketDisconnect
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    import httpx
    headers=httpx.Headers([('Host','attacker.invalid'),('Host',origin.removeprefix('https://')),('Cookie',cookie),('Origin',origin)])
    with pytest.raises(WebSocketDisconnect) as err:
        with c.websocket_connect(origin.replace('https:','wss:')+'/socket',headers=headers): pass
    assert err.value.code==4403
    assert seen==[]


def test_actual_main_legacy_drive_lock_blocks_all_writes_but_not_reads(integration_env,upstream,monkeypatch):
    from types import SimpleNamespace
    from app.services import external_services as external
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    root,_=upstream
    real_load=external.load
    real_check=external.check_resolved
    monkeypatch.setattr(external,'load',lambda db,kind: SimpleNamespace(browser_url=root,upstream_url=root,auth_mode='token',token='SYNTHETIC-CACHED-ADMIN') if kind=='drive' else real_load(db,kind))
    def only_fixture(url):
        if url.rstrip('/')==root.rstrip('/'): return None
        return real_check(url)
    monkeypatch.setattr(external,'check_resolved',only_fixture)
    writes=[('POST','api/fs/remove'),('POST','api/admin/setting/save'),('POST','api/admin/settings/save'),('PUT','api/fs/put'),('DELETE','api/admin/storage/delete')]
    for method,path in writes:
        assert c.request(method,'/drive/openlist/'+path,json={},headers={'Authorization':'SYNTHETIC-CACHED-ADMIN','Origin':'https://stella.xiya.live'}).status_code==200
    assert len(seen)==len(writes);seen.clear()
    assert c.post('/auth/admin/lock').status_code==410
    for method,path in writes:
        r=c.request(method,'/drive/openlist/'+path,json={},headers={'Authorization':'SYNTHETIC-CACHED-ADMIN','Origin':'https://stella.xiya.live'})
        assert r.status_code==200,r.text
    assert len(seen)==len(writes);seen.clear()
    assert c.post('/drive/openlist/api/fs/list',json={'path':'/'},headers={'Authorization':'SYNTHETIC-CACHED-ADMIN'}).status_code==200
    assert seen==[('POST','api/fs/list')]
    assert c.post('/auth/logout').status_code==200
    seen.clear()
    for method,path in writes:
        assert c.request(method,'/drive/openlist/'+path,json={},headers={'Authorization':'SYNTHETIC-CACHED-ADMIN','Origin':'https://stella.xiya.live'}).status_code==401
    assert seen==[]


def test_missing_host_rejected_by_actual_asgi_before_routing(integration_env):
    import asyncio
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    messages=[]
    async def recv(): return {'type':'http.request','body':b'','more_body':False}
    async def send(msg): messages.append(msg)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','scheme':'https','method':'GET','path':'/auth/me','raw_path':b'/auth/me','root_path':'','query_string':b'','headers':[], 'server':('stella.xiya.live',443),'client':('127.0.0.1',1)}
    asyncio.run(app(scope,recv,send))
    assert messages[0]['type']=='http.response.start' and messages[0]['status']==421
    assert seen==[]


def test_read_owner_check_never_enters_lazy_pin_initialization(integration_env,monkeypatch):
    from app.services import admin_security as owner_service
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    real_read=owner_service.read_state
    reads=[]
    def pin_disappears_between_reads(db):
        row,state=real_read(db)
        reads.append(True)
        if len(reads)>1: state.pop('owner_id',None)
        return row,state
    def forbidden_initialization(db):
        raise AssertionError('Integration reads must never enter lazy owner initialization')
    monkeypatch.setattr(owner_service,'read_state',pin_disappears_between_reads)
    monkeypatch.setattr(owner_service,'locked_state',forbidden_initialization)
    # One validated identity snapshot is an authorization linearization point;
    # subsequent revocation is observed on the next fresh request/WS check.
    assert c.get(origin+'/echo',headers={'Cookie':cookie}).status_code==200
    assert len(reads)==1


@pytest.fixture
def stream_lifespan_env(integration_env, monkeypatch):
    """Bind the real startup hook, not just HTTP get_db, to owned SQLite.

    PG-only periodic workers are outside a proxy-stream test: retain their real
    construction/stop but fence their scheduler start, never auth or streaming.
    This wrapper is local; importers of integration_env keep the same fixture.
    """
    from sqlalchemy import JSON, MetaData
    from sqlalchemy.dialects.postgresql import JSONB
    from app import database
    from app.models.node import Node
    from app.models.monitor import MonitorGroup
    from app.services.backup_center import BackupCenter
    from app.services.node_deadlines import NodeDeadlineWatcher
    c, factory, app, *_ = integration_env
    engine = factory.kw['bind']
    metadata = MetaData()
    for model in (Node, MonitorGroup):
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    metadata.create_all(engine)
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(database, 'sessionLocal', factory)
    monkeypatch.setattr(app.state, 'backup_center', None, raising=False)
    monkeypatch.setattr(app.state, 'node_deadlines', None, raising=False)
    started = []
    def owned_deadlines(cls, url):
        assert url == engine.url
        return cls(engine)
    def scheduler_start(worker, *args, **kwargs):
        assert worker.engine is engine
        started.append(type(worker))
    monkeypatch.setattr(NodeDeadlineWatcher, 'from_url', classmethod(owned_deadlines))
    monkeypatch.setattr(NodeDeadlineWatcher, 'start', scheduler_start)
    monkeypatch.setattr(BackupCenter, 'start', scheduler_start)
    yield integration_env
    assert started == [NodeDeadlineWatcher, BackupCenter]
    assert app.state.backup_center.stop_event.is_set()
    assert app.state.node_deadlines.stop_event.is_set()
    assert app.state.backup_center.timer is app.state.node_deadlines.timer is None
    with factory() as fresh:
        # Actual lifespan reconciliation committed its owned groups.
        assert fresh.query(Node).count() == 0
        assert fresh.query(MonitorGroup).count() == 2
    assert set(app.dependency_overrides) == {get_db}


def test_real_stream_releases_db_before_body_and_disconnect(stream_lifespan_env,upstream):
    import asyncio
    import httpx
    from fastapi.responses import StreamingResponse
    c,f,app,uid,sid,mid,origin,cookie,seen=stream_lifespan_env
    root,_=upstream
    # Reach fixture FastAPI through the registered handler's owner.
    # The streaming upstream is separate from production and contains only synthetic data.
    stream_app=FastAPI(); closed=threading.Event()
    @stream_app.get('/events')
    async def events():
        async def chunks():
            try:
                yield b'data: synthetic\n\n'
                await asyncio.sleep(30)
            finally: closed.set()
        return StreamingResponse(chunks(),media_type='text/event-stream')
    sock=socket.socket();sock.bind(('127.0.0.1',0))
    upstream_server=uvicorn.Server(uvicorn.Config(stream_app,log_level='error'))
    upstream_thread=threading.Thread(target=upstream_server.run,kwargs={'sockets':[sock]},daemon=True);upstream_thread.start()
    downstream=socket.socket();downstream.bind(('127.0.0.1',0))
    proxy_server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    proxy_thread=threading.Thread(target=proxy_server.run,kwargs={'sockets':[downstream]},daemon=True);proxy_thread.start()
    engine=f.kw['bind']
    try:
        deadline=time.monotonic()+5
        while (not upstream_server.started or not proxy_server.started) and time.monotonic()<deadline: time.sleep(.01)
        assert upstream_server.started and proxy_server.started
        with f() as db:
            row=db.get(AppConfig,store.KEY);state=json.loads(row.value)
            state['targets']['target']['upstream_url']=f'http://127.0.0.1:{sock.getsockname()[1]}/'
            row.value=json.dumps(state);db.commit()
        with httpx.Client(trust_env=False,timeout=4) as real:
            with real.stream('GET',f'http://127.0.0.1:{downstream.getsockname()[1]}/events',headers={'Host':origin.removeprefix('https://'),'Cookie':cookie}) as response:
                assert response.status_code==200
                assert next(response.iter_raw())==b'data: synthetic\n\n'
                if hasattr(engine.pool,'checkedout'): assert engine.pool.checkedout()==0
                # Independent fresh DB authorization still works during the stream.
                with f() as db: assert sessions.authorize(db,mid,origin,cookie.split('=',1)[1])['sid']==sid
            assert closed.wait(4), 'upstream not cancelled on disconnect'
    finally:
        proxy_server.should_exit=True;upstream_server.should_exit=True
        proxy_thread.join(5);upstream_thread.join(5);downstream.close();sock.close()
    assert not proxy_thread.is_alive() and not upstream_thread.is_alive()


@pytest.fixture
def integration_pg(integration_env):
    """Explicit disposable PG only; copy the real main-issued identity and grant."""
    from sqlalchemy.orm import Session
    from uuid import uuid4
    dsn = os.environ.get('STELLA_INTEGRATION_LOOP_TEST_DSN')
    if not dsn: pytest.skip('explicit owned PG fixture required')
    c, source, app, uid, sid, mid, origin, cookie, seen = integration_env
    root = create_engine(dsn)
    assert root.url.database == 'integration_offload'
    schema = 'integration_offload_' + uuid4().hex
    with root.begin() as conn: conn.exec_driver_sql('CREATE SCHEMA ' + schema)
    engine = create_engine(dsn, connect_args={'options':'-csearch_path='+schema})
    tables = (User.__table__, AuthSession.__table__, AppConfig.__table__)
    for table in tables: table.create(engine)
    # Keep the source Session scoped too; never leave fixture connections open.
    with source() as source_db, engine.begin() as dest:
        for table in tables:
            rows = [dict(row) for row in source_db.execute(table.select()).mappings()]
            if rows: dest.execute(table.insert(), rows)
    trace = []
    class OwnedSession(Session):
        def __init__(self, *a, **kw):
            self.trace_id = len(trace)
            trace.append(('create', self.trace_id, threading.get_ident()))
            super().__init__(*a, **kw)
        def close(self):
            trace.append(('close', self.trace_id, threading.get_ident()))
            return super().close()
    factory = sessionmaker(engine, class_=OwnedSession)
    try: yield factory, engine, trace, mid, origin, cookie, sid
    finally:
        engine.dispose()
        with root.begin() as conn: conn.exec_driver_sql('DROP SCHEMA '+schema+' CASCADE')
        root.dispose()


@pytest.mark.parametrize('phase', ['read', 'checkout', 'redeem', 'alias', 'websocket'])
def test_integration_preparation_pg_keeps_loop_alive(integration_pg, monkeypatch, phase):
    import asyncio
    from app.services import access_entries, integrations_proxy
    from starlette.responses import Response
    factory, engine, trace, mid, origin, cookie, sid = integration_pg
    if phase == 'alias':
        origin = 'https://immich.xiya.live'
        assert origin.removeprefix('https://') in store.IMMICH_HOSTS
        with factory() as db, store.edit(db) as config:
            config['modules'][mid]['origin'] = origin
            config['modules'][mid]['adapter'] = 'immich'
    ticket = None
    if phase == 'redeem':
        with factory() as db:
            ticket = sessions.issue(db, store.get_module(db, mid), sid, 'https://stella.xiya.live')['fields']['ticket']
    trace.clear()
    started, release = threading.Event(), threading.Event()
    checks = []
    checkout_count = []
    def slow_sql(conn, cursor, statement, parameters, context, many):
        trace.append(('sql', id(conn), threading.get_ident()))
        selected = ('FOR UPDATE' in statement.upper() if phase == 'redeem' else
                    store.KEY in str(parameters) if phase != 'checkout' else False)
        if selected and not started.is_set():
            started.set(); cursor.execute('SELECT pg_sleep(0.25)')
            assert release.wait(2), 'bounded PG release failed'
    def slow_checkout(conn, record, proxy):
        checkout_count.append(threading.get_ident())
        if phase == 'checkout' and len(checkout_count) == 2:
            started.set(); conn.cursor().execute('SELECT pg_sleep(0.25)')
            assert release.wait(2)
    event.listen(engine, 'before_cursor_execute', slow_sql)
    event.listen(engine, 'checkout', slow_checkout)
    def releaser():
        if started.wait(3): time.sleep(.3); release.set()
    thread = threading.Thread(target=releaser); thread.start()
    async def exercise():
        loop_thread = threading.get_ident()
        ticks, sent, body_checkouts = [], [], []
        async def heartbeat():
            while not release.is_set():
                if started.is_set(): ticks.append(time.monotonic())
                await asyncio.sleep(.005)
        async def app(*a): pytest.fail('integration must not fall through to main')
        async def http(request, module, target, source_origin):
            assert engine.pool.checkedout() == 0
            assert module['origin'] == origin and source_origin == 'https://stella.xiya.live'
            assert target['allowed_ips'] == ['127.0.0.1']
            checks.append(access_entries.current())
            return Response('synthetic')
        async def ws(socket, module, target, db_factory, grant):
            assert engine.pool.checkedout() == 0
            assert grant['sid'] == sid
            checks.append(access_entries.current())
            await socket.close()
        monkeypatch.setattr(integrations_proxy, 'proxy_http', http)
        monkeypatch.setattr(integrations_proxy, 'proxy_websocket', ws)
        headers=[(b'host',origin.removeprefix('https://').encode()),(b'cookie',cookie.encode())]
        path = '/__stella/bootstrap' if ticket else '/echo'
        if ticket: headers += [(b'origin',b'https://stella.xiya.live'),(b'content-type',b'application/x-www-form-urlencoded')]
        scope={'type':'websocket' if phase=='websocket' else 'http','asgi':{'version':'3.0'},'http_version':'1.1','scheme':'https','method':'POST' if ticket else 'GET','path':path,'raw_path':path.encode(),'root_path':'','query_string':b'','headers':headers,'server':('fixture',443),'client':('127.0.0.1',1)}
        async def receive():
            assert threading.get_ident() == loop_thread
            body_checkouts.append(engine.pool.checkedout())
            return {'type':'http.request','body':('ticket='+ticket).encode() if ticket else b'','more_body':False}
        async def send(message): sent.append(message)
        beat=asyncio.create_task(heartbeat())
        try:
            await IntegrationsHostMiddleware(app, factory)(scope, receive, send)
            assert started.is_set(), 'expected PG boundary was not exercised'
            assert len(ticks)>=5, f'integration {phase} blocked independent heartbeat: {len(ticks)} ticks'
            assert not any(body_checkouts), 'no Session may span bootstrap body receive'
            sessions_by_id = {}
            for kind, identity, tid in trace:
                if kind in {'create','close'}: sessions_by_id.setdefault(identity, []).append((kind,tid))
                assert tid != loop_thread, trace
            assert all([kind for kind,_ in events]==['create','close'] and len({tid for _,tid in events})==1 for events in sessions_by_id.values())
            assert engine.pool.checkedout() == 0
            if phase == 'alias': assert sent[0]['status'] == 410
            elif ticket: assert sent[0]['status'] == 303
            else: assert checks and checks[0] is not None
            assert access_entries.current() is None
        finally:
            release.set(); await beat
    try: asyncio.run(exercise())
    finally:
        release.set(); thread.join(4)
        event.remove(engine, 'before_cursor_execute', slow_sql)
        event.remove(engine, 'checkout', slow_checkout)


@pytest.mark.parametrize('phase', ['read', 'redeem'])
def test_cancel_blocked_integration_pg_eventually_closes(integration_pg, monkeypatch, phase):
    import asyncio
    from app.services import access_entries, integrations_proxy
    factory, engine, trace, mid, origin, cookie, sid = integration_pg
    ticket = None
    if phase == 'redeem':
        with factory() as db:
            ticket = sessions.issue(db, store.get_module(db, mid), sid, 'https://stella.xiya.live')['fields']['ticket']
    trace.clear()
    entered, release = threading.Event(), threading.Event()
    def block(conn, cursor, statement, params, context, many):
        selected = 'FOR UPDATE' in statement.upper() if ticket else store.KEY in str(params)
        if selected and not entered.is_set():
            entered.set()
            cursor.execute('SELECT pg_sleep(0.1)')
            assert release.wait(3)
    event.listen(engine, 'before_cursor_execute', block)
    # This also bounds an unfixed event-loop block, so RED cannot hang pytest.
    timer = threading.Timer(1, release.set); timer.start()
    async def exercise():
        async def forbidden(*args): pytest.fail('cancelled preparation must not proxy')
        monkeypatch.setattr(integrations_proxy, 'proxy_http', forbidden)
        path='/__stella/bootstrap' if ticket else '/echo'
        headers=[(b'host',origin.removeprefix('https://').encode()),(b'cookie',cookie.encode())]
        if ticket: headers += [(b'origin',b'https://stella.xiya.live'),(b'content-type',b'application/x-www-form-urlencoded')]
        scope={'type':'http','scheme':'https','method':'POST' if ticket else 'GET','path':path,'raw_path':path.encode(),'query_string':b'','headers':headers}
        async def receive(): return {'type':'http.request','body':('ticket='+ticket).encode() if ticket else b'','more_body':False}
        async def send(message): pytest.fail('cancelled request must not respond')
        middleware=IntegrationsHostMiddleware(forbidden, factory)
        task=asyncio.create_task(middleware(scope,receive,send))
        try:
            while not entered.is_set(): await asyncio.sleep(.001)
            assert not release.is_set(), 'blocked integration prevented cancellation admission'
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert access_entries.current() is None
            assert not any(c['total'] for c in middleware._inflight.values())
        finally:
            release.set()
            for _ in range(2000):
                creates=[row for row in trace if row[0]=='create']
                closes=[row for row in trace if row[0]=='close']
                if len(creates)==len(closes) and engine.pool.checkedout()==0: break
                await asyncio.sleep(.001)
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert len(creates)==len(closes)==2, trace
        for _, identity, tid in creates:
            assert tid != threading.get_ident()
            assert ('close', identity, tid) in closes
        assert engine.pool.checkedout()==0
    try: asyncio.run(exercise())
    finally:
        release.set(); timer.cancel(); timer.join(2)
        event.remove(engine, 'before_cursor_execute', block)


def _assert_worker_threads_off_loop(workers, loops):
    # Keep strong Thread references: ident can be reused by later portal threads.
    assert workers and loops and all(w[1] is not loop[1] for w in workers for loop in loops), 'integration preparation ran on request loop thread'


def test_worker_thread_oracle_survives_reused_numeric_ident():
    from types import SimpleNamespace
    # A local observer models legal ident reuse after a previous thread exits;
    # never monkeypatch threading.get_ident (threading itself depends on it).
    def observe(kind, thread): return (kind, thread, None)
    worker=observe('worker',SimpleNamespace(ident=7))
    loop=observe('loop',SimpleNamespace(ident=7))
    with pytest.raises(AssertionError):
        assert worker[1].ident != loop[1].ident  # The CI184 numeric oracle is RED.
    _assert_worker_threads_off_loop([worker],[loop])
    with pytest.raises(AssertionError,match='preparation ran on request loop'):
        _assert_worker_threads_off_loop([worker],[observe('loop',worker[1])])


@pytest.mark.parametrize('lane', ['public', 'private'])
def test_worker_context_projection_and_bootstrap_remain_request_local(integration_env, monkeypatch, lane):
    from app.services import access_entries, integrations_proxy
    from app.routers import integrations_host
    from starlette.responses import Response
    c, factory, app, uid, sid, mid, public, cookie, seen = integration_env
    parent='https://stella.xiya.live'
    private_parent='https://stella.p.xiya.live'
    private='https://app-'+mid+'.p.xiya.live'
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([
        {'service_id':'stella','public':parent,'private':private_parent},
        {'service_id':mid,'public':public,'private':private}]))
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS',parent+','+private_parent)
    with factory() as db:
        with store.edit(db) as config:
            config['modules'][mid].update(mapping_configured=True,alternate_address='http://127.0.0.2/other',
                alternate_binding={'target_id':'b'*32,'initial_path':'/other'})
            config['targets']['b'*32]=dict(config['targets']['target'],id='b'*32,allowed_ips=['127.0.0.2'])
        before=db.get(AppConfig,store.KEY).value
        db.add(AppConfig(key=access_entries.KEY,value=json.dumps({'owner_id':str(uid),'settings':{'revision':7,'enabled':True,'public_origin':parent,'private_origin':private_parent}})))
        db.commit()
    expected={'revision':7,'enabled':True,'public_origin':parent,'private_origin':private_parent}
    observations=[]; request_loops=[]
    real_offload=integrations_host.run_in_threadpool
    async def observe_prepare(func, *args, **kwargs):
        # Observe each bootstrap/read's live submitting loop, not only the final
        # GET's proxy loop after earlier TestClient portals have already exited.
        request_loops.append(('loop',threading.current_thread(),access_entries.current()))
        return await real_offload(func,*args,**kwargs)
    monkeypatch.setattr(integrations_host,'run_in_threadpool',observe_prepare)
    real_get=store.get_module
    def get(db, module_id):
        snapshot=access_entries.current()
        assert dict(snapshot)==expected
        with pytest.raises(TypeError): snapshot['revision']=8
        observations.append(('worker',threading.current_thread(),snapshot))
        return real_get(db,module_id)
    monkeypatch.setattr(store,'get_module',get)
    chosen=public if lane=='public' else private
    source=parent if lane=='public' else private_parent
    async def proxy(request,module,target,source_origin):
        assert dict(access_entries.current())==expected
        assert module['origin']==chosen and source_origin==source
        assert module['target_id']==('target' if lane=='public' else 'b'*32)
        assert target['allowed_ips']==(['127.0.0.1'] if lane=='public' else ['127.0.0.2'])
        observations.append(('loop',threading.current_thread(),access_entries.current()))
        return Response('isolated')
    monkeypatch.setattr(integrations_proxy,'proxy_http',proxy)
    with factory() as db:
        # issue is a sync consumer and receives the same immutable snapshot.
        with access_entries.request_snapshot(factory):
            issued=sessions.issue(db,real_get(db,mid),sid,source)
    boot=c.post(chosen+'/__stella/bootstrap',data=issued['fields'],headers={'Origin':source},follow_redirects=False)
    assert boot.status_code==303,boot.text
    grant_cookie=boot.headers['set-cookie'].split(';')[0]
    assert c.post(chosen+'/__stella/bootstrap',data=issued['fields'],headers={'Origin':source},follow_redirects=False).status_code==401
    assert c.get(chosen+'/echo',headers={'Cookie':grant_cookie}).text=='isolated'
    workers=[row for row in observations if row[0]=='worker']; loops=[row for row in observations if row[0]=='loop']
    _assert_worker_threads_off_loop(workers,request_loops+loops)
    assert loops
    assert all(any(w[2] is loop[2] for loop in request_loops) for w in workers)
    assert workers[-1][2] is loops[-1][2]
    with factory() as db:
        after=json.loads(db.get(AppConfig,store.KEY).value)
        assert after['modules']==json.loads(before)['modules']
        assert after['targets']==json.loads(before)['targets']
    change_identity(factory,uid,sid,'revoked')
    assert c.get(chosen+'/echo',headers={'Cookie':grant_cookie}).status_code==401


@pytest.mark.parametrize('kind,status', [('method',405), ('query',405), ('origin',403), ('content_type',415), ('large',413), ('format',400)])
def test_bootstrap_validation_precedes_integration_db(integration_env, kind, status):
    c, factory, app, uid, sid, mid, origin, cookie, seen = integration_env
    reads=[]
    def record(conn, cursor, statement, params, context, many):
        if store.KEY in str(params): reads.append(statement)
    engine=factory.kw['bind']
    event.listen(engine,'before_cursor_execute',record)
    headers={'Origin':'https://stella.xiya.live','Content-Type':'application/x-www-form-urlencoded'}
    method='GET' if kind=='method' else 'POST'
    if kind=='origin': headers['Origin']='https://attacker.invalid'
    if kind=='content_type': headers['Content-Type']='application/json'
    body='x=y' if kind=='format' else 'ticket='+('x'*2050 if kind=='large' else 'synthetic')
    try:
        result=c.request(method,origin+'/__stella/bootstrap'+('?bad=1' if kind=='query' else ''),content=body,headers=headers,follow_redirects=False)
        assert result.status_code==status,result.text
        assert reads==[], 'invalid body/origin must not checkout integration state'
    finally: event.remove(engine,'before_cursor_execute',record)
    assert seen==[]


@pytest.mark.parametrize('method', ['GET','WEBSOCKET'])
def test_encoded_reserved_path_cannot_escape_to_proxy(integration_env, method):
    c, factory, app, uid, sid, mid, origin, cookie, seen = integration_env
    result=c.request(method,origin+'/%5f%5fstella/unknown',headers={'Cookie':cookie})
    assert result.status_code==404,result.text
    assert result.json()=={'detail':'保留集成路径'}
    assert seen==[]


def test_main_passthrough_keeps_one_snapshot_and_no_integration_queries(integration_env, monkeypatch):
    from app.services import access_entries
    from starlette.responses import Response
    _, factory, *_ = integration_env
    public='https://stella.xiya.live'; private='https://stella.p.xiya.live'
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([{'service_id':'stella','public':public,'private':private}]))
    statements=[]; snapshots=[]
    async def app(scope,receive,send):
        snapshots.append(dict(access_entries.current()))
        await Response('main')(scope,receive,send)
    def sql(conn,cursor,statement,params,context,many): statements.append((statement,params))
    engine=factory.kw['bind']; event.listen(engine,'before_cursor_execute',sql)
    try:
        client=TestClient(IntegrationsHostMiddleware(app,factory))
        try:
            for origin in (public, private):
                statements.clear()
                response=client.get(origin+'/assets/main.css')
                assert response.status_code==200 and response.text=='main'
                assert len(statements)==1 and access_entries.KEY in str(statements[0][1]), statements
        finally: client.close()
        assert snapshots==[{'revision':0,'enabled':False,'public_origin':public,'private_origin':private}]*2
    finally: event.remove(engine,'before_cursor_execute',sql)
