"""Synthetic-only reveal acceptance; production settings, keys and TCP forbidden."""
import importlib
import json

import pytest

from tests_isolated.test_oidc_pool_security import offline_modules  # noqa: F401
from tests_isolated.test_oidc_provider import oidc, api  # noqa: F401


def seed(oidc):
    with oidc._locked_clients() as clients:
        clients['fixture-rp'] = {
            'name': 'Fixture', 'client_secret': 'synthetic-existing-value',
            'credential_version': 'fixture-version', 'enabled': True,
            'redirect_uris': ['customapp:///oauth/callback', 'https://rp.test/callback'],
            'scopes': ['openid'], 'extension': {'keep': True},
        }


def test_reveal_returns_existing_secret_without_mutating_clients_or_credentials(oidc):
    seed(oidc)
    before = oidc.CLIENT_FILE.read_bytes(), oidc.CLIENT_FILE.stat().st_mtime_ns
    assert oidc.reveal_client_secret('fixture-rp') == {
        'client_id': 'fixture-rp', 'client_secret': 'synthetic-existing-value'}
    assert (oidc.CLIENT_FILE.read_bytes(), oidc.CLIENT_FILE.stat().st_mtime_ns) == before
    assert 'client_secret' not in oidc.list_clients()[0]


def test_http_reveal_is_explicit_owner_elevated_origin_bound_and_private(api, oidc, monkeypatch, caplog):
    seed(oidc)
    monkeypatch.setattr(oidc, 'get_client_secret', lambda *_a, **_kw: pytest.fail('compatibility generator forbidden during reveal'))
    caplog.set_level('INFO', logger='app.routers.auth_provider')
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'https://stella.xiya.live,https://alternate.test')
    api.app.include_router(importlib.import_module('app.routers.auth_provider').router)
    c = api.client
    path = '/auth/provider/clients/fixture-rp/reveal-secret'
    headers = {'Origin': 'https://stella.xiya.live'}
    before = oidc.CLIENT_FILE.read_bytes()
    # Historical test ID retained; single-owner retires management elevation,
    # not identity, session validity or exact-origin checks.
    assert api.app.dependency_overrides == {}
    for cookie, expected in [(None, 401), (api.foreign_cookie, 403),
                             (api.owner_cookie, 200)]:
        c.cookies.clear()
        if cookie:
            c.cookies.set('stella_at', cookie)

        response = c.post(path, headers=headers)
        assert response.status_code == expected
        assert response.headers.get('cache-control') == 'no-store'
        if expected == 200:
            assert response.json() == {'client_id': 'fixture-rp', 'client_secret': 'synthetic-existing-value'}
        else:
            assert 'client_secret' not in response.text
    for origin in [None, 'null', 'https://evil.test', 'https://alternate.test', 'https://stella.xiya.live/']:
        response = c.post(path, headers={} if origin is None else {'Origin': origin})
        assert response.status_code == 403
        assert response.headers.get('cache-control') == 'no-store'
        assert 'client_secret' not in response.text
    assert c.post(path, headers=[('Origin', headers['Origin']), ('Origin', headers['Origin'])]).status_code == 403
    assert c.get(path, headers=headers).status_code == 405
    assert c.post(path.replace('fixture-rp', 'foreign-client'), headers=headers).status_code == 404
    for suffix in ['/config', '/clients', '/clients/fixture-rp']:
        assert 'synthetic-existing-value' not in c.get('/auth/provider' + suffix).text
    assert c.get('/auth/provider/config').json()['capabilities']['secret_reveal'] is True
    from app.models.config import AppConfig
    from app.services import admin_security
    with api.factory() as db:
        row = db.get(AppConfig, admin_security.STATE_KEY)
        state = json.loads(row.value)
        assert state['grants'] == {}
        state['grants'] = {'legacy': {'expires_at': '2000-01-01T00:00:00+00:00'}}
        row.value = json.dumps(state)
        db.commit()
    assert c.post(path, headers=headers).status_code == 200
    with api.factory() as db:
        assert json.loads(db.get(AppConfig, admin_security.STATE_KEY).value) == state
    assert oidc.CLIENT_FILE.read_bytes() == before
    assert 'synthetic-existing-value' not in caplog.text
    events = [record for record in caplog.records if getattr(record, 'action', '') == 'oidc.client.secret_reveal']
    assert len(events) == 2 and all(event.client_id == 'fixture-rp' for event in events)
    assert 'synthetic-existing-value' not in repr(vars(events[0]))


@pytest.mark.parametrize('client_id', ['unknown', 'openlist'])
def test_reveal_does_not_initialize_missing_file_or_default_client(oidc, client_id):
    with pytest.raises(KeyError):
        oidc.reveal_client_secret(client_id)
    assert not oidc.OIDC_DIR.exists()


@pytest.mark.parametrize('value', [None, '', False, 123, {'unexpected': 'object'}])
def test_reveal_missing_or_invalid_secret_fails_without_generation(oidc, value):
    seed(oidc)
    with oidc._locked_clients() as clients:
        clients['fixture-rp']['client_secret'] = value
    before = oidc.CLIENT_FILE.read_bytes(), oidc.CLIENT_FILE.stat().st_mtime_ns
    with pytest.raises(ValueError, match='no existing secret'):
        oidc.reveal_client_secret('fixture-rp')
    assert (oidc.CLIENT_FILE.read_bytes(), oidc.CLIENT_FILE.stat().st_mtime_ns) == before


