"""Public Stella OIDC endpoints; management lives in auth_provider."""
import base64
import binascii
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, unquote_plus

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import get_db
from app.services import oidc as oidc_svc
from app.models.user import User
from app.routers import auth as auth_mod
from app.routers.auth import current_user

router = APIRouter(tags=['oidc'])
PRIVATE_HEADERS = {'Cache-Control': 'no-store', 'Pragma': 'no-cache'}


def _host_issuer(request: Request) -> str:
    return oidc_svc.resolve_issuer(request.headers.get('host', ''))


@dataclass(frozen=True)
class OIDCPrincipal:
    id: str
    username: str
    email: str
    session_id: str | None = None


def _optional_user(request: Request, response: Response, db: Session = Depends(get_db)):
    """Resolve auth, snapshot scalar claims, then release before provider SQL.

    Refresh commits its own token rotation. Rollback here releases only any
    remaining read transaction; returning an ORM object would expire/reacquire it.
    """
    try:
        try:
            user = current_user(request, db)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
            try:
                user = auth_mod.rotate_refresh(request, response, db)
            except HTTPException as refresh_exc:
                if refresh_exc.status_code != 401:
                    raise
                return None
        session = getattr(request.state, 'auth_session', None)
        return OIDCPrincipal(id=str(user.id), username=user.username, email=user.email or '',
                             session_id=str(session.id) if session is not None else None)
    finally:
        db.rollback()


def _with_cookies(result, injected_response):
    # Returning a Response bypasses FastAPI's injected-response cookie merge.
    if injected_response is not None:
        result.raw_headers.extend((key, value) for key, value in injected_response.raw_headers
                                  if key.lower() == b'set-cookie')
    return result


def _error(error, status=400, injected_response=None):
    headers = dict(PRIVATE_HEADERS)
    if status == 401:
        headers['WWW-Authenticate'] = 'Basic realm="Stella OIDC"' if error == 'invalid_client' else 'Bearer'
    return _with_cookies(JSONResponse({'error': error}, status_code=status, headers=headers), injected_response)


def _redirect(url, injected_response):
    return _with_cookies(RedirectResponse(url, headers=PRIVATE_HEADERS), injected_response)


def _callback(redirect_uri, params, state, response):
    if state is not None:
        params['state'] = state
    sep = '&' if '?' in redirect_uri else '?'
    return _redirect(f'{redirect_uri}{sep}{urlencode(params)}', response)


@router.get('/.well-known/openid-configuration')
def openid_configuration(request: Request):
    return oidc_svc.openid_configuration(_host_issuer(request))


@router.get('/oauth/jwks')
def jwks():
    return oidc_svc.jwks()


