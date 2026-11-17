"""Exercise the candidate policy against a disposable DB on isolated preview PG."""
from pathlib import Path
import os,subprocess,secrets
import psycopg2
from psycopg2 import sql
from dotenv import dotenv_values
from sqlalchemy.engine import URL
ROOT=Path(__file__).resolve().parents[3]
e=dotenv_values('/var/lib/stella-preview-20261018/private/app.env')
assert e['POSTGRES_PORT']=='25436' and e['POSTGRES_DB']=='stella_preview_20261018'
c=psycopg2.connect(host=e['POSTGRES_HOST'],port=e['POSTGRES_PORT'],user=e['POSTGRES_USER'],password=e['POSTGRES_PASSWORD'],dbname=e['POSTGRES_DB']);c.autocommit=True
with c.cursor() as x:
 x.execute('select system_identifier::text from pg_control_system()');assert x.fetchone()[0]=='7698041980212371498'
 name='stella_policy_'+secrets.token_hex(5)
 x.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
try:
 env={**os.environ,'POSTGRES_HOST':'127.0.0.1','POSTGRES_PORT':'1','POSTGRES_DB':'policy_tests','STELLA_SECRET_KEY':'isolated-policy-test-only-key-32-bytes','PYTHONPATH':str(ROOT)}
 env['STELLA_POLICY_TEST_DATABASE_URL']=URL.create('postgresql',username=e['POSTGRES_USER'],password=e['POSTGRES_PASSWORD'],host='127.0.0.1',port=25436,database=name).render_as_string(hide_password=False)
 result=subprocess.run(['/opt/hermes-workstation/stella-preview-20261018/.venv/bin/python','-m','pytest','tests_isolated/test_node_monitor_policy.py','tests_isolated/test_node_monitor_policy_pg.py','tests_isolated/test_host_monitor_display.py','-q'],cwd=ROOT,env=env)
finally:
 with c.cursor() as x:x.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
 c.close()
raise SystemExit(result.returncode)
