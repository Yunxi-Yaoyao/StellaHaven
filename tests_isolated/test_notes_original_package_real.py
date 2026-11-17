"""Real original-package import/render/convert on a tiny owned PG, never production.
Explicit launcher required; no full production backup or historical metrics.
"""
import base64,hashlib,importlib,json,os,socket,subprocess,threading,time,zipfile
from pathlib import Path
from sqlalchemy.orm import Session
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes
ROOT=Path(__file__).resolve().parents[1]

def test_notes_original_package_real_journey(notes,monkeypatch,tmp_path):
    import uvicorn
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    import app.database as database
    monkeypatch.setattr(database,'sessionLocal',lambda:Session(notes.engine),raising=False)
    from app.routers.web_project_host import WebProjectHostMiddleware
    from app.services import web_projects
    evidence=Path(os.environ['NOTES_REAL_PACKAGE_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True)
    original=Path(os.environ['NOTES_REAL_PACKAGE_ZIP']);assert original.is_file()
    original_hash=hashlib.sha256(original.read_bytes()).hexdigest()
    with zipfile.ZipFile(original) as z:
        original_names=z.namelist();original_files={n:hashlib.sha256(z.read(n)).hexdigest() for n in original_names if not n.endswith('/')}
    monkeypatch.setattr(database,'sessionLocal',lambda:Session(notes.engine),raising=False)
    app=notes.client.app
    for name in ['workspace','notes_preferences','notes_tools','web_projects','project_files','detached_sources','attachment','tag','doc_tag','document_link','document_version']:
        app.include_router(importlib.import_module('app.routers.'+name).router)
    dist=ROOT/'frontend/dist';assert (dist/'index.html').is_file()
    app.mount('/static',StaticFiles(directory=dist/'static'),name='built-static')
    @app.get('/notes',include_in_schema=False)
    def built():return FileResponse(dist/'index.html')
    @app.get('/avatar.png',include_in_schema=False)
    def avatar():return FileResponse(dist/'avatar.png')
    @app.get('/favicon.svg',include_in_schema=False)
    def favicon():return FileResponse(dist/'favicon.svg')
    app=WebProjectHostMiddleware(app,lambda:Session(notes.engine))
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    source,target=f'https://stella.test:{port}',f'https://pages.test:{port}'
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([{'service_id':'stella','public':source},{'service_id':'web-project-runtime','public':target}]))
    key,cert=tmp_path/'key.pem',tmp_path/'cert.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=stella.test','-addext','subjectAltName=DNS:stella.test,DNS:pages.test','-keyout',str(key),'-out',str(cert)],check=True,capture_output=True)
    pub=x509.load_pem_x509_certificate(cert.read_bytes()).public_key().public_bytes(Encoding.DER,PublicFormat.SubjectPublicKeyInfo)
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning',lifespan='off',ssl_keyfile=str(key),ssl_certfile=str(cert),proxy_headers=False));thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    spec={'source':source,'target':target,'port':port,'token':notes.token,'spki':base64.b64encode(hashlib.sha256(pub).digest()).decode(),'evidence':str(evidence),'zip':str(original),'workspace':str(notes.wid),'source_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    thread.start()
    try:
        end=time.monotonic()+8
        while not server.started and time.monotonic()<end:time.sleep(.02)
        assert server.started
        node='/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'
        result=subprocess.run([node,str(ROOT/'frontend/tests/notes-original-package-real.mjs')],env={**os.environ,'NODE_ENV':'test','STELLA_PROJECT_FIXTURE':json.dumps(spec)},capture_output=True,text=True,timeout=240)
        (evidence/'browser.log').write_text(result.stdout+result.stderr)
        receipt=json.loads((evidence/'browser-results.json').read_text())
        assert result.returncode==0,result.stdout+result.stderr
        assert receipt['passed'],receipt
        with Session(notes.engine) as db:
            project=web_projects.manifest(db,notes.uid,receipt['project_id'])
            paths={f['path'] for f in project['files']}
            assert paths==set(original_files),(paths,set(original_files))
            for name,h in original_files.items():assert hashlib.sha256(web_projects.read_file(db,notes.uid,receipt['project_id'],name)[0]).hexdigest()==h,name
            assert project['entry']=='index.html'
        assert hashlib.sha256(original.read_bytes()).hexdigest()==original_hash
        (evidence/'PARENT-READBACK.json').write_text(json.dumps({'real_pg_original_files_retained':len(original_files),'entry':'index.html','original_zip_sha256':original_hash,'project_id':receipt['project_id'],'ui_receipt':receipt,'boundary':'real built Vue/current routers/owned random PG and seeded auth fixture; not production login or user data'},ensure_ascii=False,indent=2))
    finally:
        server.should_exit=True;thread.join(10)
        assert not thread.is_alive(),'owned HTTP server stopped'
