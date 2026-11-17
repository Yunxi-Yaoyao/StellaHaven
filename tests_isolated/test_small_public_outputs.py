"""HTTP output boundaries using synthetic state only; no main/app lifespan."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def api(tmp_path, monkeypatch):
    # Set before importing auth/settings; never read a checkout .env/signing key.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('STELLA_SECRET_KEY', 'synthetic-offline-signing-key-at-least-32')
    monkeypatch.delenv('STELLA_SHARED_STATE', raising=False)
    monkeypatch.delenv('STELLA_OIDC_PRIVATE_KEY_FILE', raising=False)
    from app.routers import auth, admin_email, operations_status, oidc
    from app.services import oidc as oidc_svc
    from app.database import get_db, engine

    def forbidden(*args, **kwargs):
        raise AssertionError('live I/O or unexpected write attempted')

    monkeypatch.setattr(engine, 'connect', forbidden)
    monkeypatch.setattr(admin_email, '_send', forbidden)
    monkeypatch.setattr(admin_email, '_save', forbidden)
    monkeypatch.setattr(admin_email, 'CONFIG_FILE', tmp_path / 'smtp.json')
    monkeypatch.setattr(oidc_svc, 'OIDC_DIR', tmp_path / 'oidc')
    monkeypatch.setattr(oidc_svc, 'PRIVATE_KEY_PATH', tmp_path / 'oidc' / 'private.json')
    monkeypatch.setattr(oidc_svc, 'CLIENT_FILE', tmp_path / 'oidc' / 'clients.json')
    user = SimpleNamespace(avatar_history=None)
    db = SimpleNamespace(get=lambda *a, **kw: None)
    app = FastAPI()
    for module in (auth, admin_email, operations_status, oidc):
        app.include_router(module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[auth.current_user] = lambda: user
    app.dependency_overrides[auth.admin_user] = lambda: user
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(client=client, app=app, user=user, db=db, auth=auth,
                              email=admin_email, oidc=oidc_svc)


@pytest.mark.parametrize('stored,expected', [
    (None, []), ('broken json', []), ('null', []), ('42', []), ('true', []),
    ('"secret-string"', []), ('{"password":"object-secret"}', []),
    (json.dumps(['/assets/avatars/a.png', 'https://images.invalid/a.png']),
     ['/assets/avatars/a.png', 'https://images.invalid/a.png']),
    (json.dumps(['/assets/avatars/a.png', {'password': 'object-secret'}, 1, None,
                 'javascript:alert(1)', '', '//evil.invalid/x', 'https://u:p@img.invalid/a']),
     ['/assets/avatars/a.png']),
])
def test_avatar_history_is_url_array_even_for_legacy(api, stored, expected):
    api.user.avatar_history = stored
    response = api.client.get('/auth/avatars')
    assert response.status_code == 200
    assert response.json() == expected
    assert 'object-secret' not in response.text
    assert api.user.avatar_history == stored


@pytest.mark.parametrize('backend', ['file', 'shared'])
@pytest.mark.parametrize('stored,expected', [
    ({}, {'host': '', 'port': 465, 'username': '', 'password': '',
          'from_name': 'StellaHaven 港务局', 'enabled': False}),
    ({'host': 'smtp.invalid', 'port': 587, 'username': 'owner@example.invalid',
      'password': 'synthetic-password', 'from_name': 'Sender', 'enabled': True,
      'api_secret': {'nested': 'object-secret'}},
     {'host': 'smtp.invalid', 'port': 587, 'username': 'owner@example.invalid',
      'password': '••••••', 'from_name': 'Sender', 'enabled': True}),
    ({'host': {'secret': 'object-secret'}, 'port': True, 'username': ['object-secret'],
      'password': {'secret': 'object-secret'}, 'from_name': 12, 'enabled': 'false'},
     {'host': None, 'port': None, 'username': None, 'password': '••••••',
      'from_name': None, 'enabled': None}),
    ({'port': '587', 'enabled': 1}, {'host': '', 'port': None, 'username': '',
      'password': '', 'from_name': 'StellaHaven 港务局', 'enabled': None}),
])
def test_smtp_public_allowlist_types_mask_and_no_mutation(api, monkeypatch, backend, stored, expected):
    from contextlib import contextmanager
    original = json.dumps(stored)
    if backend == 'file':
        api.email.CONFIG_FILE.write_text(original)
    else:
        @contextmanager
        def locked_state(key, default):
            assert key == 'smtp.config'
            yield stored
        monkeypatch.setattr(api.email.ha_state, 'enabled', lambda: True)
        monkeypatch.setattr(api.email.ha_state, 'locked_state', locked_state)
    response = api.client.get('/admin/email/config')
    assert response.status_code == 200
    assert response.json() == expected
    assert 'object-secret' not in response.text
    assert 'synthetic-password' not in response.text
    assert json.dumps(stored) == original
    if backend == 'file':
        assert api.email.CONFIG_FILE.read_text() == original


@pytest.mark.parametrize('stored', ['null', '[]', '[["enabled", true]]', '42', '"secret"', '{bad'])
def test_smtp_invalid_root_is_configuration_error_not_default_success(api, stored):
    api.email.CONFIG_FILE.write_text(stored)
    response = api.client.get('/admin/email/config')
    assert response.status_code == 503
    assert response.json() == {'detail': '邮箱服务配置无效，请检查服务器配置'}
    assert api.email.CONFIG_FILE.read_text() == stored


AUDIT_EVENT = {'timestamp': '2026-10-16T09:00:00+00:00', 'action': 'integration.update',
               'actor_id': '7f925ced-5453-4f7f-b6ef-46545169d9c9', 'resource_id': None,
               'changed_fields': ['enabled', 'title']}
UNKNOWN_EVENT = dict.fromkeys(AUDIT_EVENT)


def set_audit(api, stored):
    row = SimpleNamespace(value=stored)
    api.db.get = lambda *args, **kwargs: row
    return row


def test_audit_known_values_normalize_without_fabricating_events(api):
    entries = [AUDIT_EVENT,
               {'action': 'legacy.update'},
               {'timestamp': {'password': 'object-secret'}, 'action': ['object-secret'],
                'actor_id': False, 'resource_id': {'token': 'object-secret'},
                'changed_fields': [{'password': 'object-secret'}], 'token': 'object-secret'},
               {'timestamp': 'not-a-date', 'action': 'bad action', 'actor_id': 'not-uuid',
                'resource_id': 'not-uuid', 'changed_fields': 'title'},
               {'changed_fields': ['title', 'password', 'object-secret']},
               'non-event']
    raw = json.dumps(entries)
    row = set_audit(api, raw)
    response = api.client.get('/operations/change-audit')
    assert response.status_code == 200
    expected_legacy = {**UNKNOWN_EVENT, 'action': 'legacy.update'}
    assert response.json() == {'events': [UNKNOWN_EVENT, UNKNOWN_EVENT, UNKNOWN_EVENT,
                                          expected_legacy, AUDIT_EVENT], 'limit': 200}
    assert response.headers['cache-control'] == 'no-store'
    assert 'object-secret' not in response.text
    assert row.value == raw


def test_audit_current_events_order_limit_and_no_unknown_fields(api):
    events = [{**AUDIT_EVENT, 'action': f'integration.update_{i}', 'private': 'object-secret'}
              for i in range(200)]
    set_audit(api, json.dumps(events))
    response = api.client.get('/operations/change-audit')
    assert response.status_code == 200
    result = response.json()
    assert result['limit'] == 200 and len(result['events']) == 200
    assert [e['action'] for e in result['events']] == [e['action'] for e in reversed(events)]
    assert all(set(e) == set(AUDIT_EVENT) for e in result['events'])
    assert 'object-secret' not in response.text


@pytest.mark.parametrize('stored', ['{}', 'null', '{bad', json.dumps([{}] * 201)])
def test_audit_bad_slot_keeps_controlled_unavailable_response(api, stored):
    set_audit(api, stored)
    response = api.client.get('/operations/change-audit')
    assert response.status_code == 503
    assert response.json() == {'detail': '变更审计记录无效，请检查受控审计槽'}


@pytest.fixture
def rsa_key():
    from authlib.jose import JsonWebKey
    return JsonWebKey.generate_key('RSA', 2048, is_private=True).as_dict(is_private=True)


def provision_key(api, key):
    api.oidc.PRIVATE_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(key)
    api.oidc.PRIVATE_KEY_PATH.write_text(raw)
    return raw


def test_jwks_rsa_allowlist_is_real_verification_key_not_metadata(api, rsa_key):
    from authlib.jose import jwt
    stored = {**rsa_key, 'kid': 'legacy-id', 'alg': 'RS256', 'use': 'sig',
              'k': 'symmetric-secret', 'password': 'object-secret',
              'x5c': ['object-secret'], 'custom': {'secret': 'object-secret'}}
    raw = provision_key(api, stored)
    response = api.client.get('/oauth/jwks')
    assert response.status_code == 200
    expected = {key: rsa_key[key] for key in ('kty', 'n', 'e')}
    expected.update(kid='legacy-id', alg='RS256', use='sig')
    assert response.json() == {'keys': [expected]}
    assert 'object-secret' not in response.text and 'symmetric-secret' not in response.text
    assert not {'d', 'p', 'q', 'dp', 'dq', 'qi', 'oth', 'k'} & set(response.json()['keys'][0])
    # Authlib uses provisioned kid metadata despite the signer's fallback header.
    token = api.oidc._sign_id_token('owner', 'Owner', 'owner@example.invalid', None, 'rp')
    assert jwt.decode(token, response.json())['sub'] == 'owner'
    assert api.oidc.PRIVATE_KEY_PATH.read_text() == raw


@pytest.mark.parametrize('kind,crv', [('oct', 256), ('EC', 'P-256'), ('OKP', 'Ed25519'), ('OKP', 'X25519')])
def test_jwks_rejects_keys_not_supported_by_actual_rs256_signer(api, kind, crv):
    from authlib.jose import JsonWebKey
    key = JsonWebKey.generate_key(kind, crv, is_private=True).as_dict(is_private=True)
    raw = provision_key(api, key)
    response = api.client.get('/oauth/jwks')
    assert response.status_code == 503
    assert response.json() == {'detail': 'OIDC 签名密钥配置无效或不支持，请检查服务器配置'}
    assert api.oidc.PRIVATE_KEY_PATH.read_text() == raw


@pytest.mark.parametrize('changes', [
    {'alg': 'HS256'}, {'alg': 'RS512'}, {'use': 'enc'}, {'kid': {'secret': 'object-secret'}},
    {'n': {'secret': 'object-secret'}}, {'e': []}, {'n': ''}, {'n': 'AA'},
    {'e': 'AA'}, {'n': 'not base64!'}, {'d': 'invalid-private-value'},
])
def test_jwks_bad_rsa_configuration_is_sanitized_503_and_never_replaced(api, rsa_key, changes):
    raw = provision_key(api, {**rsa_key, **changes})
    response = api.client.get('/oauth/jwks')
    assert response.status_code == 503
    assert response.json() == {'detail': 'OIDC 签名密钥配置无效或不支持，请检查服务器配置'}
    assert api.oidc.PRIVATE_KEY_PATH.read_text() == raw


@pytest.mark.parametrize('raw', ['null', '[]', '42', '"object-secret"', '{bad'])
def test_jwks_bad_json_is_controlled_configuration_error(api, raw):
    api.oidc.PRIVATE_KEY_PATH.parent.mkdir(parents=True)
    api.oidc.PRIVATE_KEY_PATH.write_text(raw)
    response = api.client.get('/oauth/jwks')
    assert response.status_code == 503
    assert response.json() == {'detail': 'OIDC 签名密钥配置无效或不支持，请检查服务器配置'}
    assert api.oidc.PRIVATE_KEY_PATH.read_text() == raw


def test_jwks_missing_key_does_not_generate_or_replace_key(api, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('public GET must never generate a production signing key')
    monkeypatch.setattr(api.oidc.JsonWebKey, 'generate_key', forbidden)
    response = api.client.get('/oauth/jwks')
    assert response.status_code == 503
    assert not api.oidc.OIDC_DIR.exists()


@pytest.mark.parametrize('kid', [None, 'stella-oidc-1', 'provisioned-key'])
@pytest.mark.parametrize('backend', ['file', 'shared'])
def test_jwks_effective_kid_and_synthetic_ha_path_verify_real_signature(api, rsa_key, monkeypatch, tmp_path, kid, backend):
    from authlib.jose import jwt
    rsa_key.pop('kid', None)
    if kid is not None:
        rsa_key['kid'] = kid
    if backend == 'shared':
        path = tmp_path / 'shared-key.json'
        monkeypatch.setenv('STELLA_SHARED_STATE', 'postgres')
        monkeypatch.setenv('STELLA_OIDC_PRIVATE_KEY_FILE', str(path))
        path.write_text(json.dumps(rsa_key))
    else:
        provision_key(api, rsa_key)
    response = api.client.get('/oauth/jwks')
    assert response.status_code == 200
    assert response.json()['keys'][0]['kid'] == (kid or api.oidc.KID)
    token = api.oidc._sign_id_token('owner', 'Owner', '', None, 'rp')
    assert jwt.decode(token, response.json())['sub'] == 'owner'


@pytest.mark.parametrize('operations', [['encrypt'], ['verify'], 'sign', [1], ['sign', 'unknown']])
def test_jwks_incompatible_key_operations_are_not_advertised(api, rsa_key, operations):
    provision_key(api, {**rsa_key, 'key_ops': operations})
    response = api.client.get('/oauth/jwks')
    assert response.status_code == 503
    assert response.json() == {'detail': 'OIDC 签名密钥配置无效或不支持，请检查服务器配置'}


@pytest.mark.parametrize('url', ['/assets/' + chr(0xD800) + '.png', 'https://image.invalid:bad/a',
                                 'https://image.invalid:99999/a', 'https://[broken/a'])
def test_avatar_malformed_url_text_cannot_trigger_500(api, url):
    api.user.avatar_history = json.dumps([url])
    response = api.client.get('/auth/avatars')
    assert response.status_code == 200
    assert response.json() == []


def test_smtp_non_utf8_legacy_text_is_unknown_not_server_error(api):
    api.email.CONFIG_FILE.write_text(json.dumps(dict.fromkeys(('host', 'username', 'from_name'), chr(0xD800))))
    response = api.client.get('/admin/email/config')
    assert response.status_code == 200
    assert response.json() == {**api.email.DEFAULTS, 'host': None, 'username': None, 'from_name': None}


def test_audit_non_utf8_timestamp_is_unknown_not_server_error(api):
    set_audit(api, json.dumps([{**AUDIT_EVENT, 'timestamp': '2026-10-16' + chr(0xD800) + '09:00:00+00:00'}]))
    response = api.client.get('/operations/change-audit')
    assert response.status_code == 200
    assert response.json()['events'] == [{**AUDIT_EVENT, 'timestamp': None}]


def test_jwks_non_utf8_kid_is_configuration_error(api, rsa_key):
    provision_key(api, {**rsa_key, 'kid': chr(0xD800)})
    response = api.client.get('/oauth/jwks')
    assert response.status_code == 503
