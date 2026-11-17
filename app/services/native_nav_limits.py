"""Bound native-nav writes before JSON/multipart parsing, even chunked uploads."""
from starlette.responses import JSONResponse

class NativeNavLimitsMiddleware:
    def __init__(self,app):
        self.app=app
        self.active=0
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope.get('method') not in {'POST','PUT'} or scope.get('path') not in {'/nav-data','/nav-import-preview','/nav-assets','/nav-package-preview','/nav-package-import','/nav-assets-category','/nav-assets-batch-delete'}:
            return await self.app(scope,receive,send)
        if self.active>=2:
            return await JSONResponse({'detail':'导航正在处理其他请求，请稍后重试'},503,headers={'Retry-After':'2'})(scope,receive,send)
        self.active+=1
        try:
            headers=dict(scope.get('headers',[]));limit=(48 if scope.get('path') in {'/nav-package-preview','/nav-package-import'} else 4)*1024*1024
            try: size=int(headers.get(b'content-length',b'0'))
            except ValueError: size=-1
            if size<0 or size>limit:
                return await JSONResponse({'detail':'导航请求超过 4 MiB 或长度无效'},413)(scope,receive,send)
            # At most two bounded bodies per worker. The parser never gets an
            # unbounded upload or a receive exception that could turn into HTTP400.
            parts=[];received=0
            while True:
                message=await receive()
                if message['type']=='http.disconnect': return
                chunk=message.get('body',b'');received+=len(chunk)
                if received>limit:
                    return await JSONResponse({'detail':'导航请求超过 4 MiB'},413)(scope,receive,send)
                parts.append(chunk)
                if not message.get('more_body'): break
            body=b''.join(parts);del parts
            delivered=False
            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered=True
                    return {'type':'http.request','body':body,'more_body':False}
                return await receive()
            await self.app(scope,replay,send)
        finally:
            self.active-=1
