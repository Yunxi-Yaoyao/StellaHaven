"""Synthetic SQLite + real loopback upstream; run --noconftest from scratch cwd."""
import json
import socket

import pytest
from tests_isolated.test_integration_security_hotfix import integration_env
from tests_isolated.test_oidc_provider import oidc


@pytest.fixture
def upstream():
    import threading
    import time
    import uvicorn
    from fastapi import FastAPI, Request, WebSocket
    from starlette.responses import HTMLResponse, Response, RedirectResponse
    app = FastAPI(); seen = []
    @app.get('/html')
    def html():
        return HTMLResponse('<html><head></head><body>private synthetic page</body></html>')
    @app.get('/redirect')
    def redirect():
        return RedirectResponse('/html')
    @app.get('/media')
    def media(request: Request):
        assert request.headers['range'] == 'bytes=2-5'
        return Response(b'2345', status_code=206, headers={'Content-Range': 'bytes 2-5/10'}, media_type='video/mp4')
    @app.get('/echo')
    def echo(request: Request):
        seen.append(request.url.path)
        return {'synthetic': True}
    @app.websocket('/socket')
    async def ws(ws: WebSocket):
        from starlette.websockets import WebSocketDisconnect
        await ws.accept()
        try:
            while True: await ws.send_text(await ws.receive_text())
        except WebSocketDisconnect: pass
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline: time.sleep(.01)
    assert server.started
    try: yield f'http://127.0.0.1:{sock.getsockname()[1]}/', seen
    finally:
        server.should_exit = True; thread.join(5); sock.close()
        assert not thread.is_alive()
from app.services import integrations_sessions as sessions

