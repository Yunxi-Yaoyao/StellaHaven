"""Dedicated disposable PostgreSQL + real HTTP/auth; never production."""
import os
from pathlib import Path
from uuid import UUID, uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(os.getenv('NAV_NATIVE_PG_TEST') != '1', reason='explicit dedicated native-nav PostgreSQL required')

@pytest.fixture
def lane():
    from qa.native_nav_pg_guard import target, verify_connection
    port, database, username, container_id = target()
    from app.database import Base, get_db
    from app.models.user import User, AuthSession
    from app.models.config import AppConfig
    from app.routers import auth
    engine = create_engine(f'postgresql://{username}@127.0.0.1:{port}/{database}')
    schema = 'nav_' + uuid4().hex
    with engine.begin() as c:
        verify_connection(c, database, username)
        c.execute(text(f'CREATE SCHEMA {schema}'))
    scoped = create_engine(engine.url, connect_args={'options': f'-csearch_path={schema}'})
    factory = sessionmaker(scoped)
    app = FastAPI()
    if Path(os.environ['NAV_ROOT'], 'app/services/native_nav_limits.py').exists():
        from app.services.native_nav_limits import NativeNavLimitsMiddleware
        app.add_middleware(NativeNavLimitsMiddleware)
    app.include_router(auth.router)
    nav = None
    if Path(os.environ['NAV_ROOT'], 'app/routers/native_nav.py').exists():
        from app.routers import native_nav as nav
        app.include_router(nav.router)
    tables = [User.__table__, AuthSession.__table__, AppConfig.__table__]
    if nav:
        tables += [nav.NavState.__table__, nav.NavAsset.__table__]
    Base.metadata.create_all(scoped, tables=tables)
    def dbdep():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = dbdep
    from app.services.admin_security import STATE_KEY
    import json
    uid, other = uuid4(), uuid4()
    with factory() as db:
        db.add_all([User(id=uid,username='nav-owner',display_name='Nav owner'), User(id=other,username='nav-other',display_name='Other')])
        db.add(AppConfig(key=STATE_KEY,value=json.dumps({'owner_id': str(uid)})))
        db.commit()
    client = TestClient(app, base_url='https://nav-qa.test')
    from starlette.requests import Request
    from starlette.responses import Response
    with factory() as db:
        response = Response()
        req = Request({'type':'http','scheme':'https','server':('nav-qa.test',443),'path':'/auth/login','headers':[(b'host', b'nav-qa.test')],'query_string':b'','client':('127.0.0.1',12345)})
        auth._create_session(db,db.get(User,uid),req,response,False)
        db.commit()
        for cookie in response.headers.getlist('set-cookie'):
            client.cookies.update({cookie.split('=',1)[0]:cookie.split('=',1)[1].split(';',1)[0]})
    try:
        yield client, factory, uid, other, nav, app
    finally:
        client.close(); scoped.dispose()
        with engine.begin() as c:
            c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        engine.dispose()

def test_additive_native_migration_roundtrip_preserves_users(lane):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    client,factory,uid,other,nav,app=lane
    spec=importlib.util.spec_from_file_location('nav_migration',Path(os.environ['NAV_ROOT'],'alembic/versions/cf20261023nav_native_navigation.py'))
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    with factory().get_bind().begin() as c:
        migration.op=Operations(MigrationContext.configure(c));migration.downgrade();migration.upgrade()
        assert {'nav_states','nav_assets'}<=set(inspect(c).get_table_names())
        assert c.scalar(text('select count(*) from users'))==2
        assert 'owner_id' in {x['name'] for x in inspect(c).get_columns('nav_states')}
    assert client.get('/nav-data').status_code==200


def test_asset_delete_and_reference_race_is_serialized(lane):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import base64
    client,factory,uid,other,nav,app=lane
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qXYAAAAASUVORK5CYII=')
    a=client.post('/nav-assets',files={'file':('race.png',png,'image/png')}).json()
    body=client.get('/nav-data').json();body['mutation_id']=str(uuid4());body['data']['preferences']['backgroundUrl']=a['url']
    gate=Barrier(2)
    def write():gate.wait(timeout=5);return client.put('/nav-data',json=body).status_code
    def delete():gate.wait(timeout=5);return client.delete(a['url']).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        w,d=pool.submit(write),pool.submit(delete);statuses=(w.result(),d.result())
    assert statuses in {(200,409),(422,200)}
    with factory() as db:
        state=db.get(nav.NavState,uid);asset=db.get(nav.NavAsset,UUID(a['id']))
        assert state.data['preferences']['backgroundUrl']!=a['url'] or asset is not None


