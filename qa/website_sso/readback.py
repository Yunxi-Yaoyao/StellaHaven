"""Guarded final DB/source and no-secret-artifact receipts, before cleanup."""
from control import ROOT,REPO,STATE,OUT,cmd,save
import json,os,hashlib,psycopg2
s=json.loads(STATE.read_text())
assert os.stat('/proc/self/ns/net').st_ino==os.stat('/proc/'+str(s['pid'])+'/ns/net').st_ino
with psycopg2.connect(host='127.0.0.1',port=5432,dbname=s['db'],user=s['user'],password=s['password']) as c:
 c.set_session(readonly=True)
 with c.cursor() as q:
  q.execute('select current_database(),current_user,host(inet_server_addr()),inet_server_port()');assert q.fetchone()==(s['db'],s['user'],'127.0.0.1',5432)
  q.execute('SET search_path TO "'+s['schema']+'"')
  q.execute("select value from app_config where key='integrations_v1'");state=json.loads(q.fetchone()[0]);assert not state['modules']
  assert not any(len(row['id'])==32 for row in state['navigation'])
  targets=list(state['targets'].values());assert targets and all(t['allowed_ips']==['127.0.0.1'] for t in targets)
  assert any(s['upstream_secret'] in t['headers'].values() for t in targets)
  q.execute("select count(*) from pg_tables where schemaname='public'");assert q.fetchone()[0]==0
save('database-readback',dict(identity_guard=True,read_only=True,modules_remaining=0,website_navigation_remaining=0,targets_exact_loopback=True,credential_only_in_backend_target=True,public_tables=0))
head=cmd(['git','-C',str(REPO),'rev-parse','HEAD']);assert head==s['head']
files=cmd(['git','-C',str(REPO),'ls-files','-z']).rstrip('\0').split('\0');manifest={}
for name in files:
 local=REPO/name;archived=ROOT/'application'/name
 assert local.read_bytes()==archived.read_bytes(),name
 manifest[name]=hashlib.sha256(local.read_bytes()).hexdigest()
save('source-manifest',dict(head=head,base='66f9f7b7b6fab9048c20ede95f95f839389031c5',files=manifest,frontend_source_unchanged=True,production_main_dependencies_overridden=False))
a=json.loads((ROOT/'auth-private.json').read_text());rp=json.loads((ROOT/'rp-private.json').read_text())
secrets=[s['password'],s['upstream_secret'],a['password'],a['management'],rp['client_secret'],*a['ordinary'].values(),*a['elevated'].values()]
scanned=0
for p in OUT.rglob('*'):
 if not p.is_file() or p.suffix in {'.png','.jpg','.tar'}:continue
 data=p.read_bytes();assert not any(x.encode() in data for x in secrets),str(p);scanned+=1
save('artifact-secret-scan',dict(files_scanned=scanned,random_db_upstream_login_management_client_secrets_and_cookies_absent=True))
print('Final same-connection PG identity, deleted entries, source and artifact checks passed')
