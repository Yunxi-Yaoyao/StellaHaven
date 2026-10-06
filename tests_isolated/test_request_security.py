"""Main-origin, cookie, OIDC and SPA boundaries, no production DB or secrets."""
import pytest
from tests_isolated.test_owner_admin_security import auth_env, owner, DAILY
from fastapi.testclient import TestClient
from app.database import get_db


def test_spa_root_containment_and_symlink_escape(auth_env, monkeypatch, tmp_path):
    import main
    root = tmp_path / 'dist'
    root.mkdir()
    (root / 'index.html').write_text('fixture-spa')
    (root / 'asset.js').write_text('fixture-static')
    (tmp_path / 'outside.txt').write_text('outside-marker-never-public')
    (root / 'escape.txt').symlink_to(tmp_path / 'outside.txt')
    (root / 'index-alias').symlink_to(root / 'asset.js')
    monkeypatch.setattr(main, 'FRONTEND_DIR', root)
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','http://testserver')
    c = TestClient(main.app)
    for path in ['/%2e%2e/outside.txt','/%252e%252e/outside.txt','/escape.txt','/%2fetc/passwd','/..%5coutside.txt']:
        response = c.get(path)
        assert response.status_code == 404, (path, response.status_code)
        assert 'outside-marker-never-public' not in response.text
    assert c.get('/notes/deep-link').text == 'fixture-spa'
    assert c.get('/asset.js').text == 'fixture-static'
    assert c.get('/index-alias').text == 'fixture-static'
    assert c.get('/users/').status_code == 404
    c.close()


def test_main_site_exact_origin_and_host_validation(auth_env, monkeypatch):
    import main
    c0, db, _ = auth_env
    owner(c0)
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'https://stella.fixture,http://testserver')
    main.app.dependency_overrides[get_db] = lambda: db
    c = TestClient(main.app)
    payload = {'username':'owner','password':DAILY}
    for origin in ['https://evil.fixture','https://app-demo.xiya.live','https://testserver','null']:
        response = c.post('/auth/login',json=payload,headers={'Origin':origin})
        assert response.status_code == 403, (origin,response.text)
    assert c.post('/auth/login',json=payload,headers={'Origin':'http://testserver'}).status_code == 200
    assert c.post('/auth/login',json=payload,headers={'Referer':'https://evil.fixture/page'}).status_code == 403
    assert c.post('/auth/login',json=payload,headers={'Sec-Fetch-Site':'same-site'}).status_code == 403
    assert c.post('/auth/login',json=payload,headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403
    # Forwarded host/scheme do NOT make an untrusted origin authoritative.
    assert c.post('/auth/login',json=payload,headers={'Origin':'https://evil.fixture','X-Forwarded-Host':'evil.fixture','X-Forwarded-Proto':'https'}).status_code == 403
    assert c.get('/auth/me',headers={'Host':'app-demo.xiya.live'}).status_code in (400,404,421)
    assert c.get('/notes',headers={'Host':'arbitrary.fixture'}).status_code in (400,404,421)
    assert c.post('/auth/login',json=payload,headers={'Host':'stella.fixture','Origin':'https://stella.fixture'}).status_code == 200
    c.close()
    main.app.dependency_overrides.clear()


def test_secure_host_only_cookies_ignore_spoofed_forwarded_ip(auth_env, monkeypatch):
    c, db, app = auth_env
    monkeypatch.delenv('STELLA_COOKIE_SECURE',raising=False)
    response = c.post('/auth/register',json={'username':'owner','password':DAILY},
                      headers={'X-Forwarded-For':'192.0.2.99'})
    assert response.status_code == 201
    cookies = response.headers.get_list('set-cookie')
    assert len(cookies) == 2
    for cookie in cookies:
        assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=lax' in cookie
        assert 'Domain=' not in cookie
    from app.models.user import AuthSession
    assert db.query(AuthSession).one().ip != '192.0.2.99'


def test_oidc_login_next_preserves_all_authorize_parameters(auth_env, monkeypatch):
    c, db, app = auth_env
    from app.routers.oidc import router, oidc_svc
    from urllib.parse import urlencode, urlparse, parse_qs
    app.include_router(router)
    monkeypatch.setattr(oidc_svc,'resolve_issuer',lambda host:'http://testserver')
    monkeypatch.setattr(oidc_svc,'_get_client',lambda id:{'id':id})
    monkeypatch.setattr(oidc_svc,'verify_redirect_uri',lambda *args:True)
    query = urlencode({'client_id':'fixture','redirect_uri':'https://client.fixture/cb?x=1&y=2',
                       'state':'state&x','nonce':'nonce+space','scope':'openid email'})
    url = 'http://testserver/oauth/authorize?' + query
    response = c.get(url,follow_redirects=False)
    assert response.status_code == 307
    assert parse_qs(urlparse(response.headers['location']).query)['next'] == [url]


def test_legacy_agent_query_is_removed_from_asgi_access_scope_before_response_start(monkeypatch):
    import asyncio
    from app.services.request_security import MainSiteSecurityMiddleware
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','http://testserver')
    scope = {'type':'http','method':'POST','path':'/agent/commands/1/result',
             'headers':[(b'host',b'testserver')], 'query_string':b'token=fixture-secret&stdout=fixture-output'}
    observed = []
    async def endpoint(scope,receive,send):
        assert scope['query_string']  # routing still gets legacy input
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'{}'})
    async def send(message):
        if message['type'] == 'http.response.start':
            observed.append(scope['query_string'])
    asyncio.run(MainSiteSecurityMiddleware(endpoint)(scope,None,send))
    assert observed == [b'']


def test_operations_routes_are_registered_once_on_main_before_spa(auth_env,monkeypatch,tmp_path):
    import main
    c0, db, _ = auth_env
    owner(c0)
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','http://testserver')
    monkeypatch.setenv('STELLA_BACKUP_RECEIPT_DIR',str(tmp_path/'receipts'))
    schema = main.app.openapi()['paths']
    assert '/operations/backup-health' in schema
    assert '/operations/change-audit' in schema
    # Modern FastAPI keeps included routers lazy; app.routes is not a flat list.
    import ast, inspect
    tree = ast.parse(inspect.getsource(main))
    registrations = [n for n in ast.walk(tree) if isinstance(n,ast.Call) and
                     isinstance(n.func,ast.Attribute) and n.func.attr == 'include_router' and
                     n.args and isinstance(n.args[0],ast.Name) and n.args[0].id == 'operations_status_router']
    assert len(registrations) == 1
    main.app.dependency_overrides[get_db] = lambda:db
    c = TestClient(main.app)
    c.cookies.update(c0.cookies)
    assert c.get('/operations/backup-health').json()['status'] == 'missing'
    assert c.get('/operations/change-audit').status_code == 403
    c.close()
    main.app.dependency_overrides.clear()
