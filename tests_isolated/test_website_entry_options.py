"""Bounded website entry settings: no infrastructure or identity mutation."""
import json
import pytest
from fastapi import HTTPException
from app.services import entry_registry as registry
from tests_website_settings.test_website_settings import upstream
P='https://stella.test';L='https://stella.p.test'

@pytest.fixture
def api_env(tmp_path,monkeypatch):
 """Real persisted identities, private copied DDL, real entry-snapshot middleware."""
 from datetime import datetime,timezone
 from uuid import UUID,uuid4
 from fastapi import FastAPI
 from fastapi.testclient import TestClient
 from sqlalchemy import JSON,MetaData,create_engine
 from sqlalchemy.dialects.postgresql import JSONB
 from sqlalchemy.orm import sessionmaker
 from app.database import get_db
 from app.models.config import AppConfig
 from app.models.user import User,AuthSession
 from app.models.node import Node
 from app.models.monitor import MonitorGroup
 from app.routers.integrations import router
 from app.routers.website_settings import router as settings_router
 from app.routers.config import router as config_router
 from app.routers.integrations_host import IntegrationsHostMiddleware
 from app.security import make_access_token
 from app.services import admin_security
 monkeypatch.delenv('STELLA_OWNER_ID',raising=False)
 monkeypatch.setenv('STELLA_TRUSTED_ORIGINS',P+','+L+',http://stella.test')
 engine=create_engine('sqlite:///'+str(tmp_path/'website.sqlite'),connect_args={'check_same_thread':False})
 metadata=MetaData()
 for original in (AppConfig.__table__,User.__table__,AuthSession.__table__,Node.__table__,MonitorGroup.__table__):
  table=original.to_metadata(metadata)
  for column in table.columns:
   if isinstance(column.type,JSONB):column.type=JSON()
 metadata.create_all(engine)
 factory=sessionmaker(engine,expire_on_commit=False)
 uid=UUID('00000000-0000-4000-8000-000000000001');sid=uuid4();now=datetime.now(timezone.utc)
 with factory() as db:
  db.add(User(id=uid,username='owner',display_name='Owner'));db.flush()
  db.add(AuthSession(id=sid,user_id=uid,refresh_hash='synthetic',remember=True,created_at=now,last_seen=now))
  db.add(AppConfig(key=admin_security.STATE_KEY,value=json.dumps({'owner_id':str(uid),'grants':{}})));db.commit()
 app=FastAPI();app.include_router(settings_router);app.include_router(router);app.include_router(config_router)
 def database():
  with factory() as db:yield db
 app.dependency_overrides[get_db]=database
 app.add_middleware(IntegrationsHostMiddleware,db_factory=factory,main_origin='http://stella.test')
 try:
  with TestClient(app,base_url='http://stella.test') as client:
   client.cookies.set('stella_at',make_access_token(str(uid),str(sid)))
   assert set(app.dependency_overrides)=={get_db}
   yield client,factory,app,[]
 finally:engine.dispose()

@pytest.fixture
def mapped(monkeypatch):
 monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([{'service_id':'stella','public':P,'private':L},{'service_id':'site','public':'https://site.test','private':'https://site.p.test'}]))
 return {'id':'site','mode':'iframe','browser_url':'https://site.test/path?q=1#x','private_address':'https://site.p.test/private?q=2#y','entry_policy':'follow'}

def test_explicit_private_suffix_and_public_policy(mapped):
 assert registry.browser_url(mapped,L)==mapped['private_address']
 mapped['entry_policy']='public'
 assert registry.browser_url(mapped,L)==mapped['browser_url']
 with pytest.raises(HTTPException):registry.browser_url(mapped,'https://evil.test')

def test_private_address_requires_exact_deployed_mapping(mapped):
 registry.validate_website_entry(mapped)
 for private in ['https://evil.test/','https://site.p.test.evil/','http://site.p.test/','https://site.p.test:444/']:
  with pytest.raises(HTTPException):registry.validate_website_entry(mapped|{'private_address':private})
 # Direct destinations are not Host trust; proxy origins still need deployment.
 registry.validate_website_entry(mapped|{'id':'not-deployed'})
 assert 'not-deployed' not in registry.records()
 registry.validate_website_entry(mapped|{'mode':'isolated_proxy'})
 with pytest.raises(HTTPException):registry.validate_website_entry(mapped|{'id':'not-deployed','mode':'isolated_proxy'})
 with pytest.raises(HTTPException):registry.module_context(mapped|{'id':'not-deployed','origin':'https://site.test'},L)
 registry.validate_website_entry(mapped|{'mode':'isolated_proxy','private_address':None,'entry_policy':'public'})

