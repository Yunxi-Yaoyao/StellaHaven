"""Project import services on real disposable PG; binary ownership survives copies."""
import io,zipfile
from uuid import uuid4
from sqlalchemy.orm import Session
from fastapi import HTTPException
import pytest
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes

def test_web_project_preserves_source_and_binary_copy_survives_project_delete(notes):
 from app.services import web_projects as projects,blob_store
 from app.models.attachment import Attachment
 raw=io.BytesIO()
 with zipfile.ZipFile(raw,'w') as z:
  z.writestr('index.html','<h1>原页面</h1><script src="js/app.js"></script><img src="images/x.png">')
  z.writestr('js/app.js','localStorage.setItem("progress","1");')
  z.writestr('images/x.png',b'\x89PNG\r\n\x1a\nfixture')
 ident=uuid4()
 with Session(notes.engine) as db:
  result=projects.create(db,notes.uid,notes.wid,None,ident,raw.getvalue(),'web.zip','index.html')
  replay=projects.create(db,notes.uid,notes.wid,None,ident,raw.getvalue(),'web.zip','index.html')
  assert replay['id']==result['id']
  root=result['id']
  manifest=projects.manifest(db,notes.uid,root)
  assert {f['path'] for f in manifest['files']}=={'index.html','js/app.js','images/x.png'}
  source=projects.read_file(db,notes.uid,root,'js/app.js');assert source[0]==b'localStorage.setItem("progress","1");'
  copied=projects.copy_asset(db,notes.uid,root,'images/x.png',notes.did,uuid4())
  assert copied['url'].startswith('/attachments/')
  notes.svc.permanently_delete_document(db,root)
  from app.models.config import AppConfig
  assert db.get(AppConfig,'web-project:'+str(root)) is None
  assert db.get(AppConfig,'web-project-state:'+str(root)) is None
  att=db.get(Attachment,copied['id']);assert att and att.doc_id==notes.did
  assert b''.join(blob_store.read_range(db,'attachments/'+str(att.id),0,att.size))==b'\x89PNG\r\n\x1a\nfixture'
  with pytest.raises(HTTPException):projects.manifest(db,notes.uid,root)

def test_runtime_grant_requires_current_session_and_exact_entry(notes,monkeypatch):
 import json
 from app.services import web_projects as projects,web_project_runtime as runtime
 monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([{'service_id':'stella','public':'https://stella.test','private':'https://stella.p.test'},{'service_id':'web-project-runtime','public':'https://pages.test','private':'https://pages.p.test'}]))
 raw=io.BytesIO()
 with zipfile.ZipFile(raw,'w') as z:z.writestr('index.html','<html><head></head><body><script>localStorage.setItem("score","1")</script></body></html>')
 with Session(notes.engine) as db:
  result=projects.create(db,notes.uid,notes.wid,None,uuid4(),raw.getvalue(),'test.zip','index.html');root=result['id']
  grant=runtime.launch(db,notes.uid,root,notes.sid,'https://stella.p.test');cap=grant['capability']
  assert grant['url'].startswith('https://pages.p.test/p/')
  with pytest.raises(HTTPException):runtime.resource(db,cap,'https://pages.test','index.html')
  body,mime,headers=runtime.resource(db,cap,'https://pages.p.test','index.html')
  assert body.index(b'__stella_storage.js')<body.index(b'localStorage.setItem')
  assert 'sandbox allow-scripts;' in headers['Content-Security-Policy'] and 'allow-same-origin' not in headers['Content-Security-Policy']
  assert headers['Access-Control-Allow-Origin']=='*' and headers['Cache-Control']=='no-store'
  projects.reset_state(db,notes.uid,root)
  with pytest.raises(HTTPException):runtime.resource(db,cap,'https://pages.p.test','index.html')


