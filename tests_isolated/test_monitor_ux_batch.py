"""Owned in-memory database, actual HTTP router; no configured application startup."""
import pytest
from test_node_monitor_policy import node
from test_monitor_group_delete import db, sqlite_db
from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember

def test_real_app_monitor_ux_over_owned_pg(db):
 import os, socket, threading, subprocess, time, json
 from pathlib import Path
 from types import SimpleNamespace
 from fastapi import FastAPI, Request
 from sqlalchemy.orm import Session
 from app.routers.monitor import monitor_router
 from app.routers.auth import current_user, admin_user
 from app.database import get_db
 from app.models.monitor import MonitorCheck
 from app.models.task import MtrTask
 from app.models.config import AppConfig
 from app.models.node import Node
 import uvicorn
 if not os.environ.get('STELLA_MONITOR_UX_BROWSER'):
  pytest.skip('explicit owned-PG actual App browser required')
 assert db.get_bind().dialect.name=='postgresql'
 for table in (MonitorCheck.__table__,MtrTask.__table__):table.create(db.get_bind(),checkfirst=True)
 bind=db.get_bind();db.rollback()
 app=FastAPI();app.include_router(monitor_router)
 def session():
  with Session(bind,autoflush=False) as own:yield own
 def user(request:Request):
  request.state.auth_session=SimpleNamespace(id='owned-browser-session')
  return object()
 app.dependency_overrides[get_db]=session;app.dependency_overrides[current_user]=user;app.dependency_overrides[admin_user]=lambda:object()
 @app.post('/_fixture/reset')
 def reset():
  with Session(bind) as own:
   for model in (MtrTask,MonitorCheck,MonitorGroupMember,Monitor,MonitorGroup,AppConfig,Node):own.execute(model.__table__.delete())
   n=Node(name='隔离探测节点',host='192.0.2.7',platform='linux',status='pending');own.add(n);own.flush()
   g=MonitorGroup(name='业务监控组');own.add(g);own.flush()
   m=Monitor(name='组内探测',node_id=n.id,type='https',target='https://example.com:8443/legacy?q=1#x');own.add(m);own.flush();own.add(MonitorGroupMember(group_id=g.id,monitor_id=m.id,position=0))
   own.commit();return dict(node_id=n.id,group_id=g.id,member_id=m.id)
 @app.get('/_fixture/state')
 def state():
  with Session(bind) as own:
   return dict(monitors=[dict(id=m.id,name=m.name,type=m.type,target=m.target) for m in own.query(Monitor).order_by(Monitor.id)],groups=[dict(id=g.id,name=g.name,child_ids=[m.monitor_id for m in own.query(MonitorGroupMember).filter_by(group_id=g.id)]) for g in own.query(MonitorGroup)],checks=own.query(MonitorCheck).count())
 sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
 server=uvicorn.Server(uvicorn.Config(app,log_level='warning',lifespan='off'));thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
 try:
  for _ in range(100):
   if server.started:break
   time.sleep(.02)
  assert server.started
  env={k:v for k,v in os.environ.items() if k not in ('NODE_ENV','PYTHONPATH')};env.update(STELLA_MONITOR_UX_HTTP=f'http://127.0.0.1:{sock.getsockname()[1]}',PLAYWRIGHT_BROWSERS_PATH='/root/.cache/ms-playwright')
  root=Path(__file__).resolve().parents[1]
  run=subprocess.run(['/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node',str(root/'frontend/src/modules/servers/monitorUxBatch.browser.mjs')],cwd=root/'frontend',env=env,capture_output=True,text=True,timeout=180)
  out=Path(os.environ['STELLA_MONITOR_UX_OUT']);out.mkdir(parents=True,exist_ok=True);(out/'browser-execution.log').write_text(run.stdout+run.stderr)
  assert run.returncode==0,run.stdout+run.stderr
  result=json.loads((out/'browser-result.json').read_text());assert result['passed'] and len(result['checks'])==2
 finally:
  server.should_exit=True;thread.join(timeout=10);sock.close();assert not thread.is_alive()


