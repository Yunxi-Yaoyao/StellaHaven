"""Private SQLite process (--noconftest); real auth, synthetic HTTP upstream only."""
import pytest
import httpx
from tests_isolated.test_owner_admin_security import auth_env, configure, DAILY, ADMIN


@pytest.fixture
def drive_env(auth_env, monkeypatch):
    from types import SimpleNamespace
    from app.routers.drive import router
    from app.services import external_services as external
    c, db, app = auth_env
    app.include_router(router)
    configure(c)
    calls = []
    transport = httpx.MockTransport(lambda req: record(req))
    def record(req):
        calls.append((req.method, req.url.path, req.headers.get('authorization')))
        return httpx.Response(200, stream=httpx.ByteStream(b'{"synthetic":true}'), headers={'content-type':'application/json'})
    client_cls = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: client_cls(transport=transport, **kw))
    monkeypatch.setattr(external, 'load', lambda *a: SimpleNamespace(browser_url='https://synthetic.invalid', upstream_url='https://synthetic.invalid', auth_mode='token', token='SYNTHETIC-CACHED-ADMIN'))
    monkeypatch.setattr(external, 'check_resolved', lambda url: None)
    yield c, db, calls


def test_cached_openlist_token_cannot_write_after_real_lock(drive_env):
    c, db, calls = drive_env
    headers = {'Authorization': 'SYNTHETIC-CACHED-ADMIN'}
    path = '/drive/openlist/api/fs/remove'
    assert c.post(path, headers=headers, json={'dir':'/','names':['synthetic.txt']}).status_code == 200
    assert len(calls) == 1
    assert c.post('/auth/admin/lock').status_code == 200
    r = c.post(path, headers=headers, json={'dir':'/','names':['synthetic.txt']})
    assert r.status_code == 403, r.text
    assert r.json()['detail']['code'] == 'admin_elevation_required'
    assert len(calls) == 1


@pytest.mark.parametrize('method,path',[
    ('POST','api/admin/setting/save'), ('POST','api/admin/settings/save'),
    ('PUT','api/fs/put'), ('DELETE','api/admin/storage/delete'),
    ('PATCH','api/fs/rename'), ('POST','api/fs/other'), ('GET','api/fs/other'),
    ('POST','api/auth/login'), ('POST','api/me/update'),
    ('POST','api/fs/list/'), ('POST','api/fs/unknown'),
    ('GET','api/admin/storage/list'), ('HEAD','api/admin/setting/list'),
])
def test_unsafe_and_management_requests_require_elevation(drive_env,method,path):
    c,db,calls=drive_env
    headers={'Authorization':'SYNTHETIC-CACHED-ADMIN'}
    assert c.request(method,'/drive/openlist/'+path,headers=headers,json={}).status_code==200
    assert len(calls)==1
    calls.clear()
    assert c.post('/auth/admin/lock').status_code==200
    r=c.request(method,'/drive/openlist/'+path,headers=headers,json={})
    assert r.status_code==403
    if method!='HEAD': assert r.json()['detail']['code']=='admin_elevation_required'
    assert calls==[]


@pytest.mark.parametrize('method,path',[
    ('GET',''), ('GET','assets/app.js'), ('GET','d/synthetic.txt'), ('HEAD','p/synthetic.txt'),
    *[('POST',p) for p in ['api/fs/list','api/fs/get','api/fs/search','api/fs/dirs','api/fs/archive/meta','api/fs/archive/list','api/public/settings','api/public/init_status','api/public/archive_extensions','api/public/offline_download_tools']],
])
def test_read_resources_and_explicit_post_keep_daily_access(drive_env,method,path):
    c,db,calls=drive_env
    assert c.post('/auth/admin/lock').status_code==200
    r=c.request(method,'/drive/openlist/'+path,json={'path':'/'},headers={'Authorization':'SYNTHETIC-CACHED-ADMIN'})
    assert r.status_code==200
    assert len(calls)==1


def test_options_is_local_preflight_not_management_authorization(drive_env):
    c,db,calls=drive_env
    c.post('/auth/admin/lock')
    assert c.options('/drive/openlist/api/fs/remove').status_code==204
    assert calls==[]
    assert c.post('/drive/openlist/api/fs/remove').status_code==403
    assert calls==[]


def test_expired_elevation_and_other_device_cannot_reuse_openlist_token(drive_env):
    from fastapi.testclient import TestClient
    from app.models.config import AppConfig
    from app.services.admin_security import STATE_KEY
    import json
    c,db,calls=drive_env
    row=db.get(AppConfig,STATE_KEY);state=json.loads(row.value)
    for g in state['grants'].values(): g['expires_at']='2000-01-01T00:00:00+00:00'
    row.value=json.dumps(state);db.commit()
    assert c.put('/drive/openlist/api/fs/put',content=b'synthetic').status_code==403
    assert c.post('/auth/admin/unlock',json={'password':ADMIN}).status_code==200
    with TestClient(c.app) as other:
        assert other.post('/auth/login',json={'username':'owner','password':DAILY}).status_code==200
        assert other.post('/drive/openlist/api/fs/remove',headers={'Authorization':'SYNTHETIC-CACHED-ADMIN'}).status_code==403
    assert calls==[]


def test_noncanonical_admin_path_cannot_be_normalized_upstream(drive_env):
    c,db,calls=drive_env
    c.post('/auth/admin/lock')
    for p in ['api//admin/setting/list','/api/admin/setting/list']:
        r=c.get('/drive/openlist/'+p)
        assert r.status_code==400,r.text
    assert calls==[]
