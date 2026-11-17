"""Offline OIDC provider regressions: no application settings, live DB or keys."""
import base64
import copy
import hashlib
import importlib
import json
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

import pytest


@pytest.fixture
def oidc(tmp_path, monkeypatch):
    from app.services import oidc as svc
    monkeypatch.delenv('STELLA_SHARED_STATE', raising=False)
    monkeypatch.delenv('STELLA_OIDC_PRIVATE_KEY_FILE', raising=False)
    monkeypatch.setattr(svc, 'OIDC_DIR', tmp_path / 'oidc')
    monkeypatch.setattr(svc, 'CLIENT_FILE', tmp_path / 'oidc' / 'clients.json')
    monkeypatch.setattr(svc, 'PRIVATE_KEY_PATH', tmp_path / 'oidc' / 'private.json')
    monkeypatch.setattr(svc, 'DEFAULT_CLIENT', {**svc.DEFAULT_CLIENT, 'client_secret': None})
    return svc


def test_unknown_client_cannot_generate_secret_or_receive_default_redirects(oidc):
    with pytest.raises(ValueError, match='unknown client'):
        oidc.get_client_secret('unregistered')
    assert oidc._get_client('unregistered') is None
    assert not oidc.CLIENT_FILE.exists()


@pytest.fixture(params=['legacy', 'postgres'])
def storage(oidc, monkeypatch, request):
    if request.param == 'postgres':
        from app.services import ha_state
        states, lock = {}, RLock()
        @contextmanager
        def locked_states(defaults):
            with lock:
                selected = {key: copy.deepcopy(states.get(key, default))
                            for key, default in defaults.items()}
                yield selected
                states.update(copy.deepcopy(selected))
        @contextmanager
        def locked_state(key, default):
            with locked_states({key: default}) as selected:
                yield selected[key]
        monkeypatch.setattr(ha_state, 'locked_states', locked_states)
        monkeypatch.setattr(ha_state, 'locked_state', locked_state)
        monkeypatch.setenv('STELLA_SHARED_STATE', 'postgres')
    return oidc


def test_explicit_management_preserves_legacy_data_and_never_echoes_secret(storage):
    oidc = storage
    created = oidc.create_client('photos', name='Photos', redirect_uris=['https://photos.test/cb'])
    secret = created['client_secret']
    assert len(secret) >= 32
    assert created['client_id'] == 'photos' and created['has_secret']
    assert 'client_secret' not in oidc.list_clients()[0]
    with oidc._locked_clients() as clients:
        clients['photos']['future_metadata'] = {'preserved': True}
    updated = oidc.update_client('photos', {'name': 'New Photos', 'enabled': False})
    assert not updated['enabled'] and 'client_secret' not in updated
    assert oidc.get_client_secret('photos') == secret
    assert oidc._get_client('photos')['future_metadata'] == {'preserved': True}
    rotated = oidc.rotate_client_secret('photos')
    assert rotated['client_secret'] != secret
    assert oidc.get_client_secret('photos') == rotated['client_secret']
    with pytest.raises(ValueError, match='exists'):
        oidc.create_client('photos', name='Duplicate', redirect_uris=['https://photos.test/cb'])
    with pytest.raises(KeyError):
        oidc.update_client('Photos', {'name': 'Wrong case'})
    oidc.delete_client('photos')
    assert oidc._get_client('photos') is None
    if oidc.ha_state.enabled():
        assert not oidc.CLIENT_FILE.exists()


