"""Connect to an independently managed Immich instance."""
from app.services import external_services as external


def browser_url(db, hostname=''):
    cfg = external.load(db, 'gallery')
    host = hostname.lower().rstrip('.')
    base = cfg.alternate_browser_url if cfg.alternate_browser_url and (host == 'yunxi.life' or host.endswith('.yunxi.life')) else cfg.browser_url
    # Immich's global autoLaunch may be enabled; respect Stella's explicit manual choice.
    return base + ('/auth/login?autoLaunch=0' if cfg.auth_mode == 'manual' else '/')


def get_status(db):
    cfg = external.load(db, 'gallery')
    return {'configured': True, 'browser_url': cfg.browser_url, 'auth_mode': cfg.auth_mode}
