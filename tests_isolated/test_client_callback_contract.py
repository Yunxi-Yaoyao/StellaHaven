"""Callback editor wire contract against real routes; no production settings/TCP.

The PG variant uses the existing owned-container marker and loopback guard.
Auth/elevation tables are disposable SQLite; OIDC clients use real PostgreSQL.
"""
import importlib
import pytest
from tests_isolated.test_oidc_pool_security import offline_modules  # noqa: F401
from tests_isolated.test_oidc_provider import oidc, api  # noqa: F401
from tests_isolated.test_oidc_secret_reveal_pg import pg  # noqa: F401

SPARSE = ['https://photos.test/auth/login', 'https://photos.p/user-settings',
          'http://localhost:2283/auth/login', 'https://yunxi.life/old/callback',
          'app.immich:///oauth-callback']


def wire_contract(api, oidc):
    with oidc._locked_clients() as clients:
        clients['photos'] = {'name': 'Photos', 'client_secret': 'synthetic-keep',
            'credential_version': 'previous-version', 'enabled': True,
            'redirect_uris': list(SPARSE), 'scopes': ['openid', 'email'],
            'future_extension': {'preserve': True}}
        clients['other'] = {'name': 'Other', 'enabled': True,
            'redirect_uris': ['https://other.test/cb'], 'scopes': ['openid']}
    api.app.include_router(importlib.import_module('app.routers.auth_provider').router)
    c = api.client
    try:
        before = oidc._get_client('photos')
        # Persisted ownership replaces the retired independent elevation grant.
        c.cookies.clear()
        assert c.patch('/auth/provider/clients/photos', json={'name': 'Anonymous'}).status_code == 401
        assert oidc._get_client('photos') == before
        c.cookies.set('stella_at', api.foreign_cookie)
        assert c.patch('/auth/provider/clients/photos', json={'name': 'Foreign'}).status_code == 403
        assert oidc._get_client('photos') == before
        c.cookies.set('stella_at', api.owner_cookie)
        changed = c.patch('/auth/provider/clients/photos', json={'name': '家庭相册'})
        assert changed.status_code == 200
        assert oidc._get_client('photos')['credential_version'] == before['credential_version']
        assert oidc._get_client('photos')['redirect_uris'] == SPARSE
        for uri in ['https://photos.test/user-settings', 'https://photos.p/auth/login',
                    'https://photos.test/anywhere', 'https://other.test/cb',
                    'https://stella.xiya.live/auth/login', 'app.immich:////oauth-callback']:
            denied = c.get('/oauth/authorize', params={'response_type':'code',
                'client_id':'photos', 'redirect_uri':uri, 'scope':'openid'},
                headers={'Forwarded':'host=photos.test;proto=https'}, follow_redirects=False)
            assert denied.status_code == 400
            assert 'location' not in denied.headers
        expanded = SPARSE + ['https://photos.test/user-settings', 'https://photos.p/auth/login']
        saved = c.patch('/auth/provider/clients/photos', json={'redirect_uris': expanded})
        assert saved.status_code == 200
        read = c.get('/auth/provider/clients/photos')
        assert read.status_code == 200 and read.json()['redirect_uris'] == expanded
        current = oidc._get_client('photos')
        assert current['credential_version'] != 'previous-version'
        assert current['client_secret'] == 'synthetic-keep'
        assert current['future_extension'] == {'preserve': True}
        assert current['scopes'] == ['openid', 'email']
        assert 'client_secret' not in saved.json() and 'synthetic-keep' not in read.text
        for uri in expanded:
            assert oidc.verify_redirect_uri('photos', uri)
        for extra in ['https://photos.test/*', 'http://localhost:2283/new',
                      'app.immich:////oauth-callback', 'another:///cb']:
            assert c.patch('/auth/provider/clients/photos', json={'redirect_uris': expanded+[extra]}).status_code == 400
            assert oidc._get_client('photos') == current
        assert not oidc.verify_redirect_uri('other','https://photos.test/user-settings')
    finally:
        # Only fixture-owned cookies; no real browser/account session exists.
        c.cookies.clear()


def test_exact_callback_editor_http_wire_contract(api, oidc):
    wire_contract(api, oidc)


def test_exact_callback_editor_http_with_owned_pg_clients(api, pg):
    oidc, _ha, _engine = pg
    wire_contract(api, oidc)
