"""Outermost ASGI Host dispatch: integration origins NEVER fall through to Stella.

Trust the actual Host only, not forwarded-host. main_origin must be the canonical
HTTPS browser origin (local mock tests map Host without modifying DNS).
"""
import re
from urllib.parse import parse_qs
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
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
        from app.services.access_entries import async_request_snapshot
        try:
            async with async_request_snapshot(self.db_factory):
                return await self.dispatch(scope,receive,send)
        except HTTPException as exc:
            return await self.error(scope,receive,send,exc.status_code,exc.detail)

    async def dispatch(self,scope,receive,send):
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
        match=re.fullmatch(r'app-([0-9a-f]{32})\.(?:p\.)?xiya\.live',host)
        from app.services.entry_registry import records
        from urllib.parse import urlsplit
        try:
            registered_mid = next((sid for sid, pair in records().items()
                                   if re.fullmatch(r'[0-9a-f]{32}', sid)
                                   and any(urlsplit(value).netloc == host for value in pair.values())), None)
        except HTTPException as exc:
            return await self.error(scope,receive,send,exc.status_code,exc.detail)
        alias_mid=registered_mid
        if host in store.IMMICH_HOSTS:
            candidates=await run_in_threadpool(self.alias_candidates,host)
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

    def alias_candidates(self,host):
        with self.db_factory() as db:
            return [m['id'] for m in store.state(db)['modules'].values() if m['adapter']=='immich' and m['origin']=='https://'+host]

    def prepare(self,mid,origin,method,path,raw_cookie,source_origin=None,ticket=None,decoded_path=None):
        """One bounded worker owns the entire Session; only JSON DTOs leave it.

        run_in_threadpool copies the request's access_entries ContextVar. Never
        move a live Session across the body receive or proxy/stream awaits.
        """
        with self.db_factory() as db:
            module=store.get_module(db,mid)
            if module['mode']!='isolated_proxy' or not module['enabled']:
                raise HTTPException(404,'集成 Host 未启用')
            from app.services.entry_registry import parent_for_module
            parent_for_module(module, origin)
            from app.services.website_mapping import proxy_projection
            module=proxy_projection(module, origin)
            if module.get('adapter','generic') != 'generic':
                raise HTTPException(410,'遗留专用模块须先显式迁移为通用网站')
            target=store.state(db)['targets'].get(module['target_id'])
            if target is None: raise HTTPException(404,'上游目标不存在')
            if ticket is not None:
                return module,target,sessions.redeem(db,mid,origin,source_origin,ticket)
            if decoded_path is not None and decoded_path.startswith('/__stella/'):
                raise HTTPException(404,'保留集成路径')
            grant=sessions.authorize(db,mid,origin,raw_cookie)
            from app.services.website_policy import require_grant
            require_grant(db,grant,module,method,path)
            return module,target,grant

    async def integration(self,scope,receive,send,mid,origin):
        try:
            if scope['type']=='websocket':
                from starlette.websockets import WebSocket
                ws=WebSocket(scope,receive,send)
                module,target,grant=await run_in_threadpool(self.prepare,mid,origin,'WEBSOCKET',
                    ws.scope.get('raw_path',ws.url.path.encode()).decode('ascii'),ws.cookies.get(sessions.COOKIE))
                return await proxy.proxy_websocket(ws,module,target,self.db_factory,grant)
            request=Request(scope,receive)
            if request.url.path=='/__stella/bootstrap':
                if request.method!='POST' or request.url.query:
                    raise HTTPException(405,'启动票据仅接受 POST body')
                origins=request.headers.getlist('origin')
                if len(origins)!=1:
                    raise HTTPException(403,'启动必须来自主站')
                from app.services.entry_registry import parent_context
                parent_origin=origins[0]
                parent_context(parent_origin)
                if request.headers.get('content-type','').split(';')[0]!='application/x-www-form-urlencoded':
                    raise HTTPException(415,'启动需要表单 POST')
                body=b''
                async for chunk in request.stream():
                    body+=chunk
                    if len(body)>2048: raise HTTPException(413,'启动请求过大')
                values=parse_qs(body.decode('utf-8'),strict_parsing=True)
                if set(values)!={'ticket'} or len(values['ticket'])!=1 or len(values['ticket'][0])>128:
                    raise HTTPException(400,'启动票据格式错误')
                module,target,raw_cookie=await run_in_threadpool(self.prepare,mid,origin,request.method,
                    request.url.path,None,parent_origin,values['ticket'][0])
                response=RedirectResponse(module['initial_path'],status_code=303,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
                response.set_cookie(sessions.COOKIE,raw_cookie,max_age=sessions.GRANT_SECONDS,secure=True,httponly=True,samesite='strict',path='/')
            else:
                module,target,grant=await run_in_threadpool(self.prepare,mid,origin,request.method,
                    request.scope.get('raw_path',request.url.path.encode()).decode('ascii'),request.cookies.get(sessions.COOKIE),decoded_path=request.url.path)
                response=await proxy.proxy_http(request,module,target,grant['source_origin'])
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