def test_cross_owner_pinned_switch_cannot_reuse_old_session(lane):
    import json
    from app.models.config import AppConfig
    from app.services.admin_security import STATE_KEY
    client,factory,uid,other,nav,app=lane
    with factory() as db:
        db.get(AppConfig,STATE_KEY).value=json.dumps({'owner_id':str(other)});db.commit()
    assert client.get('/nav-data').status_code==403
    assert client.get('/nav-assets').status_code==403
    assert client.post('/nav-import-preview',json={'source':'{}'}).status_code==403
    assert client.get('/nav-export').status_code==403


def test_native_http_body_limits_before_parse(lane):
    client,*_=lane
    assert client.put('/nav-data',content=b'x'*(4*1024*1024+1),headers={'Content-Type':'application/json'}).status_code==413
    assert client.post('/nav-assets',content=b'x'*(4*1024*1024+1),headers={'Content-Type':'multipart/form-data; boundary=x'}).status_code==413


def test_cross_owner_session_and_snapshot_cas(lane):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    client,factory,uid,other,nav,app=lane
    from app.schemas.native_nav import NavData
    with factory() as db:
        foreign=NavData().model_dump(mode='json');foreign['preferences']['title']='OTHER-OWNER-SECRET'
        db.add(nav.NavState(owner_id=other,revision=8,data=foreign,mutation_id='',mutation_hash=''));db.commit()
    assert 'OTHER-OWNER-SECRET' not in client.get('/nav-data').text
    initial=client.get('/nav-data').json()
    payload={**initial,'mutation_id':str(uuid4())};payload['data']['preferences']['title']='原生'
    gate=Barrier(2)
    def save(n):
        body={**payload,'mutation_id':str(uuid4())};gate.wait(timeout=5)
        return client.put('/nav-data',json=body).status_code
    with ThreadPoolExecutor(max_workers=2) as pool: assert sorted(pool.map(save,[1,2]))==[200,409]
    actual=client.get('/nav-data').json();assert actual['revision']==1
    p={**actual,'mutation_id':str(uuid4())};p['data']['preferences']['hideTitle']=True
    saved=client.put('/nav-data',json=p);assert saved.status_code==200
    assert client.put('/nav-data',json=p).json()==saved.json()
    p['data']['preferences']['hideTitle']=False
    assert client.put('/nav-data',json=p).status_code==409
    assert client.put('/nav-data',json={**actual,'mutation_id':str(uuid4()),'owner_id':str(other)}).status_code==422
    with factory() as db: assert db.get(nav.NavState,other).revision==8
    from app.models.user import AuthSession
    with factory() as db:
        for session in db.query(AuthSession).filter(AuthSession.user_id==uid): session.revoked=True
        db.commit()
    assert client.get('/nav-data').status_code==401
    assert client.get('/nav-export').status_code==401


def test_validation_layout_tristate_and_export(lane):
    client,factory,uid,other,nav,app=lane
    original=client.get('/nav-data').json();body={**original,'mutation_id':str(uuid4())}
    body['data']['groups']=[{'id':str(uuid4()),'title':'继承','style':{'layout':None,'hideTitle':None,'hideDescription':False},'items':[]}]
    r=client.put('/nav-data',json=body);assert r.status_code==200,r.text
    style=r.json()['data']['groups'][0]['style'];assert style=={'layout':None,'textColor':None,'hideTitle':None,'hideDescription':False}
    exported=client.get('/nav-export').json();assert exported['data']==r.json()['data']
    assert exported['boundary']['asset_bytes'] is False
    import json
    preview=client.post('/nav-import-preview',json={'source':json.dumps(exported)});assert preview.status_code==200,preview.text
    assert preview.json()['settings']==exported['data']['preferences']
    for field,value in [('backgroundUrl','javascript:alert(1)'),('titleImage','https://user:pass@example.test/a'),('hideTitle','false')]:
        wrong={**r.json(),'mutation_id':str(uuid4())};wrong['data']=json.loads(json.dumps(wrong['data']));wrong['data']['preferences'][field]=value
        assert client.put('/nav-data',json=wrong).status_code==422
    assert client.get('/nav-data').json()==r.json()


