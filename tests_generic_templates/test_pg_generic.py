"""Owned disposable PG only; explicit receipt + same-connection identity guards."""
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from tests_generic_templates.test_generic_templates import upstream


@pytest.fixture
def pg_factory():
    if os.getenv('STELLA_GENERIC_TEST_PG') != '1':
        pytest.skip('requires operator-owned PG receipt, run STELLA_GENERIC_TEST_PG=1')
    receipt=json.loads(Path('/root/.credentials/stella-generic-templates-20261007/test-pg.json').read_text())
    info=json.loads(subprocess.check_output(['docker','inspect',receipt['container']]))[0]
    assert info['Id']==receipt['container_id']=='46029e5011ac371557cef5fd5c18ea2aaea63364d15774f1baa75338df22403a'
    assert info['State']['Running'] and info['HostConfig']['Tmpfs']
    assert info['NetworkSettings']['Ports']['5432/tcp']==[{'HostIp':'127.0.0.1','HostPort':'38632'}]
    env=dict(line.split('=',1) for line in Path('/root/.credentials/stella-generic-templates-20261007/pg-test.env').read_text().splitlines() if '=' in line)
    assert env['POSTGRES_DB']=='stella_test' and env['POSTGRES_USER']=='stalla'
    url=URL.create('postgresql+psycopg2',username=env['POSTGRES_USER'],password=env['POSTGRES_PASSWORD'],host='127.0.0.1',port=38632,database='stella_test')
    assert (url.host,url.port,url.database,url.username)==('127.0.0.1',38632,'stella_test','stalla') and not url.query
    engine=create_engine(url)
    schema='generic_'+uuid4().hex
    def identity(c):
        assert tuple(c.execute(text('select current_database(),current_user,inet_server_port(),host(inet_server_addr())')).one())==('stella_test','stalla',5432,receipt['ip'])
    with engine.begin() as c:
        identity(c); c.execute(text('CREATE SCHEMA '+schema))
    test_engine=create_engine(url,connect_args={'options':'-csearch_path='+schema})
    from app.models.config import AppConfig
    from app.models.user import User,AuthSession,EmailCode
    with test_engine.begin() as c:
        identity(c)
        for table in (AppConfig.__table__,User.__table__,AuthSession.__table__,EmailCode.__table__):table.create(c)
    try: yield sessionmaker(test_engine,expire_on_commit=False)
    finally:
        test_engine.dispose()
        with engine.begin() as c:
            identity(c); c.execute(text('DROP SCHEMA '+schema+' CASCADE'))
            assert c.execute(text('select 1 from pg_namespace where nspname=:s'),{'s':schema}).first() is None
        engine.dispose()


def test_pg_real_owner_loader_elevation_and_generic_proxy_policy(pg_factory,upstream,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers.auth import router as auth
    from app.routers.website_settings import router,assets_router
    from app.routers.integrations import router as modules
    from app.routers.integrations_host import IntegrationsHostMiddleware
    from app.services.website_templates import catalog
    monkeypatch.delenv('STELLA_OWNER_ID',raising=False)
    app=FastAPI()
    for r in (auth,router,assets_router,modules):app.include_router(r)
    def db():
        with pg_factory() as session:yield session
    app.dependency_overrides[get_db]=db
    root,_,seen=upstream
    with TestClient(app,base_url='https://stella.test') as c:
        assert c.get('/website-templates').status_code==401
        assert c.post('/auth/register',json={'username':'fixture-owner','password':'generic-fixture-daily'}).status_code==201
        assert c.post('/auth/admin/setup',json={'user_password':'generic-fixture-daily','new_password':'generic-fixture-admin'}).status_code==200
        assert c.post('/auth/admin/unlock',json={'password':'generic-fixture-admin'}).status_code==200
        draft=catalog(main_origin='https://stella.test')[1]['draft']|{'address':root+'/','idempotency_key':'pg-loader'}
        draft['custom']['js']='window.privateActive=73'
        response=c.post('/website-settings',json=draft)
        assert response.status_code==201,response.text
        mid=response.json()['id']
        assert 'privateActive=73' in c.get('/website-assets/'+mid+'.js').text
        draft=catalog(main_origin='https://stella.test')[0]['draft']|{'address':root+'/drive/openlist/','idempotency_key':'pg-proxy'}
        proxy=c.post('/website-settings',json=draft).json()
        ticket=c.post('/external-modules/'+proxy['id']+'/launch').json()
        with TestClient(IntegrationsHostMiddleware(app,db_factory=pg_factory,main_origin='https://stella.test'),base_url=proxy['origin']) as frame:
            boot=frame.post('/__stella/bootstrap',data=ticket['fields'],headers={'Origin':'https://stella.test'},follow_redirects=False)
            assert boot.status_code==303,boot.text
            assert c.post('/auth/admin/lock').status_code==200
            assert 'privateActive=73' in c.get('/website-assets/'+mid+'.js').text
            assert c.patch('/website-settings/'+mid,json={'address':root+'/'}).status_code==403
            seen.clear()
            denied=frame.get('/drive/openlist/api/admin/settings')
            assert denied.status_code==403,denied.text
            assert denied.json()['detail']['code'].startswith('admin_')
            assert not seen
            assert c.post('/auth/admin/unlock',json={'password':'generic-fixture-admin'}).status_code==200
            assert frame.get('/drive/openlist/api/admin/settings').status_code==200
        token=c.cookies.get('stella_at')
        assert c.post('/auth/logout').status_code==200
        c.cookies.set('stella_at',token)
        assert 'privateActive=73' not in c.get('/website-assets/'+mid+'.js').text
    with TestClient(app,base_url='https://stella.test') as anon:
        response=anon.get('/website-assets/'+mid+'.js')
        assert 'privateActive' not in response.text and 'Immich logo' not in response.text
        assert 'access-control-allow-origin' not in response.headers


def test_pg_concurrent_migration_one_mapping_and_atomic_failure(pg_factory,monkeypatch):
    from tests_generic_templates.test_migration import seed
    from app.services import integrations as store
    from app.services.website_migration import migrate_legacy,rollback_legacy
    from app.models.config import AppConfig
    seed(pg_factory)
    barrier=threading.Barrier(2)
    def migrate():
        with pg_factory() as db:
            barrier.wait()
            return migrate_legacy(db,approved_ips=['127.0.0.1'],actor_id='00000000-0000-4000-8000-000000000001')
    with ThreadPoolExecutor(2) as pool: results=list(pool.map(lambda _:migrate(),range(2)))
    assert results[0]==results[1]
    with pg_factory() as db:
        assert len(store.state(db)['modules'])==3
        rollback_legacy(db)
        before={r.key:r.value for r in db.query(AppConfig).all()}
    def broken(*args,**kwargs):raise RuntimeError('synthetic transaction fault')
    monkeypatch.setattr(store,'record_change',broken)
    with pg_factory() as db:
        with pytest.raises(RuntimeError,match='synthetic transaction fault'):
            migrate_legacy(db,approved_ips=['127.0.0.1'],actor_id='00000000-0000-4000-8000-000000000001')
        assert {r.key:r.value for r in db.query(AppConfig).all()}==before