@pytest.mark.parametrize('mode',['iframe','link','isolated_proxy'])
def test_saved_entry_validates_the_mode_specific_browser_host(mapped,mode):
 # Direct persistence keeps an unrelated internal proxy Host; proxy persistence
 # keeps the upstream browser_url separate from its deployed browser Host.
 module=mapped|{'mode':mode,'origin':'https://site.test' if mode=='isolated_proxy' else 'https://app-internal.test'}
 if mode=='isolated_proxy':module['browser_url']='https://upstream.test/path'
 before=registry.records()
 registry.validate_website_entry(module)
 assert registry.records()==before
 if mode!='isolated_proxy':
  assert registry.browser_url(module,L)==module['private_address']
  assert registry.browser_url(module,P)==module['browser_url']
 # Neither the irrelevant field nor suffix lookalikes can rescue a wrong Host.
 field='origin' if mode=='isolated_proxy' else 'browser_url'
 for wrong in ['https://evil.test/path','https://site.test.evil/path','https://site.test:444/path']:
  with pytest.raises(HTTPException) as rejected:
   registry.validate_website_entry(module|{field:wrong})
  assert rejected.value.status_code==422
 for wrong in ['https://evil.test/','https://site.p.test.evil/','https://site.p.test:444/']:
  with pytest.raises(HTTPException) as rejected:
   registry.validate_website_entry(module|{'private_address':wrong})
  assert rejected.value.status_code==422
 assert registry.records()==before


def test_loader_uses_exact_selected_entry_and_never_unregistered_origin(api_env,mapped):
 from app.services import integrations as store
 from app.services.website_assets import asset_code
 _,factory,_,_=api_env
 with factory() as db,store.edit(db) as state:
  state['modules']['site']=mapped|{'enabled':True,'connection':{'injection_delivery':'loader'},'injection':{'active':{'enabled':True,'css':'','js':'window.fixture=1','version':'v1','timing':'dom_ready'}}}
 with factory() as db:
  code=asset_code(db,'site',custom_allowed=True,parent_origin=L)
  assert '"origin": "https://site.p.test"' in code
  with pytest.raises(HTTPException):asset_code(db,'site',custom_allowed=True,parent_origin='https://evil.test')

def test_checks_use_exact_request_parent_and_reject_unknown_host(api_env,upstream,mapped):
 c,_,_,_=api_env;root,_,_=upstream
 response=c.post(L+'/website-settings/check',json={'address':root+'/'})
 assert response.status_code==200,response.text
 assert response.json()['embedding']['reason_code']=='isolated_https_proxy'
 assert response.json()['embedding']['status']=='allowed'
 direct=c.post(L+'/website-settings/check',json={'address':root+'/','connection':{'transport':'direct','injection_delivery':'loader'}})
 assert direct.status_code==200,direct.text
 assert direct.json()['embedding']['reason_code']=='mixed_content'
 assert direct.json()['can_save'] is False
 rejected=c.post('https://evil.test/website-settings/check',json={'address':root+'/'},headers={'X-Forwarded-Host':'stella.test'})
 assert rejected.status_code==403

