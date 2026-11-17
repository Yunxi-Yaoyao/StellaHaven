"""Owned TLS App fixture. Real website routers/SQLite/proxy; authentication is synthetic.
No production app import, credentials, account, deployment, DNS or TLS modification.
"""
import os
import json
import socket
import ssl
import threading
from pathlib import Path
from uuid import UUID
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

out=Path(os.environ['V6_EVIDENCE'])
listener=socket.socket(); listener.bind(('127.0.0.1',0)); listener.listen(128)
port=listener.getsockname()[1]
main=f'https://main.fixture.test:{port}'; other=f'https://other.fixture.test:{port}'
os.environ.update(STELLA_SECRET_KEY='synthetic-v6-website-signing-only-000000',POSTGRES_HOST='127.0.0.1',POSTGRES_PORT='1',POSTGRES_DB='stella_test_v6_websites',POSTGRES_USER='fixture',POSTGRES_PASSWORD='synthetic-only',STELLA_MAIN_ORIGIN=main,STELLA_APP_ORIGIN_TEMPLATE=f'https://app-{{id}}.fixture.test:{port}')
os.environ['STELLA_TRUSTED_ORIGINS']=main+','+other
seen=[]
unknown=[]
def observations():
    (out/'server-observations.json').write_text(json.dumps(dict(seen=seen,unknown=unknown)))
observations()
class Upstream(BaseHTTPRequestHandler):
    def do_GET(self):
        seen.append({'port':self.server.server_port,'path':self.path,'has_credential':bool(self.headers.get('Authorization'))})
        observations()
        if self.path.startswith('/blocked'):
            self.send_response(403);self.end_headers();return
        body=f'<html><head><title>自有网站</title></head><body style="background:#eadff5"><h1>上游 {self.server.server_port}</h1><p id="path">{self.path}</p></body></html>'.encode()
        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args): pass
servers=[]
for tls in (False,False,True,True):
    s=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
    if tls:
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(os.environ['V6_CERT'],os.environ['V6_KEY']);s.socket=ctx.wrap_socket(s.socket,server_side=True)
    threading.Thread(target=s.serve_forever,daemon=True).start();servers.append(s)
allowed={port,*[s.server_port for s in servers]}
real_connect=socket.socket.connect; real_connect_ex=socket.socket.connect_ex; real_dns=socket.getaddrinfo

def checked_destination(address):
    if isinstance(address,tuple) and (address[0] not in {'127.0.0.1','::1'} or address[1] not in allowed):
        raise AssertionError('Non-owned network destination blocked')
def guarded_connect(sock,address): checked_destination(address);return real_connect(sock,address)
def guarded_connect_ex(sock,address): checked_destination(address);return real_connect_ex(sock,address)
def guarded_dns(host,port,*args,**kwargs):
    value=host.decode() if isinstance(host,bytes) else host
    if value and str(value).endswith('.fixture.test'): host='127.0.0.1'
    elif value not in {None,'127.0.0.1','::1','localhost'}: raise OSError('Non-owned DNS blocked')
    return real_dns(host,port,*args,**kwargs)
socket.socket.connect=guarded_connect;socket.socket.connect_ex=guarded_connect_ex;socket.getaddrinfo=guarded_dns

from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker

from fastapi import FastAPI,Request,WebSocket
from fastapi.responses import FileResponse,JSONResponse
from app.database import get_db,engine as unused_pg
from app.models.config import AppConfig
from app.routers import auth
from app.routers.integrations import router as integrations_router
from app.routers.website_settings import router as websites_router,assets_router
from app.routers.integrations_host import IntegrationsHostMiddleware
from app.services import integrations as store,integrations_sessions as sessions

event.listen(unused_pg,'do_connect',lambda *a,**kw: (_ for _ in ()).throw(AssertionError('Application PG forbidden')))
database_path=out/'website-fixture.sqlite'
database_path.unlink(missing_ok=True)
engine=create_engine('sqlite:///'+str(database_path),connect_args={'check_same_thread':False})
AppConfig.__table__.create(engine);factory=sessionmaker(engine,expire_on_commit=False)
database_path.chmod(0o600)
owner=SimpleNamespace(id=UUID('00000000-0000-4000-8000-000000000006'))
def database():
    with factory() as db:
        try: yield db
        finally: db.rollback()
