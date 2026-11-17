"""Opt-in self-provisioning Notes PG runner. Never accepts an existing DSN.

Run with the existing project venv and --run-disposable-postgres. Creates its
own labeled loopback-only PG, random database/role/password, and removes it in
finally. Uses scratch HOME/TMPDIR and fails closed before schema writes.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path('/root/.hermes/cache/scratch')


def docker(*args, check=True):
    return subprocess.run(['docker', *args], text=True, capture_output=True, check=check)


def main():
    if '--run-disposable-postgres' not in sys.argv:
        raise SystemExit('Explicit --run-disposable-postgres opt-in required; no existing DSNs accepted')
    # libpq PGHOSTADDR/PGOPTIONS must not override the explicit private target.
    for key in list(os.environ):
        if key.startswith('PG'):
            os.environ.pop(key)
    import psycopg2
    nonce = uuid4().hex
    name = 'notes-boundary-' + nonce
    dbname = 'notes_boundary_' + nonce
    role = 'notes_role_' + nonce
    password = secrets.token_hex(24)
    cid = None
    receipt = {'name': name, 'database': dbname, 'role': role, 'schemas_clean': False, 'container_absent': False}
    report_arg = next((v.split('=', 1)[1] for v in sys.argv if v.startswith('--receipt=')), None)
    if not report_arg:
        raise SystemExit('--receipt=PATH required')
    with tempfile.TemporaryDirectory(prefix='notes-boundary-pg-', dir=SCRATCH) as tmp:
        try:
            env_file = Path(tmp) / 'pg.env'
            env_file.write_text(f'POSTGRES_DB={dbname}\nPOSTGRES_USER={role}\nPOSTGRES_PASSWORD={password}\n')
            env_file.chmod(0o600)
            cid = docker('run', '-d', '--name', name, '--label', 'stella.notes-boundary='+nonce,
                         '--publish', '127.0.0.1::5432', '--env-file', str(env_file),
                         '--memory', '768m', '--memory-swap', '768m',
                         '--tmpfs', '/var/lib/postgresql/data:rw,size=512m', 'postgres:16-alpine').stdout.strip()
            meta = json.loads(docker('inspect', cid).stdout)[0]
            assert meta['Id'] == cid and meta['Config']['Labels']['stella.notes-boundary'] == nonce
            binding = meta['NetworkSettings']['Ports']['5432/tcp']
            assert len(binding) == 1 and binding[0]['HostIp'] == '127.0.0.1'
            port = int(binding[0]['HostPort'])
            receipt.update(container_id=cid, host='127.0.0.1', port=port)
            connection = None
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    connection = psycopg2.connect(host='127.0.0.1', port=port, dbname=dbname, user=role,
                                                  password=password, connect_timeout=2)
                    break
                except psycopg2.OperationalError:
                    time.sleep(.2)
            assert connection is not None, 'Disposable PG TCP readiness failed'
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute('select current_database(), current_user')
                    assert cursor.fetchone() == (dbname, role)
            connection.close()
            manifest = Path(tmp) / 'manifest.json'
            manifest.write_text(json.dumps(dict(nonce=nonce, cid=cid, host='127.0.0.1', port=port,
                                                database=dbname, role=role, password=password)))
            manifest.chmod(0o600)
            env = {k:v for k,v in os.environ.items() if not k.startswith(('STELLA_', 'PG', 'HERMES_', 'MCP_', 'UV_'))
                   and k not in ('DATABASE_URL', 'VIRTUAL_ENV', 'NODE_ENV', 'PYTHONPATH')}
            env.update(HOME=tmp, TMPDIR=tmp, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', STELLA_BLOB_STORAGE='postgres',
                       NOTES_BOUNDARY_PG_MANIFEST=str(manifest))
            args = [arg for arg in sys.argv[1:] if arg != '--run-disposable-postgres' and not arg.startswith('--receipt=')]
            result = subprocess.run([sys.executable, '-m', 'pytest', '--noconftest', '-q',
                                     'tests_isolated/test_notes_review_boundaries_pg.py', *args], cwd=ROOT, env=env)
            receipt['pytest_exit'] = result.returncode
            connection = psycopg2.connect(host='127.0.0.1', port=port, dbname=dbname, user=role, password=password)
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute('select current_database(), current_user')
                    assert cursor.fetchone() == (dbname, role)
                    cursor.execute("select nspname from pg_namespace where nspname like 'notes_case_%'")
                    remaining = cursor.fetchall()
                    cursor.execute("select tablename from pg_tables where schemaname='public'")
                    public = cursor.fetchall()
                    receipt.update(remaining_schemas=remaining, public_tables=public, schemas_clean=not remaining and not public)
            connection.close()
            assert receipt['schemas_clean'], 'Disposable schema cleanup incomplete'
        finally:
            if cid:
                meta = json.loads(docker('inspect', cid).stdout)[0]
                assert meta['Id'] == cid and meta['Config']['Labels']['stella.notes-boundary'] == nonce
                docker('rm', '-f', cid)
                absent = docker('inspect', cid, check=False)
                receipt['container_absent'] = absent.returncode != 0 and 'no such' in absent.stderr.lower()
            Path(report_arg).write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))
    return receipt.get('pytest_exit', 1)


if __name__ == '__main__':
    raise SystemExit(main())
