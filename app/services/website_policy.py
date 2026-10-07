"""Data-defined management boundary, checked before any upstream bytes."""
from urllib.parse import urlsplit
from uuid import UUID
from fastapi import HTTPException


def management_required(module, method, path):
    policy = module.get('request_policy')
    if not policy: return False
    # Browser-encoded UTF-8 filenames and spaces are ordinary read resources.
    # Encoded ASCII route spellings, separators and double encodings remain
    # rejected rather than being normalized differently by another proxy hop.
    if '%' in path:
        import re
        from urllib.parse import unquote
        escapes=re.findall(r'%([0-9a-fA-F]{2})',path)
        if re.sub(r'%[0-9a-fA-F]{2}','',path).find('%')!=-1 or any(int(v,16)<128 and int(v,16)!=32 for v in escapes):
            raise HTTPException(400,'非法权限匹配编码')
        try: path=unquote(path,errors='strict')
        except UnicodeError: raise HTTPException(400,'非法路径编码') from None
    if not path.startswith('/') or '//' in path or '%' in path or '\\' in path or '?' in path or '#' in path or any(ord(c)<32 for c in path) or any(p in {'.','..'} for p in path.split('/')):
        raise HTTPException(400,'非法权限匹配路径')
    # Rules are root-relative and also relative to the configured entry directory.
    # Checking both prevents bypasses through a root API alias or a basepath API.
    base = urlsplit(module.get('initial_path','/')).path.rstrip('/')
    candidates = {path.rstrip('/') or '/'}
    if base and (path == base or path.startswith(base+'/')):
        candidates.add(path[len(base):].rstrip('/') or '/')
    for candidate in candidates:
        if any(prefix=='/' or candidate == prefix or candidate.startswith(prefix+'/') for prefix in policy.get('management_prefixes',[])):
            return True
    if method in {'GET','HEAD','OPTIONS'}: return False
    if method == 'POST' and any(p in policy.get('read_post_paths',[]) for p in candidates): return False
    return policy.get('protect_other_writes',False)


def require_grant(db, grant, module, method, path):
    if not management_required(module,method,path): return
    from app.models.user import AuthSession
    from app.services.admin_security import require_admin
    try: sid = UUID(grant['sid'])
    except (ValueError,TypeError,KeyError): raise HTTPException(401,'集成会话无效') from None
    session = db.get(AuthSession,sid)
    if session is None: raise HTTPException(401,'集成会话无效')
    require_admin(db,session)
