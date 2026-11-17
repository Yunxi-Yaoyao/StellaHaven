"""Owned Notes joint acceptance resources; never accepts an existing DSN."""
import io,json,os,secrets,subprocess,sys,tarfile,time
from pathlib import Path
ROOT=Path('/root/.hermes/cache/scratch/notes-joint-6b01e8e')
REPO=Path('/opt/hermes-workstation/stella-notes-final-joint-20261016')
OUT=Path('/opt/hermes-workstation/docs/Stella-API/remediation')
PY='/opt/Yunxi-workstation/Stella/.venv/bin/python'
STATE=ROOT/'private.json'
def cmd(args,**kw): return subprocess.run(args,check=True,capture_output=True,text=True,**kw).stdout.strip()
def inspect(cid): return json.loads(cmd(['docker','inspect',cid]))[0]
def save(name,data): (OUT/('review-notes-joint-'+name+'.json')).write_text(json.dumps(data,indent=2))
def env():
    e={k:os.environ[k] for k in ['PATH','LANG','TZ'] if k in os.environ}
    e.update(HOME=str(ROOT/'home'),TMPDIR=str(ROOT/'tmp'),PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1')
    return e
if sys.argv[1]=='provision':
    assert not STATE.exists(); ROOT.mkdir(parents=True,exist_ok=True)
    head=cmd(['git','-C',str(REPO),'rev-parse','HEAD']);assert head=='6b01e8e7714b7cd87c425ae71cb74ca3df956a65'
    app=ROOT/'application';app.mkdir()
    archive=subprocess.run(['git','-C',str(REPO),'archive','HEAD'],check=True,capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        assert not any(Path(m.name).name=='.env' for m in tf.getmembers());tf.extractall(app,filter='data')
    for d in ['home','tmp']: (ROOT/d).mkdir(exist_ok=True)
    # Install the frozen lockfile into scratch; never borrow a different lane's versions/caches.
    subprocess.run(['npm','ci','--include=dev','--ignore-scripts'],cwd=app/'frontend',env=env(),check=True)
    n=secrets.token_hex(8)
    s=dict(name='notes-joint-'+n,label='notes-joint-'+n,db='notes_joint_'+n,user='audit_'+n,password=secrets.token_urlsafe(32),schema='joint_'+n,head=head)
    STATE.write_text(json.dumps(s));STATE.chmod(0o600)
    e=dict(os.environ,POSTGRES_USER=s['user'],POSTGRES_PASSWORD=s['password'],POSTGRES_DB=s['db'])
    cid=cmd(['docker','run','-d','--name',s['name'],'--label','stella.audit='+s['label'],'--memory','768m','--cpus','1','--publish','127.0.0.1::5432','--publish','127.0.0.1::18080','--tmpfs','/var/lib/postgresql/data:rw,size=536870912','-e','POSTGRES_USER','-e','POSTGRES_PASSWORD','-e','POSTGRES_DB','postgres:16-alpine'],env=e)
    m=inspect(cid);s.update(id=cid,pid=m['State']['Pid'],port=int(m['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']),http_port=int(m['NetworkSettings']['Ports']['18080/tcp'][0]['HostPort']),ip=next(iter(m['NetworkSettings']['Networks'].values()))['IPAddress'])
    STATE.write_text(json.dumps(s));STATE.chmod(0o600)
    assert m['Config']['Labels']['stella.audit']==s['label'] and m['Id']==cid
    assert all(v[0]['HostIp']=='127.0.0.1' for v in m['NetworkSettings']['Ports'].values() if v)
    import psycopg2
    for _ in range(150):
        try:
            c=psycopg2.connect(host='127.0.0.1',port=s['port'],dbname=s['db'],user=s['user'],password=s['password'],connect_timeout=1)
            with c.cursor() as q:
                q.execute('select current_database(),current_user');assert q.fetchone()==(s['db'],s['user'])
            c.close();break
        except psycopg2.OperationalError:time.sleep(.2)
    else:raise RuntimeError('TCP readiness failed')
    pre=['nsenter','-t',str(s['pid']),'-n']
    for rule in [['iptables','-A','OUTPUT','-o','lo','-p','tcp','--dport','5432','-j','ACCEPT'],['iptables','-A','OUTPUT','-m','conntrack','--ctstate','ESTABLISHED,RELATED','-j','ACCEPT'],['iptables','-P','OUTPUT','DROP'],['ip6tables','-P','OUTPUT','DROP']]:cmd(pre+rule)
    save('resource',{k:v for k,v in s.items() if k!='password'}|dict(memory=m['HostConfig']['Memory'],nanocpus=m['HostConfig']['NanoCpus'],bindings=m['NetworkSettings']['Ports'],firewall=cmd(pre+['iptables','-S','OUTPUT']),rationale='768MiB memory / 512MiB data tmpfs budgets include WAL and indexes; CPU capped at 1'))
    print('Provisioned',s['name'],'HTTP',s['http_port'])
elif sys.argv[1]=='serve':
    s=json.loads(STATE.read_text());m=inspect(s['id']);assert m['Config']['Labels']['stella.audit']==s['label']
    os.execvpe('nsenter',['nsenter','-t',str(s['pid']),'-n',PY,str(REPO/'qa/notes_joint/server.py')],env())
elif sys.argv[1]=='build':
    with (OUT/'review-notes-joint-build.log').open('w') as f:
        for args in [['node','node_modules/vue-tsc/bin/vue-tsc.js','-b'],['node','node_modules/vite/bin/vite.js','build']]:
            p=subprocess.run(args,cwd=ROOT/'application/frontend',env=env(),stdout=f,stderr=subprocess.STDOUT)
            if p.returncode:sys.exit(p.returncode)
    print('production build passed')
elif sys.argv[1]=='cleanup':
    s=json.loads(STATE.read_text());m=inspect(s['id']);assert m['Id']==s['id'] and m['Config']['Labels']['stella.audit']==s['label']
    import psycopg2
    with psycopg2.connect(host='127.0.0.1',port=s['port'],dbname=s['db'],user=s['user'],password=s['password']) as c:
        with c.cursor() as q:
            q.execute('select current_database(),current_user');assert q.fetchone()==(s['db'],s['user'])
            q.execute('DROP SCHEMA "'+s['schema']+'" CASCADE')
            q.execute('select count(*) from pg_namespace where nspname=%s',(s['schema'],));assert q.fetchone()[0]==0
            q.execute("select count(*) from pg_tables where schemaname='public'");assert q.fetchone()[0]==0
    save('precleanup',dict(schema_absent=True,public_tables=0,firewall=cmd(['nsenter','-t',str(s['pid']),'-n','iptables','-L','OUTPUT','-v','-n','-x'])))
    cmd(['docker','rm','-f',s['id']]);r=subprocess.run(['docker','inspect',s['id']],capture_output=True,text=True);assert r.returncode and 'no such' in r.stderr.lower()
    save('cleanup',dict(container_absent=True,id=s['id'],schema_absent=True));STATE.unlink();print('Owned container/schema removed and absence verified')
