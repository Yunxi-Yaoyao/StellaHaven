"""Offline browser-session contracts. No production config or database imports."""
import importlib
import json
import sys
import types
from uuid import uuid4

import pytest


@pytest.fixture
def api(monkeypatch, request):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
    from sqlalchemy.pool import StaticPool
    before = {n: m for n, m in sys.modules.items() if n == 'app' or n.startswith('app.')}
    attrs = {n: dict(m.__dict__) for n, m in before.items()}
    monkeypatch.setenv('STELLA_SECRET_KEY', 'offline-browser-test-key-not-production-123456789')
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'https://one.test,https://two.test')
    monkeypatch.delenv('STELLA_OWNER_ID', raising=False)
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    factory = sessionmaker(engine)
    dbmod = types.ModuleType('app.database')
    dbmod.Base = declarative_base()
    def get_db():
        with factory() as db:
            yield db
    dbmod.get_db = get_db
    monkeypatch.setitem(sys.modules, 'app.database', dbmod)
    try:
        from app.models.user import User, AuthSession
        from app.models.config import AppConfig
        from app.security import hash_password
        from app.services.admin_security import STATE_KEY
        auth = importlib.import_module('app.routers.auth')
        for t in (User.__table__, AuthSession.__table__, AppConfig.__table__):
            t.create(engine)
        uid = uuid4()
        if getattr(request, 'param', True):
            with factory() as db:
                db.add(User(id=uid, username='owner', display_name='Owner', password_hash=hash_password('secret123')))
                db.add(AppConfig(key=STATE_KEY, value=json.dumps({'owner_id': str(uid)})))
                db.commit()
        app = FastAPI()
        app.include_router(auth.router)
        client = TestClient(app, base_url='https://one.test', client=('198.51.100.1', 50000))
        yield types.SimpleNamespace(client=client, factory=factory, AuthSession=AuthSession, User=User, uid=uid, auth=auth)
    finally:
        engine.dispose()
        sys.modules.pop('tests.test_session_policy', None)
        tests_package = sys.modules.get('tests')
        if tests_package and hasattr(tests_package, 'test_session_policy'):
            delattr(tests_package, 'test_session_policy')
        for n in list(sys.modules):
            if (n == 'app' or n.startswith('app.')) and n not in before:
                del sys.modules[n]
        sys.modules.update(before)
        for n, m in before.items():
            for k, v in list(m.__dict__.items()):
                if isinstance(v, types.ModuleType) and v.__name__.startswith('app.') and k not in attrs[n]:
                    delattr(m, k)
            for k, v in attrs[n].items():
                if isinstance(v, types.ModuleType) and v.__name__.startswith('app.'):
                    setattr(m, k, v)


def login(api, bid=None, **extra):
    data = {'username': 'owner', 'password': 'secret123', **extra}
    if bid is not None:
        data['browser_id'] = bid
    return api.client.post('/auth/login', json=data)


@pytest.mark.parametrize('api', [False], indirect=True)
def test_initial_register_persists_browser_group_and_owner(api):
    from app.models.config import AppConfig
    from app.services.admin_security import STATE_KEY
    bid = str(uuid4())
    with api.factory() as db:
        assert db.query(api.User).count() == db.query(api.AuthSession).count() == 0
        assert db.query(AppConfig).count() == 0
    api.client.base_url = 'https://two.test'
    result = api.client.post('/auth/register', json={
        'username': 'owner', 'password': 'secret123', 'browser_id': bid,
    }, headers={'origin': 'https://two.test',
                'user-agent': 'Mozilla Windows Chrome/130 Safari/537 Edg/130'})
    assert result.status_code == 201
    with api.factory() as db:
        session = db.query(api.AuthSession).one()
        assert str(session.browser_id) == bid
        assert session.login_origin == 'https://two.test'
        assert (session.browser_name, session.os_name) == ('Edge', 'Windows')
        assert session.remember and not session.revoked
        user = db.query(api.User).one()
        assert user.is_admin and str(user.id) == result.json()['id']
        assert json.loads(db.get(AppConfig, STATE_KEY).value)['owner_id'] == str(user.id)
    listed = api.client.get('/auth/sessions').json()
    assert len(listed) == 1 and listed[0]['browser_id'] == bid
    assert listed[0]['ip_location'] is None
    assert api.client.get('/auth/me').status_code == 200
    assert api.client.post('/auth/register', json={
        'username': 'other', 'password': 'secret123', 'browser_id': bid,
    }).status_code == 403
    # Cookie loss must still group the initial registration with password login.
    api.client.cookies.clear()
    api.client.headers['origin'] = 'https://two.test'
    assert login(api, bid).status_code == 200
    with api.factory() as db:
        assert db.query(api.User).count() == 1
        assert db.query(api.AuthSession).count() == 2
        assert db.query(api.AuthSession).filter_by(revoked=False).count() == 1
    assert api.client.get('/auth/sessions/history').json()['total'] == 1


