"""Operator-owned exact browser origins, never derived from forwarded headers.

STELLA_ENTRY_REGISTRY is a JSON list of {service_id, public, private?} records.
The reserved service_id 'stella' defines the parent pair. Module records use
stable module IDs and must match their persisted public origin. No wildcard or
suffix substitution is used; absent private mappings fail closed.
"""
import json
import os
import re
from urllib.parse import urlsplit

from fastapi import HTTPException


def _origin(value, *, legacy_http=False):
    scheme = 'https?' if legacy_http else 'https'
    if not isinstance(value, str) or not re.fullmatch(scheme + r'://[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[1-9][0-9]{0,4})?', value):
        raise ValueError('Registry requires exact HTTPS origins')
    parsed = urlsplit(value)
    if parsed.port is not None and (parsed.port > 65535 or parsed.port == 443):
        raise ValueError('Noncanonical origin port')
    if any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in (parsed.hostname or '').split('.')):
        raise ValueError('Invalid origin hostname')
    return value


def records():
    try:
        raw = os.getenv('STELLA_ENTRY_REGISTRY')
        rows = json.loads(raw) if raw else [{'service_id': 'stella', 'public': os.getenv('STELLA_MAIN_ORIGIN', 'https://stella.xiya.live')}]
        if not isinstance(rows, list):
            raise ValueError('Registry must be a list')
        result = {}; origins = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) - {'service_id', 'public', 'private'}:
                raise ValueError('Invalid registry record')
            sid = row['service_id']
            if not isinstance(sid, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', sid) or sid in result:
                raise ValueError('Duplicate or invalid service ID')
            # Preserve explicitly configured single-origin development behavior.
            # New multi-entry registries remain HTTPS-only without this fallback.
            pair = {lane: _origin(row[lane], legacy_http=not raw) for lane in ('public', 'private') if lane in row}
            if 'public' not in pair or any(value in origins for value in pair.values()) or len(set(pair.values())) != len(pair):
                raise ValueError('Missing public or duplicate origin')
            origins.update(pair.values()); result[sid] = pair
        if 'stella' not in result:
            raise ValueError('Missing Stella entry')
        return result
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, '入口登记配置无效') from exc


def parent_context(source_origin):
    for lane, origin in records()['stella'].items():
        if origin == source_origin:
            return lane
    raise HTTPException(403, '启动来源未登记')


def module_context(module, source_origin):
    from app.services.access_entries import lane as selection_lane
    lane = selection_lane(source_origin,policy=module.get('entry_policy','follow'))
    row = records().get(module['id'])
    if row is None:
        if lane == 'public':
            return module['origin']
        raise HTTPException(403, '模块未登记此入口')
    if row['public'] != module['origin'] or lane not in row:
        raise HTTPException(403, '模块入口登记与配置不匹配')
    return row[lane]


def parent_for_module(module, target_origin):
    # This is deployment topology, NOT today's selection. Already-issued
    # tickets/grants remain bound to their own source across selection changes.
    pair = records().get(module['id'],{'public':module['origin']})
    if pair['public'] == module['origin']:
        for lane, value in pair.items():
            if value == target_origin and lane in records()['stella']:
                return records()['stella'][lane]
    raise HTTPException(404, '集成 Host 未登记')


def request_origin(request):
    # ASGI scheme must be supplied by a trusted TLS terminator, with actual Host.
    # In particular, X-Forwarded-Host is never an input to this registry.
    origin = str(request.base_url).rstrip('/')
    parent_context(origin)
    return origin


def browser_url(module, source_origin):
    """Map only an explicitly registered direct site's origin, keeping its suffix."""
    from app.services.access_entries import lane as selection_lane
    lane = selection_lane(source_origin,policy=module.get('entry_policy','follow'))
    validate_website_entry(module)
    original = module['browser_url']
    if module.get('mapping_configured'):
        # User upstream mapping never adds trusted Hosts or changes identity.
        return module.get('alternate_address') or original if lane == 'private' else original
    pair = records().get(module['id'])
    if not pair:
        # Direct browser addresses are not Host trust or server credential targets.
        return module['private_address'] if lane == 'private' and module.get('private_address') else original
    parsed = urlsplit(original)
    origin = parsed.scheme + '://' + parsed.netloc
    if origin != pair['public']:
        raise HTTPException(409, '网站入口登记与地址不匹配')
    if lane not in pair:
        # Direct browser navigation only: no proxy target/header fallback.
        return original
    if lane == 'private' and module.get('private_address'):
        return module['private_address']
    return pair[lane] + original[len(origin):]


def validate_website_entry(module):
    """Settings select deployed entries, never provision DNS/TLS or trust."""
    policy = module.get('entry_policy', 'follow')
    private = module.get('private_address')
    if policy not in {'follow', 'public'}:
        raise HTTPException(422, '不支持的入口选择')
    if module.get('mapping_configured') and module.get('mode') != 'isolated_proxy':
        # A retained legacy alias is not the selected direct upstream anymore.
        # It stays stored, but must neither override nor block an explicit mapping.
        from app.services.website_check import normalize_url
        try:
            for address in (module['browser_url'],module.get('alternate_address')):
                if address is not None and normalize_url(address) != address:
                    raise ValueError('Noncanonical upstream mapping')
        except (ValueError,KeyError):
            raise HTTPException(422,'网站地址映射无效，请重新检测') from None
        return
    if not private:
        return
    from app.services.website_check import normalize_url, origin
    try:
        if normalize_url(private) != private:
            raise ValueError('Noncanonical private address')
        parsed = urlsplit(private)
        _origin(parsed.scheme + '://' + parsed.netloc)
        pair = records().get(module.get('id'))
        if pair:
            # Only proxy mode uses the deployed proxy Host as its browser origin.
            # Direct sites retain an internal proxy origin but navigate browser_url.
            public = origin((module.get('origin') or module['browser_url']) if module.get('mode') == 'isolated_proxy' else module['browser_url'])
            if 'private' not in pair or public != origin(pair['public']) or origin(private) != origin(pair['private']):
                raise ValueError('Not a deployed private entry')
        elif module.get('mode') == 'isolated_proxy':
            raise ValueError('Proxy entry needs deployed exact Host')
    except (ValueError, KeyError):
        raise HTTPException(422, '内网地址必须匹配此网站已部署的精确入口；保存不会配置 DNS、TLS 或登录回调')


def browser_origin(host, issuer):
    """Private browser endpoint is separate from the stable issuer identity."""
    for origin in records()['stella'].values():
        if urlsplit(origin).netloc == host:
            return origin
    return issuer
