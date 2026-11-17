"""Owned, egress-denied browser acceptance. Never accepts an existing database."""
import io,json,os,secrets,subprocess,sys,tarfile,time,shutil,hashlib
from pathlib import Path
ROOT=Path('/root/.hermes/cache/scratch/website-sso-final-66f9f7b')
REPO=Path('/opt/hermes-workstation/stella-website-sso-closeout')
OUT=Path('/opt/hermes-workstation/docs/Stella-完整收尾/website-sso')
BORROW=Path('/root/.hermes/cache/scratch/product-closeout-66f9f7b/application/frontend')
PY='/opt/Yunxi-workstation/Stella/.venv/bin/python'
STATE=ROOT/'private.json'
def cmd(args,**kw):return subprocess.run(args,check=True,capture_output=True,text=True,**kw).stdout.strip()
def inspect(cid):return json.loads(cmd(['docker','inspect',cid]))[0]
def save(name,data):(OUT/(name+'.json')).write_text(json.dumps(data,indent=2,ensure_ascii=False))
def env():
 e={k:os.environ[k] for k in ['PATH','LANG','TZ'] if k in os.environ}
 e.update(HOME=str(ROOT/'home'),TMPDIR=str(ROOT/'tmp'),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
 return e
if __name__=='__main__':
 action=sys.argv[1]
 if action=='provision':
  assert not STATE.exists();ROOT.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True);(OUT/'screenshots').mkdir(exist_ok=True)
  for d in ['home','tmp']:(ROOT/d).mkdir(exist_ok=True)
  head=cmd(['git','-C',str(REPO),'rev-parse','HEAD'])
  assert cmd(['git','-C',str(REPO),'merge-base','66f9f7b',head]).startswith('66f9f7b')
  assert not cmd(['git','-C',str(REPO),'status','--porcelain','--untracked-files=no'])
  subprocess.run(['uv','pip','install','--offline','--python',PY,'--target',str(ROOT/'deps'),'tinycss2==1.5.1','webencodings==0.6.1'],check=True,env=env()|{'UV_CACHE_DIR':'/root/.cache/uv'})
  app=ROOT/'application';app.mkdir()
  raw=subprocess.run(['git','-C',str(REPO),'archive','HEAD'],capture_output=True,check=True).stdout
  with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
   assert not any(Path(m.name).name=='.env' for m in tf.getmembers());tf.extractall(app,filter='data')
  assert (BORROW/'package-lock.json').read_bytes()==(app/'frontend/package-lock.json').read_bytes()
  # The prior frozen production build is identical frontend source, not a dev server.
  tracked=cmd(['git','-C',str(REPO),'ls-files','frontend/src','frontend/index.html','frontend/vite.config.ts']).splitlines()
  for name in tracked:assert (REPO/name).read_bytes()==(BORROW.parent/name).read_bytes(),name
  shutil.copytree(BORROW/'dist',app/'frontend/dist')
  save('bundle-provenance',dict(head=head,source_files_equal=len(tracked),lock_sha256=hashlib.sha256((BORROW/'package-lock.json').read_bytes()).hexdigest(),borrowed=str(BORROW/'dist'),assets={str(p.relative_to(app/'frontend/dist')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (app/'frontend/dist').rglob('*') if p.is_file()}))
  from cryptography import x509
  from cryptography.x509.oid import NameOID
  from cryptography.hazmat.primitives import hashes,serialization
  from cryptography.hazmat.primitives.asymmetric import rsa
  import datetime,ipaddress,base64
  key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
  name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Owned acceptance only')]);now=datetime.datetime.now(datetime.timezone.utc)
  cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).add_extension(x509.SubjectAlternativeName([x509.DNSName('audit.xiya.live'),x509.DNSName('*.xiya.live'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256())
  (ROOT/'tls.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,serialization.NoEncryption()));(ROOT/'tls.key').chmod(0o600)
  (ROOT/'tls.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
  import certifi
  (ROOT/'ca.pem').write_bytes(Path(certifi.where()).read_bytes()+cert.public_bytes(serialization.Encoding.PEM))
  from authlib.jose import JsonWebKey
  jwk=JsonWebKey.generate_key('RSA',2048,is_private=True).as_dict(is_private=True);jwk['kid']='stella-oidc-1';(ROOT/'jwk.json').write_text(json.dumps(jwk));(ROOT/'jwk.json').chmod(0o600)
  n=secrets.token_hex(8)
  s=dict(name='website-sso-'+n,label='website-sso-'+n,db='website_'+n,user='audit_'+n,password=secrets.token_urlsafe(32),schema='website_'+n,head=head,origin='https://stella.xiya.live',spki=base64.b64encode(hashlib.sha256(key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode(),upstream_secret=secrets.token_urlsafe(32))
  STATE.write_text(json.dumps(s));STATE.chmod(0o600)
  e=env()|dict(POSTGRES_USER=s['user'],POSTGRES_PASSWORD=s['password'],POSTGRES_DB=s['db'])
  cid=cmd(['docker','run','-d','--name',s['name'],'--label','stella.audit='+s['label'],'--memory','768m','--cpus','1','--publish','127.0.0.1::5432','--tmpfs','/var/lib/postgresql/data:rw,size=536870912','-e','POSTGRES_USER','-e','POSTGRES_PASSWORD','-e','POSTGRES_DB','postgres:16-alpine'],env=e)
  m=inspect(cid);s.update(id=cid,pid=m['State']['Pid'],port=int(m['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']),ip=next(iter(m['NetworkSettings']['Networks'].values()))['IPAddress']);STATE.write_text(json.dumps(s))
  assert m['Config']['Labels']['stella.audit']==s['label'] and m['Id']==cid and m['NetworkSettings']['Ports']['5432/tcp'][0]['HostIp']=='127.0.0.1'
  import psycopg2
  for _ in range(150):
   try:
    c=psycopg2.connect(host='127.0.0.1',port=s['port'],dbname=s['db'],user=s['user'],password=s['password'],connect_timeout=1)
    with c.cursor() as q:q.execute('select current_database(),current_user');assert q.fetchone()==(s['db'],s['user'])
    c.close();break
   except psycopg2.OperationalError:time.sleep(.2)
  else:raise RuntimeError('TCP readiness failed')
  pre=['nsenter','-t',str(s['pid']),'-n']
  for port in [5432,443,18081,18443]:cmd(pre+['iptables','-A','OUTPUT','-o','lo','-p','tcp','--dport',str(port),'-j','ACCEPT'])
  for rule in [['iptables','-A','OUTPUT','-m','conntrack','--ctstate','ESTABLISHED,RELATED','-j','ACCEPT'],['iptables','-P','OUTPUT','DROP'],['ip6tables','-P','OUTPUT','DROP']]:cmd(pre+rule)
  save('resource',{k:v for k,v in s.items() if k not in {'password','upstream_secret'}}|dict(bindings=m['NetworkSettings']['Ports'],firewall=cmd(pre+['iptables','-S','OUTPUT'])))
  print('Owned resource provisioned, exact ID and loopback binding verified')
 elif action in {'serve','upstream','bootstrap','browser','readback'}:
  s=json.loads(STATE.read_text());m=inspect(s['id']);assert m['Id']==s['id'] and m['Config']['Labels']['stella.audit']==s['label'] and m['State']['Pid']==s['pid']
  script=REPO/'qa/website_sso'/({'serve':'server.py','upstream':'upstream.py','bootstrap':'bootstrap.py','browser':'browser.mjs','readback':'readback.py'}[action])
  binary=shutil.which('node') if action=='browser' else PY
  os.execvpe('nsenter',['nsenter','-t',str(s['pid']),'-n',binary,str(script),*sys.argv[2:]],env())
 elif action=='cleanup':
  s=json.loads(STATE.read_text());m=inspect(s['id']);assert m['Id']==s['id'] and m['Config']['Labels']['stella.audit']==s['label']
  import psycopg2
  with psycopg2.connect(host='127.0.0.1',port=s['port'],dbname=s['db'],user=s['user'],password=s['password']) as c:
   with c.cursor() as q:
    q.execute('select current_database(),current_user');assert q.fetchone()==(s['db'],s['user'])
    q.execute('DROP SCHEMA IF EXISTS "'+s['schema']+'" CASCADE');q.execute('select count(*) from pg_namespace where nspname=%s',(s['schema'],));assert q.fetchone()[0]==0
    q.execute("select count(*) from pg_tables where schemaname='public'");assert q.fetchone()[0]==0
  save('precleanup',dict(schema_absent=True,public_tables=0,firewall=cmd(['nsenter','-t',str(s['pid']),'-n','iptables','-L','OUTPUT','-v','-n','-x'])))
  cmd(['docker','rm','-f',s['id']]);r=subprocess.run(['docker','inspect',s['id']],capture_output=True,text=True);assert r.returncode and 'no such' in r.stderr.lower()
  private=['private.json','auth-private.json','rp-private.json','tls.key','jwk.json']
  for p in private:(ROOT/p).unlink(missing_ok=True)
  save('cleanup',dict(container_absent=True,id=s['id'],schema_absent=True,private_files_absent={p:not(ROOT/p).exists() for p in private}));print('Cleanup verified')
