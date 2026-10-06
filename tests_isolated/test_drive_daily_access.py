"""Real ordinary auth; secrets only reach synthetic upstream, never the browser."""
import json
from types import SimpleNamespace
import httpx
import pytest
from tests_isolated.test_owner_admin_security import auth_env, owner, configure
from app.models.config import AppConfig

TOKEN = 'SYNTHETIC-OPENLIST-SERVER-ONLY-TOKEN'

@pytest.fixture
def daily_drive(auth_env, monkeypatch):
    from app.routers.drive import router
    from app.services import external_services as external
    c, db, app = auth_env
    app.include_router(router)
    configure(c)
    c.post('/auth/admin/lock')
    cfg = SimpleNamespace(browser_url='https://owned.invalid/drive/openlist', upstream_url='https://owned.invalid/drive/openlist', auth_mode='token', token=TOKEN)
    monkeypatch.setattr(external, 'load', lambda *a: cfg)
    monkeypatch.setattr(external, 'check_resolved', lambda url: None)
    calls = []
    def upstream(req):
        calls.append({'path':req.url.path, 'auth':req.headers.get('authorization'), 'cookie':req.headers.get('cookie')})
        return httpx.Response(200, stream=httpx.ByteStream(b'{"code":200,"data":{"username":"owner"}}'), headers={'content-type':'application/json'})
    cls = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: cls(transport=httpx.MockTransport(upstream), **kw))
    return c, db, app, cfg, calls

def test_daily_launch_never_reveals_admin_token_or_requests_elevation(daily_drive):
    c, _, _, _, calls = daily_drive
    assert c.get('/auth/security').json()['elevated'] is False
    r = c.get('/drive/login-url')
    assert r.status_code == 200, r.text
    assert r.json() == {'url':'/drive/openlist/'}
    assert TOKEN not in r.text and '?' not in r.json()['url']
    assert r.headers['cache-control'] == 'no-store'
    assert calls == []

@pytest.mark.parametrize('method,path', [('GET','api/me'), ('POST','api/fs/list'), ('POST','api/fs/get')])
def test_daily_read_proxies_credential_only_on_server(daily_drive, method, path):
    c, _, _, _, calls = daily_drive
    r = c.request(method, '/drive/openlist/'+path, json={'path':'/'})
    assert r.status_code == 200
    assert calls[-1]['auth'] == TOKEN
    assert calls[-1]['cookie'] is None
    assert TOKEN not in r.text

@pytest.mark.parametrize('path',['api/admin/setting/list','api/admin/storage/list'])
def test_daily_access_does_not_unlock_openlist_admin(daily_drive, path):
    c, _, _, _, calls = daily_drive
    r = c.get('/drive/openlist/'+path)
    assert r.status_code == 403 and r.json()['detail']['code'] == 'admin_elevation_required'
    assert calls == []

def test_static_assets_do_not_receive_server_credential(daily_drive):
    c, _, _, _, calls = daily_drive
    assert c.get('/drive/openlist/assets/app.js').status_code == 200
    assert calls[-1]['auth'] is None

def test_manual_mode_keeps_original_user_login(daily_drive):
    c, _, _, cfg, calls = daily_drive
    cfg.auth_mode = 'manual'
    r = c.get('/drive/openlist/api/me', headers={'Authorization':'synthetic-user-token'})
    assert r.status_code == 200
    assert calls[-1]['auth'] == 'synthetic-user-token'

def test_stale_browser_admin_token_is_not_authority(daily_drive):
    c, _, _, _, calls = daily_drive
    r = c.get('/drive/openlist/api/me', headers={'Authorization':'stale-local-token'})
    assert r.status_code == 200 and calls[-1]['auth'] == TOKEN
    calls.clear()
    assert c.get('/drive/openlist/api/admin/setting/list', headers={'Authorization':TOKEN}).status_code == 403
    assert calls == []

def test_anonymous_cannot_use_server_credential(daily_drive):
    from fastapi.testclient import TestClient
    c, _, app, _, calls = daily_drive
    with TestClient(app) as anonymous:
        assert anonymous.get('/drive/login-url').status_code == 401
        assert anonymous.get('/drive/openlist/api/me').status_code == 401
    assert calls == []

def test_external_openlist_alias_keeps_same_daily_boundary(daily_drive, monkeypatch):
    c, _, app, _, calls = daily_drive
    from app.routers.integrations import router
    from app.services import integrations
    monkeypatch.setattr(integrations, 'get_module', lambda db, mid: {'id':mid,'enabled':True,'mode':'openlist','adapter':'openlist'})
    app.include_router(router)
    r = c.post('/external-modules/drive-alias/launch')
    assert r.status_code == 200, r.text
    assert r.json()['url'] == '/drive/openlist/'
    assert TOKEN not in r.text