@pytest.mark.parametrize('api', [False], indirect=True)
@pytest.mark.parametrize('bid', ['bad', '', 'https://evil.test'])
def test_initial_register_invalid_browser_id_has_no_side_effects(api, bid):
    from app.models.config import AppConfig
    result = api.client.post('/auth/register', json={
        'username': 'owner', 'password': 'secret123', 'browser_id': bid,
    })
    assert result.status_code == 422
    assert not result.headers.get_list('set-cookie')
    with api.factory() as db:
        assert db.query(api.User).count() == 0
        assert db.query(api.AuthSession).count() == 0
        assert db.query(AppConfig).count() == 0


@pytest.mark.parametrize('api', [False], indirect=True)
@pytest.mark.parametrize('payload', [{}, {'browser_id': None}])
def test_initial_register_browser_id_remains_optional(api, payload):
    assert api.client.post('/auth/register', json={
        'username': 'owner', 'password': 'secret123', **payload,
    }).status_code == 201
    with api.factory() as db:
        session = db.query(api.AuthSession).one()
        assert session.browser_id is None
        assert session.login_origin == 'https://one.test'


@pytest.mark.parametrize('api', [False], indirect=True)
def test_register_untrusted_origin_is_not_stored_or_used_for_grouping(api):
    # Router-only fixture deliberately tests the metadata guard, not the
    # production MainSiteSecurityMiddleware (which rejects this Origin).
    bid = str(uuid4())
    assert api.client.post('/auth/register', json={
        'username': 'owner', 'password': 'secret123', 'browser_id': bid,
    }, headers={'origin': 'https://evil.test'}).status_code == 201
    with api.factory() as db:
        session = db.query(api.AuthSession).one()
        assert str(session.browser_id) == bid and session.login_origin is None
    api.client.cookies.clear()
    assert login(api, bid).status_code == 200
    with api.factory() as db:
        assert db.query(api.AuthSession).filter_by(revoked=False).count() == 2


@pytest.mark.parametrize('api', [False], indirect=True)
def test_initial_register_group_replaced_by_valid_otp_not_browser_id_alone(api):
    from app.models.user import EmailCode
    from app.services.email_attempts import issue_code
    bid = str(uuid4())
    assert api.client.post('/auth/register', json={
        'username': 'owner', 'password': 'secret123', 'browser_id': bid,
    }).status_code == 201
    with api.factory() as db:
        EmailCode.__table__.create(db.get_bind())
        owner = db.query(api.User).one()
        owner.email = 'owner@example.test'
        owner.email_verified = True
        db.commit()
        code = issue_code(db, owner.email, 'login')
        assert isinstance(code, str)
    api.client.cookies.clear()
    assert api.client.get('/auth/me', params={'browser_id': bid}).status_code == 401
    data = {'email': 'owner@example.test', 'code': 'not-the-code', 'browser_id': bid}
    assert api.client.post('/auth/login-code', json=data).status_code == 401
    with api.factory() as db:
        assert db.query(api.AuthSession).count() == 1
        assert db.query(api.AuthSession).filter_by(revoked=False).count() == 1
    data['code'] = code
    api.client.headers['user-agent'] = 'Mozilla iPhone like Mac OS X Version/17 Mobile Safari/604'
    assert api.client.post('/auth/login-code', json=data).status_code == 200
    with api.factory() as db:
        rows = db.query(api.AuthSession).all()
        assert len(rows) == 2 and sum(not row.revoked for row in rows) == 1
        assert {str(row.browser_id) for row in rows} == {bid}
        assert {row.login_origin for row in rows} == {'https://one.test'}
        live = next(row for row in rows if not row.revoked)
        assert (live.browser_name, live.os_name) == ('Safari', 'iOS')
    assert api.client.get('/auth/sessions/history').json()['total'] == 1