@pytest.mark.parametrize('client_id,uri', [
    ('../oops', 'https://rp.test/cb'), (' rp', 'https://rp.test/cb'),
    ('rp', 'http://localhost/cb'), ('rp', '/relative'),
    ('rp', 'https://rp.test/*'), ('rp', 'https://rp.test/cb?next=oops'),
    ('rp', 'https://rp.test/cb#fragment'), ('rp', 'https://user:pw@rp.test/cb'),
    ('rp', 'https://rp.test:bad/cb'), ('rp', 'https://rp.test\\evil/cb'),
    ('rp', 'https://rp.test/%0acb'), ('rp', 'https://rp.test/%2acb'),
])
def test_registration_rejects_invalid_ids_and_redirects(oidc, client_id, uri):
    with pytest.raises(ValueError):
        oidc.create_client(client_id, name='RP', redirect_uris=[uri])
    assert oidc.list_clients() == []


def test_updates_preserve_only_exact_existing_legacy_http_redirects(oidc):
    old_uri = 'http://192.168.1.5:5244/api/auth/sso_callback'
    with oidc._locked_clients() as clients:
        clients['openlist'] = {'client_secret': 'keep', 'redirect_uris': [old_uri]}
    oidc.update_client('openlist', {'redirect_uris': [old_uri, 'https://files.test/cb']})
    assert oidc.get_client_secret('openlist') == 'keep'
    with pytest.raises(ValueError):
        oidc.update_client('openlist', {'redirect_uris': [old_uri + '/changed']})
    with pytest.raises(ValueError):
        oidc.update_client('openlist', {'client_secret': 'override'})
    with pytest.raises(ValueError):
        oidc.update_client('openlist', {'scopes': ['openid', 'admin']})


def test_pkce_s256_wrong_verifier_client_redirect_expiry_and_replay_fail_closed(storage, monkeypatch):
    oidc = storage
    monkeypatch.setattr(oidc, '_sign_id_token', lambda *a, **kw: 'signed')
    secret = oidc.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])['client_secret']
    verifier = 'a' * 43
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    code = oidc.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Actual Owner', 'owner@test', 'nonce',
                                          code_challenge=challenge, code_challenge_method='S256', scope='openid email')
    assert oidc.exchange_code(code, 'unknown', secret, 'https://rp.test/cb', code_verifier=verifier) is None
    assert oidc.exchange_code(code, 'rp', secret, 'https://wrong.test/cb', code_verifier=verifier) is None
    assert oidc.exchange_code(code, 'rp', 'wrong', 'https://rp.test/cb', code_verifier=verifier) is None
    assert oidc.exchange_code(code, 'rp', secret, 'https://rp.test/cb', code_verifier='b' * 43) is None
    assert oidc.exchange_code(code, 'rp', secret, 'https://rp.test/cb') is None
    result = oidc.exchange_code(code, 'rp', secret, 'https://rp.test/cb', code_verifier=verifier)
    assert result['scope'] == 'openid email'
    assert oidc.userinfo(result['access_token'])['sub'] == 'owner'
    assert oidc.exchange_code(code, 'rp', secret, 'https://rp.test/cb', code_verifier=verifier) is None
    expired = oidc.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Owner', '', None)
    with oidc._shared_state() as state:
        state['codes'][expired]['expires'] = 0
    assert oidc.exchange_code(expired, 'rp', secret, 'https://rp.test/cb') is None


@pytest.mark.parametrize('challenge,method,scope', [
    ('x' * 43, 'plain', 'openid'), ('short', 'S256', 'openid'),
    ('', 'S256', 'openid'), ('x' * 43, '', 'openid'),
    ('', '', 'openid admin'), ('', '', 'profile'),
])
def test_authorization_rejects_invalid_pkce_and_scopes(oidc, challenge, method, scope):
    oidc.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])
    with pytest.raises(ValueError):
        oidc.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Owner', '', None,
                                       code_challenge=challenge, code_challenge_method=method, scope=scope)


