"""Scoped owner-facing website projections; never mutate stored configuration.

Unknown properties have no public extension contract. Code is owner content,
not a credential: CSS/JS and version provenance are deliberately preserved.
Malformed known values use typed conservative fallbacks and an explicit
incomplete marker containing *only schema paths*, never rejected input.
"""
from copy import deepcopy
from typing import Annotated, Literal, get_args
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


def _url(value: str) -> str:
    if not value:
        return value
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            '\\' in value or any(ord(c) < 33 or ord(c) == 127 for c in value)):
        raise ValueError('invalid public URL')
    _ = parsed.port
    return value


def _path(value: str) -> str:
    if not value.startswith('/') or value.startswith('//') or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('invalid local path')
    return value


def _policy_path(value: str) -> str:
    import re
    if not re.fullmatch(r'/[A-Za-z0-9_./~-]*', value) or '//' in value or any(p in {'.', '..'} for p in value.split('/')):
        raise ValueError('invalid permission path')
    return value  # projection does not rewrite valid stored spelling/order


def _code(value: str, limit: int) -> str:
    if '\x00' in value or len(value.encode('utf-8')) > limit:
        raise ValueError('invalid owner code')
    return value


URL = Annotated[str, AfterValidator(_url)]
LocalPath = Annotated[str, AfterValidator(_path)]
PolicyPath = Annotated[str, Field(max_length=256), AfterValidator(_policy_path)]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')]


