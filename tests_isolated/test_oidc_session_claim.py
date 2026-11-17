"""Optional authenticated session claim for real RP account linking."""
from urllib.parse import urlsplit, parse_qs
import pytest
from tests_isolated.test_oidc_pool_security import offline_modules
from tests_isolated.test_oidc_provider import oidc, api


@pytest.mark.parametrize('cookie', ['access', 'refresh'])
def test_http_id_token_sid_is_bound_to_authenticated_session(api, oidc, cookie):
    from authlib.jose import jwt
    secret=oidc.create_client('rp',name='RP',redirect_uris=['https://rp.test/cb'])['client_secret']
    if cookie == 'access':
        api.client.cookies.set('stella_at',api.owner_cookie)
    else:
        api.client.cookies.set('stella_rt',api.rt)
    response=api.client.get('/oauth/authorize',params={'response_type':'code','client_id':'rp','redirect_uri':'https://rp.test/cb','state':'exact','session_id':'attacker-supplied'},follow_redirects=False)
    code=parse_qs(urlsplit(response.headers['location']).query)['code'][0]
    tokens=api.client.post('/oauth/token',data={'grant_type':'authorization_code','client_id':'rp','client_secret':secret,'redirect_uri':'https://rp.test/cb','code':code}).json()
    claims=jwt.decode(tokens['id_token'],oidc._get_key())
    from app.security import read_access_token
    assert claims['sid']==read_access_token(api.owner_cookie)['sid']
    assert claims['sub']==str(api.owner_id)


def test_legacy_service_without_session_does_not_invent_sid(oidc):
    from authlib.jose import jwt
    secret=oidc.create_client('rp',name='RP',redirect_uris=['https://rp.test/cb'])['client_secret']
    code=oidc.create_authorization_code('rp','https://rp.test/cb','owner','Owner','',None)
    token=oidc.exchange_code(code,'rp',secret,'https://rp.test/cb')
    assert 'sid' not in jwt.decode(token['id_token'],oidc._get_key())
