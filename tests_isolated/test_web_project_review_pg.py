"""Runtime review regressions, only via owned disposable PostgreSQL runner."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes, wait_for_lock

@pytest.mark.parametrize('operation',['rename','move','folder-rename'])
def test_reserved_adapter_path_rename_or_move_rolls_back(notes,operation):
 import io,zipfile
 from app.services import web_projects as projects
 from app.schemas.document import DocumentUpdate
 from app.models.document import Document
 archive=io.BytesIO()
 with zipfile.ZipFile(archive,'w') as z:
  z.writestr('index.html','<p>fixture</p>')
  z.writestr('app.js','window.original=true;')
  z.writestr('nested/__stella_storage.js','window.nested=true;')
 with Session(notes.engine) as db:
  root=projects.create(db,notes.uid,notes.wid,None,uuid4(),archive.getvalue(),'fixture.zip','index.html')['id']
  info=projects.manifest(db,notes.uid,root)
  if operation=='rename':
   ident=next(f['id'] for f in info['files'] if f['path']=='app.js');changes={'title':'__stella_storage.js'}
  elif operation=='move':
   ident=next(f['id'] for f in info['files'] if f['path']=='nested/__stella_storage.js');changes={'parent_id':root}
  else:
   ident=str(db.query(Document).filter_by(parent_id=root,title='nested').one().id);changes={'title':'__stella_storage.js'}
  item=db.get(Document,projects.uid(ident));old_title,old_parent=item.title,item.parent_id
  with pytest.raises(HTTPException) as exc:notes.svc.update_document(db,item.id,DocumentUpdate(updated_at=item.updated_at,**changes))
  assert exc.value.status_code==409
  db.expire_all();item=db.get(Document,projects.uid(ident));assert (item.title,item.parent_id)==(old_title,old_parent)
  assert projects.read_file(db,notes.uid,root,'app.js')[0]==b'window.original=true;'

@pytest.fixture
def project(notes,monkeypatch):
 from app.services import web_projects as projects, web_project_runtime as runtime
 from app.routers.web_projects import router
 monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([{'service_id':'stella','public':'https://stella.test'},{'service_id':'web-project-runtime','public':'https://pages.test'}]))
 notes.client.app.include_router(router)
 with Session(notes.engine) as db:
  root=projects.create(db,notes.uid,notes.wid,None,uuid4(),b'<p>synthetic</p>','index.html','index.html')['id']
  grant=runtime.launch(db,notes.uid,root,notes.sid,'https://stella.test')
 return root,grant

def put(notes,project,data,token=None):
 root,grant=project
 return notes.client.put('https://stella.test/web-projects/'+str(root)+'/state',headers={'Origin':'https://stella.test','Cookie':'stella_at='+(token or notes.token)},json={'revision':0,'epoch':0,'write_id':str(uuid4()),'data':data,'capability':grant['capability']})

def test_capability_bound_to_authenticated_sid(notes,project):
 from app.security import make_access_token
 second=uuid4()
 with Session(notes.engine) as db:
  db.add(notes.models.AuthSession(id=second,user_id=notes.uid,refresh_hash=str(second),created_at=notes.now,last_seen=notes.now));db.commit()
 response=put(notes,project,{'wrong':'sid'},make_access_token(str(notes.uid),str(second)))
 assert response.status_code==403,response.text
 assert put(notes,project,{'correct':'sid'}).status_code==200

def test_state_transport_is_bounded_before_json_parse(notes,project):
 from app.services import web_projects as projects
 # Invalid JSON deliberately: bounded rejection must precede JSON parsing.
 # Chunked streaming prevents trusting only a declared Content-Length.
 response=notes.client.put('https://stella.test/web-projects/'+str(project[0])+'/state',headers={'Origin':'https://stella.test','Cookie':'stella_at='+notes.token,'Content-Type':'application/json'},content=(b'x'*1048576 for _ in range(7)))
 assert response.status_code==413,response.text[:200]
 with Session(notes.engine) as db:assert projects.read_state(db,notes.uid,project[0])['revision']==0

@pytest.mark.parametrize('data',[{'k':'x'*(1048576-8)},{'键':'中'*349522}])
def test_compact_utf8_quota_boundary(notes,project,data):
 from app.services import web_projects as projects
 assert len(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode())<=1048576
 response=put(notes,project,data);assert response.status_code==200,response.text[:200]
 with Session(notes.engine) as db:assert projects.read_state(db,notes.uid,project[0])['data']==data

@pytest.mark.parametrize('data',[{'k':'\ud800'},{'\udfff':'v'}])
def test_surrogate_is_controlled_and_state_unchanged(notes,project,data):
 from app.services import web_projects as projects
 # Escaped JSON permits transport while preserving the malformed string.
 response=notes.client.put('https://stella.test/web-projects/'+str(project[0])+'/state',headers={'Origin':'https://stella.test','Cookie':'stella_at='+notes.token,'Content-Type':'application/json'},content=json.dumps({'revision':0,'epoch':0,'write_id':str(uuid4()),'data':data,'capability':project[1]['capability']}))
 assert response.status_code==422,response.text
 with Session(notes.engine) as db:assert projects.read_state(db,notes.uid,project[0])['revision']==0

@pytest.mark.parametrize('change',['revoke','expire','relaunch'])
def test_authorization_rechecked_after_actual_pg_workspace_wait(notes,project,monkeypatch,change):
 from app.services import web_projects as projects,web_project_runtime as runtime
 from app.models.config import AppConfig
 from app.models.user import AuthSession
 from app.services.notes_tools import lock_key
 original=projects.lock_workspace;waiting=threading.Event();pids={}
 def observed(db,wid,*args,**kwargs):
  pids['waiter']=db.execute(text('select pg_backend_pid()')).scalar_one();waiting.set()
  return original(db,wid,*args,**kwargs)
 monkeypatch.setattr(projects,'lock_workspace',observed)
 with Session(notes.engine) as blocker:
  pids['blocker']=blocker.execute(text('select pg_backend_pid()')).scalar_one()
  lock_key(blocker,'document-tree:'+str(notes.wid))
  with ThreadPoolExecutor(max_workers=1) as pool:
   future=pool.submit(put,notes,project,{'late':'no'})
   try:
    assert waiting.wait(5)
    wait_for_lock(notes.engine,pids['waiter'],pids['blocker'])
    with Session(notes.engine) as other:
     if change=='revoke':other.get(AuthSession,notes.sid).revoked=True;other.commit()
     elif change=='expire':
      row=other.get(AppConfig,runtime.key(project[1]['capability']));value=json.loads(row.value);value['expires']=0;row.value=json.dumps(value);other.commit()
     else:runtime.launch(other,notes.uid,project[0],notes.sid,'https://stella.test')
   finally:blocker.rollback()
   response=future.result(timeout=8)
  assert response.status_code==403,response.text
 with Session(notes.engine) as db:assert projects.read_state(db,notes.uid,project[0])['revision']==0