def test_router_contract_has_canonical_auth_routes_not_api_aliases(api):
    paths = {route.path for route in api.auth.router.routes}
    for suffix in ('register', 'login', 'login-code', 'sessions', 'sessions/history', 'activity'):
        assert '/auth/' + suffix in paths
        assert '/api/auth/' + suffix not in paths
    assert api.client.post('/api/auth/register', json={
        'username': 'owner', 'password': 'secret123',
    }).status_code == 404


def test_proxy_entry_hint_preserves_public_group_and_replaces_local_cookie_loss(api, monkeypatch):
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'https://stella.xiya.live')
    api.client.base_url = 'https://stella.xiya.live'
    api.client.headers.update({'origin': 'https://stella.xiya.live',
        'x-forwarded-host': 'stella.xiya.live', 'referer': 'https://stella.xiya.live/'})
    bid = str(uuid4())
    assert login(api, bid).status_code == 200
    public_cookies = dict(api.client.cookies)
    assert login(api, bid, entry_origin='https://stella.p.xiya.live').status_code == 200
    assert api.client.get('/auth/me').status_code == 200
    rows = api.client.get('/auth/sessions').json()
    assert {r['login_origin'] for r in rows} == {'https://stella.xiya.live', 'https://stella.p.xiya.live'}
    assert login(api, bid, password='wrong', entry_origin='https://stella.p.xiya.live').status_code == 401
    assert len(api.client.get('/auth/sessions').json()) == 2
    api.client.cookies.clear()
    assert login(api, bid, entry_origin='https://stella.p.xiya.live').status_code == 200
    assert len(api.client.get('/auth/sessions').json()) == 2
    with api.factory() as db:
        rows = db.query(api.AuthSession).all()
        assert len(rows) == 3 and sum(r.revoked for r in rows) == 1
        assert next(r for r in rows if r.revoked).login_origin == 'https://stella.p.xiya.live'
    api.client.cookies.clear()
    api.client.cookies.update(public_cookies)
    assert api.client.get('/auth/me').status_code == 200


@pytest.mark.parametrize('hint', [
    'https://evil.test', 'https://stella.p.xiya.live/path',
    'https://stella.p.xiya.live/', 'https://stella.p.xiya.live:444',
    'https://stella.p.xiya.live:443', 'https://user@stella.p.xiya.live',
    'http://stella.p.xiya.live', 'https://other.p.xiya.live',
    'https://stella.p.xiya.live?x=1', 'https://stella.p.xiya.live#x',
])
def test_entry_hint_is_exact_display_alias_not_arbitrary_url(api, monkeypatch, hint):
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'https://stella.xiya.live')
    api.client.base_url = 'https://stella.xiya.live'
    assert login(api, str(uuid4()), entry_origin=hint).status_code == 200
    assert api.client.get('/auth/sessions').json()[0]['login_origin'] == 'https://stella.xiya.live'


