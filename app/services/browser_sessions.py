"""Display-only UA metadata; never used for authentication or browser grouping."""


def detect_user_agent(value: str) -> tuple[str, str]:
    ua = value[:4096].lower()
    os_name = next((label for key, label in (
        ('android', 'Android'), ('iphone', 'iOS'), ('ipad', 'iOS'),
        ('ipod', 'iOS'), ('windows', 'Windows'), ('mac', 'macOS'),
        ('linux', 'Linux')) if key in ua), '未知系统')
    if any(key in ua for key in ('micromessenger', '; wv', 'qqbrowser', 'ucbrowser', 'electron', 'fban', 'fbav')):
        return '未知浏览器', os_name
    browser = next((label for key, label in (
        ('edg/', 'Edge'), ('edga/', 'Edge'), ('edgios/', 'Edge'),
        ('opr/', 'Opera'), ('opera', 'Opera'), ('fxios/', 'Firefox'),
        ('firefox/', 'Firefox'), ('crios/', 'Chrome'), ('chrome/', 'Chrome'),
        ('safari/', 'Safari')) if key in ua), '未知浏览器')
    return browser, os_name


def resolve_display_entry(request, entry_origin: str | None) -> str | None:
    """Resolve untrusted display/group metadata, never an authentication Origin.

    A client can forge this hint. Use it only for already-authenticated account
    grouping/display; never CSRF, trusted origins, issuer, cookies or redirects.
    The one explicit deployment alias accounts for canonicalizing LAN proxies.
    """
    from app.services.request_security import canonical_origin, trusted_origins
    supplied = request.headers.get('origin')
    actual = canonical_origin(supplied) if supplied else canonical_origin(str(request.base_url))
    if not actual or actual not in trusted_origins() or len(actual) > 512:
        return None
    # Exact serialized HTTPS origin only: no path, port, credentials or URL
    # normalization that could turn an arbitrary hint into an accepted alias.
    if (entry_origin and entry_origin.startswith('https://') and
            canonical_origin(entry_origin) == entry_origin and
            (entry_origin == actual or (entry_origin, actual) ==
             ('https://stella.p.xiya.live', 'https://stella.xiya.live'))):
        return entry_origin
    return actual


def session_metadata(session):
    return {'browser_id': str(session.browser_id) if session.browser_id else None,
            'browser_name': session.browser_name, 'os_name': session.os_name,
            'login_origin': session.login_origin, 'ip_location': None}
