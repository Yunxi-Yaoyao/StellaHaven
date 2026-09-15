#!/usr/bin/env python3
"""Disabled-by-default entrypoints. Never initialize, chown, copy, or delete PGDATA."""
import json
import os
from pathlib import Path
import sys

from readiness import check_resources, secret
from release import SCOPE, Refused


def check_pgdata(data):
    data = Path(data)
    if not (data / 'PG_VERSION').is_file() or (data / 'PG_VERSION').read_text().strip() != '18':
        raise Refused('operator-seeded independent PostgreSQL 18 PGDATA required; init/clone is not authorized here')
    if not (data / '.local-ha-independent').is_file() or (data / '.local-ha-independent').read_text().strip() != SCOPE:
        raise Refused('independent PGDATA inventory marker missing; NEVER reuse a k3s volume')


def start(role, argv):
    if os.environ.get('LOCAL_HA_PROFILE') != 'manual':
        raise Refused('automatic profile not implemented; no verified hardware fencing')
    env = dict(os.environ)
    if role == 'app':
        if env.get('LOCAL_HA_ENABLE_APP') != 'operator-approved':
            raise Refused('app startup not authorized')
        if env.get('STELLA_HA_MODE') != 'primary-only':
            raise Refused('single-writer app gate required')
        if env.get('STELLA_BLOB_STORAGE') != 'postgres' or env.get('STELLA_SHARED_STATE') != 'postgres':
            raise Refused('independent app requires transactional PG state/media')
        secret('/run/secrets/oidc-private.json')
        check_resources(full=True)
        if len(secret('/data/secret_key')) < 32:
            raise Refused('externally provisioned shared signing secret required; no key generation')
        env['POSTGRES_PASSWORD'] = secret('/run/secrets/app-password')
        if not argv:
            raise Refused('app command missing')
        os.execvpe(argv[0], argv, env)
    elif role == 'pg':
        if env.get('LOCAL_HA_ENABLE_DATABASE') != 'operator-approved':
            raise Refused('database startup not authorized')
        check_pgdata('/var/lib/postgresql/local-ha/pgdata')
        config = json.loads(Path('/etc/local-ha/patroni.json').read_text())
        if config.get('scope') != SCOPE or config.get('tags', {}).get('nofailover') is not True:
            raise Refused('isolated scope and nofailover=true required')
        if config.get('watchdog', {}).get('mode') != 'off' or 'bootstrap' in config or 'pause' in config:
            raise Refused('manual template only; watchdog/initialization/pause not authorized')
        env.update(PATRONI_SUPERUSER_PASSWORD=secret('/run/secrets/pg-super-password'),
                   PATRONI_REPLICATION_PASSWORD=secret('/run/secrets/pg-repl-password'),
                   PATRONI_RESTAPI_USERNAME='local-ha-operator',
                   PATRONI_RESTAPI_PASSWORD=secret('/run/secrets/patroni-api-password'))
        os.execvpe('gosu', ['gosu', 'postgres', 'patroni', '/etc/local-ha/patroni.json'], env)
    else:
        raise Refused('unknown role')


if __name__ == '__main__':
    try:
        start(sys.argv[1], sys.argv[2:])
    except Exception as exc:
        print(json.dumps({'status': 'refused', 'error': type(exc).__name__}), file=sys.stderr)
        raise SystemExit(2)
