"""Outermost ASGI Host dispatch: integration origins NEVER fall through to Stella.

Trust the actual Host only, not forwarded-host. main_origin must be the canonical
HTTPS browser origin (local mock tests map Host without modifying DNS).
"""
import re
from urllib.parse import parse_qs
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from app.database import sessionLocal
from app.services import integrations as store, integrations_sessions as sessions, integrations_proxy as proxy


def canonical_host(value):
    """Strict HTTP authority, not urlsplit's permissive URL repair semantics."""
    host=value.decode('ascii').lower()
    match=re.fullmatch(r'(\[[0-9a-f:.]+\]|[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::([1-9][0-9]{0,4}))?',host)
    if not match or (match[2] and int(match[2])>65535):
        raise ValueError('invalid authority')
    name=match[1]
    if name.startswith('['):
        import ipaddress
        if str(ipaddress.IPv6Address(name[1:-1]))!=name[1:-1]:
            raise ValueError('noncanonical IPv6')
    elif len(name)>253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in name.split('.')):
        raise ValueError('invalid DNS name')
    return host


class IntegrationsHostMiddleware:
    def __init__(self,app,db_factory=sessionLocal,main_origin='https://stella.xiya.live',max_inflight=128,max_per_module=16):
        import weakref
        self.app=app
        self.db_factory=db_factory
        self.main_origin=main_origin.rstrip('/')
        self.max_inflight=max_inflight
        self.max_per_module=max_per_module
        self._inflight=weakref.WeakKeyDictionary()

    async def __call__(self,scope,receive,send):
        if scope['type'] not in {'http','websocket'}:
            return await self.app(scope,receive,send)
        hosts=[value for key,value in scope['headers'] if key.lower()==b'host']
        if len(hosts)!=1:
            return await self.error(scope,receive,send,421,'需要唯一 Host')
        try:
            host=canonical_host(hosts[0])
        except (ValueError,UnicodeError):
            return await self.error(scope,receive,send,421,'非法 Host authority')
        raw=dict(scope['headers'])
        match=re.fullmatch(r'app-([0-9a-f]{32})\.xiya\.live',host)
        alias_mid=None
        if host in store.IMMICH_HOSTS:
            with self.db_factory() as db:
                candidates=[m['id'] for m in store.state(db)['modules'].values() if m['adapter']=='immich' and m['origin']=='https://'+host]
                if len(candidates)==1: alias_mid=candidates[0]
            if alias_mid is None:
                return await self.error(scope,receive,send,404,'Immich 集成 Host 尚未接管')
        reserved=host.startswith('app-') and '.xiya.live' in host
        if not match and alias_mid is None:
            if reserved:
                return await self.error(scope,receive,send,404,'集成 Host 不存在')
            if scope['type']=='http' and scope['method'] not in {'GET','HEAD','OPTIONS'}:
                origin=raw.get(b'origin',b'').decode('latin1')
                from urllib.parse import urlsplit
                from app.services.request_security import trusted_origins, canonical_origin
                approved = trusted_origins() or {canonical_origin(self.main_origin)}
                expected = {o for o in approved if o and urlsplit(o).netloc == host}
                if origin and canonical_origin(origin) not in expected:
                    return await self.error(scope,receive,send,403,'主站拒绝其他 origin 写请求')
            return await self.app(scope,receive,send)
        import asyncio
        loop=asyncio.get_running_loop()
        counts=self._inflight.setdefault(loop,{'total':0,'modules':{}})
        mid=alias_mid or match[1]
        if counts['total']>=self.max_inflight or counts['modules'].get(mid,0)>=self.max_per_module:
            return await self.error(scope,receive,send,429,'集成代理并发预算已满')
        counts['total']+=1; counts['modules'][mid]=counts['modules'].get(mid,0)+1
        try:
            return await self.integration(scope,receive,send,mid,'https://'+host)
        finally:
            counts['total']-=1; counts['modules'][mid]-=1
            if not counts['modules'][mid]: del counts['modules'][mid]

    async def integration(self,scope,receive,send,mid,origin):
        try:
            with self.db_factory() as db:
                module=store.get_module(db,mid)
                if module['mode']!='isolated_proxy' or not module['enabled'] or module['origin']!=origin:
                    raise HTTPException(404,'集成 Host 未启用')
                target=store.state(db)['targets'].get(module['target_id'])
                if target is None: raise HTTPException(404,'上游目标不存在')
                if scope['type']=='websocket':
                    from starlette.websockets import WebSocket
                    ws=WebSocket(scope,receive,send)
                    grant=sessions.authorize(db,mid,origin,ws.cookies.get(sessions.COOKIE))
                    db.close()  # no DB connection held for lifetime of stream/socket
                    return await proxy.proxy_websocket(ws,module,target,self.db_factory,grant)
                request=Request(scope,receive)
                if request.url.path=='/__stella/bootstrap':
                    if request.method!='POST' or request.url.query:
                        raise HTTPException(405,'启动票据仅接受 POST body')
                    if request.headers.get('origin')!=self.main_origin:
                        raise HTTPException(403,'启动必须来自主站')
                    if request.headers.get('content-type','').split(';')[0]!='application/x-www-form-urlencoded':
                        raise HTTPException(415,'启动需要表单 POST')
                    body=b''
                    async for chunk in request.stream():
                        body+=chunk
                        if len(body)>2048: raise HTTPException(413,'启动请求过大')
                    values=parse_qs(body.decode('utf-8'),strict_parsing=True)
                    if set(values)!={'ticket'} or len(values['ticket'])!=1 or len(values['ticket'][0])>128:
                        raise HTTPException(400,'启动票据格式错误')
                    raw_cookie=sessions.redeem(db,mid,origin,self.main_origin,values['ticket'][0])
                    response=RedirectResponse(module['initial_path'],status_code=303,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
                    response.set_cookie(sessions.COOKIE,raw_cookie,max_age=sessions.GRANT_SECONDS,secure=True,httponly=True,samesite='strict',path='/')
                else:
                    if request.url.path.startswith('/__stella/'):
                        raise HTTPException(404,'保留集成路径')
                    sessions.authorize(db,mid,origin,request.cookies.get(sessions.COOKIE))
                    db.close()
                    def read_builtin_snapshot(site):
                        from app.services import builtin_injection
                        with self.db_factory() as snapshot_db:
                            return builtin_injection.read(snapshot_db, site)['active']
                    response=await proxy.proxy_http(request,module,target,self.main_origin,
                                                    builtin_reader=read_builtin_snapshot)
            return await response(scope,receive,send)
        except HTTPException as exc:
            return await self.error(scope,receive,send,exc.status_code,exc.detail)
        except (ValueError,UnicodeError):
            return await self.error(scope,receive,send,400,'非法请求')

    async def error(self,scope,receive,send,status,detail):
        if scope['type']=='websocket':
            await send({'type':'websocket.close','code':4401 if status==401 else 4403})
        else:
            await JSONResponse({'detail':detail},status_code=status,headers={'Cache-Control':'no-store'})(scope,receive,send)
