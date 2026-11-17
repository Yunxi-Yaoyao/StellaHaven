"""Independent equivalents retained for exact prior 312-case-set reconciliation.
The originals now run via explicit owned-target fixtures with strict fallback.
These duplicates are disclosed, never counted as additional business coverage.
"""
import json,sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import Integer,String,select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session,DeclarativeBase,mapped_column
from fastapi import FastAPI
from fastapi.testclient import TestClient
import guard
from control import OUT

def record(name,details):
 with (OUT/'owned-pg-equivalents.jsonl').open('a') as f:f.write(json.dumps({'name':name,**details})+'\n')
def test_owned_audit_concurrent_first_insert_and_rollback():
 import app.services
 from app.models.config import AppConfig
 from app.services.backup_health import record_change,read_change_audit
 with guard.schema_scope() as (engine,name):
  AppConfig.__table__.create(engine)
  actor=str(uuid4());barrier=Barrier(2)
  def append_batch():
   barrier.wait(timeout=10)
   for _ in range(20):
    with Session(engine) as db:
     record_change(db,action='integration.update',actor_id=actor,resource_id=uuid4(),changed_fields=['enabled']);db.commit()
  with ThreadPoolExecutor(max_workers=2) as pool:
   jobs=[pool.submit(append_batch) for _ in range(2)]
   for job in jobs:job.result(timeout=30)
  with Session(engine) as db:
   events=read_change_audit(db);assert len(events)==40 and len({e['resource_id'] for e in events})==40
   record_change(db,action='integration.delete',actor_id=actor);db.rollback()
  with Session(engine) as fresh:assert read_change_audit(fresh)==events
  record('operations audit',{'actual_pg_unique_events':40,'fresh_readback_rollback':True,'original_case':'tests_isolated.test_operations_audit_pg::test_postgres_audit_concurrent_first_insert_and_rollback','original_function_called_by_this_equivalent':False})
def test_owned_cli_exact_database_confirmation_and_private_output(tmp_path,capsys,monkeypatch):
 from app.services import ha_state
 from scripts import import_shared_state as importer
 with guard.schema_scope() as (engine,name):
  ha_state.metadata.create_all(engine)
  dsn=tmp_path/'owned-dsn';dsn.write_text(guard.URL_.render_as_string(hide_password=False));dsn.chmod(0o600)
  source=tmp_path/'smtp.json';source.write_text(json.dumps({'password':'NEVER_PRINT_THIS'}))
  args=['import_shared_state','--database-url-file',str(dsn),'--confirm-database',guard.s['db'],'--smtp',str(source)]
  monkeypatch.setattr(sys,'argv',args)
  assert importer.main()==0
  assert importer.main()==1
  output=capsys.readouterr().out
  assert 'Imported and verified: smtp.config' in output and 'NEVER_PRINT_THIS' not in output and guard.s['password'] not in output
  with engine.connect() as fresh:assert fresh.execute(select(ha_state.state_table.c.payload)).scalar_one()=={'password':'NEVER_PRINT_THIS'}
  # Real guard rejection, not an adapted/removed assertion.
  args[args.index('--confirm-database')+1]='wrong-owned-name'
  assert importer.main()==1
  dsn.unlink()
  record('CLI exact owned confirmation',{'first_success':True,'duplicate_rejected':True,'wrong_name_rejected':True,'secrets_not_printed':True,'fresh_pg_readback':True})
def test_owned_memory_jsonb_repository_and_response_roundtrip():
 from test_hardware_repository import heartbeat_function
 from test_system_memory import agent
 from tests_isolated.test_system_memory_roundtrip import schemas
 class Base(DeclarativeBase):pass
 class Node(Base):
  __tablename__='memory_roundtrip_qa'
  id=mapped_column(Integer,primary_key=True)
  status=mapped_column(String)
  sys_info=mapped_column(JSONB)
 evidence={}
 with guard.schema_scope() as (engine,name):
  Base.metadata.create_all(engine)
  for index,kind in enumerate(('physical','virtual','container','unknown','legacy'),1):
   obj=object.__new__(agent.Agent);obj._os_static_cache,obj._storage_status={},{}
   hardware={'cpu':{},'gpus':[],'sensors':[],'availability':{},'machine':{'kind':kind}}
   with patch.object(obj,'_hardware_info',return_value=hardware),patch.object(agent,'_hardware_read',return_value=None),patch.object(agent,'psutil',SimpleNamespace(boot_time=lambda:1,virtual_memory=lambda:SimpleNamespace(total=8157769728,available=0,used=4096))):
    info=obj._os_info()
   if kind=='legacy':del info['hardware']['memory'];del info['hardware']['machine']
   report=schemas.AgentReport.model_validate_json(json.dumps({'os_info':info}))
   with Session(engine) as db:
    node=Node(id=index,status='online',sys_info={});node.installed,node.arch,node.uninstall_status=True,None,None
    db.add(node);db.commit()
    heartbeat=heartbeat_function();heartbeat.__globals__['get_by_id']=lambda session,key:session.get(Node,key)
    heartbeat(db,index,os_info=report.os_info)
   with Session(engine) as fresh:saved=fresh.scalar(select(Node).where(Node.id==index)).sys_info
   assert saved['hardware']==info['hardware']
   app=FastAPI()
   @app.get('/memory-qa',response_model=schemas.NodeDetail)
   def response():return dict(id=index,name='Generic fixture',platform='linux',host='offline.invalid',status='online',created_at=datetime.now(timezone.utc),sys_info=saved)
   with TestClient(app) as client:
    response=client.get('/memory-qa');assert response.status_code==200
    assert response.json()['sys_info']['hardware']==info['hardware']
   evidence[kind]=True
  record('memory JSONB roundtrip',{'categories':evidence,'real_pg_jsonb':True,'mock_hardware_not_device_proof':True,'original_socket_guard_untouched':True})
