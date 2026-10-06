"""Fixed-target transport: approved DNS result is the actual socket destination.

httpx 0.28/httpcore 1.0 backend hook is deliberately encapsulated here. TLS SNI
and certificate validation still use the original hostname, never the IP.
"""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, unquote

import httpx
from httpcore._backends.anyio import AnyIOBackend
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.services import integrations as store


def allowed_address(value):
    addr = ipaddress.ip_address(value)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if addr.is_link_local or addr.is_unspecified or addr.is_multicast or addr.is_reserved or str(addr) in {'100.100.100.200','fd00:ec2::254','168.63.129.16'}:
        raise ValueError('禁止元数据、链路本地、保留地址')
    return str(addr)


def upstream_url(value):
    store.browser_url(value)
    p = urlsplit(value)
    if p.query or p.fragment or p.path not in {'','/'} or p.hostname.lower().rstrip('.') in {'metadata.google.internal','metadata','instance-data'}:
        raise ValueError('上游必须为完整 origin 根，无 query/hash/base_path')
    return value.rstrip('/')+'/'


class ResolveTargetInput(BaseModel):
    """DNS-only preview. Private destinations require explicit administrator consent."""
    model_config = ConfigDict(extra='forbid')
    upstream_url: str = Field(min_length=1, max_length=2048)
    allow_private: bool = Field(default=False, strict=True)

    @field_validator('upstream_url')
    @classmethod
    def root(cls, value):
        value = upstream_url(value)
        p = urlsplit(value)
        if '?' in value or '#' in value or p.port == 0:
            raise ValueError('上游必须为合法 origin 根')
        host = (p.hostname or '').lower().rstrip('.').encode('idna').decode('ascii')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            import re
            if len(host) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
                raise ValueError('非法上游主机名')
        else:
            allowed_address(host)
        return value


def _preview_addresses(origin):
    p = urlsplit(origin)
    port = p.port or (443 if p.scheme == 'https' else 80)
    addresses = {allowed_address(entry[4][0]) for entry in socket.getaddrinfo(p.hostname, port, type=socket.SOCK_STREAM)}
    if not addresses or len(addresses) > 16:
        raise ValueError('解析结果为空或超过固定目标上限')
    return sorted(addresses)


async def resolve_target_preview(incoming: ResolveTargetInput):
    p = urlsplit(incoming.upstream_url)
    host = (p.hostname or '').lower().rstrip('.').encode('idna').decode('ascii')
    if ':' in host:
        host = '[' + host + ']'
    port = p.port
    origin = p.scheme + '://' + host
    if port is not None and port != (443 if p.scheme == 'https' else 80):
        origin += ':' + str(port)
    try:
        addresses = await asyncio.wait_for(asyncio.to_thread(_preview_addresses, origin), 5)
        private = any(not ipaddress.ip_address(ip).is_global for ip in addresses)
        if private and not incoming.allow_private:
            raise ValueError('私网/本机地址需要明确批准')
    except (ValueError, OSError, TimeoutError) as exc:
        raise HTTPException(422, '目标解析失败、地址被禁止或私网未明确批准') from exc
    return dict(normalized_origin=origin, resolved_ips=addresses, status='resolved', private_addresses=private)


class TargetInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1,max_length=100)
    upstream_url: str
    allowed_ips: list[str] = Field(min_length=1,max_length=16)
    controlled: bool = False
    headers: dict[str,str] = Field(default_factory=dict)

    @field_validator('upstream_url')
    @classmethod
    def url(cls,value):
        return upstream_url(value)

    @field_validator('allowed_ips')
    @classmethod
    def ips(cls,values):
        return list(dict.fromkeys(allowed_address(v) for v in values))

    @field_validator('headers')
    @classmethod
    def safe_headers(cls,values):
        if len(values)>8:
            raise ValueError('凭据头过多')
        for k,v in values.items():
            if k.lower() not in {'authorization','x-api-key','x-auth-token'} or not v or len(v)>8192 or any(ord(c)<32 or ord(c)>126 for c in v):
                raise ValueError('只支持受控凭据头，不允许换行')
        return {k.lower():v for k,v in values.items()}


def resolve(target):
    p=urlsplit(target['upstream_url'])
    port=p.port or (443 if p.scheme=='https' else 80)
    addresses={allowed_address(entry[4][0]) for entry in socket.getaddrinfo(p.hostname,port,type=socket.SOCK_STREAM)}
    if not addresses or not addresses<=set(target['allowed_ips']):
        raise ValueError('DNS 解析不完全属于批准 IP 列表')
    return sorted(addresses)[0]


