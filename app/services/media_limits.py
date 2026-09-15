"""Opt-in per-worker media admission/backpressure before multipart parsing."""
from starlette.responses import JSONResponse
class BodyTooLarge(Exception):pass

class MediaLimitsMiddleware:
    def __init__(self,app,enabled=False,concurrency=2,limits=None):
        self.app=app;self.enabled=enabled;self.active=0;self.maximum=concurrency
        self.limits=limits or {'/homebg/upload':82*1024*1024,'/auth/avatar':11*1024*1024,'/attachments/':26*1024*1024,'/documents/import/zip':33*1024*1024}

    async def __call__(self,scope,receive,send):
        if not self.enabled or scope['type']!='http':return await self.app(scope,receive,send)
        path=scope.get('path','');method=scope.get('method','GET')
        uploads=[v for p,v in self.limits.items() if path==p or (p.endswith('/') and path.startswith(p))]
        selected=bool(uploads and method=='POST') or (method in ('GET','HEAD') and path.startswith(('/attachments/','/assets/homebg/','/assets/avatars/')))
        if not selected:return await self.app(scope,receive,send)
        if self.active>=self.maximum:return await JSONResponse({'detail':'Media concurrency limit reached'},503,headers={'Retry-After':'2'})(scope,receive,send)
        self.active+=1;received=0;exceeded=False;started=False
        limit=uploads[0] if uploads and method=='POST' else None
        async def limited_receive():
            nonlocal received,exceeded
            message=await receive()
            if message['type']=='http.request' and limit is not None:
                received+=len(message.get('body',b''))
                if received>limit:exceeded=True;raise BodyTooLarge()
            return message
        async def guarded_send(message):
            nonlocal started
            if message['type']=='http.response.start':
                started=True
                # Frameworks may convert a body parser exception to HTTP400.
                if exceeded:message={**message,'status':413}
            await send(message)
        try:
            headers=dict(scope.get('headers',[]))
            if limit is not None and b'content-length' in headers:
                try:length=int(headers[b'content-length'])
                except ValueError:length=-1
                if length<0:return await JSONResponse({'detail':'Invalid Content-Length'},400)(scope,receive,send)
                if length>limit:return await JSONResponse({'detail':'Upload too large'},413)(scope,receive,send)
            await self.app(scope,limited_receive,guarded_send)
        except BodyTooLarge:
            if not started:await JSONResponse({'detail':'Upload too large'},413)(scope,receive,send)
            else:raise
        finally:
            self.active-=1
