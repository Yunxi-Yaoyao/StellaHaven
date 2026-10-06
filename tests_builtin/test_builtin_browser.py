import json
import os
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
import httpx
import uvicorn
from fastapi import FastAPI
from starlette.responses import HTMLResponse
from sqlalchemy.orm import Session
from tests_builtin.pg_fixture import pg_engine, pg_db
from app.services import builtin_injection as builtin
from app.services.integrations_injection import InjectionInput

@contextmanager
def local_server(app, *, tls=False, hostname='127.0.0.1'):
    sock=socket.socket(); sock.bind(('127.0.0.1',0)); sock.listen(128)
    origin=f'{"https" if tls else "http"}://{hostname}:{sock.getsockname()[1]}'
    options={}
    import tempfile
    certdir=tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
    if tls:
        key=Path(certdir.name)/'key.pem';cert=Path(certdir.name)/'cert.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=builtin.test','-addext','subjectAltName=DNS:stella.builtin.test,DNS:immich.builtin.test,IP:127.0.0.1'],check=True,capture_output=True)
        options={'ssl_keyfile':str(key),'ssl_certfile':str(cert)}
    server=uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off',**options))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True); thread.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.02)
        assert server.started
        yield origin
    finally:
        server.should_exit=True; thread.join(timeout=5); sock.close();certdir.cleanup(); assert not thread.is_alive()


def test_real_classic_cross_origin_loader_apply_disable_rollback(pg_db,pg_engine,monkeypatch):
    monkeypatch.setenv('STELLA_COOKIE_SECURE', 'true')  # This fixture exercises actual HTTPS origins.
    from app.database import get_db
    from app.routers.builtin_injection import assets_router
    from app.routers.auth import router as auth_router,AT_COOKIE
    from app.models.user import User,AuthSession,EmailCode
    from fastapi.testclient import TestClient
    from app.services.drive import OPENLIST_THEME_CSS,OPENLIST_THEME_JS
    # API/target root domains are never redirected into the main host grant model.
    assets=FastAPI();assets.include_router(assets_router)
    assets.include_router(auth_router)
    monkeypatch.delenv('STELLA_OWNER_ID',raising=False)
    for table in (User.__table__,AuthSession.__table__,EmailCode.__table__):table.create(pg_engine,checkfirst=True)
    def request_db():
        with Session(pg_engine) as db: yield db
    assets.dependency_overrides[get_db]=request_db
    target=FastAPI()
    target_cookie_leaks=[];asset_cookie_seen=[]
    @target.middleware('http')
    async def observe_target(request,call_next):
        if request.cookies.get(AT_COOKIE):target_cookie_leaks.append(True)
        return await call_next(request)
    @assets.middleware('http')
    async def observe_assets(request,call_next):
        if request.url.path=='/integration-assets/gallery.js':asset_cookie_seen.append(bool(request.cookies.get(AT_COOKIE)))
        return await call_next(request)
    denied_calls=[]
    @target.post('/api/fs/remove')
    def deny_mock():
        from starlette.responses import JSONResponse
        denied_calls.append('POST')
        return JSONResponse({'detail':{'code':'admin_elevation_required'}},status_code=403)
    @target.get('/api/replay-counts')
    def replay_counts(): return {'calls':len(denied_calls)}
    @target.get('/api/mobile')
    def native_mobile(): return {'native':'unchanged'}
    @target.post('/api/fs/move')
    def write_mock(): return {'code':200}
    @target.get('/drive/openlist/')
    def drive_html():
        upstream_script="window.upstreamKept=1;window.snapshotCache=new Map([['/src',1],['/dst',2]]);document.addEventListener('click',e=>{const a=e.target.closest('a');if(a)window.snapshotCache.delete(a.getAttribute('href'))},true);"
        html=f'<html><head><style>{OPENLIST_THEME_CSS}</style><script>{OPENLIST_THEME_JS}</script><script>{upstream_script}</script></head><body><div id="root"><nav class="hope-breadcrumb"></nav><header><button aria-label="switch layout">duplicate</button><button aria-label="switch layout">keep</button></header></div></body></html>'
        with Session(pg_engine) as db: return HTMLResponse(builtin.transform_html(html,'drive',db))
    with local_server(assets,tls=True,hostname='stella.builtin.test') as asset_origin:
        with TestClient(assets,base_url=asset_origin) as authenticated:
            assert authenticated.post('/auth/register',json={'username':'browser-owner','password':'browser-daily-fixture'}).status_code==201
            cookie=next(item for item in authenticated.cookies.jar if item.name==AT_COOKIE)
            assert cookie.domain=='stella.builtin.test' and not cookie.domain_specified and cookie.secure
            assert cookie._rest.get('SameSite','').lower()=='lax' and 'HttpOnly' in cookie._rest
            cookies=[{'name':AT_COOKIE,'value':authenticated.cookies.get(AT_COOKIE),'url':asset_origin,'secure':True,'httpOnly':True,'sameSite':'Lax'}]
        @target.get('/')
        def gallery():
            return HTMLResponse('<html><head>'+builtin.gallery_head_loader(asset_origin)+'</head><body><img alt="Immich logo"><h1>图库</h1></body></html>')
        with local_server(target,tls=True,hostname='immich.builtin.test') as target_origin:
            monkeypatch.setenv('STELLA_GALLERY_CLIENT_ORIGINS',target_origin)
            @assets.get('/')
            def main():
                return HTMLResponse(f'<html><head><script src="{asset_origin}/integration-assets/gallery.js"></script></head><body><div id="main">MAIN-UNCHANGED</div><iframe src="{target_origin}/"></iframe></body></html>')
            actor='00000000-0000-4000-8000-000000000001'
            draft=InjectionInput(enabled=True,css='h1{color:rgb(12,34,56)}',js='window.galleryClient="中文 </script> </style> \\u2028";')
            builtin.validate_draft(pg_db,'gallery',draft)
            results=[]
            def check(expected,with_owner=True):
                denied_calls.clear()
                asset_cookie_seen.clear();target_cookie_leaks.clear()
                env=os.environ | {'BUILTIN_BROWSER_INPUT':json.dumps({'assetOrigin':asset_origin,'targetOrigin':target_origin}),'BUILTIN_BROWSER_COOKIES':json.dumps(cookies if with_owner else []),'BUILTIN_EXPECTED':expected}
                result=subprocess.run(['node','tests/builtin-cross-origin.mjs'],cwd=Path(__file__).resolve().parents[1]/'frontend',env=env,text=True,capture_output=True,timeout=60)
                assert result.returncode==0,result.stdout+result.stderr
                evidence=json.loads(result.stdout); results.append(evidence)
                assert httpx.get(target_origin.replace('immich.builtin.test','127.0.0.1')+'/api/mobile',verify=False,trust_env=False).json()=={'native':'unchanged'}
                assert not target_cookie_leaks
                assert asset_cookie_seen and all(value==with_owner for value in asset_cookie_seen)
                return evidence
            check('disabled') # saved draft must not execute
            first=builtin.apply(pg_db,'gallery',actor)['active']['version']; enabled=check('enabled')
            assert enabled['gallery']['version']==first
            assert check('disabled',with_owner=False)['gallery']['version']=='preset-v1'
            builtin.validate_draft(pg_db,'gallery',draft.model_copy(update={'enabled':False}));builtin.apply(pg_db,'gallery',actor)
            check('disabled')
            assert builtin.rollback(pg_db,'gallery',actor)['active']['version']==first
            check('enabled')
            print('CROSS_ORIGIN_EVIDENCE='+json.dumps(results,ensure_ascii=False))
