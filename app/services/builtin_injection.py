"""Target-only builtin injection, with permanent compatibility fixes.

No external credentials are ever loaded here. Client CSS/JS are public code.
"""
import re
import copy
import json
import os
from urllib.parse import urlsplit
from contextlib import contextmanager
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.models.config import AppConfig
from app.services.integrations_injection import errors
from app.services.backup_health import record_change
from app.services.integrations_injection import InjectionInput, safe_json

KEY = 'builtin_injection_v1'
GALLERY_LOGO_CSS = 'img[alt="Immich logo"]{content:url("https://stella.xiya.live/avatar.png");border-radius:50%;object-fit:cover}img[alt="Immich logo"].h-12{width:48px}'


def presets(site, appearance=None):
    from app.services.service_appearance import DEFAULTS, check_site
    check_site(site)
    appearance = appearance or DEFAULTS[site]
    if site == 'drive':
        from app.services.openlist_appearance import THEME_CSS, SIMPLIFIED_CSS, BACKGROUND_CSS, SIMPLIFIED_JS
        from app.services.openlist_compat import CACHE_JS, BACKGROUND_JS
        css = BACKGROUND_CSS
        if appearance['theme'] == 'stella': css = THEME_CSS + '\n' + css
        if appearance['simplified']: css += '\n' + SIMPLIFIED_CSS
        js = CACHE_JS + '\n' + BACKGROUND_JS + '\n' + admin_notice_code()
        if appearance['simplified']: js += '\n' + SIMPLIFIED_JS
        return css, js
    return GALLERY_LOGO_CSS if appearance['logo'] == 'stella' else '', ''


def default_active(site):
    presets(site)
    return InjectionInput().model_dump() | {'version': 'preset-v1', 'status': 'active'}


def empty_state():
    return {site: {'draft': None, 'active': default_active(site), 'previous': None}
            for site in ('drive', 'gallery')}


def read(db, site):
    presets(site)
    row = db.get(AppConfig, KEY, populate_existing=True) if db is not None else None
    config = json.loads(row.value) if row else empty_state()
    return copy.deepcopy(config[site]) | {'site': site, 'source': 'postgres' if row else 'preset'}


@contextmanager
def edit(db):
    db.execute(insert(AppConfig).values(key=KEY, value=json.dumps(empty_state())).on_conflict_do_nothing(index_elements=['key']))
    row = db.execute(select(AppConfig).where(AppConfig.key == KEY).with_for_update().execution_options(populate_existing=True)).scalar_one()
    config = json.loads(row.value)
    try:
        yield config
        row.value = json.dumps(config, ensure_ascii=False)
        db.commit()
    except BaseException:
        db.rollback()
        raise


def draft_errors(value):
    # Reuse syntax/size/timing DTO and validator, but never change upstream CSP.
    problems = errors(value, {'mode': 'isolated_proxy'}, {'controlled': False})
    if value['csp_policy'] != 'reject':
        problems.append('内置加载器保留原 CSP，不支持自动修改')
    return problems


def validate_draft(db, site, incoming):
    presets(site)
    value = incoming.model_dump()
    problems = draft_errors(value)
    with edit(db) as config:
        config[site]['draft'] = value
    return {'valid': not problems, 'errors': problems, 'draft': value}


def apply(db, site, actor_id):
    presets(site)
    with edit(db) as config:
        state = config[site]
        value = state['draft']
        if value is None: raise HTTPException(422, '没有可发布草稿')
        problems = draft_errors(value)
        if problems: raise HTTPException(422, {'errors': problems})
        state['previous'] = state['active'] | {'status': 'revoked'}
        state['active'] = value | {'version': uuid4().hex, 'status': 'active'}
        record_change(db, action='injection.apply', actor_id=actor_id, resource_id=None, changed_fields=['injection'])
    return read(db, site)


def rollback(db, site, actor_id):
    presets(site)
    with edit(db) as config:
        state = config[site]
        if state['previous'] is None: raise HTTPException(409, '没有上一版本')
        state['active'], state['previous'] = state['previous'] | {'status': 'active'}, state['active'] | {'status': 'revoked'}
        record_change(db, action='injection.rollback', actor_id=actor_id, resource_id=None, changed_fields=['injection'])
    return read(db, site)


def strip_legacy(html, site):
    if site == 'drive':
        # Immutable originals are only fingerprints, never runtime presets.
        from app.services.drive import OPENLIST_THEME_CSS, OPENLIST_THEME_JS
        css, js = OPENLIST_THEME_CSS, OPENLIST_THEME_JS
    else:
        css, js = presets(site)
    counts = {'css': 0, 'js': 0}
    def remove(match):
        kind = match.group(1).lower()
        expected = css if kind == 'style' else js
        if expected and match.group(3).strip() == expected:
            counts['css' if kind == 'style' else 'js'] += 1
            return ''
        return match.group(0)
    html = re.sub(r'<(style|script)(\s[^>]*)?>(.*?)</\1\s*>', remove, html, flags=re.I | re.S)
    return html, counts


def admin_notice_code():
    """Retired management-unlock injection; upstream 403 remains untouched."""
    return ''


def client_version(site, active, appearance=None):
    from hashlib import sha256
    from app.services.service_appearance import DEFAULTS
    visual = appearance or DEFAULTS[site]
    return active['version'] + '-v2-' + sha256(safe_json(visual).encode()).hexdigest()[:12]


def runtime_snapshot(db, site):
    from app.services.service_appearance import read as read_appearance
    return {'active': read(db, site)['active'], 'appearance': read_appearance(db, site)}


