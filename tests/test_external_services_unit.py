import importlib
import pytest

def test_connection_rejects_unsafe_urls():
    from app.services import external_services as svc
    for url in ["file:///etc/passwd", "http://user:pass@localhost", "http://169.254.169.254/latest", "http://localhost:8000/admin", "https://example.com/#token"]:
        with pytest.raises(ValueError):
            svc.Connection(browser_url=url, upstream_url=url)
    assert svc.Connection(browser_url="https://files.example.com/drive", upstream_url="http://127.0.0.1:5244/drive/openlist").upstream_url.endswith("openlist")


def test_proxy_filters_stella_credentials():
    from app.routers.drive import proxy_headers
    result = proxy_headers({'cookie': 'stella_at=SECRET; stella_rt=REFRESH; openlist_session=ok', 'authorization': 'Bearer STELLA', 'range': 'bytes=0-5'})
    assert 'SECRET' not in str(result) and 'REFRESH' not in str(result) and 'STELLA' not in str(result)
    assert result['cookie'] == 'openlist_session=ok'
    assert result['range'] == 'bytes=0-5'


def test_admin_secret_not_shared(monkeypatch):
    from app.services import drive, external_services as svc
    cfg = svc.Connection(browser_url='https://files.example.com', token='private', auth_mode='token')
    monkeypatch.setattr(svc, 'load', lambda *args: cfg)
    assert 'private' not in str(drive.get_status(None))
    assert 'private' not in str(drive.get_login_url(None, False))
    assert 'private' in drive.get_login_url(None, True)['url']
    assert 'token' not in svc.masked(cfg) and svc.masked(cfg)['has_token']


def test_routes_authorization_and_removed_lifecycle(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.routers import drive, gallery
    from app.routers.auth import current_user
    from app.database import get_db
    from app.services import external_services as svc
    app = FastAPI()
    app.include_router(drive.router)
    app.include_router(gallery.router)
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(is_admin=False)
    cfg = svc.Connection(browser_url='https://example.com')
    monkeypatch.setattr(svc, 'load', lambda *args: cfg)
    with TestClient(app) as client:
        for kind in ('drive', 'gallery'):
            assert client.get('/'+kind+'/status').status_code == 200
            assert client.get('/'+kind+'/connection').status_code == 403
            assert client.put('/'+kind+'/connection', json=cfg.model_dump()).status_code == 403
            assert client.post('/'+kind+'/connection/test', json=cfg.model_dump()).status_code == 403
            for action in ('start', 'stop', 'restart', 'install', 'docker/install', 'uninstall', 'update'):
                assert client.post('/'+kind+'/'+action).status_code == 404
        app.dependency_overrides[current_user] = lambda: SimpleNamespace(is_admin=True)
        assert client.get('/drive/connection').json()['has_token'] is False


def test_probe_detects_application_failure(monkeypatch):
    import asyncio
    import httpx
    from app.services import external_services as svc
    original = httpx.AsyncClient
    monkeypatch.setattr(svc, 'check_resolved', lambda url: None)
    def factory(**kwargs):
        return original(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'code': 500})), **kwargs)
    monkeypatch.setattr(httpx, 'AsyncClient', factory)
    cfg = svc.Connection(browser_url='https://example.com')
    assert asyncio.run(svc.probe('drive', cfg))['ok'] is False


def test_token_preservation_and_clear(monkeypatch):
    from app.services import external_services as svc
    old = svc.Connection(browser_url='https://example.com', token='secret')
    monkeypatch.setattr(svc, 'load', lambda *args: old)
    incoming = svc.Connection(browser_url='https://example.com')
    assert svc.merge(None, 'drive', incoming).token == 'secret'
    incoming.clear_token = True
    assert not svc.merge(None, 'drive', incoming).token


@pytest.mark.parametrize('method', ['GET', 'HEAD'])
def test_proxy_preserves_range_and_bytes(monkeypatch, method):
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.routers import drive
    from app.routers.auth import current_user
    from app.database import get_db
    from app.services import external_services as svc
    cfg = svc.Connection(browser_url='https://files.example.com/drive/openlist', upstream_url='http://127.0.0.1:5244/drive/openlist', use_proxy=True)
    monkeypatch.setattr(svc, 'load', lambda *args: cfg)
    monkeypatch.setattr(svc, 'check_resolved', lambda url: None)
    original = httpx.AsyncClient
    class Raw(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'abcdef'
    def upstream(request):
        assert request.url.path == '/drive/openlist/file.bin'
        assert request.headers['range'] == 'bytes=0-5'
        assert 'stella_at' not in request.headers.get('cookie', '')
        return httpx.Response(206, headers={'Content-Range':'bytes 0-5/20', 'Content-Length':'6'}, stream=Raw())
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(upstream), **kw))
    app = FastAPI(); app.include_router(drive.router)
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(is_admin=False)
    with TestClient(app) as client:
        r = client.request(method, '/drive/openlist/file.bin', headers={'Range':'bytes=0-5', 'Cookie':'stella_at=SECRET'})
        assert r.status_code == 206 and r.headers['content-range'] == 'bytes 0-5/20'
        assert r.content == (b'abcdef' if method == 'GET' else b'')


def test_gallery_manual_login_does_not_force_configured_oidc(monkeypatch):
    from app.services import gallery, external_services as svc
    cfg = svc.Connection(browser_url='https://photos.example', alternate_browser_url='https://photos.yunxi.life', auth_mode='manual')
    monkeypatch.setattr(svc, 'load', lambda *args: cfg)
    assert gallery.browser_url(None) == 'https://photos.example/auth/login?autoLaunch=0'
    assert gallery.browser_url(None, 'stella.yunxi.life') == 'https://photos.yunxi.life/auth/login?autoLaunch=0'
    cfg.auth_mode = 'oidc'
    assert gallery.browser_url(None) == 'https://photos.example/'


def test_drive_single_service_url_and_explicit_admin_token_reveal(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.routers import drive
    from app.routers.auth import current_user
    from app.database import get_db
    from app.services import external_services as svc
    app=FastAPI();app.include_router(drive.router)
    app.dependency_overrides[get_db]=lambda:None
    app.dependency_overrides[current_user]=lambda:SimpleNamespace(is_admin=True)
    cfg=svc.Connection(browser_url='https://legacy.invalid/drive/openlist',upstream_url='http://10.66.0.2:12544/drive/openlist',token='TEST_SECRET',auth_mode='token')
    monkeypatch.setattr(svc,'load',lambda *args:cfg)
    with TestClient(app) as client:
        data=client.get('/drive/connection').json()
        assert data=={'service_url':cfg.upstream_url,'auth_mode':'token','has_token':True}
        assert 'TEST_SECRET' not in str(data)
        response=client.post('/drive/connection/token')
        assert response.json()=={'token':'TEST_SECRET'}
        assert response.headers['cache-control']=='no-store'
        app.dependency_overrides[current_user]=lambda:SimpleNamespace(is_admin=False)
        assert client.post('/drive/connection/token').status_code==403
    form=svc.DriveConnection(service_url=cfg.upstream_url,auth_mode='token',token='TEST_SECRET')
    assert form.as_connection().upstream_url==cfg.upstream_url
    assert form.as_connection().use_proxy is True
