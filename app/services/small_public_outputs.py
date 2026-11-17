"""Read-only, endpoint-scoped projections of legacy public values.

Never stringify containers, mutate stored state, or pass unknown keys through.
"""
import json
import re
from datetime import datetime
from uuid import UUID
from typing import Literal, TypeGuard
from urllib.parse import urlsplit
from base64 import urlsafe_b64decode, urlsafe_b64encode

from pydantic import BaseModel, ConfigDict


def _public_text(value: object) -> TypeGuard[str]:
    if not isinstance(value, str):
        return False
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


class PublicSMTPConfig(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')

    host: str | None
    port: int | None
    username: str | None
    password: str
    from_name: str | None
    enabled: bool | None


def public_smtp_config(stored: object, defaults: dict) -> PublicSMTPConfig:
    if not isinstance(stored, dict):
        raise ValueError('invalid SMTP configuration')
    values = {key: stored.get(key, defaults[key]) for key in
              ('host', 'port', 'username', 'password', 'from_name', 'enabled')}
    for key in ('host', 'username', 'from_name'):
        if not _public_text(values[key]):
            values[key] = None
    if type(values['port']) is not int or not 1 <= values['port'] <= 65535:
        values['port'] = None
    if type(values['enabled']) is not bool:
        values['enabled'] = None
    values['password'] = '••••••' if values['password'] else ''
    return PublicSMTPConfig(**values)


class PublicRSAJWK(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')

    kty: Literal['RSA']
    n: str
    e: str
    kid: str
    alg: Literal['RS256']
    use: Literal['sig']


class PublicJWKS(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')

    keys: list[PublicRSAJWK]


def public_signing_jwk(stored: object, *, kid: str) -> PublicRSAJWK:
    from authlib.jose import RSAKey

    # Discovery and the real signer ONLY support RS256. Do not advertise EC
    # (crv/x/y), OKP (crv/x), oct (k), or pretend their algorithms are RS256.
    if not isinstance(stored, dict) or stored.get('kty') != 'RSA':
        raise ValueError('unsupported signing key type')
    if stored.get('alg', 'RS256') != 'RS256' or stored.get('use', 'sig') != 'sig':
        raise ValueError('unsupported signing key purpose')
    if 'key_ops' in stored:
        operations = stored['key_ops']
        if (not isinstance(operations, list) or 'sign' not in operations
                or any(op not in ('sign', 'verify') for op in operations)):
            raise ValueError('unsupported signing key operations')
    if 'kid' in stored and (not _public_text(stored['kid']) or not stored['kid']):
        raise ValueError('invalid key identifier')
    for field in ('n', 'e'):
        _jwk_uint(stored.get(field))
    # Validate actual key material, not just the shape of Authlib's lazy dict.
    material = {field: stored[field] for field in
                ('kty', 'n', 'e', 'd', 'p', 'q', 'dp', 'dq', 'qi') if field in stored}
    for field in ('d', 'p', 'q', 'dp', 'dq', 'qi'):
        if field in material:
            _jwk_uint(material[field])
    key = RSAKey.import_key(material)
    key.get_public_key()
    if 'd' in material:
        key.get_private_key()
    # Authlib overrides the signer's header kid with a provisioned key.kid.
    # Only absent kid metadata uses the existing fixed header fallback.
    return PublicRSAJWK(kty='RSA', n=stored['n'], e=stored['e'],
                        kid=stored.get('kid', kid), alg='RS256', use='sig')


def _jwk_uint(value: object) -> None:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('invalid key integer')
    raw = urlsafe_b64decode(value + '=' * (-len(value) % 4))
    if (not raw or raw[0] == 0
            or urlsafe_b64encode(raw).rstrip(b'=').decode('ascii') != value):
        raise ValueError('invalid key integer')


class PublicAuditEvent(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')

    timestamp: str | None
    action: str | None
    actor_id: str | None
    resource_id: str | None
    changed_fields: list[str] | None


class PublicChangeAudit(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')

    events: list[PublicAuditEvent]
    limit: int


def public_audit_event(stored: dict) -> PublicAuditEvent:
    from app.services.backup_health import AUDIT_FIELDS

    # Missing/malformed legacy fields are unknown, never invented timestamps,
    # identities, actions or a claim that nothing changed.
    stamp = stored.get('timestamp')
    try:
        if not _public_text(stamp) or datetime.fromisoformat(stamp).tzinfo is None:
            stamp = None
    except ValueError:
        stamp = None
    action = stored.get('action')
    if not isinstance(action, str) or not re.fullmatch(r'[a-z][a-z0-9_.]{0,63}', action):
        action = None
    fields = stored.get('changed_fields')
    if not isinstance(fields, list) or any(not isinstance(f, str) or f not in AUDIT_FIELDS for f in fields):
        fields = None
    return PublicAuditEvent(timestamp=stamp, action=action,
                            actor_id=_public_uuid(stored.get('actor_id')),
                            resource_id=_public_uuid(stored.get('resource_id')),
                            changed_fields=fields)


def _public_uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        UUID(value)
    except ValueError:
        return None
    return value


def public_avatar_history(stored: object) -> list[str]:
    try:
        values = json.loads(stored) if isinstance(stored, str) else None
    except (ValueError, RecursionError):
        return []
    if not isinstance(values, list):
        return []
    return [value for value in values if _avatar_url(value)]


def _avatar_url(value: object) -> bool:
    if not _public_text(value) or not value or re.search(r'[\s\\\x00-\x1f\x7f]', value):
        return False
    if value.startswith('/') and not value.startswith('//'):
        return True
    try:
        url = urlsplit(value)
        url.port  # Force validation; urlsplit alone accepts malformed ports.
        return (url.scheme in ('http', 'https') and bool(url.hostname)
                and url.username is None and url.password is None)
    except ValueError:
        return False
