"""Real authorize/refresh dependencies, disposable SQLite and synthetic keys only.

Run with the isolated namespace bootstrap: never import the production app/main.
"""
import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from tests_isolated.test_oidc_provider import api, oidc  # noqa: F401


CALLBACK = 'https://rp.test/cb'
STATE = 'exact state + & = / 中文'


def request_params(**changes):
    return {'client_id': 'rp', 'redirect_uri': CALLBACK, 'response_type': 'code',
            'scope': 'openid', 'state': STATE, **changes}


def assert_callback_error(response, error, *, callback=CALLBACK, state=STATE):
    assert response.status_code == 307, response.text
    location = urlsplit(response.headers['location'])
    approved = urlsplit(callback)
    assert (location.scheme, location.netloc, location.path) == (approved.scheme, approved.netloc, approved.path)
    params = parse_qs(location.query, keep_blank_values=True)
    assert params == {'error': [error], 'state': [state]}
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['pragma'] == 'no-cache'


def test_invalid_scope_refresh_then_valid_authorize_keeps_session(api, oidc):
    oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])
    api.client.cookies.set('stella_rt', api.rt)
    invalid = api.client.get('/oauth/authorize', params=request_params(scope='openid admin'), follow_redirects=False)
    # The real refresh token is committed before this error. Both replacements
    # must reach the browser, not merely the injected FastAPI response.
    cookies = invalid.headers.get_list('set-cookie')
    assert any(cookie.startswith('stella_at=') for cookie in cookies)
    assert any(cookie.startswith('stella_rt=') for cookie in cookies)
    assert_callback_error(invalid, 'invalid_scope')
    # Force the second request to use the replacement refresh, not its access
    # cookie, so this catches loss of the rotated refresh token specifically.
    for cookie in list(api.client.cookies.jar):
        if cookie.name == 'stella_at':
            api.client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
    valid = api.client.get('/oauth/authorize', params=request_params(), follow_redirects=False)
    assert valid.status_code == 307
    location = urlsplit(valid.headers['location'])
    assert location.netloc == 'rp.test' and location.path == '/cb'
    params = parse_qs(location.query)
    assert params['code'] and params['state'] == [STATE]


@pytest.mark.parametrize('authenticated', [False, True])
@pytest.mark.parametrize('response_type', [None, ''])
def test_missing_or_empty_response_type_is_callback_invalid_request(api, oidc, authenticated, response_type):
    oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])
    if authenticated:
        api.client.cookies.set('stella_at', api.owner_cookie)
    params = request_params(response_type=response_type)
    if response_type is None:
        params.pop('response_type')
    response = api.client.get('/oauth/authorize', params=params, follow_redirects=False)
    assert_callback_error(response, 'invalid_request')
    with oidc._shared_state() as runtime:
        assert runtime['codes'] == {}


def test_prompt_none_guest_returns_callback_login_required_without_ui(api, oidc):
    oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])
    response = api.client.get('/oauth/authorize', params=request_params(prompt='none'), follow_redirects=False)
    assert_callback_error(response, 'login_required')
    with oidc._shared_state() as runtime:
        assert runtime['codes'] == {}


@pytest.mark.parametrize('session', ['guest', 'access', 'refresh'])
@pytest.mark.parametrize('freshness', [
    {'prompt': 'login'}, {'max_age': '0'}, {'max_age': '3600'},
    {'prompt': 'login', 'max_age': '0'}, {'prompt': 'none', 'max_age': '0'},
])
def test_freshness_requests_never_silently_issue_code(api, oidc, session, freshness):
    oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])
    if session == 'access':
        api.client.cookies.set('stella_at', api.owner_cookie)
    elif session == 'refresh':
        api.client.cookies.set('stella_rt', api.rt)
    response = api.client.get('/oauth/authorize', params=request_params(**freshness), follow_redirects=False)
    assert_callback_error(response, 'login_required')
    if session == 'refresh':
        cookies = response.headers.get_list('set-cookie')
        assert any(cookie.startswith('stella_at=') for cookie in cookies)
        assert any(cookie.startswith('stella_rt=') for cookie in cookies)
    with oidc._shared_state() as runtime:
        assert runtime['codes'] == {}  # refresh is not a new authentication


