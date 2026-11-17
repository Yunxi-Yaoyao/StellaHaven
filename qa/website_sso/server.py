"""Unchanged full main, private CA trust, guarded PostgreSQL, bounded egress."""
import os,sys,json,secrets,socket,shutil
from control import ROOT,OUT,STATE,save
s=json.loads(STATE.read_text());appdir=ROOT/'application';os.chdir(appdir)
assert not os.path.exists('.env') and not any(k.startswith(('STELLA','POSTGRES','PG')) for k in os.environ)
origin=s['origin']
os.environ.update(POSTGRES_HOST='127.0.0.1',POSTGRES_PORT='5432',POSTGRES_USER=s['user'],POSTGRES_PASSWORD=s['password'],POSTGRES_DB=s['db'],STELLA_SECRET_KEY=secrets.token_urlsafe(48),STELLA_COOKIE_SECURE='true',STELLA_MAIN_ORIGIN=origin,STELLA_TRUSTED_ORIGINS=origin,STELLA_SHARED_STATE='postgres',STELLA_BLOB_STORAGE='postgres',STELLA_OIDC_PRIVATE_KEY_FILE=str(ROOT/'jwk.json'))
# Add only the owned certificate as a trust anchor; verification/hostname checks stay on.
import certifi
certifi.where=lambda:str(ROOT/'ca.pem')
probes=[]
for target in [('203.0.113.1',443),('127.0.0.1',8080)]:
 with socket.socket() as sock:
  sock.settimeout(.2)
  try:sock.connect(target)
  except OSError as exc:probes.append(dict(target=target,blocked=type(exc).__name__))
  else:raise AssertionError('egress permitted')
node=shutil.which('node')
def audit(event,args):
 if event=='socket.connect':
  addr=args[1]
  if not (isinstance(addr,tuple) and addr[:2] in [('127.0.0.1',p) for p in [5432,18081,18443]]):raise PermissionError('QA egress denied')
 if event=='subprocess.Popen' and not (args[0]==node and args[1]==[node,'--check','-']):raise PermissionError('QA process denied')
 if event in {'os.system','os.exec','os.posix_spawn'}:raise PermissionError('QA process denied')
sys.addaudithook(audit);sys.path.insert(0,str(appdir));sys.path.insert(0,str(ROOT/'deps'))
import tinycss2,importlib.metadata
assert tinycss2.__version__=='1.5.1' and importlib.metadata.version('webencodings')=='0.6.1'
from sqlalchemy import event
from sqlalchemy.engine import Engine
from app.database import engine,Base
assert (engine.url.host,engine.url.port,engine.url.database,engine.url.username)==('127.0.0.1',5432,s['db'],s['user']) and not engine.url.query
def identity(c):
 with c.cursor() as q:
  q.execute('select current_database(),current_user,host(inet_server_addr()),inet_server_port()');assert q.fetchone()==(s['db'],s['user'],'127.0.0.1',5432)
@event.listens_for(engine,'connect')
def initialize(c,record):
 identity(c)
 with c.cursor() as q:q.execute('SET search_path TO "'+s['schema']+'"');q.execute("SET statement_timeout TO '12000ms'");q.execute("SET lock_timeout TO '10000ms'")
 c.commit()
@event.listens_for(engine,'checkout')
def guard(c,record,proxy):
 assert c.get_transaction_status()==0;identity(c);c.rollback()
@event.listens_for(Engine,'before_cursor_execute')
def before(conn,cursor,statement,params,context,many):
 u=conn.engine.url;assert (u.host,u.port,u.database,u.username)==('127.0.0.1',5432,s['db'],s['user'])
 if statement.lstrip().upper().startswith(('CREATE ','ALTER ','DROP ','TRUNCATE ')):identity(conn.connection.driver_connection)
import app.models
from app.services.ha_state import metadata
with engine.begin() as c:
 identity(c.connection.driver_connection);c.exec_driver_sql('CREATE SCHEMA IF NOT EXISTS "'+s['schema']+'"');Base.metadata.create_all(c);metadata.create_all(c)
import main
assert main.app.dependency_overrides=={}
import smtplib
class Sink:
 def __init__(self,*a,**kw):pass
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def __getattr__(self,name):return lambda *a,**kw:None
smtplib.SMTP=Sink;smtplib.SMTP_SSL=Sink
save('runtime',dict(origin=origin,dependency_overrides={},kernel_probes=probes,smtp='sink only',frontend=str(main.FRONTEND_DIR),schema=s['schema'],tls='owned CA appended, validation on',node_check='only allowed subprocess'))
import uvicorn
uvicorn.run(main.app,host='0.0.0.0',port=443,ssl_keyfile=str(ROOT/'tls.key'),ssl_certfile=str(ROOT/'tls.pem'),access_log=False,log_level='warning')
