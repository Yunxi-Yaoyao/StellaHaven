"""Provision an exclusive nonce PG and run shared-media HTTP/concurrency tests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def child():
    from qa.native_nav_pg_guard import target
    port, database, username, _ = target()
    def guard(event, args):
        if event == 'socket.connect':
            address = args[1]
            if not isinstance(address, tuple) or address[:2] != ('127.0.0.1', port):
                raise RuntimeError('owned PG network fence')
    sys.addaudithook(guard)
    import pytest
    args = sys.argv[2:]
    paths = [str(ROOT/'tests_isolated/test_homebg_references_pg.py')]
    if '--regressions' in args:
        args.remove('--regressions')
        paths += [str(ROOT/'tests_isolated'/name) for name in ('test_native_nav_pg.py','test_native_nav_package_pg.py','test_native_nav_review_fixes_pg.py')]
    raise SystemExit(pytest.main([*paths, '--noconftest', '-q', '--junitxml='+str(Path(os.environ['NAV_EVIDENCE'])/'tests.xml'), *args]))


def parent():
    out = Path(os.environ['NAV_EVIDENCE']).resolve()
    assert out.is_relative_to(Path(os.environ['TMPDIR']).resolve())
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    nonce = uuid4().hex
    name = 'stella-media-refs-'+nonce[:12]
    database = 'navqa_'+nonce[:12]
    container = subprocess.check_output(['docker','run','-d','--name',name,'--label','stella.navqa.purpose=native-nav-tests','--label','stella.navqa.nonce='+nonce,'--memory','512m','--cpus','2','--tmpfs','/var/lib/postgresql:rw,size=256m','-p','127.0.0.1::5432','-e','POSTGRES_DB='+database,'-e','POSTGRES_USER='+database,'-e','POSTGRES_HOST_AUTH_METHOD=trust','postgres:18'],text=True).strip()
    result = None
    try:
        row = json.loads(subprocess.check_output(['docker','inspect',container]))[0]
        port = row['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
        deadline = time.monotonic()+40
        while subprocess.run(['docker','exec',container,'psql','-h','127.0.0.1','-U',database,'-d',database,'-tAc','SELECT 1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
            assert time.monotonic()<deadline
            time.sleep(.2)
        env = {k:os.environ[k] for k in ('PATH','TMPDIR')}
        env.update(HOME=str(out),PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',NAV_ROOT=str(ROOT),NAV_EVIDENCE=str(out),NAV_NATIVE_PG_TEST='1',NAV_PG_CONTAINER=name,NAV_PG_NONCE=nonce,POSTGRES_HOST='127.0.0.1',POSTGRES_PORT=port,POSTGRES_DB=database,POSTGRES_USER=database,POSTGRES_PASSWORD='',STELLA_SECRET_KEY='owned-media-reference-signing-key',STELLA_BLOB_STORAGE='postgres',STELLA_BLOB_CACHE=str(out/'blob-cache'),STELLA_MAIN_ORIGIN='https://media-qa.test',STELLA_TRUSTED_ORIGINS='https://media-qa.test',STELLA_OIDC_PRIVATE_KEY_FILE=str(out/'oidc-key.pem'))
        (out/'target.json').write_text(json.dumps({'container':container,'nonce':nonce,'database':database,'port':port,'root':str(ROOT),'python':sys.executable},indent=2))
        with (out/'pytest.log').open('w') as log:
            result = subprocess.run([sys.executable,str(Path(__file__).resolve()),'--child',*sys.argv[1:]],cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240)
        print((out/'pytest.log').read_text())
    finally:
        subprocess.run(['docker','rm','-f',container],check=True,stdout=subprocess.DEVNULL)
        absent = subprocess.run(['docker','inspect',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0
        (out/'cleanup.json').write_text(json.dumps({'container':container,'absent':absent}))
    raise SystemExit(result.returncode if result else 1)


if __name__ == '__main__':
    child() if '--child' in sys.argv else parent()
