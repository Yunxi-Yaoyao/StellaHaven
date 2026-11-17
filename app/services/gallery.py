"""Connect to an independently managed Immich instance."""
from urllib.parse import urlsplit

from fastapi import HTTPException
from app.services import entry_registry
from app.services import external_services as external


def browser_url(db, source_origin):
    """Select the legacy gallery via the operator-owned 'gallery' entry.

    This is an explicit service mapping, not a guessed migrated module ID.
    Unknown parents and missing private mappings must never fall back to public.
    """
    lane = entry_registry.parent_context(source_origin)
    entries = entry_registry.records()
    cfg = external.load(db, 'gallery')
    # Keep the configured legacy alias only for a registered public parent.
    # Both lanes use this same public baseline; a private Host cannot select it.
    public_host = urlsplit(entries['stella']['public']).hostname or ''
    use_alternate = public_host == 'yunxi.life' or public_host.endswith('.yunxi.life')
    base = cfg.alternate_browser_url if cfg.alternate_browser_url and use_alternate else cfg.browser_url
    pair = entries.get('gallery')
    if pair is None:
        if lane != 'public':
            raise HTTPException(403, '图库未登记此入口')
    else:
        parsed = urlsplit(base)
        origin = parsed.scheme + '://' + parsed.netloc
        if origin != pair['public'] or lane not in pair:
            raise HTTPException(409, '图库入口登记与地址不匹配')
        base = pair[lane] + base[len(origin):]
    # Immich's global autoLaunch may be enabled; respect Stella's explicit manual choice.
    return base + ('/auth/login?autoLaunch=0' if cfg.auth_mode == 'manual' else '/')


def get_status(db):
    cfg = external.load(db, 'gallery')
    return {'configured': True, 'browser_url': cfg.browser_url, 'auth_mode': cfg.auth_mode}
