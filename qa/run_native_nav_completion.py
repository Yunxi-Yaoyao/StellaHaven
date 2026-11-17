"""Completion-only owned PostgreSQL runner; no restored production database."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

root=Path(__file__).resolve().parents[1]
nonce=uuid4().hex
out=Path(os.environ['NAV_EVIDENCE']).resolve();out.mkdir(parents=True,exist_ok=False)
name='stella-nav-completion-'+nonce[:12];database='navqa_'+nonce[:12]
container=subprocess.check_output(['docker','run','-d','--name',name,'--label','stella.navqa.purpose=native-nav-tests','--label','stella.navqa.nonce='+nonce,'--memory','384m','--cpus','1','--tmpfs','/var/lib/postgresql:rw,size=256m','-p','127.0.0.1::5432','-e','POSTGRES_DB='+database,'-e','POSTGRES_USER='+database,'-e','POSTGRES_HOST_AUTH_METHOD=trust','postgres:18'],text=True).strip()
try:
    row=json.loads(subprocess.check_output(['docker','inspect',container]))[0]
    port=row['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
    deadline=time.monotonic()+40
    while subprocess.run(['docker','exec',container,'pg_isready','-U',database,'-d',database],stdout=subprocess.DEVNULL).returncode:
        if time.monotonic()>deadline:raise RuntimeError('startup deadline')
        time.sleep(.2)
    scratch=Path(os.environ['TMPDIR'])/('nav-completion-'+nonce);scratch.mkdir(mode=0o700)
    env={k:os.environ[k] for k in ['PATH','HOME','TMPDIR','NAV_LEGACY_TRANSFER','NAV_BROWSER_ROOT'] if k in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONPATH=str(root),NAV_ROOT=str(root),NAV_NATIVE_PG_TEST='1',NAV_PG_CONTAINER=name,NAV_PG_NONCE=nonce,POSTGRES_HOST='127.0.0.1',POSTGRES_PORT=port,POSTGRES_DB=database,POSTGRES_USER=database,POSTGRES_PASSWORD='',AUTH_SIGNING_KEY='owned-nav-completion-synthetic-only',NAV_REHEARSAL_RECEIPT=str(out/'migration-rehearsal.json'))
    (out/'target.json').write_text(json.dumps({'container':container,'name':name,'database':database,'port':port,'nonce':nonce}))
    with (out/'pytest.log').open('w') as log:
        result=subprocess.run([sys.executable,'-m','pytest',str(root/'tests_isolated/test_native_nav_completion_pg.py'),'-q','-p','no:cacheprovider','--junitxml='+str(out/'pytest.xml'),*sys.argv[1:]],env=env,cwd=scratch,stdout=log,stderr=subprocess.STDOUT,timeout=240)
    print('pytest exit',result.returncode,'log',str(out/'pytest.log'))
finally:
    subprocess.run(['docker','rm','-f',container],check=True,stdout=subprocess.DEVNULL)
    absent=subprocess.run(['docker','inspect',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0
    (out/'cleanup.json').write_text(json.dumps({'container':container,'absent':absent}))
raise SystemExit(result.returncode)
