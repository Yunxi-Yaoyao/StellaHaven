"""Exact main-site origin boundary, deliberately independent of forwarded headers.

Integration-origin dispatch MUST wrap this middleware; its host must never
fall through to the main site's APIs, static files, cookies or SPA.
"""
import os
from pathlib import Path
from urllib.parse import urlsplit, unquote
from starlette.datastructures import Headers
from starlette.responses import JSONResponse


def canonical_origin(value):
    try:
        u = urlsplit(value)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
            return None
        if u.query or u.fragment or u.path not in ('', '/'):
            return None
        port = u.port
        host = u.hostname.lower()
        authority = '[' + host + ']' if ':' in host else host
        if port and port != (443 if u.scheme == 'https' else 80):
            authority += ':' + str(port)
        return u.scheme + '://' + authority
    except (ValueError, TypeError):
        return None


def trusted_origins():
    configured = os.getenv('STELLA_TRUSTED_ORIGINS', '')
    values = configured.split(',') if configured else []
    result = {canonical_origin(value.strip()) for value in values}
    if not values or None in result:
        return set()  # no guessed production host; operator must configure
    return result


class MainSiteSecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        downstream_send = send
        async def safe_send(message):
            if message['type'] == 'http.response.start':
                # Uvicorn logs from the raw ASGI scope at response start. Handlers
                # have already consumed the legacy query; scrub before logging.
                scope['query_string'] = b''
            await downstream_send(message)
        send = safe_send
        headers = Headers(scope=scope)
        origins = trusted_origins()
        hosts = headers.getlist('host')
        host = hosts[0].lower() if len(hosts) == 1 else ''
        expected = {o for o in origins if urlsplit(o).netloc == host}
        code, message = 0, ''
        if not origins:
            code, message = 503, '主站可信origin未配置'
        elif not expected:
            code, message = 421, '非主站Host'
        else:
            unsafe = scope['type'] == 'websocket' or scope.get('method') not in ('GET', 'HEAD', 'OPTIONS')
            origin = headers.get('origin')
            if unsafe:
                if origin is not None:
                    if len(headers.getlist('origin')) != 1 or canonical_origin(origin) not in expected:
                        code, message = 403, '跨origin请求被拒绝'
                elif headers.get('referer'):
                    u = urlsplit(headers['referer'])
                    if canonical_origin(u.scheme + '://' + u.netloc) not in expected:
                        code, message = 403, '跨origin请求被拒绝'
                elif headers.get('sec-fetch-site') in ('cross-site', 'same-site'):
                    code, message = 403, '跨origin请求被拒绝'
                # Non-browser CLI/agent clients have no Origin or Fetch metadata.
                # Cookie writes use JSON or include a browser-supplied Origin.
                elif (headers.get('cookie') and scope.get('method') not in ('GET', 'HEAD') and
                      headers.get('content-type', '').split(';')[0] not in ('', 'application/json')):
                    code, message = 403, '缺少可信origin'
        if code:
            if scope['type'] == 'websocket':
                return await send({'type': 'websocket.close', 'code': 1008})
            return await JSONResponse({'detail': message}, status_code=code)(scope, receive, send)
        await self.app(scope, receive, send)


def contained_spa_path(root: Path, full_path: str) -> Path:
    """Reject raw/encoded traversal and root-escaping symlinks, including index."""
    path = full_path
    for _ in range(8):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    if '%' in path or '\\' in path or '\x00' in path or path.startswith('/') or '..' in Path(path).parts:
        raise ValueError('unsafe SPA path')
    root = root.resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError('SPA path escaped root')
    return candidate