async def create_target(db,incoming,actor_id):
    value=incoming.model_dump()
    try:
        await asyncio.wait_for(asyncio.to_thread(resolve,value),5)
    except (ValueError,OSError,TimeoutError) as exc:
        raise HTTPException(422,'目标解析/批准列表无效') from exc
    with store.edit(db) as config:
        if len(config['targets'])>=128:
            raise HTTPException(422,'目标数量超过限制')
        from uuid import uuid4
        value['id']=uuid4().hex
        config['targets'][value['id']]=value
        store.record_change(db,action='integration.create',actor_id=actor_id,resource_id=value['id'],changed_fields=['target','name','host','port'])
    return masked_target(value)


def masked_target(value):
    return {k:v for k,v in value.items() if k!='headers'} | {'credential_headers':list(value['headers'])}


class PinnedBackend(AnyIOBackend):
    def __init__(self,host,port,address):
        self.host,self.port,self.address=host,port,address

    async def connect_tcp(self,host,port,timeout=None,local_address=None,socket_options=None):
        if host!=self.host or port!=self.port:
            raise httpx.ConnectError('禁止跨目标连接')
        return await super().connect_tcp(self.address,port,timeout,local_address,socket_options)


def request_path(value):
    decoded=value
    for _ in range(3): decoded=unquote(decoded)
    p=urlsplit(value)
    if not value.startswith('/') or value.startswith('//') or p.scheme or p.netloc or '\\' in decoded or any(ord(c)<32 or ord(c)==127 for c in decoded) or any(v in {'.','..'} for v in decoded.split('?',1)[0].split('/')):
        raise HTTPException(400,'非法代理路径')
    return value.split('#',1)[0]


async def open_response(target,path,method='GET',headers=None,content=None):
    path=request_path(path)
    try:
        address=await asyncio.wait_for(asyncio.to_thread(resolve,target),5)
    except (ValueError,OSError,TimeoutError) as exc:
        raise HTTPException(502,'上游解析不在批准列表') from exc
    p=urlsplit(target['upstream_url']); port=p.port or (443 if p.scheme=='https' else 80)
    transport=httpx.AsyncHTTPTransport(retries=0, limits=httpx.Limits(max_connections=4), trust_env=False)
    transport._pool._network_backend=PinnedBackend(p.hostname,port,address)
    client=httpx.AsyncClient(transport=transport,trust_env=False,follow_redirects=False,timeout=httpx.Timeout(60,connect=5,pool=5))
    out=dict(headers or {}); out.update(target['headers'])
    try:
        request=client.build_request(method,target['upstream_url'].rstrip('/')+path,headers=out,content=content)
        response=await client.send(request,stream=True)
        return client,response
    except BaseException:
        await client.aclose()
        raise


HOP={'connection','keep-alive','transfer-encoding','upgrade','proxy-authenticate','proxy-authorization','te','trailer'}

def hop_headers(headers):
    return HOP | {v.strip().lower() for v in headers.get('connection','').split(',')}


def safe_request_headers(headers,origin,target):
    from http.cookies import SimpleCookie
    blocked=hop_headers(headers) | {'host','cookie','forwarded','origin','referer'}
    out={k:v for k,v in headers.items() if k.lower() not in blocked and not k.lower().startswith(('x-forwarded-','x-stella-'))}
    cookies=SimpleCookie()
    try: cookies.load(headers.get('cookie',''))
    except Exception: pass
    safe=[f'{k}={v.coded_value}' for k,v in cookies.items() if not k.lower().startswith(('stella_','__host-stella_'))]
    if safe: out['cookie']='; '.join(safe)
    if headers.get('origin'):
        if headers['origin']!=origin:
            raise HTTPException(403,'跨 origin 集成请求被拒绝')
        out['origin']=target['upstream_url'].rstrip('/')
    return out