def test_existing_group_batch_checks_uuid_capacity_and_session_receipt_without_rewriting_members(db):
 from app.services.monitor_batches import create, receipt, BatchConflict
 from app.schemas.monitor import MonitorBatchCreate
 n=node(db); g=MonitorGroup(name='kept',failure_policy='any',rotation_seconds=0); db.add(g); db.commit()
 data=MonitorBatchCreate(items=[dict(name='HTTP',type='http',target='http://example.com:80',node_id=n.id)],group_id=g.id,expected_group_uuid=g.stable_uuid,request_key='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
 result=create(db,data,session_id='session')
 assert result['group_id']==g.id
 assert db.query(MonitorGroup).count()==1
 assert [m.monitor_id for m in db.query(MonitorGroupMember)]==result['monitor_ids']
 assert receipt(db,data.request_key,'other') is None
 assert create(db,data,session_id='session')==result
 replacement=data.model_copy(update={'request_key':'cccccccc-cccc-4ccc-8ccc-cccccccccccc','expected_group_uuid':'dddddddd-dddd-4ddd-8ddd-dddddddddddd'})
 with pytest.raises(BatchConflict,match='身份'):
  create(db,replacement,session_id='session')
 assert db.query(Monitor).count()==1
 for i in range(11):
  m=Monitor(name=str(i),type='ping',target='example.com',node_id=n.id);db.add(m);db.flush();db.add(MonitorGroupMember(group_id=g.id,monitor_id=m.id,position=i+1))
 db.commit()
 with pytest.raises(ValueError,match='12'):
  create(db,data.model_copy(update={'request_key':'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'}),session_id='session')
 assert db.query(Monitor).count()==12


def test_protected_and_mismatched_destinations_are_zero_write(db):
 import json
 from app.models.config import AppConfig
 from app.services.monitor_batches import create, BatchConflict
 from app.schemas.monitor import MonitorBatchCreate
 from app.repositories.config import get_monitors_version
 n=node(db);g=MonitorGroup(name='automatic');db.add(g);db.flush();db.add(AppConfig(key='entry_monitoring.groups.v1',value=json.dumps({'owned':dict(group_id=g.id,group_uuid=g.stable_uuid,purpose='node_to_center',lifecycle=2)})));db.commit()
 data=MonitorBatchCreate(items=[dict(name='probe',type='ping',target='example.com',node_id=n.id)],group_id=g.id,expected_group_uuid=g.stable_uuid,request_key='ffffffff-ffff-4fff-8fff-ffffffffffff')
 before=get_monitors_version(db)
 with pytest.raises(ValueError,match='系统'):
  create(db,data,session_id='session')
 with pytest.raises(BatchConflict):
  create(db,data.model_copy(update={'expected_group_uuid':None}),session_id='session')
 assert db.query(Monitor).count()==0 and db.query(MonitorGroupMember).count()==0
 assert get_monitors_version(db)==before
 assert db.get(AppConfig,'monitor_group.create_receipts.v1') is None


def test_parallel_pg_batch_replays_one_receipt_and_one_set(db):
 from concurrent.futures import ThreadPoolExecutor
 from sqlalchemy.orm import Session
 from app.services.monitor_batches import create
 from app.schemas.monitor import MonitorBatchCreate
 if db.get_bind().dialect.name!='postgresql':pytest.skip('owned PostgreSQL concurrency required')
 n=node(db);nid=n.id;db.rollback();bind=db.get_bind()
 data=MonitorBatchCreate(items=[dict(name='probe',type='ping',target='example.com',node_id=nid)],request_key='12345678-1234-4234-8234-123456789abc')
 def invoke(_):
  with Session(bind) as own:return create(own,data,session_id='parallel')
 with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(invoke,range(4)))
 assert all(r==results[0] for r in results)
 db.expire_all();assert db.query(Monitor).count()==1 and db.query(MonitorGroup).count()==0


def test_standalone_batch_http_is_atomic_receipted_and_never_creates_group(db):
 from fastapi import FastAPI, Request
 from fastapi.testclient import TestClient
 from types import SimpleNamespace
 from app.routers.monitor import monitor_router
 from app.routers.auth import current_user, admin_user
 from app.database import get_db
 app=FastAPI(); app.include_router(monitor_router)
 app.dependency_overrides[get_db]=lambda:db
 def user(request:Request):
  request.state.auth_session=SimpleNamespace(id='owned-session')
  return object()
 app.dependency_overrides[current_user]=user; app.dependency_overrides[admin_user]=lambda:object()
 n=node(db)
 body=dict(items=[dict(name='TCP',type='tcp',target='example.com:80',node_id=n.id),dict(name='UDP',type='udp',target='example.com:53',node_id=999)],request_key='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',group_id=None,expected_group_uuid=None)
 with TestClient(app) as c:
  assert c.post('/monitors/batches',json=body).status_code==400
  assert db.query(Monitor).count()==0
  body['items'][1]['node_id']=n.id
  response=c.post('/monitors/batches',json=body)
  assert response.status_code==201,response.text
  receipt=response.json(); assert receipt['group_id'] is None and len(receipt['monitor_ids'])==2
  assert c.get('/monitors/batches/receipts/'+body['request_key']).json()==receipt
  assert c.post('/monitors/batches',json=body).json()==receipt
  assert db.query(MonitorGroup).count()==db.query(MonitorGroupMember).count()==0
  assert db.query(Monitor).count()==2
  body['items'][0]['target']='example.com:81'
  assert c.post('/monitors/batches',json=body).status_code==409


