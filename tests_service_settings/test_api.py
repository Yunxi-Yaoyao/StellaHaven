"""Synthetic SQLite + real daily/admin auth. No application PG connections."""
import importlib.util
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def api(tmp_path, monkeypatch):
    from app.database import get_db, engine as unused
    from app.models.config import AppConfig
    from app.models.user import User, AuthSession, EmailCode
    from app.routers.auth import router as auth
    from app.services import oidc
    monkeypatch.delenv('STELLA_OWNER_ID', raising=False)
    monkeypatch.setenv('STELLA_SHARED_STATE', 'legacy')
    monkeypatch.setattr(oidc, 'CLIENT_FILE', tmp_path / 'absent-clients.json')
    def deny(*a, **kw): raise AssertionError('application PG forbidden')
    event.listen(unused, 'do_connect', deny)
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    for table in (AppConfig.__table__, User.__table__, AuthSession.__table__, EmailCode.__table__):
        table.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(auth)
    if importlib.util.find_spec('app.routers.service_settings'):
        from app.routers.service_settings import router
        app.include_router(router)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app, base_url='https://testserver') as client:
        assert client.post('/auth/register', json={'username':'settings-owner', 'password':'daily-synthetic-123'}).status_code == 201
        yield client, factory, engine, oidc
    engine.dispose()
    event.remove(unused, 'do_connect', deny)


def snapshot(factory):
    from app.models.config import AppConfig
    with factory() as db:
        return {row.key:row.value for row in db.query(AppConfig).all()}


def elevate(client):
    assert client.post('/auth/admin/setup', json={'user_password':'daily-synthetic-123','new_password':'admin-synthetic-456'}).status_code == 200
    assert client.post('/auth/admin/unlock', json={'password':'admin-synthetic-456'}).status_code == 200


def payload(site='drive'):
    return {'name':'My drive' if site == 'drive' else 'My gallery', 'icon':'star', 'visible':False,
            'connection': {'service_url':'http://127.0.0.1:5244/drive/openlist','auth_mode':'manual','token':None,'clear_token':False} if site == 'drive' else {'browser_url':'https://gallery.example','upstream_url':'','alternate_browser_url':'','auth_mode':'manual'},
            'appearance': {'theme':'original','simplified':False} if site == 'drive' else {'logo':'original'}}


def test_daily_get_is_redacted_and_sql_read_only(api):
    client, factory, engine, oidc = api
    from app.models.config import AppConfig
    from app.services import integrations as store
    config = store.empty_state()
    config['targets']['quota'] = {'headers':{'Authorization':'SYNTHETIC-QUOTA-SECRET'}}
    with factory() as db:
        db.add(AppConfig(key=store.KEY,value=json.dumps(config)))
        db.add(AppConfig(key='external_drive_connection',value=json.dumps({'browser_url':'http://127.0.0.1:5244','auth_mode':'token','token':'SYNTHETIC-DRIVE-SECRET'})))
        db.commit()
    oidc.CLIENT_FILE.write_text(json.dumps({'immich':{'client_secret':'SYNTHETIC-OIDC-SECRET','redirect_uris':['https://gallery.example/auth/login']},'private-client':{'client_secret':'OTHER-SECRET'}}))
    before = snapshot(factory)
    sql=[]
    def observe(conn,cursor,statement,*args): sql.append(statement)
    event.listen(engine,'before_cursor_execute',observe)
    try:
        drive=client.get('/service-settings/drive')
        assert drive.status_code == 200, drive.text
        gallery=client.get('/service-settings/gallery')
        assert gallery.status_code == 200, gallery.text
    finally: event.remove(engine,'before_cursor_execute',observe)
    assert set(drive.json()) == {'site','name','icon','visible','connection','appearance','injection','capabilities','scopes','oidc','compatibility'}
    assert drive.json()['connection'] == {'service_url':'http://127.0.0.1:5244','auth_mode':'token','has_token':True}
    assert drive.json()['appearance'] == {'theme':'stella','simplified':True}
    assert drive.json()['oidc'] is None
    assert gallery.json()['appearance'] == {'logo':'stella'}
    assert gallery.json()['oidc'] == {'client_registered':True,'issuer':'https://stella.xiya.live','client_id':'immich','redirect_uris':['https://gallery.example/auth/login']}
    assert gallery.json()['scopes'] == {'appearance':'domain','background':None}
    assert not any(word in (drive.text+gallery.text) for word in ('SYNTHETIC-', 'OTHER-SECRET','client_secret','targets'))
    assert snapshot(factory) == before
    assert sql and all(statement.lstrip().upper().startswith('SELECT') for statement in sql), sql
    assert client.get('/service-settings/missing').status_code == 404
    client.cookies.clear()
    assert client.get('/service-settings/drive').status_code == 401