app=FastAPI();app.include_router(websites_router);app.include_router(assets_router);app.include_router(integrations_router)
app.dependency_overrides.update({get_db:database,auth.current_user:lambda:owner,auth.admin_user:lambda:owner})
auth._presented_session=lambda request,db: SimpleNamespace(id=UUID('00000000-0000-4000-8000-000000000007'),user_id=owner.id)
sessions.session_alive=lambda db,sid: sid=='00000000-0000-4000-8000-000000000007'
# Trust the task's own certificate, never disable verification of upstream TLS.
from app.services import integrations_proxy as proxy
original_transport=proxy.httpx.AsyncHTTPTransport
trusted_context=ssl.create_default_context(cafile=os.environ['V6_CERT'])
def owned_transport(*args,**kwargs):
    kwargs.setdefault('verify',trusted_context)
    return original_transport(*args,**kwargs)
proxy.httpx.AsyncHTTPTransport=owned_transport

@app.get('/auth/me')
def me(): return dict(id=str(owner.id),username='isolated-owner',display_name='隔离测试',email='fixture@example.test',email_verified=True,is_admin=False,home_bg='',avatar_url='')
@app.get('/auth/status')
def status(): return dict(initialized=True,has_users=True,single_user=True,email_enabled=False)
@app.get('/auth/security')
def security(): return dict(enabled=False,configured=False,elevated=False,single_user=True,setup_required=False)
@app.post('/auth/activity')
def activity(): return dict(ok=True)
@app.get('/notifications/unread-count')
def unread(): return dict(count=0)
@app.get('/nodes/host')
def host(): return dict(installed=True)
@app.get('/config/public-host')
def public_host(): return dict(value='')

@app.websocket('/ws/notifications')
async def ws(websocket:WebSocket): await websocket.close()

build=Path(os.environ['V6_BUILD']).resolve()
@app.get('/{path:path}')
def static(path:str):
    candidate=(build/path).resolve()
    if candidate.is_relative_to(build) and candidate.is_file(): return FileResponse(candidate)
    if not path or path in {'settings','help'} or path.startswith('apps/'): return FileResponse(build/'index.html')
    unknown.append(path);observations();return JSONResponse({'detail':'unmocked fixture route'},status_code=418)

class Registry:
    def __init__(self,inner): self.inner=inner
    async def __call__(self,scope,receive,send):
        with factory() as db:
            modules=store.state(db)['modules']
            rows=[dict(service_id='stella',public=main,private=other)]
            rows += [dict(service_id=m['id'],public=m['origin'],private=f'https://alt-{m["id"]}.fixture.test:{port}') for m in modules.values() if m['mode']=='isolated_proxy']
        # Legacy registry-only direct fixture from the independent W1/W2 review.
        rows += [dict(service_id=m['id'],public='https://127.0.0.1:'+str(servers[2].server_port),private='https://127.0.0.1:'+str(servers[3].server_port)) for m in modules.values() if m['name'].startswith('legacy-implicit')]
        os.environ['STELLA_ENTRY_REGISTRY']=json.dumps(rows)
        return await self.inner(scope,receive,send)

os.environ['STELLA_ENTRY_REGISTRY']=json.dumps([dict(service_id='stella',public=main,private=other)])
from app.public_website import PublicModule,PublicWebsiteResult,PublicWebsiteCheck
from app.services.website_settings import WebsiteInput
from app.services.website_check import CheckInput
from app.services.website_mapping import UpstreamBinding
(out/'router-openapi.json').write_text(json.dumps(app.openapi(),ensure_ascii=False,indent=2))
(out/'dto-proposal.json').write_text(json.dumps({model.__name__:model.model_json_schema() for model in (WebsiteInput,CheckInput,PublicModule,PublicWebsiteResult,PublicWebsiteCheck,UpstreamBinding)},ensure_ascii=False,indent=2))
manifest=dict(main=main,other=other,upstreams=[('https' if index>=2 else 'http')+'://127.0.0.1:'+str(s.server_port) for index,s in enumerate(servers)],port=port,auth='synthetic dependency override; no actual account/session/OIDC')
(out/'server.json').write_text(json.dumps(manifest))
import uvicorn
server=uvicorn.Server(uvicorn.Config(Registry(IntegrationsHostMiddleware(app,db_factory=factory,main_origin=main)),ssl_certfile=os.environ['V6_CERT'],ssl_keyfile=os.environ['V6_KEY'],log_level='warning',access_log=False))
try: server.run(sockets=[listener])
finally:
    for s in servers:s.shutdown();s.server_close()
    (out/'server-observations.json').write_text(json.dumps(dict(seen=seen,unknown=unknown)))