@pytest.mark.parametrize('params', [
    {'prompt': 'none login'}, {'prompt': 'none consent'}, {'prompt': 'none none'},
    {'prompt': 'unknown'}, {'max_age': ''}, {'max_age': '-1'},
    {'max_age': '+1'}, {'max_age': '1.5'}, {'max_age': 'abc'}, {'max_age': '１２'},
])
def test_malformed_prompt_and_max_age_return_callback_invalid_request(api, oidc, params):
    oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])
    api.client.cookies.set('stella_rt', api.rt)
    response = api.client.get('/oauth/authorize', params=request_params(**params), follow_redirects=False)
    assert_callback_error(response, 'invalid_request')
    cookies = response.headers.get_list('set-cookie')
    assert any(cookie.startswith('stella_at=') for cookie in cookies)
    assert any(cookie.startswith('stella_rt=') for cookie in cookies)
    with oidc._shared_state() as runtime:
        assert runtime['codes'] == {}


@pytest.mark.parametrize('prompt', ['consent', 'select_account', 'login consent'])
def test_unimplemented_interaction_is_not_silently_ignored(api, oidc, prompt):
    oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])
    api.client.cookies.set('stella_at', api.owner_cookie)
    response = api.client.get('/oauth/authorize', params=request_params(prompt=prompt), follow_redirects=False)
    assert_callback_error(response, 'interaction_required')
    with oidc._shared_state() as runtime:
        assert runtime['codes'] == {}


@pytest.mark.parametrize('params,error', [
    ({'scope': 'openid admin'}, 'invalid_scope'),
    ({'code_challenge': 'x' * 43, 'code_challenge_method': 'plain'}, 'invalid_request'),
    ({'code_challenge': 'short', 'code_challenge_method': 'S256'}, 'invalid_request'),
    ({'code_challenge': '', 'code_challenge_method': ''}, 'invalid_request'),
    ({'code_challenge_method': 'S256'}, 'invalid_request'),
    ({'response_type': 'token'}, 'unsupported_response_type'),
])
@pytest.mark.parametrize('state', [STATE, ''])
def test_downstream_protocol_errors_use_approved_callback_and_exact_state(api, oidc, params, error, state):
    oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])
    api.client.cookies.set('stella_rt', api.rt)
    response = api.client.get('/oauth/authorize', params=request_params(state=state, **params), follow_redirects=False)
    assert_callback_error(response, error, state=state)
    cookies = response.headers.get_list('set-cookie')
    assert any(cookie.startswith('stella_at=') for cookie in cookies)
    assert any(cookie.startswith('stella_rt=') for cookie in cookies)
    with oidc._shared_state() as runtime:
        assert runtime['codes'] == {}


@pytest.mark.parametrize('params,error', [
    ({'client_id': 'unknown'}, 'invalid_client'),
    ({'client_id': ''}, 'invalid_client'),
    ({'redirect_uri': 'https://evil.test/cb'}, 'invalid_request'),
    ({'redirect_uri': CALLBACK + '/extra'}, 'invalid_request'),
    ({'redirect_uri': CALLBACK + '?next=https://evil.test'}, 'invalid_request'),
    ({'redirect_uri': CALLBACK + '#fragment'}, 'invalid_request'),
    ({'redirect_uri': ''}, 'invalid_request'),
])
def test_untrusted_client_or_callback_errors_stay_local_and_preserve_refresh(api, oidc, params, error):
    oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])
    api.client.cookies.set('stella_rt', api.rt)
    # Even downstream errors must not redirect when client/URI trust fails.
    response = api.client.get('/oauth/authorize', params=request_params(scope='openid admin', prompt='none', **params), follow_redirects=False)
    assert response.status_code == 400 and response.json() == {'error': error}
    assert 'location' not in response.headers
    assert response.headers['cache-control'] == 'no-store'
    cookies = response.headers.get_list('set-cookie')
    assert any(cookie.startswith('stella_at=') for cookie in cookies)
    assert any(cookie.startswith('stella_rt=') for cookie in cookies)
    with oidc._shared_state() as runtime:
        assert runtime['codes'] == {}


