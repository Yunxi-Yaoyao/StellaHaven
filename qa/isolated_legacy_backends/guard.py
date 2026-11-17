"""Exact owned connection identity; schema DDL always guarded, no private lookup."""
import json,os,socket,sys,secrets
from pathlib import Path
from contextlib import contextmanager
from control import ROOT,OUT
s=json.loads((ROOT/'private.json').read_text())
assert os.readlink('/proc/self/ns/net')==os.readlink(f'/proc/{s["pid"]}/ns/net')
assert not any(k.startswith(('STELLA','POSTGRES','PG')) for k in os.environ)
APP=ROOT/'application';os.chdir(APP);assert not (APP/'.env').exists()
sys.path[:0]=[str(APP),str(APP/'tests_isolated')]
os.environ.update(POSTGRES_HOST='127.0.0.1',POSTGRES_PORT='5432',POSTGRES_USER=s['user'],POSTGRES_PASSWORD=s['password'],POSTGRES_DB=s['db'],STELLA_SECRET_KEY=secrets.token_urlsafe(48),STELLA_COOKIE_SECURE='false',STELLA_MAIN_ORIGIN='http://testserver',STELLA_TRUSTED_ORIGINS='http://testserver',STELLA_SHARED_STATE='postgres',STELLA_BLOB_STORAGE='postgres')
probes=[]
for target in [('203.0.113.1',443),('127.0.0.1',8080)]:
 with socket.socket() as sock:
  sock.settimeout(.15)
  try:sock.connect(target)
  except OSError as e:probes.append(dict(target=target,blocked=type(e).__name__))
  else:raise AssertionError('egress allowed')
(OUT/'netns-probes.json').write_text(json.dumps(probes))
def audit(event,args):
 if event=='socket.connect' and isinstance(args[1],tuple) and args[1][:2] not in {('127.0.0.1',5432),('127.0.0.1',18081)}:raise PermissionError('QA egress denied')
 if event=='subprocess.Popen':
  executable,argv,cwd,env=args
  name=Path(executable).name
  media=name in {'ffmpeg','ffprobe'} and str(Path('/usr/bin')/name)==str(Path(executable).resolve()) if '/' in executable else name in {'ffmpeg','ffprobe'}
  local_args=all(not str(a).startswith(('http:','https:','ssh:','tcp:','udp:')) and (not str(a).startswith('/') or str(a).startswith(str(ROOT)+'/')) for a in argv[1:])
  browser=name=='node' and len(argv)==2 and str(argv[1]).startswith(str(ROOT/'tmp')+'/') and str(argv[1]).endswith('/notes-live.mjs')
  if (media and local_args) or browser:
   with (OUT/'allowed-local-commands.jsonl').open('a') as f:f.write(json.dumps({'executable':name,'argv':argv,'scope':'local media/browser only; no agent/install/tasks'})+'\n')
   return
  raise PermissionError('QA command fail sentinel')
 if event in {'os.system','os.exec','os.posix_spawn'}:raise PermissionError('QA command fail sentinel')
sys.addaudithook(audit)
import subprocess
try:subprocess.run(['/bin/true'],check=True)
except PermissionError:(OUT/'command-sentinel.json').write_text(json.dumps({'unapproved_process_denied':True}))
else:raise AssertionError('command sentinel did not block')
import smtplib
class Sink:
 def __init__(self,*a,**kw):pass
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def __getattr__(self,name):return lambda *a,**kw:None
smtplib.SMTP=Sink;smtplib.SMTP_SSL=Sink
from sqlalchemy import event,create_engine
from sqlalchemy.engine import Engine,URL
URL_=URL.create('postgresql+psycopg2',username=s['user'],password=s['password'],host='127.0.0.1',port=5432,database=s['db'])
active_schema=None
engines=[]
@event.listens_for(Engine,'do_connect')
def before_driver_connect(dialect,record,args,params):
 if dialect.name!='postgresql':return
 assert not args, 'positional DSN forbidden'
 assert not any(k.startswith('PG') for k in os.environ), 'ambient libpq override forbidden'
 assert (params.get('host'),int(params.get('port',0)),params.get('dbname'),params.get('user'),params.get('password'))==('127.0.0.1',5432,s['db'],s['user'],s['password'])
 assert set(params)<={'host','port','dbname','user','password','connect_timeout','options'}, 'driver override forbidden'
 options=params.get('options','')
 assert not options or (active_schema and options=='-csearch_path='+active_schema), 'foreign search_path forbidden'

def identity(c):
 with c.cursor() as q:
  q.execute('select current_database(),current_user,host(inet_server_addr()),inet_server_port()')
  assert q.fetchone()==(s['db'],s['user'],'127.0.0.1',5432)
@event.listens_for(Engine,'engine_connect')
def engine_identity(conn):
 if conn.dialect.name=='postgresql':
  u=conn.engine.url;assert (u.host,u.port,u.database,u.username)==('127.0.0.1',5432,s['db'],s['user']) and not u.query
@event.listens_for(Engine,'connect')
def on_connect(c,record):
 if not hasattr(c,'get_transaction_status'):return
 identity(c)
 with c.cursor() as q:
  if active_schema:q.execute('SET search_path TO "'+active_schema+'"')
  q.execute("SET statement_timeout TO '12000ms'");q.execute("SET lock_timeout TO '10000ms'")
 c.commit()
@event.listens_for(Engine,'checkout')
def checkout(c,record,proxy):
 if not hasattr(c,'get_transaction_status'):return
 assert c.get_transaction_status()==0;identity(c);c.rollback()
@event.listens_for(Engine,'before_cursor_execute')
def ddl(conn,cursor,statement,params,context,many):
 if conn.dialect.name=='postgresql' and statement.lstrip().upper().startswith(('CREATE ','DROP ','ALTER ','TRUNCATE ')):identity(conn.connection.driver_connection)
def engine():
 e=create_engine(URL_,pool_size=10,max_overflow=0,hide_parameters=True);engines.append(e);return e
@contextmanager
def schema_scope(prefix='coverage_'):
 global active_schema
 assert prefix in {'coverage_','upgrade_test_'}
 assert active_schema is None
 active_schema=prefix+secrets.token_hex(16)
 e=engine();name=active_schema
 with e.begin() as c:identity(c.connection.driver_connection);c.exec_driver_sql('CREATE SCHEMA "'+name+'"')
 try:yield e,name
 finally:
  for eng in engines:eng.dispose()
  with e.begin() as c:
   identity(c.connection.driver_connection);c.exec_driver_sql('DROP SCHEMA "'+name+'" CASCADE')
   assert c.exec_driver_sql('select count(*) from pg_namespace where nspname=%s',(name,)).scalar_one()==0
  e.dispose();active_schema=None
  with (OUT/'schema-receipts.jsonl').open('a') as f:f.write(json.dumps(dict(schema=name,absent=True,same_connection_guard=True))+'\n')
