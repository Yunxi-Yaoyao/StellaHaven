"""Independent positive current contracts; original IDs are also upgraded and run."""
import hashlib,json
from uuid import UUID,uuid4
import pytest
from sqlalchemy.orm import Session
from main_fixtures import workspace_id
from app.models.document import Document
from app.models.attachment import Attachment
from app.models.blob import BlobObject
from app.models.document_version import DocumentVersion
from control import OUT

def make_doc(client,workspace_id):
 r=client.post('/documents/',json={'workspace_id':workspace_id,'title':'Current contract','file_path':'/'+uuid4().hex+'.md','content':''})
 assert r.status_code==201,r.text
 return r.json()
def upload(client,doc):
 r=client.post('/attachments/'+doc['id'],files={'file':('contract.txt',b'owned-payload','text/plain')});assert r.status_code==200
 return r.json()
def save_body(client,doc,body,**extra):
 current=client.get('/documents/'+doc['id']).json()
 r=client.put('/documents/'+doc['id'],json={'updated_at':current['updated_at'],'content':body,**extra});assert r.status_code==200,r.text
 return r.json()
def proof(name,data):
 with (OUT/'positive-contract-receipts.jsonl').open('a') as f:f.write(json.dumps({'contract':name,**data})+'\n')
def test_pending_upload_is_not_implicitly_expired(client,db_session,workspace_id):
 doc=make_doc(client,workspace_id);att=upload(client,doc)
 save_body(client,doc,'unrelated text')
 assert client.get(att['url']).content==b'owned-payload'
 with Session(db_session.get_bind()) as fresh:
  assert fresh.get(Attachment,UUID(att['id'])) is not None
  assert fresh.get(BlobObject,'attachments/'+att['id']) is not None
 proof('pending upload retention',{'fresh_pg_metadata':True,'fresh_pg_blob':True,'http_bytes_retained':True})
def test_historical_version_reference_protects_removed_attachment(client,db_session,workspace_id):
 doc=make_doc(client,workspace_id);att=upload(client,doc)
 save_body(client,doc,'![]('+att['url']+')');save_body(client,doc,'reference removed from current body')
 with Session(db_session.get_bind()) as fresh:
  versions=fresh.query(DocumentVersion).filter_by(doc_id=UUID(doc['id'])).all()
  assert any(att['url'] in (v.content or '') for v in versions)
  assert fresh.get(Attachment,UUID(att['id'])) is not None
 assert client.get(att['url']).content==b'owned-payload'
 proof('version reference retention',{'version_contains_reference':True,'attachment_retained':True})
def test_repeated_soft_delete_never_escalates_and_explicit_permanent_deletes(client,db_session,workspace_id):
 doc=make_doc(client,workspace_id);att=upload(client,doc)
 for _ in range(2):assert client.delete('/documents/'+doc['id']).status_code==204
 assert doc['id'] in {d['id'] for d in client.get('/documents/trash',params={'workspace_id':workspace_id}).json()}
 with Session(db_session.get_bind()) as fresh:assert fresh.get(Document,UUID(doc['id'])).deleted_at is not None
 assert client.get(att['url']).content==b'owned-payload'
 assert client.delete('/documents/'+doc['id']+'/permanent').status_code==204
 assert client.get(att['url']).status_code==404
 with Session(db_session.get_bind()) as fresh:
  assert fresh.get(Document,UUID(doc['id'])) is None
  assert fresh.get(Attachment,UUID(att['id'])) is None
  assert fresh.get(BlobObject,'attachments/'+att['id']) is None
 assert client.delete('/documents/'+doc['id']+'/permanent').status_code==204
 proof('soft-delete idempotency and explicit permanent',{'two_soft_deletes_preserve':True,'permanent_removes_doc_attachment_blob':True,'permanent_retry_204':True})
