"""Synthetic gallery ingress contract: exact origins, no PG/OAuth/network."""
import json
import socket

import pytest
from fastapi import HTTPException
from app.services import external_services as external, gallery
from tests_isolated.test_owner_admin_security import auth_env, owner

PUBLIC = 'https://stella.example'
PRIVATE = 'https://stella.private.example'
PHOTOS = 'https://photos.example'
PRIVATE_PHOTOS = 'https://photos.private.example'


def registry(monkeypatch, *, public=PUBLIC, private=PRIVATE, pair=True, photo_private=PRIVATE_PHOTOS, photo_public=PHOTOS):
    rows = [{'service_id': 'stella', 'public': public, 'private': private}]
    if pair:
        row = {'service_id': 'gallery', 'public': photo_public}
        if photo_private:
            row['private'] = photo_private
        rows.append(row)
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps(rows))


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    registry(monkeypatch)
    def deny_network(*args, **kwargs):
        raise AssertionError('Gallery candidate tests forbid network')
    monkeypatch.setattr(socket.socket, 'connect', deny_network)


@pytest.fixture
def cfg(monkeypatch):
    cfg = external.Connection(browser_url=PHOTOS + '/photos', alternate_browser_url='https://photos.yunxi.life/photos', auth_mode='oidc')
    monkeypatch.setattr(external, 'load', lambda db, kind: cfg)
    return cfg


def test_private_gallery_uses_explicit_mapping_and_preserves_base_path(cfg):
    assert gallery.browser_url(None, PRIVATE) == PRIVATE_PHOTOS + '/photos/'


@pytest.mark.parametrize('source', ['https://yunxi.life', 'https://stella.yunxi.life'])
def test_registered_public_alias_keeps_configured_alternate(cfg, monkeypatch, source):
    registry(monkeypatch, public=source, pair=False)
    assert gallery.browser_url(None, source) == cfg.alternate_browser_url + '/'


def test_private_alias_maps_the_registered_public_alias_not_request_suffix(cfg, monkeypatch):
    registry(monkeypatch, public='https://stella.yunxi.life', photo_public='https://photos.yunxi.life')
    assert gallery.browser_url(None, PRIVATE) == PRIVATE_PHOTOS + '/photos/'


@pytest.mark.parametrize('source,expected', [(PUBLIC, PHOTOS), (PRIVATE, PRIVATE_PHOTOS)])
@pytest.mark.parametrize('mode,suffix', [('oidc', '/'), ('manual', '/auth/login?autoLaunch=0')])
def test_both_lanes_preserve_auth_choice(cfg, source, expected, mode, suffix):
    cfg.auth_mode = mode
    assert gallery.browser_url(None, source) == expected + '/photos' + suffix


@pytest.mark.parametrize('source', [
    '', 'stella.example', 'https://evil.invalid', 'https://stella.yunxi.life',
    'https://stella.example.evil.invalid', 'https://stella.example:8443',
    'http://stella.example', 'https://stella.p.example',
])
def test_unregistered_sources_including_aliases_rejected(cfg, source):
    with pytest.raises(HTTPException) as exc:
        gallery.browser_url(None, source)
    assert exc.value.status_code == 403


@pytest.mark.parametrize('pair,private,status', [(False, PRIVATE_PHOTOS, 403), (True, '', 409)])
def test_missing_private_gallery_does_not_fall_back(cfg, monkeypatch, pair, private, status):
    registry(monkeypatch, pair=pair, photo_private=private)
    with pytest.raises(HTTPException) as exc:
        gallery.browser_url(None, PRIVATE)
    assert exc.value.status_code == status
    assert gallery.browser_url(None, PUBLIC) == PHOTOS + '/photos/'


@pytest.mark.parametrize('source', [PUBLIC, PRIVATE])
def test_mismatched_gallery_mapping_fails_closed(cfg, monkeypatch, source):
    registry(monkeypatch, photo_public='https://different.example')
    with pytest.raises(HTTPException) as exc:
        gallery.browser_url(None, source)
    assert exc.value.status_code == 409


def test_generic_module_id_is_not_guessed_for_legacy_gallery(cfg, monkeypatch):
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([
        {'service_id': 'stella', 'public': PUBLIC, 'private': PRIVATE},
        {'service_id': 'synthetic-module-id', 'public': PHOTOS, 'private': PRIVATE_PHOTOS},
    ]))
    with pytest.raises(HTTPException) as exc:
        gallery.browser_url(None, PRIVATE)
    assert exc.value.status_code == 403


@pytest.mark.parametrize('source,target', [(PUBLIC, PHOTOS), (PRIVATE, PRIVATE_PHOTOS)])
def test_connect_real_http_retains_auth_guard_and_no_store(auth_env, cfg, source, target):
    from app.routers.gallery import router
    client, db, app = auth_env
    app.include_router(router)
    client.base_url = source
    assert client.get('/gallery/connect', follow_redirects=False).status_code == 401
    owner(client)
    result = client.get('/gallery/connect', follow_redirects=False)
    assert result.status_code == 307, result.text
    assert result.headers['location'] == target + '/photos/'
    assert result.headers['cache-control'] == 'no-store'
    assert 'set-cookie' not in result.headers


def test_connect_ignores_forwarded_host_and_rejects_unknown_scheme_port(auth_env, cfg):
    from app.routers.gallery import router
    client, db, app = auth_env
    app.include_router(router)
    client.base_url = PRIVATE
    owner(client)
    result = client.get('/gallery/connect', headers={'X-Forwarded-Host': 'stella.example', 'X-Forwarded-Proto': 'http'}, follow_redirects=False)
    assert result.status_code == 307, result.text
    assert result.headers['location'] == PRIVATE_PHOTOS + '/photos/'
    cookie = '; '.join(f'{key}={value}' for key, value in client.cookies.items())
    for source in ('https://evil.invalid', 'http://stella.private.example', PRIVATE + ':8443'):
        result = client.get(source + '/gallery/connect', headers={'Cookie': cookie, 'X-Forwarded-Host': 'stella.private.example'}, follow_redirects=False)
        assert result.status_code == 403, result.text
        assert 'location' not in result.headers


@pytest.mark.parametrize('case,status', [('missing', 403), ('no_private', 409), ('mismatch', 409), ('invalid', 503)])
def test_connect_mapping_errors_are_not_redirects(auth_env, cfg, monkeypatch, case, status):
    from app.routers.gallery import router
    client, db, app = auth_env
    app.include_router(router)
    client.base_url = PRIVATE
    owner(client)
    if case == 'missing':
        registry(monkeypatch, pair=False)
    elif case == 'no_private':
        registry(monkeypatch, photo_private='')
    elif case == 'mismatch':
        registry(monkeypatch, photo_public='https://different.example')
    else:
        monkeypatch.setenv('STELLA_ENTRY_REGISTRY', '{}')
    result = client.get('/gallery/connect', follow_redirects=False)
    assert result.status_code == status, result.text
    assert set(result.json()) == {'detail'} and isinstance(result.json()['detail'], str)
    assert 'location' not in result.headers


def test_connect_cannot_resurrect_migrated_gallery(auth_env, cfg):
    from app.routers.gallery import router
    from app.services import integrations as store, website_migration
    client, db, app = auth_env
    app.include_router(router)
    client.base_url = PUBLIC
    owner(client)
    with store.edit(db) as state:
        state[website_migration.MARKER] = {'synthetic': True}
    result = client.get('/gallery/connect', follow_redirects=False)
    assert result.status_code == 410, result.text
    assert 'location' not in result.headers
