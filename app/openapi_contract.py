"""OpenAPI-only contract decoration. No business imports or request-time hooks."""
import warnings
from copy import deepcopy
from dataclasses import dataclass

from fastapi.routing import APIRoute, iter_route_contexts
from app.api_response_contracts import decorate_response, response_contract_errors, response_components

HTTP_METHODS = frozenset({'get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'})

SECURITY_SCHEMES = {
    'StellaAccessCookie': {'type': 'apiKey', 'in': 'cookie', 'name': 'stella_at',
        'description': 'HttpOnly access-session cookie issued by Stella login; not an API key to paste into a header.'},
    'StellaAgentBearer': {'type': 'http', 'scheme': 'bearer',
        'description': 'Agent credential; not a browser session or OIDC access token.'},
    'StellaAgentQueryLegacy': {'type': 'apiKey', 'in': 'query', 'name': 'token',
        'description': 'Legacy agent compatibility ONLY when Authorization is absent. Prefer Bearer; query credentials can leak in URLs.'},
    'StellaRefreshCookie': {'type': 'apiKey', 'in': 'cookie', 'name': 'stella_rt',
        'description': 'HttpOnly rotating refresh cookie issued by login; not an access cookie.'},
    'StellaOIDCClientBasic': {'type': 'http', 'scheme': 'basic',
        'description': 'Registered confidential OIDC client ID/secret (client_secret_basic); not the owner login password.'},
    'StellaOIDCAccessBearer': {'type': 'http', 'scheme': 'bearer',
        'description': 'OIDC access token issued by /oauth/token, accepted by /oauth/userinfo only; not an agent token.'},
}


@dataclass(frozen=True)
class AuthPolicy:
    auth_type: str
    schemes: tuple[str, ...] = ()  # alternatives (OR), not cumulative requirements
    optional: bool = False
    elevation: str = 'none'
    detail: str = ''


ACCESS = AuthPolicy('cookie-access', ('StellaAccessCookie',))
ADMIN = AuthPolicy('cookie-access', ('StellaAccessCookie',),
    detail='Active pinned owner and persisted nonrevoked, unexpired access session. '
           'No separate management password or grant. Not the legacy is_admin flag.')
AGENT = AuthPolicy('agent-bearer', ('StellaAgentBearer', 'StellaAgentQueryLegacy'),
    detail='Authorization is authoritative; malformed/present headers never fall back to query token. '
           'The endpoint/service validates the extracted node credential.')
UNKNOWN = AuthPolicy('unclassified', detail='No reviewed authentication policy. Contract validation must fail; not evidence of public access.')


@dataclass(frozen=True)
class AuthOverride:
    endpoint: str
    dependencies: frozenset[str]
    policy: AuthPolicy


DB = frozenset({'app.database.get_db'})
OPTIONAL_SESSION = AuthPolicy('optional-cookie', ('StellaAccessCookie', 'StellaRefreshCookie'), optional=True,
    detail='No session is required to reach this endpoint; presented access or refresh cookies may identify a session.')

# Deliberately exact method + OpenAPI path + callable + dependency signature.
# No prefix wildcards, no "no Depends means public", no old auth-overrides.json.
AUTH_OVERRIDES: dict[tuple[str, str], AuthOverride] = {}


def _override(method, path, endpoint, policy, dependencies=DB):
    AUTH_OVERRIDES[(method, path)] = AuthOverride(endpoint, dependencies, policy)


