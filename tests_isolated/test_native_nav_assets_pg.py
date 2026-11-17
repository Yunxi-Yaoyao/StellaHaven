import json
from uuid import UUID,uuid4
from tests_isolated.test_native_nav_pg import lane,pytestmark
from qa.native_nav_synthetic import PNG,transfer


def test_batch_categories_dimensions_and_all_or_none_owner_reference_validation(lane):
    client,factory,uid,other,nav,app=lane
    a=client.post('/nav-assets',files={'file':('a.png',PNG,'image/png')}).json()
    b=client.post('/nav-assets',files={'file':('b.png',PNG,'image/png')}).json()
    assert (a['width'],a['height'],a['size'])==(1,1,len(PNG)) and len(a['sha256'])==64
    assert client.post('/nav-assets-category',json={'ids':[a['id'],b['id']],'category':'icon'}).status_code==200
    assert {x['category'] for x in client.get('/nav-assets').json()}=={'icon'}
    with factory() as db:
        db.get(nav.NavAsset,UUID(b['id'])).owner_id=other;db.commit()
    assert client.post('/nav-assets-category',json={'ids':[a['id'],b['id']],'category':'background'}).status_code==404
    assert client.get('/nav-assets').json()[0]['category']=='icon'
    assert client.post('/nav-assets-batch-delete',json={'ids':[a['id'],b['id']]}).status_code==404
    assert client.get(a['url']).content==PNG
    c=client.post('/nav-assets',files={'file':('c.png',PNG,'image/png')}).json()
    snap=client.get('/nav-data').json();snap['data']['preferences']['titleImage']=a['url']
    assert client.put('/nav-data',json={**snap,'mutation_id':str(uuid4())}).status_code==200
    assert client.post('/nav-assets-batch-delete',json={'ids':[a['id'],c['id']]}).status_code==409
    assert client.get(c['url']).content==PNG
    assert client.post('/nav-assets-batch-delete',json={'ids':[c['id']]}).status_code==200
    assert client.get(c['url']).status_code==404


def test_concurrent_full_import_cas_loser_writes_no_assets(lane):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    client,factory,uid,other,nav,app=lane
    sources=[json.dumps(transfer()),json.dumps(transfer()).replace('/files/synthetic.png','/files/synthetic-two.png')]
    # Each source carries a validated original list signature. Re-sign the changed legacy list.
    import hashlib
    raw=json.loads(sources[1]);unsigned={k:v for k,v in raw['list'].items() if k!='md5'}
    raw['list']['md5']=hashlib.md5(json.dumps(unsigned,ensure_ascii=False,separators=(',',':')).encode()).hexdigest();sources[1]=json.dumps(raw)
    payloads=[]
    for s in sources:
        p=client.post('/nav-package-preview',json={'source':s});assert p.status_code==200,p.text
        payloads.append({'source':s,'digest':p.json()['digest'],'revision':0,'mutation_id':str(uuid4()),'confirmed':True})
    barrier=Barrier(2)
    def run(p):barrier.wait(timeout=5);return client.post('/nav-package-import',json=p).status_code
    with ThreadPoolExecutor(max_workers=2) as pool: assert sorted(pool.map(run,payloads))==[200,409]
    assert len(client.get('/nav-assets').json())==1
    with factory() as db:
        assert db.get(nav.NavState,uid).revision==1
        assert db.query(nav.NavAsset).count()==1


def test_asset_category_migration_existing_row_roundtrip(lane):
    import importlib.util,os
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    client,factory,uid,other,nav,app=lane
    a=client.post('/nav-assets',files={'file':('old.png',PNG,'image/png')}).json()
    spec=importlib.util.spec_from_file_location('nav_category_migration',Path(os.environ['NAV_ROOT'],'alembic/versions/d020261023navcat_asset_category.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    with factory.kw['bind'].begin() as c:
        m.op=Operations(MigrationContext.configure(c));m.downgrade();m.upgrade()
        assert c.scalar(text('select count(*) from nav_assets'))==1
        assert c.scalar(text('select category from nav_assets'))=='uncategorized'
    assert client.get('/nav-assets').json()[0]['sha256']==a['sha256']


def test_native_package_same_owner_reuses_bytes_cross_owner_rebinds(lane):
    from app.models.config import AppConfig
    from app.models.user import User
    from app.services.admin_security import STATE_KEY
    from app.routers.auth import _create_session
    from starlette.requests import Request
    from starlette.responses import Response
    client,factory,uid,other,nav,app=lane
    a=client.post('/nav-assets',files={'file':('owned.png',PNG,'image/png')}).json()
    snap=client.get('/nav-data').json();snap['data']['preferences']['backgroundUrl']=a['url']
    assert client.put('/nav-data',json={**snap,'mutation_id':str(uuid4())}).status_code==200
    package=client.get('/nav-package').json()
    # Browser numeric JSON roundtrip, same owner asset ID remains stable.
    package['data']['preferences']['marginTop']=int(package['data']['preferences']['marginTop'])
    source=json.dumps(package)
    p=client.post('/nav-package-preview',json={'source':source});assert p.status_code==200,p.text
    assert p.json()['data']['preferences']['backgroundUrl']==a['url']
    body={'source':source,'digest':p.json()['digest'],'revision':p.json()['revision'],'confirmed':True,'mutation_id':str(uuid4())}
    assert client.post('/nav-package-import',json=body).status_code==200
    assert len(client.get('/nav-assets').json())==1
    with factory() as db:
        original_revision=db.get(nav.NavState,uid).revision
        db.get(AppConfig,STATE_KEY).value=json.dumps({'owner_id':str(other)});db.commit()
        req=Request({'type':'http','scheme':'https','server':('nav-qa.test',443),'path':'/auth/login','headers':[(b'host',b'nav-qa.test')],'query_string':b'','client':('127.0.0.1',12345)})
        response=Response();_create_session(db,db.get(User,other),req,response,False);db.commit()
        client.cookies.clear()
        for cookie in response.headers.getlist('set-cookie'): client.cookies.update({cookie.split('=',1)[0]:cookie.split('=',1)[1].split(';',1)[0]})
    assert client.get(a['url']).status_code==404
    p=client.post('/nav-package-preview',json={'source':source});assert p.status_code==200,p.text
    body.update(digest=p.json()['digest'],revision=0,mutation_id=str(uuid4()))
    imported=client.post('/nav-package-import',json=body);assert imported.status_code==200,imported.text
    new_url=imported.json()['data']['preferences']['backgroundUrl'];assert new_url!=a['url']
    assert client.get(new_url).content==PNG
    with factory() as db:
        assert db.get(nav.NavAsset,UUID(a['id'])).owner_id==uid
        assert db.get(nav.NavAsset,UUID(new_url.split('/')[-1])).owner_id==other
        assert db.get(nav.NavState,uid).revision==original_revision


def test_full_package_cannot_bypass_ordinary_config_budget(lane):
    from app.schemas.native_nav import NavData
    from app.services.native_nav_package import package
    client,*_=lane
    data=NavData().model_dump(mode='json')
    data['groups']=[{'id':str(uuid4()),'title':str(g),'items':[{'id':str(uuid4()),'title':'bounded-card','url':'https://example.test','description':'x'*1100} for _ in range(500)]} for g in range(4)]
    raw=package(data,[])
    before=client.get('/nav-data').json()
    r=client.post('/nav-package-preview',json={'source':json.dumps(raw)})
    assert r.status_code==413,r.text
    assert client.get('/nav-data').json()==before and client.get('/nav-assets').json()==[]
