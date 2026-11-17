"""Frozen legacy coverage: provision ONLY an owned disposable PG; no existing DSN."""
import io,json,os,secrets,subprocess,sys,tarfile,time,hashlib
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
ROOT=Path('/root/.hermes/cache/scratch/historical-contract-close')
OUT=Path('/opt/hermes-workstation/docs/Stella-API/remediation/historical-contract-close')
OLD=OUT.parent/'final-acceptance-b52c8e7'
PY='/opt/Yunxi-workstation/Stella/.venv/bin/python'
STATE=ROOT/'private.json'
def cmd(a,**kw):return subprocess.run(a,check=True,capture_output=True,text=True,**kw).stdout.strip()
def inspect(s):
 m=json.loads(cmd(['docker','inspect',s['id']]))[0]
 assert m['Id']==s['id'] and m['Config']['Labels']['stella.coverage-close']==s['nonce']
 assert m['State']['Running'] and m['State']['Pid']==s['pid']
 assert m['NetworkSettings']['Ports']['5432/tcp']==[{'HostIp':'127.0.0.1','HostPort':str(s['port'])}]
 return m
def env():
 return dict(PATH='/usr/bin:/bin',HOME=str(ROOT/'home'),TMPDIR=str(ROOT/'tmp'),LANG='C.UTF-8',TZ='UTC',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(REPO/'qa/isolated_legacy_backends')+':/root/.hermes/cache/scratch/final-b52c8e7/pydeps')