for _method, _path, _endpoint, _detail, _deps in (
    ('GET', '/homebg/media', 'app.routers.homebg.get_media', 'Public metadata for already-public local backgrounds.', DB),
    ('GET', '/auth/status', 'app.routers.auth.status', 'Public initialization/email-service status.', DB),
    ('POST', '/auth/register', 'app.routers.auth.register', 'Anonymous bootstrap only on a genuinely empty installation; returns 403 after initialization.', DB),
    ('POST', '/auth/login', 'app.routers.auth.login', 'Login credentials in JSON body; issues HttpOnly cookies. No pre-existing API-key or bearer token.', DB),
    ('POST', '/auth/forgot', 'app.routers.auth.forgot_password', 'Recovery initiation; no authenticated session required.', DB),
    ('POST', '/auth/login-code/send', 'app.routers.auth.send_login_code', 'Send code to verified owner email; no session required.', DB),
    ('POST', '/auth/login-code', 'app.routers.auth.login_by_code', 'Verified email/code in JSON body establishes session cookies; no pre-existing token.', DB),
    ('POST', '/auth/reset', 'app.routers.auth.reset_password', 'Recovery code in JSON body is required; no existing session cookie.', DB),
    ('GET', '/auth/invites', 'app.routers.auth.retired_invitation_api', 'Unconditionally retired: HTTP 410, not an invitation facility.', frozenset()),
    ('POST', '/auth/invites', 'app.routers.auth.retired_invitation_api', 'Unconditionally retired: HTTP 410.', frozenset()),
    ('POST', '/auth/register-invite', 'app.routers.auth.retired_invitation_api', 'Unconditionally retired: HTTP 410.', frozenset()),
    ('GET', '/agent/script', 'app.routers.monitor.agent_script', 'Public credential-free agent program.', frozenset()),
    ('GET', '/agent/version', 'app.routers.monitor.agent_version', 'Public agent version/manifest.', frozenset()),
    ('GET', '/agent/release', 'app.routers.monitor.agent_release', 'Public credential-free source metadata only; no-store; not an updater instruction.', frozenset()),
    ('GET', '/agent/install.sh', 'app.routers.monitor.agent_install_sh', 'Public credential-free installer.', frozenset()),
    ('GET', '/agent/install.ps1', 'app.routers.monitor.agent_install_ps1', 'Public credential-free installer.', frozenset()),
    ('GET', '/agent/run-agent.ps1', 'app.routers.monitor.agent_run_ps1', 'Public credential-free task entry point.', frozenset()),
    ('GET', '/agent/hardware-sensors.ps1', 'app.routers.monitor.agent_hardware_sensors_ps1', 'Public credential-free hardware bridge.', frozenset()),
    ('GET', '/config/site-background', 'app.routers.config.get_site_background', 'Public owner background URL for the login page.', DB),
    ('GET', '/.well-known/openid-configuration', 'app.routers.oidc.openid_configuration', 'Public OIDC discovery; host/issuer validation still applies.', frozenset()),
    ('GET', '/oauth/jwks', 'app.routers.oidc.jwks', 'Public signing keys only.', frozenset()),
):
    _override(_method, _path, _endpoint, AuthPolicy('anonymous', detail=_detail), _deps)

for _kind, _endpoint in [('homebg', 'background_asset'), ('avatars', 'avatar_asset')]:
    for _method in ('GET', 'HEAD'):
        _override(_method, '/assets/' + _kind + '/{filename}', 'app.routers.dynamic_assets.' + _endpoint,
                  AuthPolicy('anonymous', detail='Compatibility URL for already-public uploaded media.'))

_override('POST', '/auth/refresh', 'app.routers.auth.refresh',
          AuthPolicy('cookie-refresh', ('StellaRefreshCookie',), detail='Requires valid rotating refresh cookie; access cookie alone is insufficient.'))
_override('POST', '/auth/logout', 'app.routers.auth.logout', OPTIONAL_SESSION)
_override('GET', '/agent/files/config', 'app.routers.node_files.config',
          AuthPolicy('agent-bearer', ('StellaAgentBearer',),
                     detail='Bearer node credential only; query-only tokens and browser cookies are rejected. '
                            'Read-only existing authority; Cache-Control: no-store. Other Agent routes retain legacy compatibility.'),
          DB | {'app.security.agent_token'})
_override('POST', '/auth/email/resend', 'app.routers.auth.resend_code',
          AuthPolicy('conditional-cookie', ('StellaAccessCookie',), optional=True,
                     detail='purpose=bind requires current_user/access cookie; login/reset do not require a session, but validate the verified owner email.'))
_override('GET', '/oauth/authorize', 'app.routers.oidc.authorize',
          AuthPolicy('optional-cookie', ('StellaAccessCookie', 'StellaRefreshCookie'), optional=True,
                     detail='Try access session then rotating refresh. Without a session: login redirect or OIDC login_required; NEVER issue an anonymous authorization code. Client and exact redirect URI are validated first.'),
          DB | {'app.routers.oidc._optional_user'})