def test_batch_receipt_bounded_shared_storage_eviction_and_namespace_are_literal(db):
 import json
 from app.models.config import AppConfig
 from app.services.monitor_batches import create, receipt
 from app.services.monitor_groups import MAX_RECEIPTS, RECEIPTS, _receipt_slot
 from app.schemas.monitor import MonitorBatchCreate
 assert MAX_RECEIPTS == 128 and RECEIPTS == 'monitor_group.create_receipts.v1'
 n=node(db)
 old={f'old-{i}':dict(digest='old',group_id=123,monitor_ids=[i]) for i in range(MAX_RECEIPTS)}
 db.add(AppConfig(key=RECEIPTS,value=json.dumps(old)));db.commit()
 data=MonitorBatchCreate(items=[dict(name='probe',type='ping',target='example.com',node_id=n.id)],request_key='12345678-1234-4234-8234-123456789abc')
 result=create(db,data,session_id='bounded-session')
 stored=json.loads(db.get(AppConfig,RECEIPTS).value)
 assert len(stored)==MAX_RECEIPTS and 'old-0' not in stored and 'old-1' in stored
 assert stored[_receipt_slot('batch:'+data.request_key,'bounded-session')]==dict(digest=__import__('hashlib').sha256(data.model_dump_json(exclude={'request_key'}).encode()).hexdigest(),**result)
 assert _receipt_slot(data.request_key,'bounded-session') not in stored
 assert receipt(db,data.request_key,'other-session') is None
 assert db.query(MonitorGroup).count()==0
 # Receipt is not a permanent idempotency registry after actual bounded eviction.
 slot=_receipt_slot('batch:'+data.request_key,'bounded-session')
 reordered={slot:stored[slot],**{k:v for k,v in stored.items() if k!=slot}}
 db.get(AppConfig,RECEIPTS).value=json.dumps(reordered);db.commit()
 create(db,data.model_copy(update={'request_key':'12345678-1234-4234-8234-123456789abd'}),session_id='bounded-session')
 assert receipt(db,data.request_key,'bounded-session') is None
 again=create(db,data,session_id='bounded-session')
 assert again['monitor_ids']!=result['monitor_ids'] and db.query(Monitor).count()==3


def test_batch_version_commit_failure_rolls_back_definitions_relations_receipt_and_version(db,monkeypatch):
 from app.services import monitor_batches as svc
 from app.schemas.monitor import MonitorBatchCreate
 from app.models.config import AppConfig
 from app.repositories.config import get_monitors_version
 from app.services.monitor_groups import RECEIPTS
 n=node(db);g=MonitorGroup(name='kept');db.add(g);db.commit()
 before=get_monitors_version(db)
 data=MonitorBatchCreate(items=[dict(name='probe',type='ping',target='example.com',node_id=n.id)],request_key='12345678-1234-4234-8234-123456789abc',group_id=g.id,expected_group_uuid=g.stable_uuid)
 def fail(own):
  own.flush()
  raise RuntimeError('after receipt and relation SQL')
 monkeypatch.setattr(svc,'bump_monitors_version',fail)
 with pytest.raises(RuntimeError,match='after receipt and relation SQL'):svc.create(db,data,session_id='rollback-session')
 assert db.query(Monitor).count()==db.query(MonitorGroupMember).count()==0
 assert db.query(MonitorGroup).count()==1 and db.get(AppConfig,RECEIPTS) is None
 assert get_monitors_version(db)==before


def test_batch_receipt_get_is_select_only_and_retained_deleted_replay_never_recreates(db):
 from app.services.monitor_batches import create, receipt
 from app.schemas.monitor import MonitorBatchCreate
 from sqlalchemy import event
 from app.repositories.config import get_monitors_version
 n=node(db)
 data=MonitorBatchCreate(items=[dict(name='probe',type='ping',target='example.com',node_id=n.id)],request_key='12345678-1234-4234-8234-123456789abc')
 result=create(db,data,session_id='read-only-session')
 db.query(Monitor).delete();db.commit();before=get_monitors_version(db)
 statements=[]
 def record(conn,cursor,sql,*args):statements.append(sql.lstrip().upper())
 event.listen(db.get_bind(),'before_cursor_execute',record)
 try:
  assert receipt(db,data.request_key,'read-only-session')==result
  assert receipt(db,data.request_key,'another-session') is None
  assert create(db,data,session_id='read-only-session')==result
 finally:event.remove(db.get_bind(),'before_cursor_execute',record)
 assert not any(s.startswith(('INSERT','UPDATE','DELETE')) for s in statements)
 assert db.query(Monitor).count()==0 and get_monitors_version(db)==before
