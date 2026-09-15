#!/usr/bin/env python3
"""Read-only local role/resource probe; no import of application startup code."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import urllib.error
import urllib.request


def secret(path):
    value = Path(path).read_text().strip()
    if not value:
        raise ValueError('required secret is empty')
    return value


def check_resources(root=Path('/app/data'), *, full=False):
    root = Path(root).resolve()
    manifest = root / 'manifest.json'
    raw = manifest.read_bytes()
    files = json.loads(raw)['files']
    if not isinstance(files, dict) or not files:
        raise ValueError('resource manifest must list required files')
    for name, record in files.items():
        relative = PurePosixPath(name)
        path = root / relative
        if relative.is_absolute() or '..' in relative.parts or not path.resolve().is_relative_to(root):
            raise ValueError('resource path escapes bundle')
        if not path.is_file() or path.is_symlink() or path.stat().st_size != record['size']:
            raise ValueError('required resource missing or changed')
        if full:
            with path.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            if digest != record['sha256']:
                raise ValueError('resource digest mismatch')
    return hashlib.sha256(raw).hexdigest()


def http_status(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def sql_role(connect=None):
    if connect is None:
        import psycopg2
        connect = psycopg2.connect
    # Intentionally fixed same-node endpoint, never settings fallback or pg-rw.
    with connect(host='127.0.0.1', port=24532, dbname=os.environ.get('POSTGRES_DB', 'stella'),
                 user=os.environ.get('POSTGRES_USER', 'stalla'),
                 password=secret('/run/secrets/app-password'), connect_timeout=2,
                 options='-c statement_timeout=2000') as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_is_in_recovery(), current_setting('transaction_read_only') = 'on'")
            return cursor.fetchone()


def report():
    recovery, readonly = sql_role()
    result = {'name': os.environ['LOCAL_HA_NODE'],
              'primary_http': http_status('http://127.0.0.1:24808/primary'),
              'in_recovery': recovery, 'read_only': readonly,
              'app_ok': http_status('http://127.0.0.1:24131/live') == 200,
              'resources_ok': True, 'bundle_id': check_resources(),
              'signing_key_id': hashlib.sha256(secret('/data/secret_key').encode()).hexdigest()}
    result['ready_primary'] = (result['primary_http'] == 200 and recovery is False and readonly is False
                               and result['app_ok'] and http_status('http://127.0.0.1:24131/ready-primary') == 200)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--primary', action='store_true')
    args = parser.parse_args()
    try:
        result = report()
        print(json.dumps(result))
        raise SystemExit(0 if not args.primary or result['ready_primary'] else 1)
    except Exception as exc:
        print(json.dumps({'status': 'unready', 'error': type(exc).__name__}))
        raise SystemExit(1)
