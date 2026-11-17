"""Outermost resource-only host dispatcher for imported webpage projects."""
from urllib.parse import urlsplit
from fastapi import HTTPException
from starlette.responses import Response,JSONResponse
from app.services.entry_registry import records
from app.routers.integrations_host import canonical_host

class WebProjectHostMiddleware:
 def __init__(self,app,db_factory):self.app=app;self.db_factory=db_factory
 async def __call__(self,scope,receive,send):
  if scope['type'] not in {'http','websocket'}:return await self.app(scope,receive,send)
  try:
   hosts=[v for k,v in scope['headers'] if k.lower()==b'host']
   if len(hosts)!=1:raise HTTPException(421,'需要唯一Host')
   try:
    host=canonical_host(hosts[0])
   except (ValueError,UnicodeError):
    raise HTTPException(421,'非法 Host authority') from None
   origins=records().get('web-project-runtime',{})
   target=next((origin for origin in origins.values() if urlsplit(origin).netloc==host),None)
   if target is None:return await self.app(scope,receive,send)
   if scope['type']=='websocket':return await send({'type':'websocket.close','code':4403})
   if scope['method'] not in {'GET','HEAD'}:raise HTTPException(405,'网页资源只读')
   parts=scope['path'].split('/',3)
   if len(parts)!=4 or parts[1]!='p':raise HTTPException(404,'网页资源不存在')
   from app.services.web_project_runtime import resource
   # This origin never authenticates with, forwards or exposes incoming cookies.
   with self.db_factory() as db:body,mime,headers=resource(db,parts[2],target,parts[3])
   headers['Content-Length']=str(len(body))
   response=Response(body if scope['method']=='GET' else b'',headers=headers,media_type=mime)
  except HTTPException as exc:
   if scope['type']=='websocket':return await send({'type':'websocket.close','code':4403})
   response=JSONResponse({'detail':exc.detail},status_code=exc.status_code,headers={'Cache-Control':'no-store','Content-Security-Policy':"sandbox; default-src 'none'; frame-ancestors 'none'"})
  except (ValueError,UnicodeError):
   response=JSONResponse({'detail':'非法网页资源请求'},status_code=400,headers={'Cache-Control':'no-store'})
  return await response(scope,receive,send)