@pytest.mark.parametrize('change', ['rotate', 'disable', 'delete', 'redirects', 'scopes'])
def test_client_security_changes_revoke_codes_and_access_tokens(storage, monkeypatch, change):
    oidc = storage
    monkeypatch.setattr(oidc, '_sign_id_token', lambda *a, **kw: 'signed')
    secret = oidc.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])['client_secret']
    def issue():
        return oidc.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Owner', '', None)
    issued, pending = issue(), issue()
    token = oidc.exchange_code(issued, 'rp', secret, 'https://rp.test/cb')['access_token']
    assert oidc.userinfo(token)
    if change == 'rotate':
        secret = oidc.rotate_client_secret('rp')['client_secret']
    elif change == 'delete':
        oidc.delete_client('rp')
    else:
        oidc.update_client('rp', {'disable': {'enabled': False},
                                 'redirects': {'redirect_uris': ['https://other.test/cb']},
                                 'scopes': {'scopes': ['openid']}}[change])
    assert oidc.userinfo(token) is None
    assert oidc.exchange_code(pending, 'rp', secret, 'https://rp.test/cb') is None
    if change == 'disable':
        with pytest.raises(ValueError, match='invalid_client'):
            issue()


@pytest.fixture
def api(oidc, monkeypatch, tmp_path):
    """Real owner/session dependencies on disposable SQLite only."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
    from sqlalchemy.pool import StaticPool
    before = {n: m for n, m in sys.modules.items() if n == 'app' or n.startswith('app.')}
    attrs = {n: dict(m.__dict__) for n, m in before.items()}
    monkeypatch.setenv('STELLA_SECRET_KEY', 'offline-oidc-test-signing-key-never-production-12345')
    monkeypatch.delenv('STELLA_OWNER_ID', raising=False)
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    dbmod = types.ModuleType('app.database')
    dbmod.Base = declarative_base()
    factory = sessionmaker(engine, expire_on_commit=False)
    def get_db():
        with factory() as db:
            yield db
    dbmod.get_db = get_db
    monkeypatch.setitem(sys.modules, 'app.database', dbmod)
    try:
        from app.models.user import User, AuthSession
        from app.models.config import AppConfig
        from app.routers import auth
        from app import security
        from app.services import admin_security
        for table in (User.__table__, AuthSession.__table__, AppConfig.__table__):
            table.create(engine)
        now = datetime.now(timezone.utc)
        owner_id, sid, foreign_id, foreign_sid = uuid4(), uuid4(), uuid4(), uuid4()
        rt, rt_hash = security.make_refresh_token()
        with factory() as db:
            db.add_all([User(id=owner_id, username='actual-owner', display_name='Actual Owner', email='owner@test', is_admin=False),
                        User(id=foreign_id, username='foreign', display_name='Foreign', is_admin=True),
                        AuthSession(id=sid, user_id=owner_id, refresh_hash=rt_hash, remember=True, created_at=now, last_seen=now),
                        AuthSession(id=foreign_sid, user_id=foreign_id, refresh_hash='unused', remember=True, created_at=now, last_seen=now),
                        AppConfig(key=admin_security.STATE_KEY, value=json.dumps({'owner_id': str(owner_id), 'password_hash': 'configured', 'enabled': True, 'version': 1, 'grants': {}}))])
            db.commit()
        app = FastAPI()
        public = importlib.import_module('app.routers.oidc')
        app.include_router(public.router)

        yield types.SimpleNamespace(app=app, client=TestClient(app, base_url='https://stella.xiya.live'),
                                    owner_cookie=security.make_access_token(str(owner_id), str(sid)),
                                    foreign_cookie=security.make_access_token(str(foreign_id), str(foreign_sid)),
                                    rt=rt, owner_id=owner_id, auth=auth, factory=factory)
    finally:
        engine.dispose()
        for name in list(sys.modules):
            if (name == 'app' or name.startswith('app.')) and name not in before:
                del sys.modules[name]
        sys.modules.update(before)
        for name, module in before.items():
            original = attrs[name]
            for key, value in list(module.__dict__.items()):
                if isinstance(value, types.ModuleType) and value.__name__.startswith('app.') and key not in original:
                    delattr(module, key)
            for key, value in original.items():
                if isinstance(value, types.ModuleType) and value.__name__.startswith('app.'):
                    setattr(module, key, value)


def test_management_uses_real_owner_and_elevation_and_one_time_secret(api):
    management = importlib.import_module('app.routers.auth_provider')
    api.app.include_router(management.router)
    c = api.client
    assert c.get('/auth/provider/config').status_code == 401
    c.cookies.set('stella_at', api.foreign_cookie)
    assert c.get('/auth/provider/config').status_code == 403
    c.cookies.set('stella_at', api.owner_cookie)
    denial = c.get('/auth/provider/config')
    assert denial.status_code == 200  # the normal authenticated owner is sufficient
    config = c.get('/auth/provider/config')
    assert config.status_code == 200
    assert config.json()['issuer'] == 'https://stella.xiya.live'
    assert config.json()['discovery_url'].endswith('/.well-known/openid-configuration')
    assert config.json()['capabilities']['code_challenge_methods_supported'] == ['S256']
    payload = {'client_id': 'photos', 'name': 'Photos', 'redirect_uris': ['https://photos.test/cb'], 'generate_secret': True}
    created = c.post('/auth/provider/clients', json=payload)
    assert created.status_code == 201, created.text
    secret = created.json()['client_secret']
    assert created.headers['cache-control'] == 'no-store'
    listing = c.get('/auth/provider/clients')
    assert listing.status_code == 200 and listing.json()[0]['has_secret']
    assert secret not in listing.text and secret not in c.get('/auth/provider/config').text
    assert c.post('/auth/provider/clients', json=payload).status_code == 409
    assert c.patch('/auth/provider/clients/Photos', json={'name': 'Wrong'}).status_code == 404
    updated = c.patch('/auth/provider/clients/photos', json={'name': 'Renamed'})
    assert updated.status_code == 200 and 'client_secret' not in updated.json()
    rotated = c.post('/auth/provider/clients/photos/rotate-secret')
    assert rotated.status_code == 200 and rotated.json()['client_secret'] != secret
    assert c.delete('/auth/provider/clients/photos').status_code == 200
    assert c.get('/auth/provider/clients/photos').status_code == 404
    invalid = c.post('/auth/provider/clients', json={**payload, 'client_secret': 'never-echo-this'})
    assert invalid.status_code == 422 and 'never-echo-this' not in invalid.text
    assert all('input' not in error and 'ctx' not in error for error in invalid.json()['detail'])


def test_public_discovery_basic_and_post_exchange_with_pkce(api, oidc):
    c = api.client
    discovery = c.get('/.well-known/openid-configuration')
    assert discovery.status_code == 200
    assert discovery.json()['token_endpoint_auth_methods_supported'] == ['client_secret_basic', 'client_secret_post']
    assert discovery.json()['code_challenge_methods_supported'] == ['S256']
    assert discovery.json()['scopes_supported'] == ['openid', 'profile', 'email']
    secret = oidc.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])['client_secret']
    c.cookies.set('stella_at', api.owner_cookie)
    verifier = 'v' * 43
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    for method in ('basic', 'post'):
        authorize = c.get('/oauth/authorize', params={'response_type': 'code', 'client_id': 'rp', 'redirect_uri': 'https://rp.test/cb',
                          'scope': 'openid profile email', 'code_challenge': challenge, 'code_challenge_method': 'S256',
                          'state': 'exact-state', 'nonce': 'exact-nonce'}, follow_redirects=False)
        assert authorize.status_code in (302, 307), authorize.text
        from urllib.parse import parse_qs, urlsplit
        params = parse_qs(urlsplit(authorize.headers['location']).query)
        assert params['state'] == ['exact-state']
        payload = {'grant_type': 'authorization_code', 'code': params['code'][0], 'redirect_uri': 'https://rp.test/cb', 'code_verifier': verifier}
        if method == 'basic':
            headers = {'Authorization': 'Basic ' + base64.b64encode(f'rp:{secret}'.encode()).decode()}
        else:
            headers = {}
            payload.update(client_id='rp', client_secret=secret)
        result = c.post('/oauth/token', data=payload, headers=headers)
        assert result.status_code == 200, result.text
        assert result.headers['cache-control'] == 'no-store'
        from authlib.jose import jwt
        claims = jwt.decode(result.json()['id_token'], oidc._get_key())
        assert claims['sub'] == str(api.owner_id) and claims['email'] == 'owner@test'
        assert claims['nonce'] == 'exact-nonce' and claims['iss'] == discovery.json()['issuer']
        info = c.get('/oauth/userinfo', headers={'Authorization': 'Bearer ' + result.json()['access_token']})
        assert info.json()['preferred_username'] == 'actual-owner'
        assert c.post('/oauth/token', data=payload, headers=headers).status_code == 400


def test_authorize_validates_before_login_and_preserves_refresh_cookies(api, oidc):
    from urllib.parse import parse_qs, urlsplit
    c = api.client
    oidc.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])
    query = {'response_type': 'code', 'client_id': 'rp', 'redirect_uri': 'https://rp.test/cb',
             'scope': 'openid admin', 'state': 'exact-error-state'}
    bad = c.get('/oauth/authorize', params=query, follow_redirects=False)
    assert bad.status_code == 307
    assert bad.headers['location'].startswith('https://rp.test/cb?')
    assert parse_qs(urlsplit(bad.headers['location']).query) == {'error': ['invalid_scope'], 'state': ['exact-error-state']}
    query.update(scope='openid', code_challenge='x' * 43, code_challenge_method='plain')
    bad_pkce = c.get('/oauth/authorize', params=query, follow_redirects=False)
    assert bad_pkce.status_code == 307
    assert bad_pkce.headers['location'].startswith('https://rp.test/cb?')
    assert parse_qs(urlsplit(bad_pkce.headers['location']).query) == {'error': ['invalid_request'], 'state': ['exact-error-state']}
    query.pop('code_challenge'); query.pop('code_challenge_method')
    login = c.get('/oauth/authorize', params=query, follow_redirects=False)
    assert '/login?' in login.headers['location']
    c.cookies.set('stella_rt', api.rt)
    refreshed = c.get('/oauth/authorize', params=query, follow_redirects=False)
    assert refreshed.status_code in (302, 307) and refreshed.headers['location'].startswith('https://rp.test/cb?code=')
    cookies = refreshed.headers.get_list('set-cookie')
    assert any(cookie.startswith('stella_at=') for cookie in cookies)
    assert any(cookie.startswith('stella_rt=') for cookie in cookies)
    assert c.get('/auth/provider/config').status_code == 404  # management not mounted in this fixture


def test_token_rejects_ambiguous_auth_without_consuming_code(api, oidc):
    secret = oidc.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])['client_secret']
    code = oidc.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Owner', '', None)
    headers = {'Authorization': 'Basic ' + base64.b64encode(f'rp:{secret}'.encode()).decode()}
    payload = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': 'https://rp.test/cb',
               'client_id': 'rp', 'client_secret': secret}
    denied = api.client.post('/oauth/token', data=payload, headers=headers)
    assert denied.status_code == 401 and denied.json()['error'] == 'invalid_client'
    assert api.client.post('/oauth/token', data=payload).status_code == 200


def test_unknown_exchange_has_no_registration_side_effect(oidc):
    assert oidc.exchange_code('unknown', 'unknown', 'wrong', 'https://rp.test/cb') is None
    assert not oidc.CLIENT_FILE.exists()


@pytest.mark.parametrize('scope,expected,excluded', [
    ('openid', set(), {'name', 'preferred_username', 'email'}),
    ('openid email', {'email'}, {'name', 'preferred_username'}),
    ('openid profile', {'name', 'preferred_username'}, {'email'}),
])
def test_identity_claims_follow_granted_scopes(oidc, scope, expected, excluded):
    secret = oidc.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])['client_secret']
    code = oidc.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Actual Owner', 'owner@test', None, scope=scope)
    result = oidc.exchange_code(code, 'rp', secret, 'https://rp.test/cb')
    from authlib.jose import jwt
    claims = jwt.decode(result['id_token'], oidc._get_key())
    info = oidc.userinfo(result['access_token'])
    for data in (claims, info):
        assert expected <= data.keys() and excluded.isdisjoint(data.keys())


def test_empty_explicit_pkce_is_not_silently_ignored(oidc):
    oidc.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])
    with pytest.raises(ValueError, match='invalid_request'):
        oidc.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Owner', '', None,
                                       code_challenge='', code_challenge_method='')


@pytest.mark.parametrize('uri', ['https://!/cb', 'https://.test/cb', 'https://bad..test/cb', 'https://bad_host.test/cb'])
def test_redirect_authority_must_be_real_hostname(oidc, uri):
    with pytest.raises(ValueError, match='invalid redirect URI'):
        oidc.create_client('rp', name='RP', redirect_uris=[uri])


def test_only_existing_local_http_callbacks_can_be_retained(oidc):
    with oidc._locked_clients() as clients:
        clients['old'] = {'client_secret': 'preserve', 'redirect_uris': ['http://remote.example/cb']}
    with pytest.raises(ValueError, match='HTTPS'):
        oidc.update_client('old', {'redirect_uris': ['http://remote.example/cb']})


def test_serialized_concurrent_management_preserves_clients_and_secret(storage):
    from concurrent.futures import ThreadPoolExecutor
    oidc = storage
    def create(_):
        try:
            return oidc.create_client('race', name='Race', redirect_uris=['https://rp.test/cb'])
        except ValueError as exc:
            assert str(exc) == 'client already exists'
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(create, range(16)))
    successes = [item for item in results if item]
    assert len(successes) == 1
    secret = successes[0]['client_secret']
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: oidc.create_client(f'rp-{i}', name='RP', redirect_uris=['https://rp.test/cb']), range(16)))
    assert len(oidc.list_clients()) == 17 and oidc.get_client_secret('race') == secret


@pytest.mark.parametrize('method,path,payload', [
    ('get', '/config', None), ('get', '/clients', None), ('get', '/clients/rp', None),
    ('post', '/clients', {'client_id': 'rp', 'name': 'RP', 'redirect_uris': ['https://rp.test/cb']}),
    ('patch', '/clients/rp', {'enabled': False}), ('delete', '/clients/rp', None),
    ('post', '/clients/rp/rotate-secret', None),
])
def test_every_management_route_requires_elevated_owner(api, method, path, payload):
    api.app.include_router(importlib.import_module('app.routers.auth_provider').router)
    owner_status=201 if method=='post' and path=='/clients' else 200 if method=='get' and path in {'/config','/clients'} else 404
    for cookie, status in [(None, 401), (api.foreign_cookie, 403), (api.owner_cookie, owner_status)]:
        api.client.cookies.clear()
        if cookie:
            api.client.cookies.set('stella_at', cookie)
        result = api.client.request(method, '/auth/provider' + path, json=payload)
        assert result.status_code == status, result.text


@pytest.mark.parametrize('authorization', ['Basic !!!', 'Basic ' + base64.b64encode(b'no-colon').decode(), 'Bearer ignored'])
def test_malformed_client_authentication_never_creates_client(api, oidc, authorization):
    result = api.client.post('/oauth/token', data={'grant_type': 'authorization_code', 'code': 'unknown', 'redirect_uri': 'https://rp.test/cb'}, headers={'Authorization': authorization})
    assert result.status_code == 401 and result.json()['error'] == 'invalid_client'
    assert oidc.list_clients() == []