def save(n,d): (OUT/n).write_text(json.dumps(d,indent=2))
if __name__=='__main__':
 mode=sys.argv[1];ROOT.mkdir(exist_ok=True);OUT.mkdir(exist_ok=True)
 if mode=='provision':
  assert not STATE.exists()
  head=cmd(['git','-C',str(REPO),'rev-parse','HEAD']);assert head=='40f7332e760d84c8a3edd599850b947c3fd1ea3a'
  files=[f for f in cmd(['git','-C',str(REPO),'ls-files','-z']).split('\0') if f];save('source-before.json',{f:hashlib.sha256((REPO/f).read_bytes()).hexdigest() for f in files})
  app=ROOT/'application';app.mkdir()
  data=subprocess.run(['git','-C',str(REPO),'archive','HEAD'],check=True,capture_output=True).stdout
  with tarfile.open(fileobj=io.BytesIO(data)) as tf:
   assert not any(Path(m.name).name=='.env' for m in tf);tf.extractall(app,filter='data')
  for d in ['home','tmp','wrappers']:(ROOT/d).mkdir(exist_ok=True)
  n=secrets.token_hex(16);s=dict(nonce=n,name='coverage-close-'+n,db='stella_test_'+n,user='coverage_'+n,password=secrets.token_urlsafe(32),head=head)
  STATE.write_text(json.dumps(s));STATE.chmod(0o600)
  e=dict(os.environ,POSTGRES_USER=s['user'],POSTGRES_DB=s['db'],POSTGRES_PASSWORD=s['password'])
  cid=cmd(['docker','run','-d','--name',s['name'],'--label','stella.coverage-close='+n,'--memory','2g','--cpus','1','--publish','127.0.0.1::5432','--tmpfs','/var/lib/postgresql/data:rw,size=1073741824','-e','POSTGRES_USER','-e','POSTGRES_PASSWORD','-e','POSTGRES_DB','postgres:17-alpine'],env=e)
  m=json.loads(cmd(['docker','inspect',cid]))[0];s.update(id=cid,pid=m['State']['Pid'],port=int(m['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']))
  STATE.write_text(json.dumps(s));STATE.chmod(0o600);inspect(s)
  import psycopg2
  for _ in range(150):
   try:
    c=psycopg2.connect(host='127.0.0.1',port=s['port'],dbname=s['db'],user=s['user'],password=s['password'],connect_timeout=1)
    with c.cursor() as q:q.execute('select current_database(),current_user');assert q.fetchone()==(s['db'],s['user'])
    c.close();break
   except psycopg2.OperationalError:time.sleep(.2)
  else:raise RuntimeError('PG TCP readiness failed')
  pre=['nsenter','-t',str(s['pid']),'-n']
  for rule in [['iptables','-A','OUTPUT','-o','lo','-p','tcp','--dport','5432','-j','ACCEPT'],['iptables','-A','OUTPUT','-m','conntrack','--ctstate','ESTABLISHED,RELATED','-j','ACCEPT'],['iptables','-P','OUTPUT','DROP'],['ip6tables','-P','OUTPUT','DROP']]:cmd(pre+rule)
  save('resource.json',{k:v for k,v in s.items() if k!='password'}|dict(memory=m['HostConfig']['Memory'],cpus=m['HostConfig']['NanoCpus'],firewall=cmd(pre+['iptables','-S','OUTPUT'])))
  print('Owned resource ready',s['id'])
 elif mode=='browser-artifacts':
  import shutil
  source=ROOT/'application/frontend';target=source
  lock=json.loads((source/'package-lock.json').read_text())
  for name,meta in lock['packages'].items():
   if name and (source/name/'package.json').exists():assert json.loads((source/name/'package.json').read_text())['version']==meta['version'],name
  assert (source/'package-lock.json').read_bytes()==(target/'package-lock.json').read_bytes()
  if not (target/'dist').exists():shutil.copytree(source/'dist',target/'dist')
  if not (target/'node_modules').exists():(target/'node_modules').symlink_to(source/'node_modules',target_is_directory=True)
  assert (target/'node_modules').resolve()==(source/'node_modules').resolve()
  hashes=lambda base:{str(p.relative_to(base)):hashlib.sha256(p.read_bytes()).hexdigest() for p in base.rglob('*') if p.is_file()}
  assert hashes(source/'dist')==hashes(target/'dist')
  s=json.loads(STATE.read_text());inspect(s);pre=['nsenter','-t',str(s['pid']),'-n','iptables']
  rule=['OUTPUT','-o','lo','-p','tcp','--dport','18081','-j','ACCEPT']
  if subprocess.run(pre+['-C']+rule,capture_output=True).returncode:cmd(pre+['-I']+rule)
  save('browser-artifacts.json',dict(dist_sha256=hashes(target/'dist'),package_lock_sha256=hashlib.sha256((target/'package-lock.json').read_bytes()).hexdigest(),dependency_directory=str((target/'node_modules').resolve()),dependency_writes=False,firewall=cmd(pre+['-S','OUTPUT'])))
  print('Frozen browser artifact parity and owned HTTP rule verified')
 elif mode=='run':
  s=json.loads(STATE.read_text());inspect(s)
  binding={k:s[k] for k in ('id','nonce','pid','port','db','user')}
  binding['netns']=os.readlink(f'/proc/{s["pid"]}/ns/net')
  (ROOT/'binding.json').write_text(json.dumps(binding));(ROOT/'binding.json').chmod(0o600)
  os.execvpe('nsenter',['nsenter','-t',str(s['pid']),'-n',PY,str(REPO/'qa/isolated_legacy_backends/execute.py'),*sys.argv[2:]],env())
 elif mode=='cleanup':
  s=json.loads(STATE.read_text());inspect(s)
  import psycopg2
  with psycopg2.connect(host='127.0.0.1',port=s['port'],dbname=s['db'],user=s['user'],password=s['password']) as c:
   with c.cursor() as q:
    q.execute('select current_database(),current_user');assert q.fetchone()==(s['db'],s['user'])
    q.execute("select nspname from pg_namespace where nspname like 'coverage_%' or nspname like 'upgrade_test_%'");schemas=[r[0] for r in q.fetchall()]
    for schema in schemas:q.execute('DROP SCHEMA "'+schema+'" CASCADE')
    q.execute("select nspname from pg_namespace where nspname like 'coverage_%' or nspname like 'upgrade_test_%'");assert not q.fetchall()
    q.execute("select count(*) from pg_tables where schemaname='public'");assert q.fetchone()==(0,)
  save('precleanup.json',dict(rescued_schemas=schemas,remaining_schemas=0,public_tables=0,firewall=cmd(['nsenter','-t',str(s['pid']),'-n','iptables','-L','OUTPUT','-nvx'])))
  cmd(['docker','rm','-f',s['id']]);r=subprocess.run(['docker','inspect',s['id']],capture_output=True,text=True);assert r.returncode and 'no such' in r.stderr.lower()
  STATE.unlink();save('cleanup.json',dict(container_absent=True,id=s['id'],private_state_absent=not STATE.exists()));print('Cleanup verified')