_override('POST', '/oauth/token', 'app.routers.oidc.token',
          AuthPolicy('oidc-client', ('StellaOIDCClientBasic',), optional=True,
                     detail='Client authentication is mandatory: client_secret_basic OR client_secret_post form fields. OpenAPI cannot encode form-body security schemes; the empty security alternative represents required body credentials, NOT anonymous access. Never send both methods.'), frozenset())
_override('GET', '/oauth/userinfo', 'app.routers.oidc.userinfo',
          AuthPolicy('oidc-userinfo', ('StellaOIDCAccessBearer',)), frozenset())
_override('GET', '/website-assets/{mid}.js', 'app.routers.website_settings.website_asset',
          AuthPolicy('optional-cookie', ('StellaAccessCookie',), optional=True,
                     detail='Public safe asset baseline; valid persisted owner/access session enables custom code. Invalid/absent session does not expose custom code.'))

for _method in ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'):
    _override(_method, '/drive/openlist/{path}', 'app.routers.drive.openlist_proxy',
              AuthPolicy('cookie-access', ('StellaAccessCookie',),
                         elevation='none',
                         detail='Access session always required. OPTIONS returns locally; other methods apply '
                                'app.services.openlist_access.management_required(method, path), then admin_user '
                                'to revalidate the same owner/session for management paths/unsafe writes; no second password. '
                                'Read-only POST allowlist is not blanket POST permission.'),
              DB | {'app.routers.auth.current_user', 'app.routers.legacy_guard.legacy_available'})

for _method, _path, _endpoint, _elevation, _detail in (
    ('PUT', '/auth/security', 'update_security', 'none', 'Retired: authenticated owner receives HTTP 410; no credential or policy mutation.'),
    ('POST', '/auth/admin/password', 'change_management_password', 'none', 'Retired: authenticated owner receives HTTP 410; no password mutation.'),
    ('POST', '/auth/admin/setup', 'admin_setup', 'none', 'Retired: authenticated owner receives HTTP 410; no second password creation.'),
    ('POST', '/auth/admin/unlock', 'admin_unlock', 'none', 'Retired: authenticated owner receives HTTP 410; old hashes cannot grant access.'),
):
    _override(_method, _path, 'app.routers.auth.' + _endpoint,
              AuthPolicy('cookie-access', ('StellaAccessCookie',), elevation=_elevation, detail=_detail),
              DB | {'app.routers.auth.current_user'})


def callable_name(call) -> str:
    return f"{getattr(call, '__module__', '')}.{getattr(call, '__qualname__', '')}"


def dependency_names(dependant) -> frozenset[str]:
    """Walk every Depends/Security branch without executing it; tolerate sharing/cycles."""
    names, seen = set(), set()
    stack = list(dependant.dependencies)
    while stack:
        dep = stack.pop()
        if id(dep) in seen:
            continue
        seen.add(id(dep))
        names.add(callable_name(dep.call))
        stack.extend(dep.dependencies)
    return frozenset(names)


def classify_auth(method: str, path: str, endpoint: str, dependencies: frozenset[str]) -> AuthPolicy:
    override = AUTH_OVERRIDES.get((method.upper(), path))
    if override is not None:
        return override.policy if endpoint == override.endpoint and dependencies == override.dependencies else UNKNOWN
    if 'app.security.agent_token' in dependencies:
        if dependencies & {'app.routers.auth.current_user', 'app.routers.auth.admin_user', 'app.routers.oidc._optional_user'}:
            return UNKNOWN
        return AGENT
    if 'app.routers.auth.admin_user' in dependencies:
        return ADMIN
    if 'app.routers.auth.current_user' in dependencies:
        return ACCESS
    return UNKNOWN


class ContractError(ValueError):
    """A release/CI contract failure, never an HTTP authentication exception."""