def test_atomic_put_readback_keeps_registry_and_custom_versions(api, monkeypatch):
    client,factory,engine,_=api
    from app.models.config import AppConfig
    from app.services import integrations as store, builtin_injection as injection
    before=snapshot(factory)
    assert client.put('/service-settings/drive',json=payload()).status_code==403
    assert snapshot(factory)==before
    elevate(client)
    registry=store.empty_state()
    registry['targets']['quota']={'headers':{'Authorization':'SYNTHETIC-QUOTA-SECRET'}}
    registry['navigation']=[{'id':'home','visible':False},{'id':'drive','title':'Old drive','icon':'hard-drive','visible':True}]
    with factory() as db:
        db.add(AppConfig(key=store.KEY,value=json.dumps(registry)))
        db.commit()
    custom={'enabled':True,'css':'body{color:red}','js':'window.testCustom=1;','timing':'dom_ready','csp_policy':'reject'}
    data=payload()|{'custom':custom}
    data['connection'].update(auth_mode='token',token='SYNTHETIC-TOKEN')
    saved=client.put('/service-settings/drive',json=data)
    assert saved.status_code==200,saved.text
    result=saved.json()
    assert result==client.get('/service-settings/drive').json()
    assert result['name']==data['name'] and result['appearance']==data['appearance']
    assert result['connection']['has_token'] and 'SYNTHETIC-TOKEN' not in saved.text
    assert result['injection']['draft']==custom
    assert result['injection']['previous']['version']=='preset-v1'
    first=result['injection']['active']['version']
    assert first!='preset-v1'
    with factory() as db:
        state=store.state(db)
        assert state['targets']==registry['targets']
        assert state['navigation'][0]==registry['navigation'][0]
        assert state['navigation'][1]=={'id':'drive','title':'My drive','icon':'star','visible':False}
    assert client.put('/service-settings/drive',json=data).json()==result
    # Omitted custom retains even a draft different from the active version.
    with factory() as db:
        row=db.get(AppConfig,injection.KEY);state=json.loads(row.value)
        state['drive']['draft']=custom|{'css':'body{color:blue}'}
        row.value=json.dumps(state);db.commit()
    without=payload();without['connection'].update(auth_mode='token')
    saved=client.put('/service-settings/drive',json=without)
    assert saved.status_code==200,saved.text
    assert saved.json()['injection']['active']['version']==first
    assert saved.json()['injection']['draft']['css']=='body{color:blue}'
    assert saved.json()['connection']['has_token']
    # Fault after every slot is flushed must roll the WHOLE transaction back.
    before=snapshot(factory)
    from app.services import service_settings
    def fault(*args,**kw): raise RuntimeError('synthetic audit failure')
    monkeypatch.setattr(service_settings,'record_change',fault)
    with pytest.raises(RuntimeError,match='synthetic audit failure'):
        client.put('/service-settings/drive',json=data|{'name':'Never stored','custom':custom|{'js':'window.other=2;'}})
    assert snapshot(factory)==before


def test_check_unsaved_connection_is_readonly_real_loopback(api):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    client,factory,engine,_=api
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path,dict(self.headers)))
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(b'{"code":200}')
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.2',5244),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    before=snapshot(factory)
    sql=[]
    def observe(conn,cursor,statement,*args):sql.append(statement)
    event.listen(engine,'before_cursor_execute',observe)
    try:
        response=client.post('/service-settings/drive/check',json={'connection':{'service_url':'http://127.0.0.2:5244/unsaved','auth_mode':'manual'}})
        assert response.status_code==200,response.text
        assert response.json()['ok'] is True
        assert '浏览器' in response.json()['warning']
        assert [item[0] for item in seen]==['/unsaved/api/public/settings']
        assert not any(k.lower() in {'cookie','authorization','referer'} for k in seen[0][1])
        assert all(s.lstrip().upper().startswith('SELECT') for s in sql),sql
    finally:
        event.remove(engine,'before_cursor_execute',observe)
        server.shutdown();server.server_close();thread.join(3);assert not thread.is_alive()
    assert snapshot(factory)==before