@pytest.mark.parametrize('change,expected', [
    # Preserve original node ID; its 403 suffix denotes the historical contract.
    pytest.param('expired-grant', 200, id='expired-grant-403'),
    ('revoked-session', 401), ('expired-session', 401),
    ('inactive-owner', 401), ('changed-owner', 403),
])
def test_http_rechecks_real_admission_after_credential_lock(api, oidc, monkeypatch, change, expected):
    from contextlib import contextmanager
    from app.models.config import AppConfig
    from app.models.user import AuthSession, User
    from app.services import admin_security
    seed(oidc)
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'https://stella.xiya.live')
    api.app.include_router(importlib.import_module('app.routers.auth_provider').router)
    api.client.cookies.set('stella_at', api.owner_cookie)
    assert api.app.dependency_overrides == {}
    before = oidc.CLIENT_FILE.read_bytes()
    original = oidc._locked_clients
    @contextmanager
    def after_wait(*args, **kwargs):
        with original(*args, **kwargs) as clients:
            # Simulate external state changing during the credential lock wait,
            # AFTER the real router dependency admitted the initial request.
            with api.factory() as db:
                if change == 'expired-grant':
                    row = db.get(AppConfig, admin_security.STATE_KEY)
                    state = json.loads(row.value)
                    state['grants'] = {'legacy': {'expires_at': '2000-01-01T00:00:00+00:00'}}
                    row.value = json.dumps(state)
                elif change == 'changed-owner':
                    row = db.get(AppConfig, admin_security.STATE_KEY)
                    state = json.loads(row.value)
                    foreign = db.query(User).filter(User.id != api.owner_id).one()
                    state['owner_id'] = str(foreign.id)
                    row.value = json.dumps(state)
                elif change == 'inactive-owner':
                    db.get(User, api.owner_id).is_active = False
                else:
                    session = db.query(AuthSession).filter(AuthSession.user_id == api.owner_id).one()
                    if change == 'revoked-session':
                        session.revoked = True
                    else:
                        from datetime import datetime
                        session.created_at = datetime(2000, 1, 1)
                db.commit()
            yield clients
    monkeypatch.setattr(oidc, '_locked_clients', after_wait)
    response = api.client.post('/auth/provider/clients/fixture-rp/reveal-secret',
                               headers={'Origin': 'https://stella.xiya.live'})
    assert response.status_code == expected
    assert response.headers['cache-control'] == 'no-store'
    if expected == 200:
        assert response.json() == {'client_id': 'fixture-rp', 'client_secret': 'synthetic-existing-value'}
    else:
        assert 'client_secret' not in response.text
    assert oidc.CLIENT_FILE.read_bytes() == before


def test_reveal_waits_for_concurrent_rotation_and_returns_one_complete_current_credential(oidc):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    seed(oidc)
    waiting = Event()
    def reveal():
        waiting.set()
        return oidc.reveal_client_secret('fixture-rp')
    with ThreadPoolExecutor(max_workers=1) as pool:
        with oidc._locked_clients() as clients:
            future = pool.submit(reveal)
            assert waiting.wait(2)
            assert not future.done()
            clients['fixture-rp']['client_secret'] = 'synthetic-concurrent-replacement'
            clients['fixture-rp']['credential_version'] = 'concurrent-version'
        assert future.result(timeout=3)['client_secret'] == 'synthetic-concurrent-replacement'
    state = oidc._get_client('fixture-rp')
    assert state['credential_version'] == 'concurrent-version'
    assert state['redirect_uris'] == ['customapp:///oauth/callback', 'https://rp.test/callback']


@pytest.mark.parametrize('has_row', [True, False])
def test_ha_reveal_is_existing_row_select_for_share_only_not_upsert_or_update(oidc, monkeypatch, has_row):
    # Owned SQL adapter, NOT real PostgreSQL acceptance; every statement must be
    # a SELECT FOR SHARE and the owned stored snapshot must remain unchanged.
    import copy
    import types
    from contextlib import contextmanager
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.sql.selectable import Select
    from app.services import ha_state
    payload = {'fixture-rp': {'client_secret': 'synthetic-ha-value', 'credential_version': 'ha-version'}}
    before = copy.deepcopy(payload)
    statements = []
    class Connection:
        def execute(self, stmt):
            assert isinstance(stmt, Select)
            sql = str(stmt.compile(dialect=postgresql.dialect()))
            assert 'FOR SHARE' in sql and 'oidc.clients' in stmt.compile().params.values()
            statements.append(sql)
            return types.SimpleNamespace(scalar_one_or_none=lambda: copy.deepcopy(payload) if has_row else None)
    class Engine:
        dialect = types.SimpleNamespace(name='postgresql')
        @contextmanager
        def begin(self):
            yield Connection()
    monkeypatch.setenv('STELLA_SHARED_STATE', 'postgres')
    monkeypatch.setattr(ha_state, '_engine', Engine)
    if has_row:
        assert oidc.reveal_client_secret('fixture-rp')['client_secret'] == 'synthetic-ha-value'
    else:
        with pytest.raises(KeyError):
            oidc.reveal_client_secret('fixture-rp')
    assert len(statements) == 1 and payload == before
    assert not oidc.OIDC_DIR.exists()