def validate_contract(app, *, require_all_overrides: bool = False, require_complete_responses: bool = False):
    """Explicit fail-closed release gate. Schema generation itself remains available.

    Use require_all_overrides=True for the complete Stella mounted API inventory;
    leave it False for intentionally partial isolated apps.
    """
    schema = app.openapi()
    seen, ids, errors = set(), set(), []
    for context in iter_route_contexts(app.routes):
        if not isinstance(context.original_route, APIRoute) or not context.include_in_schema:
            continue
        for method in sorted(context.methods):
            key = (method, context.path_format)
            label = f'{method} {context.path_format}'
            if key in seen:
                errors.append(f'duplicate route: {label}')
            seen.add(key)
            policy = classify_auth(method, context.path_format, callable_name(context.endpoint),
                                   dependency_names(context.dependant))
            if policy.auth_type == 'unclassified':
                errors.append(f'{label}: unclassified authentication (missing or stale review)')
            operation = schema.get('paths', {}).get(context.path_format, {}).get(method.lower(), {})
            errors.extend(f'{label}: {error}' for error in response_contract_errors(
                operation, method, context.path_format, callable_name(context.endpoint),
                require_complete=require_complete_responses))
            expected_id = operation_id(method, context.path_format)
            actual_id = operation.get('operationId')
            if actual_id != expected_id or actual_id in ids:
                errors.append(f'{label}: missing, unstable or duplicate operationId')
            ids.add(actual_id)
            expected = {}
            decorate_auth(expected, policy)
            if any(operation.get(k) != value for k, value in expected.items()):
                errors.append(f'{label}: authentication metadata differs from reviewed policy')
            schemes = schema.get('components', {}).get('securitySchemes', {})
            for name in policy.schemes:
                if schemes.get(name) != SECURITY_SCHEMES[name]:
                    errors.append(f'{label}: missing or incorrect security scheme {name}')
    if any(operation.get('x-stella-contract-status') in {'reviewed', 'incomplete', 'passthrough'}
           for item in schema.get('paths', {}).values() for method, operation in item.items() if method in HTTP_METHODS):
        for name, value in response_components().items():
            if schema.get('components', {}).get('schemas', {}).get(name) != value:
                errors.append('response component missing or changed: ' + name)
    if require_all_overrides:
        for method, path in sorted(set(AUTH_OVERRIDES) - seen):
            errors.append(f'stale override: {method} {path} is not mounted')
    if errors:
        raise ContractError('\n'.join(errors))
    return schema


def decorate_auth(operation, policy: AuthPolicy):
    operation['x-stella-auth-type'] = policy.auth_type
    operation['x-stella-elevation'] = policy.elevation
    operation['x-stella-auth-detail'] = policy.detail
    if policy.auth_type == 'oidc-client':
        operation['x-stella-client-auth'] = {
            'required': True, 'methods': ['client_secret_basic', 'client_secret_post'],
            'body-content-type': 'application/x-www-form-urlencoded',
            'body-credentials': ['client_id', 'client_secret'],
            'anonymous-allowed': False,
        }
    if policy is UNKNOWN:
        return
    operation['security'] = ([{}] if policy.optional else []) + [{name: []} for name in policy.schemes]


def operation_id(method: str, path: str) -> str:
    """Injective ASCII identifier for the exact OpenAPI method/path pair (v1)."""
    encoded = ''.join(chr(b) if 48 <= b <= 57 or 65 <= b <= 90 or 97 <= b <= 122
                      else f'_{b:02x}' for b in path.encode('utf-8'))
    return f'stella_{method.lower()}_{encoded}'


def install_openapi_contract(app):
    """Decorate schema output only; retain FastAPI's route-version-aware cache."""
    original_openapi = app.openapi

    def openapi():
        # FastAPI gives one ID to all methods on a route. All resulting path
        # operation IDs are replaced below, so suppress only this known warning.
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', message='Duplicate Operation ID .*',
                                    category=UserWarning, module='fastapi.openapi.utils')
            schema = original_openapi()
        for path, item in schema.get('paths', {}).items():
            for method, operation in item.items():
                if method in HTTP_METHODS:
                    operation['operationId'] = operation_id(method, path)
        schema.setdefault('components', {}).setdefault('securitySchemes', {}).update(deepcopy(SECURITY_SCHEMES))
        for context in iter_route_contexts(app.routes):
            if not isinstance(context.original_route, APIRoute) or not context.include_in_schema:
                continue
            names = dependency_names(context.dependant)
            for method in context.methods:
                operation = schema['paths'][context.path_format][method.lower()]
                policy = classify_auth(method, context.path_format, callable_name(context.endpoint), names)
                decorate_auth(operation, policy)
                operation['x-stella-auth-dependencies'] = sorted(names)
                decorate_response(operation, method, context.path_format, callable_name(context.endpoint), document=schema)
        return schema

    app.openapi = openapi