def test_title_only_save_preserves_draft_and_exact_consumption_clears(client,db_session,workspace_id):
 doc=make_doc(client,workspace_id);draft='unconsumed draft'
 with client.websocket_connect('/ws/'+doc['id']+'?device=contract') as ws:
  ws.send_text(json.dumps({'type':'draft','content':draft}))
  while True:
   ack=ws.receive_json()
   if ack.get('type')=='draft_ack':break
 current=client.get('/documents/'+doc['id']).json()
 r=client.put('/documents/'+doc['id'],json={'updated_at':current['updated_at'],'title':'rename only'});assert r.status_code==200
 assert client.get('/documents/'+doc['id']+'/draft').json()['content']==draft
 slot=client.get('/documents/'+doc['id']+'/draft').json()
 save_body(client,doc,draft,consumed_draft={'draft_updated_at':slot['updated_at'],'content_hash':hashlib.sha256(draft.encode()).hexdigest()})
 assert client.get('/documents/'+doc['id']+'/draft').status_code==404
 with Session(db_session.get_bind()) as fresh:
  row=fresh.get(Document,UUID(doc['id']));assert row.draft_content is None and row.content==draft
 proof('draft provenance',{'title_save_retains':True,'exact_consumption_clears':True,'fresh_pg_readback':True})
def test_expired_trash_get_is_readonly_and_owner_purge_needs_no_elevation(client,db_session,workspace_id):
 from datetime import datetime,timedelta
 from fastapi.testclient import TestClient
 from main import app
 from app.models.user import User
 from app.models.workspace import Workspace
 from control import OLD
 doc=make_doc(client,workspace_id)
 assert client.delete('/documents/'+doc['id']).status_code==204
 row=db_session.get(Document,UUID(doc['id']));row.deleted_at=datetime.now()-timedelta(days=31);db_session.commit()
 assert client.post('/auth/admin/lock').status_code==200
 assert client.get('/auth/security').json()['elevated'] is False
 assert doc['id'] in {d['id'] for d in client.get('/documents/trash',params={'workspace_id':workspace_id}).json()}
 with Session(db_session.get_bind()) as fresh:assert fresh.get(Document,UUID(doc['id'])) is not None
 with TestClient(app,headers={'Origin':'http://testserver'}) as anonymous:
  assert anonymous.post('/documents/trash/empty',params={'workspace_id':workspace_id}).status_code==401
 with Session(db_session.get_bind()) as fresh:
  foreign=User(username='retained-'+uuid4().hex,display_name='retained');fresh.add(foreign);fresh.flush()
  ws=Workspace(user_id=foreign.id,name='foreign');fresh.add(ws);fresh.commit();foreign_id=ws.id
 assert client.post('/documents/trash/empty',params={'workspace_id':str(foreign_id)}).status_code==404
 response=client.post('/documents/trash/empty',params={'workspace_id':workspace_id});assert response.status_code==200 and response.json()=={'purged':1}
 with Session(db_session.get_bind()) as fresh:
  assert fresh.get(Document,UUID(doc['id'])) is None
  assert fresh.get(Workspace,foreign_id) is not None
 contract=json.loads((OLD/'r2/API-schema-captured.json').read_text())['paths']['/documents/trash/empty']['post']
 assert contract['x-stella-elevation']=='none'
 proof('owner-only explicit empty trash',{'expired_get_readonly':True,'anonymous_401':True,'foreign_404':True,'ordinary_owner_purge_200':True,'fresh_pg_readback':True,'frozen_openapi_elevation':'none'})

def test_smtp_typed_projection_mask_and_transaction_rollback(client,db_session):
 from app.routers import admin_email
 from app.services import ha_state
 from app.services.small_public_outputs import PublicSMTPConfig
 cfg={'host':'smtp.test','username':'fixture','password':'synthetic-mail-secret'}
 assert client.put('/admin/email/config',json=cfg).status_code==200
 typed=admin_email.get_config(None);assert isinstance(typed,PublicSMTPConfig) and typed.password=='••••••'
 assert client.get('/admin/email/config').json()==typed.model_dump()
 assert client.put('/admin/email/config',json={**cfg,'host':'smtp.changed','password':'••••••'}).status_code==200
 assert admin_email._load()['password']==cfg['password']
 with pytest.raises(RuntimeError):
  with ha_state.locked_state('smtp.config',{}) as state:
   state['password']='must-rollback';raise RuntimeError('controlled')
 with db_session.get_bind().connect() as fresh:
  saved=fresh.execute(ha_state.state_table.select().where(ha_state.state_table.c.key=='smtp.config')).mappings().one()['payload']
  assert saved['password']==cfg['password'] and saved['host']=='smtp.changed'
 proof('SMTP typed projection',{'http_masked':True,'typed_return':True,'masked_write_retains_secret':True,'fresh_pg_rollback':True})