def test_hint_cannot_upgrade_untrusted_actual_origin_or_bypass_csrf(api, monkeypatch):
    from app.services.request_security import MainSiteSecurityMiddleware, trusted_origins
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'https://stella.xiya.live')
    api.client.base_url = 'https://stella.xiya.live'
    # Router-only metadata guard fails closed even without the main middleware.
    api.client.headers['origin'] = 'https://evil.test'
    assert login(api, str(uuid4()), entry_origin='https://stella.p.xiya.live').status_code == 200
    with api.factory() as db:
        assert db.query(api.AuthSession).one().login_origin is None
    from fastapi.testclient import TestClient
    with TestClient(MainSiteSecurityMiddleware(api.client.app), base_url='https://stella.xiya.live') as client:
        for actual in ('https://evil.test', 'https://stella.p.xiya.live'):
            result = client.post('/auth/login', headers={'origin': actual}, json={
                'username': 'owner', 'password': 'secret123', 'entry_origin': 'https://stella.xiya.live'})
            assert result.status_code == 403 and not result.headers.get_list('set-cookie')
    assert trusted_origins() == {'https://stella.xiya.live'}
    with api.factory() as db:
        assert db.query(api.AuthSession).count() == 1


@pytest.mark.parametrize('api', [False], indirect=True)
def test_proxy_hint_register_and_valid_otp_persist_same_logical_entry(api, monkeypatch):
    from app.models.user import EmailCode
    from app.services.email_attempts import issue_code
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'https://stella.xiya.live')
    api.client.base_url = 'https://stella.xiya.live'
    api.client.headers['origin'] = 'https://stella.xiya.live'
    bid = str(uuid4())
    assert api.client.post('/auth/register', json={'username': 'owner', 'password': 'secret123',
        'browser_id': bid, 'entry_origin': 'https://stella.p.xiya.live'}).status_code == 201
    assert api.client.get('/auth/sessions').json()[0]['login_origin'] == 'https://stella.p.xiya.live'
    with api.factory() as db:
        EmailCode.__table__.create(db.get_bind())
        owner = db.query(api.User).one()
        owner.email = 'owner@example.test'
        owner.email_verified = True
        db.commit()
        code = issue_code(db, owner.email, 'login')
    api.client.cookies.clear()
    payload = {'email': 'owner@example.test', 'code': 'wrong', 'browser_id': bid,
        'entry_origin': 'https://stella.p.xiya.live'}
    assert api.client.post('/auth/login-code', json=payload).status_code == 401
    with api.factory() as db:
        assert db.query(api.AuthSession).filter_by(revoked=False).count() == 1
    payload['code'] = code
    result = api.client.post('/auth/login-code', json=payload)
    assert result.status_code == 200
    assert all('domain=' not in h.lower() for h in result.headers.get_list('set-cookie'))
    assert api.client.get('/auth/sessions').json()[0]['login_origin'] == 'https://stella.p.xiya.live'
    with api.factory() as db:
        rows = db.query(api.AuthSession).all()
        assert len(rows) == 2 and sum(not row.revoked for row in rows) == 1
        assert {row.login_origin for row in rows} == {'https://stella.p.xiya.live'}


def test_browser_group_replaces_after_cookie_loss_but_keeps_audit(api):
    bid = str(uuid4())
    assert login(api, bid).status_code == 200
    api.client.cookies.clear()
    assert login(api, bid).status_code == 200
    with api.factory() as db:
        rows = db.query(api.AuthSession).all()
        assert len(rows) == 2
        assert sum(not r.revoked for r in rows) == 1
        assert {str(r.browser_id) for r in rows} == {bid}
    assert len(api.client.get('/auth/sessions/history').json()['items']) == 1


@pytest.mark.parametrize('ua,browser,os', [
    ('Mozilla Windows Chrome/130 Safari/537 Edg/130', 'Edge', 'Windows'),
    ('Mozilla iPhone like Mac OS X AppleWebKit Version/17 Mobile Safari/604', 'Safari', 'iOS'),
    ('Mozilla Linux Android Chrome/130 Mobile Safari/537', 'Chrome', 'Android'),
    ('Mozilla Linux Chrome/130 MicroMessenger/8', '未知浏览器', 'Linux'),
])
def test_metadata_display_uses_ua_not_client_label(api, ua, browser, os):
    api.client.headers['user-agent'] = ua
    assert login(api, str(uuid4()), browser_name='Fake', os_name='Fake', device='test-label').status_code == 200
    row = api.client.get('/auth/sessions').json()[0]
    assert row['browser_name'] == browser
    assert row['os_name'] == os
    assert row['login_origin'] == 'https://one.test'
    assert row['device'] == 'test-label'
    assert row['ip_location'] is None