async def response_headers(response,target,origin,module=None,parent_origin='https://stella.xiya.live'):
    from urllib.parse import urljoin, urlunsplit
    from http.cookies import SimpleCookie
    out=[]; blocked=hop_headers(response.headers)
    for key,value in response.headers.raw:
        name=key.decode().lower()
        if name in blocked: continue
        if name=='set-cookie':
            cookie=SimpleCookie()
            try: cookie.load(value.decode('latin1'))
            except Exception: continue
            if len(cookie)!=1: continue
            cookie_name,morsel=next(iter(cookie.items()))
            if cookie_name.lower().startswith(('stella_','__host-stella_')): continue
            morsel['domain']=''
            if not morsel['path']: morsel['path']='/'
            out.append((b'set-cookie',morsel.OutputString().encode('latin1')))
        elif name=='location':
            location=urljoin(str(response.url),value.decode('latin1'))
            p=urlsplit(location); base=urlsplit(target['upstream_url'])
            store.browser_url(location)
            # Immich's existing OIDC uses the main site's exact authorize endpoint.
            # Return to the browser only; NEVER connect/follow or forward credentials.
            parent=urlsplit(parent_origin)
            if module and module['adapter']=='immich' and target['controlled'] and (p.scheme,p.netloc,p.path)==(parent.scheme,parent.netloc,'/oidc/authorize'):
                out.append((b'location',value)); continue
            if (p.scheme,p.hostname,p.port or (443 if p.scheme=='https' else 80))!=(base.scheme,base.hostname,base.port or (443 if base.scheme=='https' else 80)):
                raise HTTPException(502,'上游重定向超出批准目标；禁止跨目标转发凭据')
            request_path(p.path or '/')
            try: await asyncio.wait_for(asyncio.to_thread(resolve,target),5)
            except (ValueError,OSError,TimeoutError) as exc: raise HTTPException(502,'重定向目标解析已变更') from exc
            out.append((b'location',(origin+urlunsplit(('','',p.path or '/',p.query,p.fragment))).encode('latin1')))
        else:
            out.append((key,value))
    return out


async def proxy_http(request,module,target,parent_origin='https://stella.xiya.live',db=None,builtin_reader=None):
    from starlette.responses import StreamingResponse, Response
    from app.services import integrations_injection as injection
    import secrets
    headers=safe_request_headers(request.headers,module['origin'],target)
    path=request.scope.get('raw_path',request.url.path.encode()).decode('ascii')
    if request.url.query: path+='?'+request.url.query
    try:
        client,response=await open_response(target,path,request.method,headers,request.stream())
    except httpx.HTTPError as exc:
        raise HTTPException(502,'上游连接失败') from exc
    try:
        upstream_headers=await response_headers(response,target,module['origin'],module,parent_origin)
    except BaseException:
        await response.aclose(); await client.aclose()
        raise
    active=module['injection']['active']
    builtin_site={'openlist':'drive','immich':'gallery'}.get(module.get('adapter'))
    injectable_html=request.method!='HEAD' and response.status_code==200 and response.headers.get('content-type','').split(';')[0].lower()=='text/html'
    if builtin_site and injectable_html:
        from app.services import builtin_injection as builtin
        # Snapshot through a short-lived session only for actual HTML responses.
        # No DB connection stays checked out while the upstream body is read.
        active = (await asyncio.to_thread(builtin_reader, builtin_site)
                  if builtin_reader is not None else builtin.read(db, builtin_site)['active'])
    if injectable_html and (builtin_site or (active and active['enabled'])):
        try:
            policies=response.headers.get_list('content-security-policy')
            controlled=active['csp_policy']=='controlled' and target['controlled']
            if (policies or response.headers.get('x-frame-options')) and not controlled:
                raise HTTPException(409,'上游 CSP/XFO 阻止注入；仅受控服务可明确配置策略')
            encoding=response.headers.get('content-encoding','').lower()
            if encoding not in {'','identity','gzip','deflate'}:
                raise HTTPException(415,'HTML 注入仅支持 identity/gzip/deflate；非 HTML 压缩原样保留')
            body=bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body)>2*1024*1024: raise HTTPException(502,'HTML 超过注入大小限制')
            charset=response.charset_encoding or 'utf-8'
            if charset.lower() not in {'utf-8','utf8','us-ascii'}:
                raise HTTPException(415,'注入仅支持 UTF-8 HTML')
            html=body.decode('utf-8')
            if __import__('re').search(r'<meta\b[^>]*http-equiv\s*=\s*[\"\']?content-security-policy',html,__import__('re').I):
                raise HTTPException(409,'HTML meta CSP 需要服务端适配，不自动剥离')
            nonce=secrets.token_urlsafe(24)
            if builtin_site:
                transformed=builtin.transform_html(html,builtin_site,db,active=active)
                html,changed=transformed,transformed!=html
            else:
                html,changed=injection.inject_html(html,module['id'],active,nonce)
            blocked=hop_headers(response.headers)|{'content-length','content-encoding','etag','content-md5','digest','last-modified'}
            if controlled: blocked|={'content-security-policy','x-frame-options'}
            output=Response(html,status_code=response.status_code)
            output.raw_headers=[(k,v) for k,v in upstream_headers if k.decode().lower() not in blocked]
            output.headers['content-length']=str(len(html.encode('utf-8')))
            output.headers['cache-control']='private, no-store'
            if controlled:
                if not policies: policies=["default-src 'self'; object-src 'none'"]
                for policy in policies:
                    output.raw_headers.append((b'content-security-policy',injection.controlled_csp(policy,nonce,parent_origin).encode()))
            return output
        finally:
            await response.aclose(); await client.aclose()
    async def chunks():
        try:
            async for chunk in response.aiter_raw(): yield chunk
        finally:
            await response.aclose(); await client.aclose()
    output=StreamingResponse(chunks(),status_code=response.status_code)
    blocked=hop_headers(response.headers)
    output.raw_headers=[(k,v) for k,v in upstream_headers if k.decode().lower() not in blocked]
    return output