@router.get('/oauth/authorize')
def authorize(request: Request, response: Response, response_type: str = '', client_id: str = '',
              redirect_uri: str = '', scope: str = 'openid', state: str = '', nonce: str = '',
              code_challenge: str | None = None, code_challenge_method: str | None = None,
              prompt: str = '', max_age: str | None = None,
              user: OIDCPrincipal | None = Depends(_optional_user)):
    issuer = _host_issuer(request)
    if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        return _error('invalid_request', injected_response=response)
    client = oidc_svc._get_client(client_id)
    # Never send an error (or state) to an untrusted callback. Establish the
    # registered client and exact URI before validating downstream parameters.
    if not client or not client.get('enabled', True):
        return _error('invalid_client', injected_response=response)
    if redirect_uri not in client.get('redirect_uris', []):
        return _error('invalid_request', injected_response=response)
    callback_state = request.query_params.get('state')
    if not response_type:
        return _callback(redirect_uri, {'error': 'invalid_request'}, callback_state, response)
    try:
        scope = oidc_svc.validate_authorization(client, redirect_uri, scope, code_challenge, code_challenge_method)
    except ValueError as exc:
        error = str(exc)
        return _callback(redirect_uri, {'error': error}, callback_state, response)
    if response_type != 'code':
        return _callback(redirect_uri, {'error': 'unsupported_response_type'}, callback_state, response)
    prompts = prompt.split()
    if (len(prompts) != len(set(prompts))
            or any(value not in {'none', 'login', 'consent', 'select_account'} for value in prompts)
            or ('none' in prompts and len(prompts) != 1)
            or (max_age is not None and not (max_age.isascii() and max_age.isdecimal()))):
        return _callback(redirect_uri, {'error': 'invalid_request'}, callback_state, response)
    if 'consent' in prompts or 'select_account' in prompts:
        return _callback(redirect_uri, {'error': 'interaction_required'}, callback_state, response)
    # No bound reauthentication ceremony/auth_time is implemented yet. Never
    # treat an access session or refresh rotation as proof of fresh login, or
    # issue an ID token claiming max_age was honored without that evidence.
    if 'login' in prompts or max_age is not None:
        return _callback(redirect_uri, {'error': 'login_required'}, callback_state, response)
    if user is None:
        if 'none' in prompts:
            return _callback(redirect_uri, {'error': 'login_required'}, callback_state, response)
        from app.services.entry_registry import browser_origin
        entry = browser_origin(request.headers.get('host', ''), issuer)
        return _redirect(f"{entry}/login?{urlencode({'next': str(request.url)})}", response)
    try:
        code = oidc_svc.create_authorization_code(
            client_id=client_id, redirect_uri=redirect_uri,
            user_id=str(user.id), username=user.username, email=user.email or '',
            nonce=nonce or None, issuer=issuer, scope=scope,
            code_challenge=code_challenge, code_challenge_method=code_challenge_method,
            session_id=user.session_id)
    except ValueError as exc:
        return _callback(redirect_uri, {'error': 'invalid_request' if str(exc) == 'invalid_redirect_uri' else str(exc)}, callback_state, response)
    return _callback(redirect_uri, {'code': code}, callback_state, response)


@router.post('/oauth/token')
async def token(request: Request):
    form = await request.form()
    return await run_in_threadpool(_token_response, form, request.headers.get('authorization'))


def _token_response(form, auth):
    # SQL row locks and signing are synchronous; keep them off the event loop.
    if any(len(form.getlist(key)) != 1 for key in form):
        return _error('invalid_request')
    if form.get('grant_type') != 'authorization_code':
        return _error('unsupported_grant_type')
    if auth is not None:
        if 'client_id' in form or 'client_secret' in form:
            return _error('invalid_client', 401)
        try:
            method, encoded = auth.split(' ', 1)
            if method.lower() != 'basic':
                raise ValueError('invalid method')
            decoded = base64.b64decode(encoded, validate=True).decode('utf-8')
            client_id, client_secret = decoded.split(':', 1)
            client_id, client_secret = unquote_plus(client_id), unquote_plus(client_secret)
        except (ValueError, UnicodeError, binascii.Error):
            return _error('invalid_client', 401)
    else:
        client_id, client_secret = form.get('client_id'), form.get('client_secret')
    if not isinstance(client_id, str) or not client_id or not isinstance(client_secret, str) or not client_secret:
        return _error('invalid_client', 401)
    # Do not call get_client_secret: public requests must never register clients.
    client = oidc_svc._get_client(client_id)
    if (not client or not client.get('enabled', True) or not client.get('client_secret')
            or not secrets.compare_digest(client_secret.encode(), client['client_secret'].encode())):
        return _error('invalid_client', 401)
    code, uri, verifier = form.get('code'), form.get('redirect_uri'), form.get('code_verifier')
    if not isinstance(code, str) or not isinstance(uri, str) or (verifier is not None and not isinstance(verifier, str)):
        return _error('invalid_request')
    result = oidc_svc.exchange_code(code, client_id, client_secret, uri, code_verifier=verifier)
    return _error('invalid_grant') if result is None else JSONResponse(result, headers=PRIVATE_HEADERS)


@router.get('/oauth/userinfo')
def userinfo(request: Request):
    parts = request.headers.get('Authorization', '').split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return _error('invalid_token', 401)
    info = oidc_svc.userinfo(parts[1])
    return _error('invalid_token', 401) if info is None else JSONResponse(info, headers=PRIVATE_HEADERS)