def test_activity_ip_is_latest_not_forwarded_and_poll_does_not_touch(api):
    assert login(api, str(uuid4())).status_code == 200
    with api.factory() as db:
        row = db.query(api.AuthSession).one()
        row.ip = '192.0.2.8'
        db.commit()
    api.client.headers['x-forwarded-for'] = '8.8.8.8'
    assert api.client.get('/auth/sessions').json()[0]['ip'] == '192.0.2.8'
    assert api.client.post('/auth/refresh').status_code == 200
    assert api.client.get('/auth/sessions').json()[0]['ip'] == '192.0.2.8'
    assert api.client.post('/auth/activity').status_code == 200
    assert api.client.get('/auth/sessions').json()[0]['ip'] == '198.51.100.1'
    with api.factory() as db:
        assert db.query(api.AuthSession).count() == 1


def test_id_and_display_input_validation(api):
    for bid in ['bad', 'https://evil.test', '']:
        assert login(api, bid).status_code == 422
    assert login(api, str(uuid4()), browser_name='x' * 81).status_code == 422
    assert login(api, str(uuid4()), password='wrong').status_code == 401
    assert api.client.get('/auth/me', params={'browser_id': str(uuid4())}).status_code == 401


def test_no_id_same_ip_ua_label_never_grouped_and_cross_origin_separate(api):
    bid = str(uuid4())
    for value in (None, None, bid):
        api.client.cookies.clear()
        assert login(api, value, device='same').status_code == 200
    api.client.base_url = 'https://two.test'
    # Even a manually forwarded cookie cannot cause cross-origin replacement.
    assert login(api, bid).status_code == 200
    with api.factory() as db:
        assert db.query(api.AuthSession).filter_by(revoked=False).count() == 4


def test_legacy_metadata_null_without_backfill(api):
    assert login(api).status_code == 200
    with api.factory() as db:
        row = db.query(api.AuthSession).one()
        row.browser_name = row.os_name = row.login_origin = None
        db.commit()
    row = api.client.get('/auth/sessions').json()[0]
    assert row['browser_id'] is None and row['login_origin'] is None
    assert row['browser_name'] is None and row['os_name'] is None


def test_location_owned_stored_ip_and_no_database_transaction_during_network(api, monkeypatch):
    assert login(api).status_code == 200
    with api.factory() as db:
        row = db.query(api.AuthSession).one()
        sid = row.id
        row.ip = '8.8.8.8'
        foreign = api.User(username='foreign', display_name='Foreign', password_hash='x')
        db.add(foreign)
        db.flush()
        other = api.AuthSession(user_id=foreign.id, refresh_hash='foreign', ip='1.1.1.1')
        db.add(other)
        db.commit()
        other_id = other.id
    from app.services import session_location
    calls = []
    observed_db = api.factory()
    api.client.app.dependency_overrides[api.auth.get_db] = lambda: observed_db
    async def lookup(ip):
        assert not observed_db.in_transaction()
        calls.append(ip)
        return 'US · Mountain View'
    monkeypatch.setattr(session_location, 'lookup_location', lookup)
    result = api.client.get(f'/auth/sessions/{sid}/location?ip=1.1.1.1')
    assert result.status_code == 200 and result.json() == {'ip': '8.8.8.8', 'ip_location': 'US · Mountain View'}
    assert calls == ['8.8.8.8']
    assert api.client.get(f'/auth/sessions/{other_id}/location').status_code == 404
    assert calls == ['8.8.8.8']
    observed_db.close()