def client_code(site, active, appearance=None):
    css, js = presets(site, appearance)
    payload = safe_json({'site': site, 'version': client_version(site, active, appearance), 'base_css': css, 'base_js': js,
                         'css': active['css'] if active['enabled'] else '',
                         'js': active['js'] if active['enabled'] else '', 'timing': active['timing']})
    return r"""(()=>{
const p=PAYLOAD,key='__stellaBuiltin_'+p.site;
if(p.site==='gallery')document.querySelectorAll('style[data-stella-gallery-base]').forEach(e=>e.remove());
if(window[key]===p.version)return;window[key]=p.version;
document.querySelectorAll('[data-stella-builtin="'+p.site+'"]').forEach(e=>e.remove());
const style=document.createElement('style');style.dataset.stellaBuiltin=p.site;style.dataset.version=p.version;style.textContent=p.base_css+'\n'+p.css;(document.head||document.documentElement).append(style);
function run(code){if(!code)return;const script=document.createElement('script');script.dataset.stellaBuiltin=p.site;script.textContent=code;(document.head||document.documentElement).append(script);}
run(p.base_js);
const custom=()=>run(p.js);
if(p.timing==='document_start'||document.readyState!=='loading')custom();else document.addEventListener('DOMContentLoaded',custom,{once:true});
})();""".replace('PAYLOAD', payload)


def gallery_origins():
    # Deployment setting only; never derived from request Host, module URL or DTO.
    origins = os.environ.get('STELLA_GALLERY_CLIENT_ORIGINS', 'https://immich.xiya.live,https://immich.yunxi.life').split(',')
    for origin in origins:
        p = urlsplit(origin)
        if not p.hostname or p.username or p.password or p.path or p.query or p.fragment or any(c in origin for c in '<>\\"\'\\\\\r\n '):
            raise ValueError('gallery client origin must be an exact root origin')
        if p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in {'127.0.0.1', 'localhost'}):
            raise ValueError('gallery client origin requires HTTPS')
        _ = p.port
    return origins


def gallery_asset(db, *, custom_allowed=False):
    active = read(db, 'gallery')['active'] if custom_allowed else default_active('gallery')
    from app.services.service_appearance import read as read_appearance
    visual = read_appearance(db, 'gallery')
    code = '(()=>{if(!'+safe_json(gallery_origins())+'.includes(window.location.origin))return;'+client_code('gallery', active, visual)+'})();'
    return code, client_version('gallery', active, visual)


def gallery_head_loader(stella_origin='https://stella.xiya.live'):
    # Deployment helper only, not an API accepting arbitrary visitor URLs.
    p = urlsplit(stella_origin)
    if not p.hostname or p.username or p.password or p.path or p.query or p.fragment or any(c in stella_origin for c in '<>\"\'\\\\\r\n '):
        raise ValueError('loader base must be a root origin')
    if p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in {'127.0.0.1', 'localhost'}):
        raise ValueError('loader requires HTTPS')
    _ = p.port
    # No crossorigin=anonymous: same-site cross-origin classic scripts send the
    # Stella host-only cookie back to Stella (NOT to Immich). No CORS expansion.
    return '<script src="'+stella_origin+'/integration-assets/gallery.js"></script>'


def gallery_nginx_snippets(stella_origin='https://stella.xiya.live'):
    loader = gallery_head_loader(stella_origin)
    return {
        'http': 'map $http_accept $stella_gallery_accept_encoding {\n    default $http_accept_encoding;\n    ~*text/html "";\n}\n',
        # sub_filter's default MIME is text/html; don't broaden it to assets/API.
        'location': 'proxy_set_header Accept-Encoding $stella_gallery_accept_encoding;\nsub_filter_once on;\nsub_filter \'</head>\' \''+loader+'</head>\';\n',
    }


def probe_public_html(html, site):
    from hashlib import sha256
    _, counts = strip_legacy(html, site)
    transformed = transform_html(html, site)
    return {'site': site, 'legacy_matches': counts,
            'authorities_after': transformed.count('name="stella-builtin-injection"'),
            'idempotent': transform_html(transformed, site) == transformed,
            'before_sha256': sha256(html.encode('utf-8')).hexdigest(),
            'after_sha256': sha256(transformed.encode('utf-8')).hexdigest(),
            'bytes_before': len(html.encode('utf-8')), 'bytes_after': len(transformed.encode('utf-8'))}


def transform_html(html, site, db=None, *, active=None, appearance=None):
    from app.services.service_appearance import read as read_appearance
    active = active or read(db, site)['active']
    appearance = appearance or read_appearance(db, site)
    marker = f'<meta name="stella-builtin-injection" content="{site}:{client_version(site, active, appearance)}">'
    if marker in html:
        return html
    html, _ = strip_legacy(html, site)
    html = re.sub(r'<!--stella-builtin:' + site + r':begin-->.*?<!--stella-builtin:' + site + r':end-->', '', html, flags=re.S)
    fragment = f'<!--stella-builtin:{site}:begin-->'+marker+'<script>'+client_code(site, active, appearance)+f'</script><!--stella-builtin:{site}:end-->'
    head = re.search(r'<head\b[^>]*>', html, re.I)
    offset = head.end() if head else 0
    html = html[:offset]+fragment+html[offset:]
    # Native color-scheme is unchanged. Image mode overrides it reversibly
    # inside BACKGROUND_JS, never by permanently rewriting upstream metadata.
    return html
