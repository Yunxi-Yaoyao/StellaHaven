"""Real loopback HTTP + PG blob cache fixture, migrated full main and real auth."""
import asyncio,io,socket,threading,time
import httpx,pytest,uvicorn
from sqlalchemy.orm import Session
import guard
@pytest.fixture
def live(tmp_path,monkeypatch):
 from app.database import engine,get_db
 from app.services import ha_state,blob_store
 from app.models import User,Workspace,Document,Attachment
 from fastapi import FastAPI
 from app.routers.attachment import router as attachment_router
 from app.routers.dynamic_assets import router as assets_router
 from app.routers.auth import router as auth_router
 app=FastAPI();app.include_router(attachment_router);app.include_router(assets_router);app.include_router(auth_router)
 from alembic.config import Config
 from alembic import command
 from fastapi.testclient import TestClient
 engine.dispose()
 monkeypatch.setenv('STELLA_BLOB_CACHE',str(tmp_path/'cache'))
 monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','http://testserver,http://127.0.0.1:18081')
 with guard.schema_scope() as (e,name):
  monkeypatch.setattr(ha_state,'_engine',lambda:e)
  command.upgrade(Config(str(guard.APP/'alembic.ini')),'head')
  def get_test_db():
   with Session(e) as db:yield db
  assert not app.dependency_overrides
  app.dependency_overrides[get_db]=get_test_db
  try:
   with TestClient(app,headers={'Origin':'http://testserver'}) as login:
    assert login.post('/auth/register',json={'username':'cachetest','password':'cache-daily-123'}).status_code==201
    assert login.post('/auth/admin/setup',json={'user_password':'cache-daily-123','new_password':'cache-management-independent'}).status_code==200
    assert login.post('/auth/logout').status_code==200
    assert login.post('/auth/login',json={'username':'cachetest','password':'cache-daily-123'}).status_code==200
    assert login.post('/auth/admin/unlock',json={'password':'cache-management-independent'}).status_code==200
    token=login.cookies.get('stella_at')
   payload=b'http-pg-cache-regression-'*65536
   with Session(e) as db:
    user=db.query(User).one();user.display_name='Cache';ws=Workspace(user_id=user.id,name='Test');db.add(ws);db.flush()
    doc=Document(workspace_id=ws.id,title='Cache test',file_path='test',content_hash='test');db.add(doc);db.flush()
    att=Attachment(doc_id=doc.id,filename='private.bin',mime='application/octet-stream',size=len(payload));db.add(att);db.flush();att_id=att.id
    blob_store.put(db,'attachments/'+str(att_id),io.BytesIO(payload),att.mime,len(payload));blob_store.put(db,'avatars/test.bin',io.BytesIO(payload),att.mime,len(payload));db.commit()
   started,release=threading.Event(),threading.Event();state={'slow':False,'checkedout':None}
   class Gate:
    async def __call__(self,scope,receive,send):
     async def gated(message):
      if state['slow'] and message['type']=='http.response.body' and message.get('body'):
       state['checkedout']=e.pool.checkedout();started.set()
       while not release.is_set():await asyncio.sleep(.01)
      await send(message)
     await app(scope,receive,gated)
   sock=socket.socket();sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind(('127.0.0.1',18081));sock.listen(128)
   server=uvicorn.Server(uvicorn.Config(Gate(),log_level='error',lifespan='off'))
   thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
   deadline=time.monotonic()+5
   while not server.started and time.monotonic()<deadline:time.sleep(.01)
   assert server.started
   try:
    with httpx.Client(base_url='http://127.0.0.1:18081',headers={'Host':'testserver','Origin':'http://testserver'},cookies={'stella_at':token},timeout=10) as client:
     yield client,e,att_id,payload,tmp_path/'cache',state,started,release
   finally:release.set();server.should_exit=True;thread.join(5);sock.close()
  finally:app.dependency_overrides.clear();engine.dispose()