@pytest.mark.parametrize('site,change',[
    ('drive',{'name':'  '}),('drive',{'icon':'not-an-icon'}),
    ('drive',{'appearance':{'theme':'invalid','simplified':True}}),
    ('drive',{'connection':{'service_url':'http://169.254.169.254','auth_mode':'manual'}}),
    ('drive',{'connection':{'service_url':'https://example.com','auth_mode':'token','token':None}}),
    ('drive',{'connection':{'service_url':'https://example.com','auth_mode':'token','token':'SYNTHETIC-TOKEN\ninvalid'}}),
    ('gallery',{'connection':{'browser_url':'https://gallery.example','auth_mode':'token','token':'SYNTHETIC-GALLERY-SECRET'}}),
    ('gallery',{'appearance':{'logo':'stella','extra':True}}),
    ('drive',{'custom':{'enabled':True,'js':'const = syntax error;'}}),
    ('drive',{'custom':{'enabled':True,'csp_policy':'controlled'}}),
    ('drive',{'custom':None}),
])
def test_invalid_put_has_no_partial_state_or_secret_echo(api,site,change):
    client,factory,_,_=api;elevate(client)
    before=snapshot(factory)
    response=client.put('/service-settings/'+site,json=payload(site)|change)
    assert response.status_code==422,response.text
    assert 'SYNTHETIC-' not in response.text
    assert snapshot(factory)==before


def test_gallery_put_and_drive_clear_token(api):
    client,factory,_,_=api;elevate(client)
    for site in ('drive','gallery'):
        saved=client.put('/service-settings/'+site,json=payload(site))
        assert saved.status_code==200,saved.text
        assert saved.json()==client.get('/service-settings/'+site).json()
        assert saved.json()['appearance']==payload(site)['appearance']
    data=payload();data['connection'].update(auth_mode='token',token='SYNTHETIC-TOKEN')
    assert client.put('/service-settings/drive',json=data).json()['connection']['has_token']
    data['connection'].update(auth_mode='manual',token=None,clear_token=True)
    assert not client.put('/service-settings/drive',json=data).json()['connection']['has_token']


def test_main_registration_and_api_fallback(monkeypatch):
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','https://stella.xiya.live')
    import main
    with TestClient(main.app,base_url='https://stella.xiya.live') as client:
        assert client.get('/service-settings/drive').status_code==401
        assert client.get('/service-settings/drive/missing').status_code==404
    assert '/service-settings' in main.API_PREFIXES


def test_daily_check_cannot_send_saved_token_to_edited_target(api, monkeypatch):
    client,factory,_,_=api
    from app.models.config import AppConfig
    from app.services import external_services as external
    with factory() as db:
        db.add(AppConfig(key='external_drive_connection',value=json.dumps({'browser_url':'https://saved.example','upstream_url':'https://saved.example/base','auth_mode':'token','token':'SYNTHETIC-STORED-SECRET'})));db.commit()
    probes=[]
    async def observe(site,cfg):
        probes.append((site,cfg));return {'ok':True,'message':'connected','warning':''}
    monkeypatch.setattr(external,'probe',observe)
    before=snapshot(factory)
    changed={'connection':{'service_url':'https://edited.example','auth_mode':'token','token':None}}
    response=client.post('/service-settings/drive/check',json=changed)
    assert response.status_code==422,response.text
    assert not probes and snapshot(factory)==before
    changed['connection']['service_url']='https://saved.example/base'
    response=client.post('/service-settings/drive/check',json=changed)
    assert response.status_code==200,response.text
    assert probes[0][1].token=='SYNTHETIC-STORED-SECRET'
    assert 'SYNTHETIC-STORED-SECRET' not in response.text
    assert snapshot(factory)==before


def test_gallery_asset_get_without_pin_never_initializes(api):
    client,factory,engine,_=api
    from app.models.config import AppConfig
    from app.services.admin_security import STATE_KEY
    from app.routers.builtin_injection import assets_router
    client.app.include_router(assets_router)
    with factory() as db:
        db.delete(db.get(AppConfig,STATE_KEY));db.commit()
    before=snapshot(factory)
    response=client.get('/integration-assets/gallery.js')
    assert response.status_code==200,response.text
    assert snapshot(factory)==before


def test_missing_owner_pin_get_never_initializes(api):
    client,factory,engine,_=api
    from app.models.config import AppConfig
    from app.services.admin_security import STATE_KEY
    with factory() as db:
        db.delete(db.get(AppConfig,STATE_KEY));db.commit()
    before=snapshot(factory)
    response=client.get('/service-settings/drive')
    assert response.status_code==503,response.text
    assert snapshot(factory)==before