async def proxy_websocket(ws,module,target,db_factory,grant):
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed, InvalidHandshake
    from starlette.websockets import WebSocketDisconnect
    from app.services import integrations_sessions as sessions
    p=urlsplit(target['upstream_url'])
    path=request_path(ws.scope.get('raw_path',ws.url.path.encode()).decode('ascii')+('?' + ws.url.query if ws.url.query else ''))
    headers=safe_request_headers(ws.headers,module['origin'],target)
    if ws.headers.get('origin')!=module['origin']:
        raise HTTPException(403,'WebSocket Origin 必须精确匹配集成域名')
    for key in list(headers):
        if key.startswith('sec-websocket-') or key in {'origin','content-length','accept-encoding'}: headers.pop(key)
    headers.update(target['headers'])
    try:
        address=await asyncio.wait_for(asyncio.to_thread(resolve,target),5)
        sock=await asyncio.to_thread(socket.create_connection,(address,p.port or (443 if p.scheme=='https' else 80)),5)
        sock.setblocking(False)
    except (ValueError,OSError,TimeoutError) as exc:
        raise HTTPException(502,'WebSocket 上游连接失败') from exc
    uri=('wss' if p.scheme=='https' else 'ws')+'://'+p.netloc+path
    tasks=[]
    try:
        # A provided pinned socket also forbids websockets' automatic redirects.
        async with connect(uri,sock=sock,proxy=None,origin=target['upstream_url'].rstrip('/'),additional_headers=headers,subprotocols=ws.scope.get('subprotocols') or None,compression=None,open_timeout=5,close_timeout=2,max_size=4*1024*1024,max_queue=16) as upstream:
            await ws.accept(subprotocol=upstream.subprotocol)
            async def to_upstream():
                while True:
                    event=await ws.receive()
                    if event['type']=='websocket.disconnect': return
                    value=event.get('text') if event.get('text') is not None else event.get('bytes')
                    if value is not None:
                        if len(value)>4*1024*1024:
                            await ws.close(code=1009); return
                        await upstream.send(value)
            async def to_browser():
                async for value in upstream:
                    if isinstance(value,str): await ws.send_text(value)
                    else: await ws.send_bytes(value)
            async def watch_session():
                while True:
                    await asyncio.sleep(5)
                    with db_factory() as db:
                        try:
                            fresh_grant=sessions.authorize(db,module['id'],module['origin'],ws.cookies.get(sessions.COOKIE))
                            if module['adapter']=='openlist':
                                from app.services.openlist_access import require_grant
                                require_grant(db,fresh_grant,'WEBSOCKET',ws.url.path.removeprefix('/'))
                        except HTTPException:
                            return
            tasks=[asyncio.create_task(fn()) for fn in (to_upstream,to_browser,watch_session)]
            done,pending=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED,timeout=max(0,grant['expires']-__import__('time').time()))
            for task in pending: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            close_code=upstream.close_code or (1008 if not done or tasks[2] in done else 1000)
            if close_code in {1005,1006,1015}: close_code=1011
            close_reason=(upstream.close_reason or '').encode('utf-8')[:120].decode('utf-8','ignore')
            try: await asyncio.wait_for(ws.close(code=close_code,reason=close_reason),2)
            except (RuntimeError,WebSocketDisconnect,TimeoutError): pass
    except (OSError,ValueError,ConnectionClosed,InvalidHandshake,TimeoutError) as exc:
        raise HTTPException(502,'WebSocket 握手/连接失败') from exc
    finally:
        for task in tasks:
            if not task.done(): task.cancel()
        if tasks: await asyncio.gather(*tasks,return_exceptions=True)
        sock.close()
