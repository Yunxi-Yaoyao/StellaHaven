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
    assert c.post('/auth/admin/setup',json={'user_password':DAILY,'new_password':ADMIN}).status_code==200
    assert c.post('/auth/admin/unlock',json={'password':ADMIN}).status_code==200
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
    assert c.post('/auth/admin/lock').status_code==200
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
        assert c.post('/auth/admin/lock').status_code==200
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
    assert c.post('/auth/admin/lock').status_code==200
    for method,path in writes:
        r=c.request(method,'/drive/openlist/'+path,json={},headers={'Authorization':'SYNTHETIC-CACHED-ADMIN','Origin':'https://stella.xiya.live'})
        assert r.status_code==403,r.text
        assert r.json()['detail']['code']=='admin_elevation_required'
    assert seen==[]
    assert c.post('/drive/openlist/api/fs/list',json={'path':'/'},headers={'Authorization':'SYNTHETIC-CACHED-ADMIN'}).status_code==200
    assert seen==[('POST','api/fs/list')]


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


def test_real_stream_releases_db_before_body_and_disconnect(integration_env,upstream):
    import asyncio
    import httpx
    from fastapi.responses import StreamingResponse
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
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
