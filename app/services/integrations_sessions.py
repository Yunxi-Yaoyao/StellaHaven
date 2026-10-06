"""Short-lived single-use boot tickets + isolated-host grants stored in shared PG."""
import hashlib
import secrets
import time
from uuid import UUID

from fastapi import HTTPException
from app.models.user import AuthSession, User
from app.services.session_policy import expired
from app.services import integrations as store

COOKIE = '__Host-stella_integration'
TICKET_SECONDS = 30
GRANT_SECONDS = 900


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def session_alive(db,sid):
    try:
        session=db.get(AuthSession,UUID(sid))
    except (ValueError,TypeError):
        return False
    if not session or session.revoked or expired(session):
        return False
    user=db.get(User,session.user_id)
    from app.services import admin_security as owner_service
    if not user or not user.is_active:
        return False
    try:
        # Grants reference an already-authenticated SID. Never initialize/pick an
        # owner on this read/WS path: absent or broken shared pin fails closed.
        _, identity=owner_service.read_state(db)
        pinned=identity.get('owner_id')
        if not pinned:
            return False
        owner_id=UUID(pinned)
        import os
        configured=os.getenv('STELLA_OWNER_ID','')
        if configured and str(owner_id)!=configured:
            return False
        # Same pin/config/active identity rule as admin_security.require_owner,
        # but do not call its lazy owner_id initializer: a second READ COMMITTED
        # lookup could lose the pin and enter a write/lock during a plain GET.
        return user.id==owner_id
    except (HTTPException,ValueError,TypeError,AttributeError):
        return False


def prune(config):
    now=time.time()
    for key in ('tickets','grants'):
        config[key]={k:v for k,v in config[key].items() if v['expires']>now}


def issue(db,module,sid,source_origin):
    if not session_alive(db,sid):
        raise HTTPException(401,'无效主站会话')
    ticket=secrets.token_urlsafe(32)
    with store.edit(db) as config:
        prune(config)
        if len(config['tickets'])>=512:
            raise HTTPException(429,'启动票据数量超过限制')
        config['tickets'][digest(ticket)]=dict(id=module['id'],sid=sid,origin=module['origin'],source_origin=source_origin,expires=time.time()+TICKET_SECONDS)
    return dict(mode='isolated_proxy',url=module['origin']+'/__stella/bootstrap',method='POST',fields={'ticket':ticket},expires_in=TICKET_SECONDS)


def redeem(db,mid,origin,source_origin,ticket):
    raw=secrets.token_urlsafe(32)
    with store.edit(db) as config:
        prune(config)
        item=config['tickets'].get(digest(ticket))
        if not item or item['id']!=mid or item['origin']!=origin:
            raise HTTPException(401,'启动票据失效')
        if item['source_origin']!=source_origin:
            raise HTTPException(403,'启动来源不匹配')
        if not session_alive(db,item['sid']):
            raise HTTPException(401,'主站会话已失效')
        if len(config['grants'])>=512:
            raise HTTPException(429,'集成会话数量超过限制')
        del config['tickets'][digest(ticket)]
        config['grants'][digest(raw)]=dict(id=mid,origin=origin,sid=item['sid'],expires=time.time()+GRANT_SECONDS)
    return raw


def authorize(db,mid,origin,raw):
    if not raw or len(raw)>128:
        raise HTTPException(401,'需要从主站启动此模块')
    grant=store.state(db)['grants'].get(digest(raw))
    if not grant or grant['expires']<=time.time() or grant['id']!=mid or grant['origin']!=origin or not session_alive(db,grant['sid']):
        raise HTTPException(401,'集成会话失效，请从主站重新启动')
    return grant
