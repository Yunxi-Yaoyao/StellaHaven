"""Real native Nav SFC/router/CSS -> TLS HTTP/session -> disposable PG + WS.

This is not the whole main.py/App lifecycle; no production login or data used.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from tests_isolated.test_native_nav_pg import lane,pytestmark


def test_completion_browser_pg(lane,tmp_path,monkeypatch):
    import uvicorn
    from starlette.responses import FileResponse
    from starlette.staticfiles import StaticFiles
    from app.models.config import AppConfig
    from app.routers import integrations
    from app.services import integrations as service,request_security
    from qa.native_nav_synthetic import transfer
    client,factory,uid,other,nav,app=lane
    out=Path(os.environ['NAV_REHEARSAL_RECEIPT']).parent/'browser';out.mkdir()
    scratch=Path(os.environ['NAV_BROWSER_ROOT']).resolve()
    assert scratch.is_relative_to(Path(os.environ['TMPDIR']).resolve())
    assert (scratch/'dist/index.html').is_file()
    root=Path(os.environ['NAV_ROOT'])
    with factory() as db:
        config=service.empty_state();module=service.ModuleInput(name='Docs',mode='link',browser_url='https://example.test').model_dump()
        config['modules']['docs']={**module,'id':'docs','origin':'https://app-docs.test','injection':{'draft':None,'active':None,'previous':None}}
        db.add(AppConfig(key=service.KEY,value=json.dumps(config)));db.commit()
    app.include_router(nav.events_router);app.include_router(integrations.router)
    @app.get('/nav')
    @app.get('/away')
    def entry():return FileResponse(scratch/'dist/index.html')
    app.mount('/',StaticFiles(directory=scratch/'dist',html=True))
    cert,key=tmp_path/'cert.pem',tmp_path/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen();port=sock.getsockname()[1]
    origin=f'https://127.0.0.1:{port}';monkeypatch.setattr(request_security,'trusted_origins',lambda:{origin})
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,ssl_keyfile=str(key),ssl_certfile=str(cert),log_level='warning'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    deadline=time.monotonic()+10
    while not server.started:
        assert thread.is_alive() and time.monotonic()<deadline;time.sleep(.02)
    state=tmp_path/'browser-state.json';state.write_text(json.dumps({'cookies':[{'name':k,'value':v,'domain':'127.0.0.1','path':'/','secure':True,'httpOnly':True,'sameSite':'Lax'} for k,v in client.cookies.items()],'origins':[]}));state.chmod(0o600)
    synthetic=tmp_path/'synthetic-transfer.json';synthetic.write_text(json.dumps(transfer()))
    try:
        env={k:os.environ[k] for k in ['PATH','HOME','TMPDIR'] if k in os.environ}
        env.update(NAV_BROWSER_ORIGIN=origin,NAV_QA_STATE=str(state),NAV_EVIDENCE=str(out),NAV_SYNTHETIC_TRANSFER=str(synthetic),PLAYWRIGHT_BROWSERS_PATH=os.environ.get('PLAYWRIGHT_BROWSERS_PATH','/root/.cache/ms-playwright'),STELLA_CHROMIUM=os.environ.get('STELLA_CHROMIUM',''))
        result=subprocess.run([os.environ.get('STELLA_CI_NODE','/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'),str(root/'frontend/e2e/native-nav-completion.mjs')],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=100)
        (out/'browser.log').write_text(result.stdout+result.stderr)
        assert result.returncode==0,result.stdout+result.stderr
        with factory() as db:
            row=db.get(nav.NavState,uid)
            assert row.data['groups'][0]['items'][0]['module_id']=='docs'
            assert db.query(nav.NavAsset).count()==1
            assert db.get(nav.NavState,other) is None
            (out/'pg-readback.json').write_text(json.dumps({'revision':row.revision,'module_id':'docs','assets':1,'foreign_state_absent':True}))
    finally:
        server.should_exit=True;thread.join(timeout=10);sock.close();state.unlink(missing_ok=True);key.unlink(missing_ok=True)
        assert not thread.is_alive()
