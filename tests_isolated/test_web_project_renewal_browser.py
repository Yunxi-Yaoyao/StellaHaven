"""Unchanged built Vue App + real renewal/host HTTP + owned PG + Chromium.

Synthetic seeded owner/project/session and short test TTL (4s/2s renewal), not
production login/lifespan. No intercepted browser API responses or fake parent.
"""
import base64
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from uuid import uuid4
import zipfile
from sqlalchemy.orm import Session
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes

ROOT = Path(__file__).resolve().parents[1]
NODE = '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'


def test_renewal_real_vue_http_pg_dynamic_resources(notes, monkeypatch, tmp_path):
    import uvicorn
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    import app.database as database
    monkeypatch.setattr(database, 'sessionLocal', lambda: Session(notes.engine), raising=False)
    from app.routers.web_project_host import WebProjectHostMiddleware
    from app.services import web_projects as projects, web_project_runtime as runtime
    from app.models.config import AppConfig
    evidence = Path(os.environ['WP_RENEW_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=True)
    dist = evidence / 'dist'
    assert (dist / 'index.html').is_file()
    monkeypatch.setattr(runtime, 'TTL', 4)
    monkeypatch.setattr(runtime, 'RENEW_AFTER', 2)
    app = notes.client.app
    for name in ('workspace','notes_preferences','notes_tools','web_projects','project_files','detached_sources','attachment','tag','doc_tag','document_link','document_version'):
        app.include_router(importlib.import_module('app.routers.'+name).router)
    app.mount('/static', StaticFiles(directory=dist/'static'))
    @app.get('/notes', include_in_schema=False)
    def built_app(): return FileResponse(dist/'index.html')
    @app.get('/avatar.png', include_in_schema=False)
    def avatar(): return FileResponse(dist/'avatar.png')
    @app.get('/favicon.svg', include_in_schema=False)
    def favicon(): return FileResponse(dist/'favicon.svg')
    app = WebProjectHostMiddleware(app, lambda: Session(notes.engine))
    sock = socket.socket(); sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
    source,target = f'https://stella.test:{port}',f'https://pages.test:{port}'
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([{'service_id':'stella','public':source},{'service_id':'web-project-runtime','public':target}]))
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('index.html','<!doctype html><html><head><meta charset="UTF-8"></head><body><h1 id="ready">原地续期验收</h1><p id="saved"></p><script>window.memoryMarker=crypto.randomUUID();document.querySelector("#saved").textContent=localStorage.getItem("answer");</script></body></html>')
        z.writestr('lazy.js','export const value="dynamic-module-ok";')
    with Session(notes.engine) as db:
        root=projects.create(db,notes.uid,notes.wid,None,uuid4(),archive.getvalue(),'renewal.zip','index.html')['id']
        baseline=projects.write_state(db,notes.uid,root,0,0,str(uuid4()),{'answer':'untouched'})
        config_before={r.key:r.value for r in db.query(AppConfig).filter(~AppConfig.key.like('wp-grant:%')).all()}
        files_before={f['path']:hashlib.sha256(projects.read_file(db,notes.uid,root,f['path'])[0]).hexdigest() for f in projects.manifest(db,notes.uid,root)['files']}
    key,cert=tmp_path/'key.pem',tmp_path/'cert.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=stella.test','-addext','subjectAltName=DNS:stella.test,DNS:pages.test','-keyout',str(key),'-out',str(cert)],check=True,capture_output=True)
    pub=x509.load_pem_x509_certificate(cert.read_bytes()).public_key().public_bytes(Encoding.DER,PublicFormat.SubjectPublicKeyInfo)
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning',lifespan='off',ssl_keyfile=str(key),ssl_certfile=str(cert),proxy_headers=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    spec=dict(source=source,target=target,port=port,token=notes.token,root=str(root),spki=base64.b64encode(hashlib.sha256(pub).digest()).decode(),evidence=str(evidence))
    (evidence/'boundary.json').write_text(json.dumps({'boundary':__doc__,'source':source,'target':target,'ttl':4,'renew_after':2,'dist_sha256':{str(p.relative_to(dist)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dist.rglob('*') if p.is_file()}},indent=2))
    thread.start();process=None
    try:
        deadline=time.monotonic()+8
        while not server.started and time.monotonic()<deadline:time.sleep(.02)
        assert server.started
        with (evidence/'browser.stdout.log').open('w') as stdout, (evidence/'browser.stderr.log').open('w') as stderr:
            process=subprocess.Popen([NODE,str(ROOT/'frontend/tests/web-project-renewal-e2e.mjs')],env={**os.environ,'NODE_ENV':'test','STELLA_PROJECT_FIXTURE':json.dumps(spec)},stdout=stdout,stderr=stderr)
            deadline=time.monotonic()+90;expired=False
            while process.poll() is None and time.monotonic()<deadline:
                if not expired and (evidence/'expire-request.json').exists():
                    request=json.loads((evidence/'expire-request.json').read_text())
                    with Session(notes.engine) as db:
                        row=db.get(AppConfig,runtime.key(request['capability']))
                        grant=json.loads(row.value)
                        assert grant['root']==str(root) and grant['sid']==str(notes.sid)
                        grant['expires']=time.time()-1;row.value=json.dumps(grant);db.commit()
                    (evidence/'expire-done.json').write_text(json.dumps({'expired':True}))
                    expired=True
                time.sleep(.03)
            assert process.poll() is not None,'Browser deadline exceeded'
            assert process.returncode==0,(evidence/'browser.stderr.log').read_text()
            assert expired
        with Session(notes.engine) as db:
            assert projects.read_state(db,notes.uid,root)==baseline
            config_after={r.key:r.value for r in db.query(AppConfig).filter(~AppConfig.key.like('wp-grant:%')).all()}
            # UI preferences may change; project/config rows must be byte-identical.
            assert all(config_after[k]==v for k,v in config_before.items())
            files_after={f['path']:hashlib.sha256(projects.read_file(db,notes.uid,root,f['path'])[0]).hexdigest() for f in projects.manifest(db,notes.uid,root)['files']}
            assert files_after==files_before
            grants=[json.loads(r.value) for r in db.query(AppConfig).filter(AppConfig.key.like('wp-grant:%')).all()]
            assert len(grants)==1 and grants[0]['root']==str(root)
        (evidence/'pg-readback.json').write_text(json.dumps({'state':baseline,'source_sha256':files_after,'project_config_unchanged':True,'grant_count':len(grants)},indent=2))
    finally:
        if process and process.poll() is None:process.kill();process.wait(timeout=5)
        server.should_exit=True;thread.join(10);sock.close()
        assert not thread.is_alive()
        (evidence/'server-cleanup.json').write_text(json.dumps({'server_stopped':not thread.is_alive(),'browser_process_stopped':process is None or process.poll() is not None}))