def test_location_bounds_cache_private_failure_and_no_redirects(api, monkeypatch):
    import asyncio
    import httpx
    from app.services import session_location as geo
    calls = []
    real_client = httpx.AsyncClient
    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'country': 'US', 'city': 'Example'})
    options = []
    def client(**kwargs):
        options.append(kwargs)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(geo.httpx, 'AsyncClient', client)
    async def run():
        assert await geo.lookup_location('192.168.0.1') == '局域网'
        assert await geo.lookup_location('http://evil.test') is None
        assert await geo.lookup_location('8.8.4.4') == 'US · Example'
        assert await geo.lookup_location('8.8.4.4') == 'US · Example'
        assert len(calls) == 1
        assert str(calls[0].url) == 'https://ipinfo.io/8.8.4.4/json'
        assert options[0]['follow_redirects'] is False
        assert options[0]['trust_env'] is False
        async def fail(request):
            raise geo.httpx.TimeoutException('offline')
        monkeypatch.setattr(geo.httpx, 'AsyncClient', lambda **kw: real_client(
            transport=httpx.MockTransport(fail), **kw))
        assert await geo.lookup_location('1.1.1.1') is None
    asyncio.run(run())


def test_location_http_cancels_real_async_stream_and_releases_database(api, monkeypatch):
    import asyncio
    import inspect
    import time
    import httpx
    from app.services import session_location as geo
    assert inspect.iscoroutinefunction(api.auth.session_location)
    assert login(api).status_code == 200
    with api.factory() as db:
        row = db.query(api.AuthSession).one()
        sid = row.id
        row.ip = '8.8.4.4'
        db.commit()
    observed_db = api.factory()
    api.client.app.dependency_overrides[api.auth.get_db] = lambda: observed_db
    class SlowBody(httpx.AsyncByteStream):
        closed = False
        yielded = 0
        async def __aiter__(self):
            for chunk in [b'{', b'"country"', b':', b'"US"', b'}']:
                await asyncio.sleep(0.55)
                self.yielded += 1
                yield chunk
        async def aclose(self):
            self.closed = True
    body = SlowBody()
    calls = []
    async def handler(request):
        assert asyncio.get_running_loop().is_running()
        assert not observed_db.in_transaction()
        calls.append(request)
        return httpx.Response(200, stream=body)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(geo.httpx, 'AsyncClient', lambda **kw: real_client(
        transport=httpx.MockTransport(handler), **kw))
    try:
        started = time.monotonic()
        result = api.client.get(f'/auth/sessions/{sid}/location')
        elapsed = time.monotonic() - started
        print(f'HTTP route async slow-drip elapsed={elapsed:.3f}s chunks={body.yielded}')
        assert result.status_code == 200
        assert result.json() == {'ip': '8.8.4.4', 'ip_location': None}
        assert 1.8 <= elapsed < 2.5 and body.closed and body.yielded == 3
        assert api.client.get(f'/auth/sessions/{sid}/location').json() == result.json()
        assert len(calls) == 1
    finally:
        observed_db.close()


@pytest.mark.parametrize('name', [
    'test_refresh_does_not_count_as_activity_and_cookie_has_remaining_lifetime',
    'test_activity_updates_idle_but_cannot_resurrect',
    'test_logout_revokes_access_without_refresh_cookie',
    'test_same_browser_login_replaces_only_presented_session',
    'test_history_paginated_and_active_excludes_expired',
    'test_unremembered_access_cookie_is_session_scoped',
])
def test_existing_session_policy_unchanged_on_private_fixture(api, name):
    from tests import test_session_policy as legacy
    assert login(api).status_code == 200
    # Reuse original assertion functions without original application's DB/config.
    with api.factory() as db:
        row = db.query(api.AuthSession).one()
        owner = db.get(api.User, api.uid)
        owner.username = 'policy-user'
        db.commit()
        api.client.app.dependency_overrides[api.auth.get_db] = lambda: db
        getattr(legacy, name)((api.client, db, row))


def test_activity_policy_expiry_and_host_only_cookies(api):
    from tests import test_session_policy as legacy
    from datetime import timedelta
    result = login(api)
    assert all('domain=' not in h.lower() for h in result.headers.get_list('set-cookie'))
    with api.factory() as db:
        row = db.query(api.AuthSession).one()
        api.client.app.dependency_overrides[api.auth.get_db] = lambda: db
        legacy.test_expired_session_rejected_by_access_and_refresh((api.client, db, row), True, timedelta(days=30))