class PublicRecord(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ProjectionStatus(PublicRecord):
    state: Literal['incomplete'] = 'incomplete'
    invalid_fields: list[str]


class PublicConnection(PublicRecord):
    transport: Literal['auto', 'proxy', 'direct'] = 'auto'
    auth_mode: Literal['original', 'header', 'oidc'] = 'original'
    header_name: Literal['Authorization', 'X-API-Key', 'X-Auth-Token'] = 'Authorization'
    injection_delivery: Literal['proxy', 'loader'] = 'proxy'
    has_token: bool = False


class PublicRequestPolicy(PublicRecord):
    management_prefixes: list[PolicyPath] = Field(default_factory=list, max_length=64)
    read_post_paths: list[PolicyPath] = Field(default_factory=list, max_length=64)
    protect_other_writes: bool = False


class PublicInjectionVersion(PublicRecord):
    enabled: bool = False
    css: Annotated[str, AfterValidator(lambda v: _code(v, 65536))] = ''
    js: Annotated[str, AfterValidator(lambda v: _code(v, 131072))] = ''
    timing: Literal['dom_ready', 'document_start'] = 'dom_ready'
    csp_policy: Literal['reject', 'controlled'] = 'reject'
    version: str = ''
    source_origin: URL = ''


class PublicInjectionVersions(PublicRecord):
    draft: PublicInjectionVersion | None = None
    active: PublicInjectionVersion | None = None
    previous: PublicInjectionVersion | None = None
    projection: ProjectionStatus | None = None


class PublicCapabilities(PublicRecord):
    injection: bool = False
    browser_status: Literal['unobservable'] = 'unobservable'
    managed_settings: str | None = None


class PublicModule(PublicRecord):
    id: Identifier = 'unavailable'
    name: Name = '配置不完整'
    icon: str = 'globe'  # unknown historical icon IDs are renderer-fallback values
    mode: Literal['iframe', 'link', 'openlist', 'isolated_proxy'] = 'iframe'
    adapter: Literal['generic', 'openlist', 'immich'] = 'generic'
    browser_url: URL = ''
    private_address: URL | None = None
    address_mode: Literal['ip', 'domain'] | None = None
    alternate_address: URL | None = None
    mapping_configured: bool = False
    entry_policy: Literal['follow', 'public'] = 'follow'
    access_adapter: Literal['auto', 'generic', 'openlist', 'immich'] = 'auto'
    target_id: Identifier | None = None
    initial_path: LocalPath = '/'
    enabled: bool = False
    keep_alive: bool = False
    origin: URL = ''
    injection: PublicInjectionVersions = Field(default_factory=PublicInjectionVersions)
    template_id: Annotated[str, Field(pattern=r'^(openlist|immich|user_[0-9a-f]{32})$')] | None = None
    connection: PublicConnection = Field(default_factory=PublicConnection)
    background: Literal['solid', 'home'] = 'solid'
    request_policy: PublicRequestPolicy = Field(default_factory=PublicRequestPolicy)
    route: LocalPath = '/settings'
    capabilities: PublicCapabilities = Field(default_factory=PublicCapabilities)
    projection: ProjectionStatus | None = None


class PublicCheckAccess(PublicRecord):
    status: Literal['reachable', 'login_required', 'blocked', 'unknown'] = 'unknown'
    http_status: Annotated[int, Field(ge=100, le=599)] | None = None


class PublicCheckEmbedding(PublicRecord):
    status: Literal['allowed', 'blocked', 'unknown'] = 'unknown'
    reason_code: str = 'incomplete_receipt'
    reason: str = '已保存的检测记录不完整，请重新检测'


class PublicCheckInjection(PublicRecord):
    status: Literal['supported', 'unsupported', 'unknown', 'loader_required'] = 'unknown'
    reason: str = '已保存的检测记录不完整，请重新检测'


class PublicCheckHelp(PublicRecord):
    title: str = '重新检测网站'
    location: str | None = None
    instructions: list[str] = Field(default_factory=list)
    external_url: URL | None = None


class PublicSoftwareHint(PublicRecord):
    type: Literal['unknown', 'openlist', 'immich'] = 'unknown'
    source: Literal['html:generator', 'html:application-name'] | None = None


class PublicAppearanceCompatibility(PublicRecord):
    enabled: bool = False
    css: str = ''
    js: str = ''
    timing: Literal['document_start', 'dom_ready'] = 'document_start'


class PublicWebsiteCheck(PublicRecord):
    alternate_normalized_url: URL | None = None
    software: PublicSoftwareHint | None = None
    compatibility: PublicAppearanceCompatibility | None = None
    normalized_url: URL = ''
    name_suggestion: str = ''
    access: PublicCheckAccess = Field(default_factory=PublicCheckAccess)
    embedding: PublicCheckEmbedding = Field(default_factory=PublicCheckEmbedding)
    injection: PublicCheckInjection = Field(default_factory=PublicCheckInjection)
    help: PublicCheckHelp | None = None
    can_save: bool = False
    recommended_behavior: Literal['embedded', 'external'] = 'external'
    issues: list[str] = Field(default_factory=list)
    projection: ProjectionStatus | None = None


class PublicWebsiteResult(PublicModule):
    check: PublicWebsiteCheck


def public_check(raw):
    issues = []
    result = _read(PublicWebsiteCheck, raw, issues,
                   required=('normalized_url', 'name_suggestion', 'access', 'embedding', 'injection', 'can_save', 'recommended_behavior', 'issues'))
    if issues:
        result['can_save'] = False
        warning = '已保存的检测记录不完整，请重新检测'
        if warning not in result['issues']:
            result['issues'].append(warning)
    return _finish(result, issues)


def public_website_result(module, check):
    result = public_module(module)
    result['check'] = public_check(check)
    return result


def _ip(value: str) -> str:
    import ipaddress
    ipaddress.ip_address(value)
    return value


class PublicTarget(PublicRecord):
    id: Identifier = 'unavailable'
    name: Name = '配置不完整'
    upstream_url: URL = ''
    allowed_ips: list[Annotated[str, AfterValidator(_ip)]] = Field(default_factory=list, max_length=16)
    controlled: bool = False
    credential_headers: list[Literal['authorization', 'x-api-key', 'x-auth-token', 'Authorization', 'X-API-Key', 'X-Auth-Token']] = Field(default_factory=list)
    projection: ProjectionStatus | None = None


class PublicNavigationEntry(PublicRecord):
    id: Identifier = 'unavailable'
    title: Name = '配置不完整'
    icon: str = 'globe'
    visible: bool = False
    route: LocalPath = '/settings'
    builtin: bool = False
    projection: ProjectionStatus | None = None


class PublicNavigation(PublicRecord):
    entries: list[PublicNavigationEntry]
    settings_route: Literal['/settings'] = '/settings'
    legacy_routes: dict[Literal['drive', 'gallery'], str] = Field(default_factory=dict)
    projection: ProjectionStatus | None = None


def public_target(raw):
    issues = []
    result = _read(PublicTarget, raw, issues, required=('id', 'name', 'upstream_url', 'allowed_ips', 'controlled'))
    headers = raw.get('headers', {}) if isinstance(raw, dict) else {}
    if not isinstance(headers, dict):
        issues.append('headers')
        headers = {}
    allowed = {'authorization', 'x-api-key', 'x-auth-token', 'Authorization', 'X-API-Key', 'X-Auth-Token'}
    if isinstance(raw, dict) and 'headers' in raw:
        result['credential_headers'] = [name for name in headers if name in allowed]
    return _finish(result, issues)


def public_navigation(config, builtins):
    issues = []
    defaults: dict[str, dict] = {e['id']: dict(e, visible=True, builtin=True) for e in builtins}
    modules = config.get('modules', {})
    if not isinstance(modules, dict):
        issues.append('modules')
        modules = {}
    for index, (mid, raw) in enumerate(modules.items()):
        try:
            TypeAdapter(Identifier).validate_python(mid, strict=True)
        except ValidationError:
            issues.append(f'modules.{index}.id')
            continue
        if mid in defaults:
            issues.append(f'modules.{index}.id')
            continue  # a stored module cannot replace a built-in route/identity
        item = public_module(raw)
        entry = dict(id=mid, title=item['name'], icon=item['icon'], visible=item['enabled'], route='/apps/' + mid, builtin=False)
        if 'projection' in item:
            entry['projection'] = item['projection']
        defaults[mid] = entry
    entries = []
    overrides = config.get('navigation', [])
    if not isinstance(overrides, list):
        issues.append('navigation')
        overrides = []
    for index, override in enumerate(overrides):
        if not isinstance(override, dict) or not isinstance(override.get('id'), str):
            issues.append(f'entries.{index}.id')
            continue
        default = defaults.pop(override['id'], None)
        if default is None:
            continue
        invalid = list(default.get('projection', {}).get('invalid_fields', []))
        for key in ('title', 'icon', 'visible'):
            if override.get(key) is None:
                continue
            try:
                value = TypeAdapter(PublicNavigationEntry.model_fields[key].rebuild_annotation()).validate_python(override[key], strict=True)
                # Only display keys are overridable; historical icon IDs remain
                # strings for the renderer's fallback. New writes stay catalog-gated.
                default[key] = _utf8(value)
            except (ValidationError, ValueError):
                invalid.append(key)
        entries.append(_finish(default, invalid))
    entries.extend(defaults.values())
    aliases = config.get('legacy_routes', {})
    aliases = aliases if isinstance(aliases, dict) else {}
    routes = {key: value for key, value in aliases.items() if key in {'drive', 'gallery'} and isinstance(value, str) and any(e['id'] == value and not e['builtin'] for e in entries)}
    return _finish(dict(entries=entries, settings_route='/settings', legacy_routes=routes), issues)


def _utf8(value):
    """Check the JSON response boundary without rewriting owner text or URIs.

    Apply only to declared, validated fields: unknown private extensions must
    never enter the public projection (including diagnostics).
    """
    if isinstance(value, str):
        value.encode('utf-8')
    elif isinstance(value, list):
        for item in value:
            _utf8(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _utf8(key)
            _utf8(item)
    return value


def _projection_paths(model):
    """Only schema-owned paths may survive a serialized projection replay."""
    paths = {'record', 'projection'} | set(model.model_fields)
    for key, field in model.model_fields.items():
        if key == 'projection':
            continue
        nested = next((t for t in (field.annotation, *get_args(field.annotation))
                       if isinstance(t, type) and issubclass(t, PublicRecord)), None)
        if nested is not None:
            paths.update(key + '.' + path for path in _projection_paths(nested))
    if model is PublicModule:
        paths.update({'navigation.title', 'navigation.icon'})
    if model is PublicTarget:
        paths.add('headers')
    return paths


def _read(model, raw, issues, prefix='', required=()):
    """Validate each declared field separately, retaining valid siblings.

    Reject rather than stringify/coerce unexpected JSON. Excluded fields never
    enter Pydantic errors; no error message or rejected value leaves this module.
    """
    if model is PublicInjectionVersion:
        required = ('enabled', 'css', 'js', 'timing', 'csp_policy')
    elif model in {PublicCheckAccess, PublicCheckEmbedding, PublicCheckInjection, PublicCheckHelp}:
        required = tuple(model.model_fields)
    if not isinstance(raw, dict):
        issues.append(prefix.rstrip('.') or 'record')
        raw = {}
    # A stored marker can only make the result more conservative. Revalidate
    # every field anyway; never echo arbitrary paths or a claimed healthy state.
    if 'projection' in model.model_fields and raw.get('projection') is not None:
        try:
            marker = ProjectionStatus.model_validate(raw['projection'])
            allowed = _projection_paths(model)
            if not marker.invalid_fields or any(p not in allowed for p in marker.invalid_fields):
                issues.append(prefix + 'projection')
            issues.extend(prefix + p for p in marker.invalid_fields if p in allowed)
        except ValidationError:
            issues.append(prefix + 'projection')
    result = {}
    for key, field in model.model_fields.items():
        if key == 'projection':
            continue  # emitted only from validated schema-owned paths
        path = prefix + key
        if key not in raw:
            if key in required:
                issues.append(path)
            if key in {'version', 'source_origin'}:
                continue
            value = field.get_default(call_default_factory=True)
            result[key] = value.model_dump(exclude={'projection'}) if isinstance(value, BaseModel) else deepcopy(value)
            continue
        value = raw[key]
        nested = next((t for t in (field.annotation, *get_args(field.annotation))
                       if isinstance(t, type) and issubclass(t, PublicRecord)), None)
        if nested is not None and value is not None:
            result[key] = _read(nested, value, issues, path + '.')
            continue
        try:
            result[key] = _utf8(TypeAdapter(field.rebuild_annotation()).validate_python(value, strict=True))
        except (ValidationError, ValueError, TypeError):
            issues.append(path)
            fallback = field.get_default(call_default_factory=True)
            result[key] = fallback.model_dump(exclude={'projection'}) if isinstance(fallback, BaseModel) else deepcopy(fallback)
    return result


def _finish(result, issues):
    if issues:
        result['projection'] = dict(state='incomplete', invalid_fields=sorted(set(issues)))
    return result


def public_versions(raw):
    issues = []
    result = _read(PublicInjectionVersions, raw, issues)
    for slot in ('draft', 'active', 'previous'):
        value = result[slot]
        if value is not None and slot != 'draft' and not value.get('version'):
            issues.append(slot + '.version')
        if value is not None and any(p == slot or p.startswith(slot + '.') for p in issues):
            value['enabled'] = False
    return _finish(result, issues)


def require_stored_version(raw, slot):
    """Reject corrupt execution inputs; never publish a projection fallback.

    Return the original version, including its private extensions. The caller's
    existing history swap/write remains unchanged for valid stored versions.
    """
    from fastapi import HTTPException
    if not isinstance(raw, dict) or not all(key in raw for key in ('draft', 'active', 'previous')):
        problem = dict(state='incomplete', invalid_fields=['injection'])
    else:
        selected = public_versions({slot: raw[slot]})
        problem = selected.get('projection')
    if problem:
        raise HTTPException(409, dict(code='incomplete_injection', projection=problem))
    return raw[slot]


def public_module(raw, config=None):
    issues = []
    original = raw if isinstance(raw, dict) else {}
    result = _read(PublicModule, raw, issues, required=('id', 'name', 'icon', 'mode', 'browser_url', 'enabled', 'origin'))
    # Preserve legacy display precedence without trusting navigation structure.
    if isinstance(config, dict) and result['adapter'] == 'generic':
        from app.navigation_icons import NAVIGATION_ICONS
        entries = config.get('navigation', [])
        if isinstance(entries, list):
            override = next((e for e in entries if isinstance(e, dict) and e.get('id') == result['id']), {})
            title, icon = override.get('title'), override.get('icon')
            if title is not None:
                try:
                    result['name'] = _utf8(TypeAdapter(Name).validate_python(title, strict=True))
                except (ValidationError, ValueError):
                    issues.append('navigation.title')
            if isinstance(icon, str) and icon in NAVIGATION_ICONS:
                result['icon'] = icon
            elif icon is not None:
                issues.append('navigation.icon')
    result['injection'] = public_versions(original.get('injection', {}))
    issues.extend('injection.' + p for p in result['injection'].get('projection', {}).get('invalid_fields', []))
    if 'connection' not in original:
        result['connection']['transport'] = 'proxy' if result['mode'] == 'isolated_proxy' else 'auto'
        targets = config.get('targets', {}) if isinstance(config, dict) else {}
        target = targets.get(result['target_id']) if isinstance(targets, dict) else None
        headers = target.get('headers', {}) if isinstance(target, dict) else {}
        if isinstance(headers, dict):
            for name in headers:
                if name.lower() in {'authorization', 'x-api-key', 'x-auth-token'}:
                    result['connection'].update(auth_mode='header', header_name={'authorization': 'Authorization', 'x-api-key': 'X-API-Key', 'x-auth-token': 'X-Auth-Token'}[name.lower()], has_token=True)
                    break
    connection = result['connection']
    if ((connection['auth_mode'] == 'header' and (connection['transport'] == 'direct' or connection['injection_delivery'] == 'loader')) or
            (connection['transport'] == 'proxy' and connection['injection_delivery'] == 'loader') or
            (connection['transport'] == 'direct' and connection['injection_delivery'] != 'loader')):
        issues.append('connection')
    result['route'] = '/apps/' + result['id']
    adapter = result['adapter']
    managed = '/settings?section=navigation&module=' + ('drive' if adapter == 'openlist' else 'gallery') if adapter in {'openlist', 'immich'} else None
    result['capabilities'] = dict(injection=not issues and adapter == 'generic' and (result['mode'] == 'isolated_proxy' or (result['mode'] == 'iframe' and connection['injection_delivery'] == 'loader')),
                                  browser_status='unobservable', managed_settings=managed)
    return _finish(result, issues)