def test_real_tls_private_save_readback_and_launch_without_credentials(api_env,tmp_path,monkeypatch):
 import ssl,subprocess,threading
 from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
 from app.services import integrations_proxy as proxy
 c,factory,_,_=api_env
 cert=tmp_path/'cert.pem';key=tmp_path/'key.pem'
 subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1'],check=True,capture_output=True)
 ca=ssl.create_default_context(cafile=str(cert));native_transport=proxy.httpx.AsyncHTTPTransport
 def transport(*args,**kwargs):return native_transport(*args,**(kwargs|{'verify':ca}))
 monkeypatch.setattr(proxy.httpx,'AsyncHTTPTransport',transport)
 seen=[]
 class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
   seen.append((self.server.server_port,self.path,dict(self.headers)));body=b'<html><head><title>TLS fixture</title></head><body>owned</body></html>'
   self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  def log_message(self,*args):pass
 servers=[];threads=[]
 try:
  for _ in range(2):
   server=ThreadingHTTPServer(('127.0.0.1',0),Handler);context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key);server.socket=context.wrap_socket(server.socket,server_side=True)
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();servers.append(server);threads.append(thread)
  public,private=[f'https://127.0.0.1:{s.server_port}' for s in servers]
  rows=[{'service_id':'stella','public':P,'private':L}];monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps(rows))
  body={'address':public+'/','idempotency_key':'tls-entry-save','connection':{'transport':'direct','injection_delivery':'loader'}}
  created=c.post(P+'/website-settings',json=body);assert created.status_code==201,created.text
  mid=created.json()['id'];rows.append({'service_id':mid,'public':public,'private':private});monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps(rows))
  saved=c.patch(P+'/website-settings/'+mid,json={'address':public+'/','private_address':private+'/private?q=2#section','entry_policy':'follow'})
  assert saved.status_code==200,saved.text
  read=c.get('/external-modules/'+mid).json();assert read['private_address']==private+'/private?q=2#section'
  inherited=c.post(L+'/external-modules/'+mid+'/launch')
  assert inherited.status_code==200,inherited.text
  assert inherited.json()['url']==private+'/private?q=2#section'
  assert inherited.json()['target_origin']==private
  # Deployed defaults work before an owner override; an explicit null still rejects.
  from app.models.config import AppConfig
  from app.services import access_entries
  with factory() as db:
   db.add(AppConfig(key=access_entries.KEY,value=json.dumps({'owner_id':'00000000-0000-4000-8000-000000000001','settings':{'revision':0,'enabled':False,'public_origin':P,'private_origin':None}})))
   db.commit()
  rejected=c.post(L+'/external-modules/'+mid+'/launch')
  assert rejected.status_code==409,rejected.text
  draft=c.get(P+'/config/access-entries').json()['settings']|{'private_origin':L}
  checked=c.post(P+'/config/access-entries/check',json=draft)
  assert checked.status_code==200 and checked.json()['can_apply'] is True,checked.text
  applied=c.put(P+'/config/access-entries',json=draft|{'checked_digest':checked.json()['digest']})
  assert applied.status_code==200,applied.text
  assert c.get(P+'/config/access-entries').json()['settings']==draft|{'revision':1}
  from app.models.config import AppConfig
  from app.services import access_entries
  with factory() as db:assert json.loads(db.get(AppConfig,access_entries.KEY).value)['settings']==draft|{'revision':1}
  launched=c.post(L+'/external-modules/'+mid+'/launch')
  public_launch=c.post(P+'/external-modules/'+mid+'/launch')
  always=c.patch(P+'/website-settings/'+mid,json={'address':public+'/','entry_policy':'public'});assert always.status_code==200,always.text
  policy_launch=c.post(L+'/external-modules/'+mid+'/launch')
  with factory() as db:
   from app.services import integrations as store
   assert store.state(db)['modules'][mid]['entry_policy']=='public'
  assert any(port==servers[1].server_port and path=='/private?q=2' for port,path,_ in seen)
  assert all(not any(k.lower() in {'authorization','cookie'} for k in headers) for _,_,headers in seen)
  # Keep this assertion RED if saved direct-site origin and registry disagree;
  # do not rewrite persisted product output or bypass launch validation.
  assert [launched.status_code,public_launch.status_code,policy_launch.status_code]==[200,200,200],{'private':launched.json(),'public':public_launch.json(),'public_policy':policy_launch.json(),'saved_origin':read['origin'],'public_address':public,'registry':registry.records()[mid]}
  assert launched.json()['url']==read['private_address']
  assert public_launch.json()['url']==public+'/'
  assert policy_launch.json()['url']==public+'/'
 finally:
  for server in servers:server.shutdown();server.server_close()
  for thread in threads:thread.join(3);assert not thread.is_alive()

def test_entry_policy_saved_read_back_and_omitted_patch_preserves_it(api_env,upstream):
 c,factory,_,_=api_env;root,_,_=upstream
 data={'address':root+'/','entry_policy':'public','idempotency_key':'entry-policy-only','connection':{'transport':'direct','injection_delivery':'loader'}}
 saved=c.post('/website-settings',json=data)
 assert saved.status_code==201,saved.text
 mid=saved.json()['id'];assert saved.json()['entry_policy']=='public'
 assert c.get('/external-modules/'+mid).json()['entry_policy']=='public'
 updated=c.patch('/website-settings/'+mid,json={'address':root+'/','name':'Kept'})
 assert updated.status_code==200,updated.text
 assert updated.json()['entry_policy']=='public'
 from app.services import integrations as store
 with factory() as db:assert store.state(db)['modules'][mid]['entry_policy']=='public'
 assert 'DNS' not in updated.text


@pytest.mark.parametrize('identity,status',[('anonymous',401),('foreign',403),('owner',200)])
def test_entry_checks_use_real_identity_without_grants(api_env,mapped,identity,status):
 from datetime import datetime,timezone
 from uuid import uuid4
 from app.models.config import AppConfig
 from app.models.user import User,AuthSession
 from app.security import make_access_token
 from app.services import access_entries,admin_security
 c,factory,app,_=api_env
 draft={'revision':0,'enabled':False,'public_origin':P,'private_origin':L}
 if identity!='owner':
  c.cookies.clear()
  if identity=='foreign':
   uid,sid=uuid4(),uuid4();now=datetime.now(timezone.utc)
   with factory() as db:
    db.add(User(id=uid,username='foreign',display_name='Foreign',is_admin=True));db.flush()
    db.add(AuthSession(id=sid,user_id=uid,refresh_hash='foreign',remember=True,created_at=now,last_seen=now));db.commit()
   c.cookies.set('stella_at',make_access_token(str(uid),str(sid)))
 assert len(app.dependency_overrides)==1
 response=c.post(P+'/config/access-entries/check',json=draft)
 assert response.status_code==status,response.text
 with factory() as db:
  assert db.get(AppConfig,access_entries.KEY) is None
  assert json.loads(db.get(AppConfig,admin_security.STATE_KEY).value)['grants']=={}
 if identity=='owner':assert response.json()['can_apply'] is True
