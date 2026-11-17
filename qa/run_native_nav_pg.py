"""Run owned ephemeral PG tests from a scrubbed scratch cwd. No production env."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

root = Path(__file__).resolve().parents[1]
nonce = uuid4().hex
name = 'stella-native-nav-followup-' + nonce[:12]
database = 'navqa_' + nonce[:12]
out = Path(os.environ['NAV_EVIDENCE']).resolve()
out.mkdir(parents=True, exist_ok=True)
cmd = ['docker', 'run', '-d', '--name', name, '--label', 'stella.navqa.purpose=native-nav-tests', '--label', f'stella.navqa.nonce={nonce}', '--memory', '384m', '--cpus', '1', '--tmpfs', '/var/lib/postgresql:rw,size=256m', '-p', '127.0.0.1::5432', '-e', f'POSTGRES_DB={database}', '-e', f'POSTGRES_USER={database}', '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', 'postgres:18']
container = subprocess.check_output(cmd, text=True).strip()
try:
    row = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    port = row['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
    deadline = time.monotonic() + 40
    while subprocess.run(['docker', 'exec', name, 'pg_isready', '-U', database, '-d', database], stdout=subprocess.DEVNULL).returncode:
        if time.monotonic() > deadline: raise RuntimeError('fixture startup deadline')
        time.sleep(.2)
    env = {k: os.environ[k] for k in ['PATH', 'HOME', 'TMPDIR'] if k in os.environ}
    env.update(PYTHONPATH=str(root), NAV_ROOT=str(root), NAV_NATIVE_PG_TEST='1', NAV_PG_CONTAINER=name, NAV_PG_NONCE=nonce, POSTGRES_HOST='127.0.0.1', POSTGRES_PORT=port, POSTGRES_DB=database, POSTGRES_USER=database, POSTGRES_PASSWORD='', AUTH_SIGNING_KEY='synthetic-native-nav-followup-not-production')
    (out/'pg-target.json').write_text(json.dumps({'container': container, 'name': name, 'port': port, 'database': database, 'nonce': nonce}, indent=2))
    scratch = Path(os.environ['TMPDIR']) / ('native-nav-test-' + nonce)
    scratch.mkdir()
    with (out/'pg-tests.log').open('w') as log:
        result = subprocess.run([sys.executable, '-m', 'pytest', str(root/'tests_isolated/test_native_nav_pg.py'), '-q', '--junitxml='+str(out/'pg-tests.xml'), *sys.argv[1:]], cwd=scratch, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    print((out/'pg-tests.log').read_text())
finally:
    subprocess.run(['docker', 'rm', '-f', container], check=True, stdout=subprocess.DEVNULL)
    absent = subprocess.run(['docker', 'inspect', container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0
    (out/'pg-cleanup.json').write_text(json.dumps({'container': container, 'absent': absent}))
raise SystemExit(result.returncode)
