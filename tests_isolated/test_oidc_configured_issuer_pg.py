"""Explicit disposable PostgreSQL only; no preview/production settings import."""
import base64
import hashlib
import os
import socket
REAL_CONNECT = socket.socket.connect
import pytest
from tests_isolated.test_oidc_configured_issuer import configure, ISSUER, ALT
from tests_isolated.test_oidc_pool_security import offline_modules
from tests_isolated.test_oidc_provider import oidc


def test_real_postgres_stable_issuer_signed_exchange_and_guards(oidc, monkeypatch, tmp_path):
    url = os.environ.get('STELLA_OIDC_TEST_PG_URL')
    if not url:
        pytest.skip('requires explicitly provisioned disposable OIDC PostgreSQL')
    from sqlalchemy import create_engine
    from app.services import ha_state
    from authlib.jose import jwt
    # Remove only this fixture's offline TCP blocker; no application DB import.
    monkeypatch.setattr(socket.socket, 'connect', REAL_CONNECT)
    configure(monkeypatch)
    monkeypatch.setenv('STELLA_SHARED_STATE', 'postgres')
    monkeypatch.setenv('STELLA_OIDC_PRIVATE_KEY_FILE', str(tmp_path/'key.json'))
    from authlib.jose import JsonWebKey
    import json
    (tmp_path/'key.json').write_text(json.dumps(JsonWebKey.generate_key('RSA',2048,is_private=True).as_dict(is_private=True)))
    engine = create_engine(url, pool_size=2, max_overflow=0)
    assert engine.url.database == 'oidc_disposable'
    monkeypatch.setattr(ha_state, '_engine', lambda: engine)
    ha_state.metadata.create_all(engine)
    try:
        secret = oidc.create_client('isolated-rp',name='Isolated RP',redirect_uris=['https://rp.test/cb'])['client_secret']
        verifier='x'*43
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        for host in (ISSUER[8:], ALT[8:]):
            issuer=oidc.resolve_issuer(host)
            code=oidc.create_authorization_code('isolated-rp','https://rp.test/cb','synthetic-owner','Preview','', 'nonce',issuer=issuer,code_challenge=challenge,code_challenge_method='S256')
            assert oidc.exchange_code(code,'isolated-rp','wrong','https://rp.test/cb',code_verifier=verifier) is None
            assert oidc.exchange_code(code,'isolated-rp',secret,'https://rp.test/changed',code_verifier=verifier) is None
            assert oidc.exchange_code(code,'isolated-rp',secret,'https://rp.test/cb',code_verifier='z'*43) is None
            token=oidc.exchange_code(code,'isolated-rp',secret,'https://rp.test/cb',code_verifier=verifier)
            claims=jwt.decode(token['id_token'],oidc.jwks(),claims_options={'iss':{'essential':True,'value':ISSUER},'aud':{'essential':True,'value':'isolated-rp'}})
            claims.validate()
            assert claims['iss']==ISSUER and claims['nonce']=='nonce'
            assert oidc.userinfo(token['access_token'])=={'sub':'synthetic-owner'}
            assert oidc.exchange_code(code,'isolated-rp',secret,'https://rp.test/cb',code_verifier=verifier) is None
    finally:
        engine.dispose()
