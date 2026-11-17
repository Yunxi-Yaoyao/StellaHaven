"""Replacement fixtures; original tests/conftest.py is NEVER imported/called.
All schemas migrated by actual Alembic; real register/setup/login/unlock.
get_db alone binds original test transaction semantics; auth is never overridden.
"""
import sys,types,json
import pytest
import guard
from control import OUT
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
OWNER_USERNAME='test_owner';OWNER_PASSWORD='testpass123';ADMIN_PASSWORD='test-management-independent-2026'
constants=types.ModuleType('tests.conftest')
for k in ('OWNER_USERNAME','OWNER_PASSWORD','ADMIN_PASSWORD'):setattr(constants,k,globals()[k])
sys.modules['tests.conftest']=constants
# Import once only after audited environment and network guards exist.
from app.database import engine,get_db
from app.services import ha_state
from main import app
from alembic.config import Config
from alembic import command
@pytest.fixture(autouse=True)
def db_session(monkeypatch):
 engine.dispose()
 with guard.schema_scope('upgrade_test_') as (scoped,name):
  monkeypatch.setattr(ha_state,'_engine',lambda:scoped)
  command.upgrade(Config(str(guard.APP/'alembic.ini')),'head')
  with scoped.connect() as c:assert c.exec_driver_sql('select version_num from alembic_version').scalar_one()=='e2a3b4c5d6f7'
  session=sessionmaker(bind=scoped,autoflush=False)()
  assert not app.dependency_overrides
  def private_db():yield session
  app.dependency_overrides[get_db]=private_db
  try:
   with TestClient(app,headers={'Origin':'http://testserver'}) as c:
    r=c.post('/auth/register',json={'username':OWNER_USERNAME,'password':OWNER_PASSWORD});assert r.status_code==201,r.text
    r=c.post('/auth/admin/setup',json={'user_password':OWNER_PASSWORD,'new_password':ADMIN_PASSWORD});assert r.status_code==200,r.text
    assert c.get('/auth/security').json()['elevated'] is False
    assert c.post('/auth/logout').status_code==200
   yield session
  finally:
   session.rollback();session.close();app.dependency_overrides.clear();engine.dispose()
   with (OUT/'main-fixtures.jsonl').open('a') as f:f.write(json.dumps(dict(schema=name,migration='e2a3b4c5d6f7',real_auth=True,override='get_db only'))+'\n')
@pytest.fixture
def client(db_session):
 with TestClient(app,headers={'Origin':'http://testserver'}) as c:
  r=c.post('/auth/login',json={'username':OWNER_USERNAME,'password':OWNER_PASSWORD});assert r.status_code==200,r.text
  r=c.post('/auth/admin/unlock',json={'password':ADMIN_PASSWORD});assert r.status_code==200,r.text
  assert c.get('/auth/security').json()['elevated'] is True
  yield c
@pytest.fixture
def workspace_id(client):
 r=client.post('/workspaces/',json={'name':'isolated fixture','user_id':client.get('/auth/me').json()['id']});assert r.status_code==201,r.text
 return r.json()['id']