PUBLIC = 'https://stella.xiya.live'
PRIVATE = 'https://stella.p.xiya.live'
MID = 'a' * 32
APP = f'https://app-{MID}.p.xiya.live'


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([
        {'service_id': 'stella', 'public': PUBLIC, 'private': PRIVATE},
        {'service_id': MID, 'public': f'https://app-{MID}.xiya.live', 'private': APP},
    ]))
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', PUBLIC + ',' + PRIVATE)
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {'127.0.0.1', '::1'}:
            raise AssertionError('Unknown test network: ' + str(address))
        return original(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', connect)


def test_private_bootstrap_binding_replay_ws_revocation(integration_env):
    c, factory, app, uid, sid, mid, public_app, cookie, seen = integration_env
    with factory() as db:
        from app.services import integrations as store
        launch = sessions.issue(db, store.get_module(db, mid), sid, PRIVATE)
    assert launch['url'] == APP + '/__stella/bootstrap'
    assert launch['target_origin'] == APP
    assert launch['source_origin'] == PRIVATE
    assert c.post(launch['url'], data=launch['fields'], headers={'Origin': PUBLIC}).status_code == 403
    assert c.post(public_app + '/__stella/bootstrap', data=launch['fields'], headers={'Origin': PUBLIC}).status_code == 401
    boot = c.post(launch['url'], data=launch['fields'], headers={'Origin': PRIVATE}, follow_redirects=False)
    assert boot.status_code == 303, boot.text
    assert 'Secure' in boot.headers['set-cookie'] and 'HttpOnly' in boot.headers['set-cookie']
    assert 'Domain=' not in boot.headers['set-cookie']
    private_cookie = boot.headers['set-cookie'].split(';')[0]
    assert c.post(launch['url'], data=launch['fields'], headers={'Origin': PRIVATE}).status_code == 401
    assert c.get(APP + '/echo', headers={'Cookie': private_cookie}).status_code == 200
    assert c.get(public_app + '/echo', headers={'Cookie': private_cookie}).status_code == 401
    with c.websocket_connect(APP.replace('https:', 'wss:') + '/socket', headers={'Cookie': private_cookie, 'Origin': APP}) as ws:
        ws.send_text('private loopback'); assert ws.receive_text() == 'private loopback'
    from tests_isolated.test_integration_security_hotfix import change_identity
    change_identity(factory, uid, sid, 'revoked')
    assert c.get(APP + '/echo', headers={'Cookie': private_cookie}).status_code == 401


def test_unknown_source_cannot_issue(integration_env):
    from fastapi import HTTPException
    from app.services import integrations as store
    c, factory, app, uid, sid, mid, *_ = integration_env
    with factory() as db, pytest.raises(HTTPException) as exc:
        sessions.issue(db, store.get_module(db, mid), sid, 'https://evil.invalid')
    assert exc.value.status_code == 403


def test_private_oidc_login_keeps_browser_origin_and_issuer():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import oidc
    from app.services import oidc as service
    app = FastAPI(); app.include_router(oidc.router)
    app.dependency_overrides[oidc._optional_user] = lambda: None
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(service, '_get_client', lambda cid: {'enabled': True, 'redirect_uris': ['https://rp.p.xiya.live/callback']})
        with TestClient(app, base_url=PRIVATE) as c:
            result = c.get('/oauth/authorize', params={'client_id': 'synthetic', 'redirect_uri': 'https://rp.p.xiya.live/callback', 'response_type': 'code'}, follow_redirects=False)
            assert result.status_code == 307, result.text
            assert result.headers['location'].startswith(PRIVATE + '/login?')
            discovery = c.get('/.well-known/openid-configuration').json()
            assert discovery['issuer'] == PUBLIC
            assert discovery['authorization_endpoint'] == PUBLIC + '/oauth/authorize'
            assert c.get('/.well-known/openid-configuration', headers={'Host': 'evil.invalid'}).status_code == 421


@pytest.mark.parametrize('source,target', [(PUBLIC, f'https://app-{MID}.xiya.live'), (PRIVATE, APP)])
def test_real_http_launch_redirect_range_csp(integration_env, source, target):
    from app.services import integrations as store
    from tests_isolated.test_owner_admin_security import DAILY
    c, factory, app, uid, sid, mid, *_ = integration_env
    # Authenticate separately on each exact browser origin (host-only sessions).
    logged = c.post(source + '/auth/login', json={'username': 'owner', 'password': DAILY}, headers={'Origin': source})
    assert logged.status_code == 200, logged.text
    assert logged.json()['id'] == str(uid)
    if source == PRIVATE:
        # No owner row inherits the exact deployed private lane at revision zero.
        inherited = c.post(source + '/external-modules/' + mid + '/launch', headers={'Origin': source})
        assert inherited.status_code == 200, inherited.text
        initial = inherited.json()
        assert initial['target_origin'] == target and initial['source_origin'] == source
        assert initial['entry_revision'] == 0
        assert initial['url'] == target + '/__stella/bootstrap'
        initial_boot = c.post(initial['url'], data=initial['fields'], headers={'Origin': source}, follow_redirects=False)
        assert initial_boot.status_code == 303, initial_boot.text
        initial_cookie = initial_boot.headers['set-cookie'].split(';')[0]
        assert c.get(target + '/echo', headers={'Cookie': initial_cookie}).status_code == 200
        assert c.post(initial['url'], data=initial['fields'], headers={'Origin': source}).status_code == 401
        from sqlalchemy import JSON, MetaData
        from sqlalchemy.dialects.postgresql import JSONB
        from app.models.config import AppConfig
        from app.models.node import Node
        from app.models.monitor import MonitorGroup
        from app.services import access_entries
        # Real apply reconciles groups and scans nodes. Adapt only private DDL
        # copies for this case; never mutate mapped columns/global compilers.
        metadata = MetaData()
        for original in (Node.__table__, MonitorGroup.__table__):
            table = original.to_metadata(metadata)
            for column in table.columns:
                if isinstance(column.type, JSONB):
                    column.type = JSON()
        metadata.create_all(factory.kw['bind'])
        with factory() as db:
            assert db.get(AppConfig, access_entries.KEY) is None
        before = c.get(source + '/config/access-entries')
        assert before.status_code == 200, before.text
        assert before.json()['settings'] == dict(revision=0, enabled=False, public_origin=PUBLIC, private_origin=PRIVATE)
        with factory() as db:
            assert db.get(AppConfig, access_entries.KEY) is None  # GET never persists inheritance
        draft = before.json()['settings'] | {'enabled': True, 'private_origin': PRIVATE}
        checked = c.post(source + '/config/access-entries/check', json=draft)
        assert checked.status_code == 200, checked.text
        assert checked.json()['can_apply'] is True
        applied = c.put(source + '/config/access-entries', json=draft | {'checked_digest': checked.json()['digest']})
        assert applied.status_code == 200, applied.text
        assert applied.json()['settings'] == draft | {'revision': 1}
        assert c.get(source + '/config/access-entries').json()['settings'] == applied.json()['settings']
        with factory() as db:
            assert json.loads(db.get(AppConfig, access_entries.KEY).value) == {
                'owner_id': str(uid), 'settings': applied.json()['settings'],
            }
        assert isinstance(Node.__table__.c.interfaces.type, JSONB)
    launch = c.post(source + '/external-modules/' + mid + '/launch', headers={'Origin': source})
    assert launch.status_code == 200, launch.text
    info = launch.json(); assert info['target_origin'] == target
    boot = c.post(info['url'], data=info['fields'], headers={'Origin': source}, follow_redirects=False)
    assert boot.status_code == 303, boot.text
    cookie = boot.headers['set-cookie'].split(';')[0]
    with factory() as db, store.edit(db) as state:
        state['modules'][mid]['injection']['active'] = dict(enabled=True, version='synthetic-v1', css='body{color:white}', js='window.synthetic=true;', timing='document_start', csp_policy='controlled')
    response = c.get(target + '/html', headers={'Cookie': cookie})
    assert response.status_code == 200
    assert 'frame-ancestors ' + source in response.headers['content-security-policy']
    assert (PRIVATE if source == PUBLIC else PUBLIC) not in response.headers['content-security-policy']
    redirect = c.get(target + '/redirect', headers={'Cookie': cookie}, follow_redirects=False)
    assert redirect.status_code == 307 and redirect.headers['location'] == target + '/html'
    media = c.get(target + '/media', headers={'Cookie': cookie, 'Range': 'bytes=2-5'})
    assert media.status_code == 206 and media.content == b'2345'
    assert media.headers['content-range'] == 'bytes 2-5/10'


@pytest.mark.parametrize('value', ['{}', '[{}]', '[{"service_id":"stella","public":"https://stella.xiya.live/"}]', '[{"service_id":"stella","public":"https://stella.xiya.live","private":"https://stella.xiya.live"}]'])
def test_invalid_registry_fails_closed(monkeypatch, value):
    from app.services.entry_registry import records
    from fastapi import HTTPException
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', value)
    with pytest.raises(HTTPException) as exc: records()
    assert exc.value.status_code == 503


def test_private_and_public_oidc_same_signing_subject_pkce_and_replay(integration_env, oidc):
    import base64
    import hashlib
    from urllib.parse import urlsplit, parse_qs
    from authlib.jose import jwt
    from tests_isolated.test_owner_admin_security import DAILY
    c, factory, app, uid, *_ = integration_env
    assert c.post(PRIVATE + '/auth/login', json={'username': 'owner', 'password': DAILY}, headers={'Origin': PRIVATE}).status_code == 200
    callbacks = ['https://rp.test/cb', 'https://rp.p.test/cb']
    secret = oidc.create_client('rp', name='Synthetic RP', redirect_uris=callbacks)['client_secret']
    verifier = 's' * 43
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    oidc._get_key()  # Initialize only this test's temporary synthetic signing key.
    jwks_response = c.get('/oauth/jwks')
    assert jwks_response.status_code == 200, jwks_response.text
    jwks = jwks_response.json()
    subjects = []
    for parent, callback in zip([PUBLIC, PRIVATE], callbacks):
        r = c.get(parent + '/oauth/authorize', params=dict(response_type='code', client_id='rp', redirect_uri=callback, scope='openid profile email', state='exact + state', nonce='same-nonce', code_challenge=challenge, code_challenge_method='S256'), follow_redirects=False)
        assert r.status_code == 307, r.text
        assert r.headers['location'].startswith(callback + '?')
        query = parse_qs(urlsplit(r.headers['location']).query)
        assert query['state'] == ['exact + state']
        payload = dict(grant_type='authorization_code', client_id='rp', client_secret=secret, code=query['code'][0], redirect_uri=callback, code_verifier='wrong' * 10)
        assert c.post(PUBLIC + '/oauth/token', data=payload, headers={'Cookie': ''}).status_code == 400
        payload['code_verifier'] = verifier
        token = c.post(PUBLIC + '/oauth/token', data=payload, headers={'Cookie': ''})
        assert token.status_code == 200, token.text
        claims = jwt.decode(token.json()['id_token'], jwks)
        claims.validate()
        assert claims['iss'] == PUBLIC and claims['nonce'] == 'same-nonce'
        subjects.append(claims['sub'])
        assert c.post(PUBLIC + '/oauth/token', data=payload, headers={'Cookie': ''}).status_code == 400
    assert subjects == [str(uid), str(uid)]
    assert c.get(PRIVATE + '/oauth/jwks').json() == jwks


def test_real_browser_bootstrap_cookie_refresh_replay(integration_env, tmp_path):
    import os
    import subprocess
    import threading
    import time
    from pathlib import Path
    import uvicorn
    from app.services import integrations as store
    c, factory, app, uid, sid, mid, *_ = integration_env
    with factory() as db, store.edit(db) as state:
        state['modules'][mid]['initial_path'] = '/html'
        state['modules'][mid]['injection']['active'] = dict(enabled=True, version='browser-v1', css='', js='window.synthetic=true;', timing='document_start', csp_policy='controlled')
    lanes = []
    for name, source in [('public', PUBLIC), ('private', PRIVATE)]:
        with factory() as db:
            lanes.append(dict(name=name, **sessions.issue(db, store.get_module(db, mid), sid, source)))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline: time.sleep(.01)
        assert server.started
        evidence = os.getenv('STELLA_DUAL_EVIDENCE', str(tmp_path))
        spec = dict(backend=f'http://127.0.0.1:{sock.getsockname()[1]}', lanes=lanes, evidence=evidence)
        # One ephemeral, synthetic certificate pinned by SPKI in the browser.
        import base64
        import hashlib
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        key, cert = tmp_path / 'synthetic.key', tmp_path / 'synthetic.crt'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=stella-dual-entry-test', '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
        public_key = x509.load_pem_x509_certificate(cert.read_bytes()).public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        spec.update(key=str(key), cert=str(cert), spki=base64.b64encode(hashlib.sha256(public_key).digest()).decode())
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', str(root / 'frontend/tests/dual-entry-browser.mjs')], env={**os.environ, 'STELLA_DUAL_BROWSER_FIXTURE': json.dumps(spec)}, capture_output=True, text=True, timeout=60)
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.should_exit = True; thread.join(5); sock.close()
        assert not thread.is_alive()
