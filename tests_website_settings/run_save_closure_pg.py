"""Outer local-only provisioner. Pytest never shells out to Docker."""
import json,os,secrets,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'docs/private-remediation/save-closure'
nonce=secrets.token_hex(16);name='save_'+nonce
scratch=Path(tempfile.mkdtemp(prefix='save-pg-',dir='/root/.hermes/cache/scratch'));scratch.chmod(0o700)
password=secrets.token_urlsafe(32)
cid=subprocess.check_output(['docker','run','-d','--name','save-closure-'+nonce,'--label','stella.qa.save-closure='+nonce,'--tmpfs','/var/lib/postgresql/data:rw,size=256m','-e','POSTGRES_USER='+name,'-e','POSTGRES_PASSWORD='+password,'-e','POSTGRES_DB='+name,'-p','127.0.0.1::5432','postgres:17-alpine'],text=True).strip()
receipt={'container':cid,'nonce':nonce}
try:
    info=json.loads(subprocess.check_output(['docker','inspect',cid]))[0]
    assert info['Id']==cid and info['Config']['Labels']['stella.qa.save-closure']==nonce
    binding=info['NetworkSettings']['Ports']['5432/tcp'][0];assert binding['HostIp']=='127.0.0.1'
    import psycopg2
    for attempt in range(100):
        try:
            connection=psycopg2.connect(host='127.0.0.1',port=binding['HostPort'],user=name,password=password,dbname=name)
            with connection.cursor() as cursor:
                cursor.execute('SELECT current_database(),current_user,system_identifier::text FROM pg_control_system()')
                database,role,system=cursor.fetchone();assert (database,role)==(name,name)
            connection.close();break
        except psycopg2.OperationalError:
            if attempt==99: raise
            time.sleep(.1)
    marker=scratch/'save-pg.json';marker.write_text(json.dumps(dict(nonce=nonce,pid=os.getpid(),port=int(binding['HostPort']),database=name,role=name,system=system,password=password)));marker.chmod(0o600)
    env=dict(PATH='/usr/bin:/bin',HOME=str(scratch),TMPDIR=str(scratch),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONPATH=str(ROOT),STELLA_SAVE_PG_RECEIPT=str(marker),STELLA_SAVE_PG_NONCE=nonce)
    command=[sys.executable,str(ROOT/'tests_website_settings/save_closure_runner.py'),'--noconftest','-p','no:cacheprovider',str(ROOT/'tests_website_settings/test_save_light_navigation.py'),str(ROOT/'tests_website_settings/test_save_closure_real_pg.py'),'-q','--junitxml='+str(EVIDENCE/'real-pg.xml')]
    with (EVIDENCE/'real-pg.log').open('w') as log: result=subprocess.run(command,env=env,cwd=scratch,stdout=log,stderr=subprocess.STDOUT)
    receipt['exit_code']=result.returncode
    print((EVIDENCE/'real-pg.log').read_text()[-6500:])
finally:
    subprocess.run(['docker','rm','-f',cid],check=True,capture_output=True)
    receipt['container_absent']=subprocess.run(['docker','inspect',cid],capture_output=True).returncode!=0
    if 'marker' in globals():marker.unlink(missing_ok=True)
    (EVIDENCE/'real-pg-resource.json').write_text(json.dumps(receipt,indent=2))
raise SystemExit(result.returncode)
