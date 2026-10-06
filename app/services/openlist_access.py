"""Same OpenList management boundary for compatible and isolated transports."""
from uuid import UUID
from fastapi import HTTPException

READ_POST = frozenset({
    'api/fs/list', 'api/fs/get', 'api/fs/search', 'api/fs/dirs',
    'api/fs/archive/meta', 'api/fs/archive/list',
    'api/public/settings', 'api/public/offline_download_tools',
    'api/public/archive_extensions', 'api/public/init_status',
})


def management_required(method, path):
    # Callers strip at most the ASGI leading slash, not arbitrary URL repair.
    if path.startswith('/') or '//' in path or any(p in ('.','..') for p in path.split('/')) or '\\' in path or '%' in path:
        raise HTTPException(400, '非法路径')
    management = path == 'api/admin' or path.startswith('api/admin/') or path.rstrip('/') == 'api/fs/other'
    readonly = method in {'GET','HEAD'} or (method == 'POST' and path in READ_POST)
    return management or not readonly


def require_grant(db, grant, method, path):
    if not management_required(method, path):
        return
    from app.models.user import AuthSession
    from app.services.admin_security import require_admin
    try:
        session = db.get(AuthSession, UUID(grant['sid']))
    except (ValueError, TypeError, KeyError):
        raise HTTPException(401, '集成会话无效') from None
    if session is None:
        raise HTTPException(401, '集成会话无效')
    require_admin(db, session)
