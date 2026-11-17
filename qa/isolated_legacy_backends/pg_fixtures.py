"""Safe substitutes for pinned PG fixtures. Original fixture guards stay uncalled.
Reduced model DDL is explicit test-level DDL in already-owned empty schemas;
full-main migration proofs are separate and run real Alembic, never create_all.
"""
import json,sys
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session,sessionmaker
import guard
from fastapi import FastAPI,Depends
from fastapi.testclient import TestClient
from owned_target import OwnedTarget
@pytest.fixture
def owned_target():
 return OwnedTarget()
@pytest.fixture
def engine():
 from app.models import Base
 from app.models.node import Node,NodeMetric,NodeSysMetric
 from app.models.monitor import Monitor,MonitorCheck
 from app.models.task import IperfTask
 with guard.schema_scope() as (e,name):
  Base.metadata.create_all(e,tables=[m.__table__ for m in [Node,NodeMetric,NodeSysMetric,Monitor,MonitorCheck,IperfTask]])
  yield e
@pytest.fixture
def db():
 with guard.schema_scope() as (e,name):yield e,name
@pytest.fixture
def pg_security(monkeypatch):
 from app.database import get_db
 from app.models.user import User,AuthSession
 from app.models.config import AppConfig
 from app.models.alert import AlertRule,Notification
 from app.routers.auth import router,admin_user
 from tests_isolated.test_owner_admin_security import DAILY
 with guard.schema_scope() as (e,name):
  for m in [User,AuthSession,AppConfig,AlertRule,Notification]:m.__table__.create(e)
  def sessions():
   with Session(e) as d:yield d
  def make_app():
   a=FastAPI();a.include_router(router);a.dependency_overrides[get_db]=sessions
   @a.post('/danger')
   def danger(user=Depends(admin_user)):return {'ok':True}
   return a
  a=make_app();c0,c1=TestClient(a),TestClient(a)
  try:
   r=c0.post('/auth/register',json={'username':'owner','password':DAILY});assert r.status_code==201,r.text
   assert c1.post('/auth/login',json={'username':'owner','password':DAILY}).status_code==200
   yield e,c0,c1,make_app
  finally:c0.close();c1.close()
@pytest.fixture
def pg(request,monkeypatch):
 file=request.module.__file__
 if 'traffic_query' in file:
  repo=request.getfixturevalue('repo')
  with guard.schema_scope() as (e,name):
   repo.Node.metadata.create_all(e,tables=[repo.Node.__table__,repo.NodeMetric.__table__]);yield e.execution_options(schema_translate_map={None:name})
 elif 'browser_sessions' in file:
  api=request.getfixturevalue('api')
  from app.models.config import AppConfig
  from app.services.admin_security import STATE_KEY
  with guard.schema_scope() as (e,name):
   for m in [api.User,api.AuthSession,AppConfig]:m.__table__.create(e)
   factory=sessionmaker(e)
   with api.factory() as source,factory() as dest:
    owner=source.get(api.User,api.uid)
    dest.add(api.User(id=api.uid,username=owner.username,display_name=owner.display_name,password_hash=owner.password_hash))
    dest.add(AppConfig(key=STATE_KEY,value=json.dumps({'owner_id':str(api.uid)})));dest.commit()
   yield api,factory,e
 elif 'shared_state' in file:
  request.getfixturevalue('safe_modules')
  from app.services import ha_state
  with guard.schema_scope() as (e,name):
   ha_state.metadata.create_all(e)
   monkeypatch.setattr(ha_state,'_engine',lambda:e);monkeypatch.setenv('STELLA_SHARED_STATE','postgres')
   yield e
 else:raise AssertionError('No audited pg adapter for '+file)
@pytest.fixture
def notes(env):
 from app.models import Tag,DocTag,DocumentLink,DocumentVersion,Attachment
 from app.models.blob import BlobObject,BlobChunk
 from app.database import get_db
 classes=[env.models.User,env.models.AuthSession,env.models.AppConfig,env.models.Workspace,env.models.Document,Tag,DocTag,DocumentLink,DocumentVersion,Attachment,BlobObject,BlobChunk]
 with guard.schema_scope() as (e,name):
  env.models.Base.metadata.create_all(e,tables=[m.__table__ for m in classes])
  with env.engine.connect() as source,e.begin() as dest:
   for cls in classes[:5]:
    values=[dict(r) for r in source.execute(select(cls.__table__)).mappings()]
    if values:dest.execute(cls.__table__.insert(),values)
  def sessions():
   with Session(e) as db:yield db
  env.client.app.dependency_overrides[get_db]=sessions;env.engine=e
  yield env