def test_import_preview_legacy_complete_mapping_readonly(lane):
    import hashlib,json
    client,factory,uid,other,nav,app=lane
    old={'version':1,'appName':'Stella-Nav-Config','exportTime':'2026-10-23','appVersion':'1','icons':[{'title':'常用','sort':0,'style':{'layout':'info','hideDescription':False,'textColor':'#abc'},'children':[{'title':'示例','sort':0,'icon':{'itemType':2,'src':'/files/private.png'},'url':'https://example.test','lanUrl':'http://192.0.2.1','description':'保留','openMethod':3}]}]}
    old['md5']=hashlib.md5(json.dumps(old,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    initial=client.get('/nav-data').json()
    initial['data']['groups']=[{'id':str(uuid4()),'title':'常用','items':[{'id':str(uuid4()),'title':'旧名称','url':'https://example.test','lanUrl':'http://192.0.2.1'}]}]
    assert client.put('/nav-data',json={**initial,'mutation_id':str(uuid4())}).status_code==200
    before=client.get('/nav-data').json()
    r=client.post('/nav-import-preview',json={'source':json.dumps(old,ensure_ascii=False)})
    assert r.status_code==200,r.text
    preview=r.json()
    assert preview['counts']=={'groups':1,'items':1}
    assert preview['source']==old
    assert preview['groups'][0]['style']['hideDescription'] is False
    assert preview['groups'][0]['children'][0]['sort']==0
    assert preview['asset_mappings'][0]['source']=='/files/private.png'
    assert preview['requires_decisions'] and preview['settings_missing']
    card_mapping=next(m for m in preview['mapping'] if 'group_index' in m)
    assert 'fields' in card_mapping and 'changes' in card_mapping
    assert card_mapping['changes']['title']=={'before':'旧名称','after':'示例'}
    assert card_mapping['fields']['lanUrl']=='http://192.0.2.1'
    assert card_mapping['target_id']==before['data']['groups'][0]['items'][0]['id']
    assert client.get('/nav-data').json()==before
    old['md5']='0'*32
    assert client.post('/nav-import-preview',json={'source':json.dumps(old)}).status_code==422


def test_assets_bounded_owned_reference_protection(lane):
    import base64
    client, factory, uid, other, nav, app = lane
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qXYAAAAASUVORK5CYII=')
    r=client.post('/nav-assets',files={'file':('pixel.png',png,'image/png')})
    assert r.status_code==200,r.text
    asset=r.json()
    assert client.get(asset['url']).content==png
    initial=client.get('/nav-data').json()
    initial['data']['preferences']['backgroundUrl']=asset['url']
    initial['data']['preferences']['background']='custom'
    assert client.put('/nav-data',json={**initial,'mutation_id':str(uuid4())}).status_code==200
    assert client.delete(asset['url']).status_code==409
    with factory() as db:
        row=db.get(nav.NavAsset,UUID(asset['id'])); row.owner_id=other; db.commit()
    assert client.get(asset['url']).status_code==404
    assert client.delete(asset['url']).status_code==404
    assert client.post('/nav-assets',files={'file':('bad.svg',b'<svg onload="alert(1)"/>','image/svg+xml')}).status_code==415
    assert client.post('/nav-assets',files={'file':('large.png',b'x'*(3*1024*1024+1),'image/png')}).status_code==413


def test_native_roundtrip_owner_snapshot(lane):
    client, factory, uid, other, nav, app = lane
    r = client.get('/nav-data')
    assert r.status_code == 200, r.text
    initial = r.json()
    assert initial['revision'] == 0 and initial['data']['groups'] == []
    assert r.headers.get('cache-control')=='private, no-store'
    desired = initial['data']
    desired['groups'] = [{'id':str(uuid4()),'title':'常用','style':{'layout':'info','hideTitle':False},'items':[{'id':str(uuid4()),'title':'文档','url':'https://example.test/docs','lanUrl':'http://192.0.2.1/docs','description':'合成书签','icon':{'itemType':2,'text':'文'}}]}]
    r = client.put('/nav-data',json={'revision':0,'mutation_id':str(uuid4()),'data':desired})
    assert r.status_code == 200, r.text
    assert r.json()['revision'] == 1
    assert client.get('/nav-data').json() == r.json()
    with factory() as db:
        assert db.get(nav.NavState,uid).revision == 1
        assert db.get(nav.NavState,other) is None


def test_complete_preference_fields_persist_and_validate(lane):
    client,*_=lane
    body=client.get('/nav-data').json()
    eid=str(uuid4())
    prefs=body['data']['preferences']
    prefs.update(width=83,widthUnit='%',marginX=17,marginTop=4,marginBottom=11,newWindowOpen=False,
                 engines=[{'id':eid,'title':'第二默认','url':'https://example.test?q={query}'}],defaultEngine=eid)
    result=client.put('/nav-data',json={**body,'mutation_id':str(uuid4())})
    assert result.status_code==200,result.text
    for key in ('width','widthUnit','marginX','marginTop','marginBottom','newWindowOpen','defaultEngine'):
        assert client.get('/nav-data').json()['data']['preferences'][key]==prefs[key]
    prefs['width']=101
    assert client.put('/nav-data',json={**body,'mutation_id':str(uuid4())}).status_code==422
    prefs['width']=80;prefs['defaultEngine']=str(uuid4())
    assert client.put('/nav-data',json={**body,'mutation_id':str(uuid4())}).status_code==422