def test_real_browser_native_storage_restores_from_postgres(notes,monkeypatch,tmp_path):
 import json,subprocess,threading,time,socket,os,hashlib
 from pathlib import Path
 import uvicorn
 from cryptography import x509
 from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
 import base64
 from app.services import web_projects as projects
 from app.routers.web_projects import router
 import app.database as database
 monkeypatch.setattr(database,'sessionLocal',lambda:Session(notes.engine),raising=False)
 from app.routers.web_project_host import WebProjectHostMiddleware
 monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([{'service_id':'stella','public':'https://stella.test','private':'https://stella.p.test'},{'service_id':'web-project-runtime','public':'https://pages.test','private':'https://pages.p.test'}]))
 raw=io.BytesIO()
 with zipfile.ZipFile(raw,'w') as z:z.writestr('index.html','<html><head></head><body><span id="score"></span><button id="inc">增加</button><script>let n=Number(localStorage.getItem("score")||0);document.querySelector("#score").textContent=n;document.querySelector("#inc").onclick=()=>{localStorage.setItem("score",String(++n));document.querySelector("#score").textContent=n;};</script></body></html>')
 with Session(notes.engine) as db:root=projects.create(db,notes.uid,notes.wid,None,uuid4(),raw.getvalue(),'native.zip','index.html')['id']
 notes.client.app.include_router(router)
 app=WebProjectHostMiddleware(notes.client.app,lambda:Session(notes.engine))
 sock=socket.socket();sock.bind(('127.0.0.1',0));server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off',proxy_headers=True,forwarded_allow_ips='127.0.0.1'));thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
 try:
  deadline=time.monotonic()+5
  while not server.started and time.monotonic()<deadline:time.sleep(.01)
  assert server.started
  key=tmp_path/'key.pem';cert=tmp_path/'cert.pem';subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=web-project-synthetic','-keyout',str(key),'-out',str(cert)],check=True,capture_output=True)
  pub=x509.load_pem_x509_certificate(cert.read_bytes()).public_key().public_bytes(Encoding.DER,PublicFormat.SubjectPublicKeyInfo)
  evidence='/opt/hermes-workstation/docs/Stella-界面改版执行-20261017/parent-recheck'
  spec={'root':str(root),'token':notes.token,'backend':'http://127.0.0.1:'+str(sock.getsockname()[1]),'key':str(key),'cert':str(cert),'spki':base64.b64encode(hashlib.sha256(pub).digest()).decode(),'evidence':evidence}
  result=subprocess.run(['node','frontend/tests/web-project-browser.mjs'],env={**os.environ,'STELLA_PROJECT_FIXTURE':json.dumps(spec),'TMPDIR':'/root/.hermes/cache/scratch'},capture_output=True,text=True,timeout=50)
  print(result.stdout);assert result.returncode==0,result.stderr
  with Session(notes.engine) as db:assert projects.read_state(db,notes.uid,root)['data']=={'score':'1'}
 finally:
  server.should_exit=True;thread.join(8);sock.close();assert not thread.is_alive()


def test_project_state_is_owner_scoped_versioned_and_reset_fenced(notes):
 from app.services import web_projects as projects
 raw=io.BytesIO()
 with zipfile.ZipFile(raw,'w') as z:z.writestr('index.html','<p>test</p>')
 with Session(notes.engine) as db:
  result=projects.create(db,notes.uid,notes.wid,None,uuid4(),raw.getvalue(),'web.zip','index.html');root=result['id']
  initial=projects.read_state(db,notes.uid,root);assert initial['data']=={}
  writeid=str(uuid4());saved=projects.write_state(db,notes.uid,root,initial['revision'],initial['epoch'],writeid,{'progress':'2'})
  assert projects.write_state(db,notes.uid,root,initial['revision'],initial['epoch'],writeid,{'progress':'2'})==saved
 with Session(notes.engine) as db:
  assert projects.read_state(db,notes.uid,root)['data']=={'progress':'2'}
  with pytest.raises(HTTPException):projects.read_state(db,uuid4(),root)
  with pytest.raises(HTTPException):projects.write_state(db,notes.uid,root,0,initial['epoch'],str(uuid4()),{'progress':'stale'})
  reset=projects.reset_state(db,notes.uid,root)
  assert reset['data']=={} and reset['epoch']!=initial['epoch']
  with pytest.raises(HTTPException):projects.write_state(db,notes.uid,root,saved['revision'],initial['epoch'],str(uuid4()),{'late':'x'})
