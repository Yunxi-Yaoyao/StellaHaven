"""Owner/elevation-gated management for Stella's native OIDC provider.

Client secrets appear only on creation, explicit rotation or gated POST reveal.
Ordinary configuration/list/detail reads never include credentials.
No issuer edits, signing keys or external discovery/network fetches are exposed.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from app.validation_errors import validation_error_response

from app.routers.auth import admin_user, current_user
from app.database import get_db
from sqlalchemy.orm import Session
from app.services import oidc


class PrivateValidationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                response = await handler(request)
            except RequestValidationError as exc:
                response = validation_error_response(request, exc)
            except HTTPException as exc:
                from fastapi.exception_handlers import http_exception_handler
                response = await http_exception_handler(request, exc)
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Pragma'] = 'no-cache'
            return response
        return private_handler


router = APIRouter(prefix='/auth/provider', tags=['auth-provider'],
                   dependencies=[Depends(admin_user)], route_class=PrivateValidationRoute)


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    client_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    enabled: StrictBool = True
    redirect_uris: list[str] = Field(min_length=1, max_length=32)
    scopes: list[str] = Field(default_factory=lambda: list(oidc.SUPPORTED_SCOPES))
    generate_secret: Literal[True] = True


class ClientPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: StrictBool | None = None
    redirect_uris: list[str] | None = Field(default=None, min_length=1, max_length=32)
    scopes: list[str] | None = None


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except KeyError:
        raise HTTPException(404, 'unknown client') from None
    except ValueError as exc:
        message = str(exc)  # service errors are fixed strings, never secrets/input
        raise HTTPException(409 if message == 'client already exists' else 400, message) from None


@router.get('/config')
def provider_config(request: Request):
    issuer = oidc.resolve_issuer(request.headers.get('host', ''))
    discovery = oidc.openid_configuration(issuer)
    return {**{k: discovery[k] for k in ('issuer', 'authorization_endpoint', 'token_endpoint', 'userinfo_endpoint', 'jwks_uri')},
            'discovery_url': issuer + '/.well-known/openid-configuration',
            'clients': oidc.list_clients(),
            'capabilities': {
                'grant_types_supported': ['authorization_code'],
                'token_endpoint_auth_methods_supported': ['client_secret_basic', 'client_secret_post'],
                'code_challenge_methods_supported': ['S256'],
                'scopes_supported': list(oidc.SUPPORTED_SCOPES),
                'secret_reveal': True,
            }}


@router.get('/clients')
def clients():
    return oidc.list_clients()


@router.get('/clients/{client_id}')
def client(client_id: str):
    for item in oidc.list_clients():
        if item['client_id'] == client_id:
            return item
    raise HTTPException(404, 'unknown client')


@router.post('/clients', status_code=201)
def create(data: ClientCreate):
    return _call(oidc.create_client, **data.model_dump(exclude={'generate_secret'}))


@router.patch('/clients/{client_id}')
def update(client_id: str, data: ClientPatch):
    return _call(oidc.update_client, client_id, data.model_dump(exclude_unset=True))


class ClientSecretReveal(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    client_id: str
    client_secret: str = Field(repr=False)


def _reveal_origin(request: Request):
    from urllib.parse import urlsplit
    from app.services.request_security import trusted_origins
    origins = request.headers.getlist('origin')
    # Sensitive reads require a singleton exact browser Origin, including for
    # CLI callers. Never trust Forwarded, query, Referer or sibling entry hosts.
    if (len(origins) != 1 or origins[0] not in trusted_origins()
            or urlsplit(origins[0]).netloc != request.headers.get('host', '').lower()):
        raise HTTPException(403, '密钥查看需要同源请求')


@router.post('/clients/{client_id}/reveal-secret', response_model=ClientSecretReveal,
             dependencies=[Depends(_reveal_origin)])
def reveal(client_id: str, request: Request, user=Depends(admin_user), db: Session = Depends(get_db)):
    def authorize():
        # Grants and session may change while waiting for a concurrent rotation.
        db.expire_all()
        admin_user(request, current_user(request, db), db)
    result = _call(oidc.reveal_client_secret, client_id, authorize=authorize)
    import logging
    logging.getLogger(__name__).info('oidc.client.secret_reveal',
        extra={'action': 'oidc.client.secret_reveal', 'client_id': client_id, 'actor_id': str(user.id)})
    return result


@router.post('/clients/{client_id}/rotate-secret')
def rotate(client_id: str):
    return _call(oidc.rotate_client_secret, client_id)


@router.delete('/clients/{client_id}')
def delete(client_id: str):
    _call(oidc.delete_client, client_id)
    return {'ok': True}