def test_disabled_client_error_stays_local(api, oidc):
    oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])
    oidc.update_client('rp', {'enabled': False})
    response = api.client.get('/oauth/authorize', params=request_params(prompt='none'), follow_redirects=False)
    assert response.status_code == 400 and response.json() == {'error': 'invalid_client'}
    assert 'location' not in response.headers


@pytest.mark.parametrize('key,value', [('redirect_uri', 'https://evil.test/cb'), ('client_id', 'unknown'),
                                        ('state', 'other-state'), ('scope', 'openid admin')])
def test_duplicate_parameters_never_issue_code_or_redirect_and_keep_cookies(api, oidc, key, value):
    oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])
    api.client.cookies.set('stella_rt', api.rt)
    params = [*request_params().items(), (key, value)]
    response = api.client.get('/oauth/authorize', params=params, follow_redirects=False)
    assert response.status_code == 400 and response.json() == {'error': 'invalid_request'}
    assert 'location' not in response.headers
    cookies = response.headers.get_list('set-cookie')
    assert any(cookie.startswith('stella_at=') for cookie in cookies)
    assert any(cookie.startswith('stella_rt=') for cookie in cookies)
    with oidc._shared_state() as runtime:
        assert runtime['codes'] == {}


def test_missing_state_is_not_invented_on_callback_error(api, oidc):
    oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])
    params = request_params(scope='openid admin')
    params.pop('state')
    response = api.client.get('/oauth/authorize', params=params, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers['location'] == CALLBACK + '?error=invalid_scope'


@pytest.mark.parametrize('session', ['access', 'refresh'])
def test_prompt_none_with_existing_session_still_supports_s256(api, oidc, session):
    secret = oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])['client_secret']
    verifier = 'v' * 43
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    api.client.cookies.set('stella_at' if session == 'access' else 'stella_rt',
                           api.owner_cookie if session == 'access' else api.rt)
    response = api.client.get('/oauth/authorize', params=request_params(
        prompt='none', code_challenge=challenge, code_challenge_method='S256', nonce='exact-nonce'), follow_redirects=False)
    assert response.status_code == 307
    location = urlsplit(response.headers['location'])
    assert location.netloc == 'rp.test' and location.path == '/cb'
    params = parse_qs(location.query)
    assert params['state'] == [STATE] and 'error' not in params
    code = params['code'][0]
    assert oidc.exchange_code(code, 'rp', secret, CALLBACK, code_verifier='y' * 43) is None
    tokens = oidc.exchange_code(code, 'rp', secret, CALLBACK, code_verifier=verifier)
    assert tokens is not None
    from authlib.jose import jwt
    claims = jwt.decode(tokens['id_token'], oidc._get_key())
    assert claims['nonce'] == 'exact-nonce' and claims['sub'] == str(api.owner_id)


def test_authorize_does_not_suppress_real_owner_security_errors(api, oidc):
    oidc.create_client('rp', name='RP', redirect_uris=[CALLBACK])
    api.client.cookies.set('stella_at', api.foreign_cookie)
    response = api.client.get('/oauth/authorize', params=request_params(prompt='none'), follow_redirects=False)
    assert response.status_code == 403
    assert 'location' not in response.headers
    with oidc._shared_state() as runtime:
        assert runtime['codes'] == {}
