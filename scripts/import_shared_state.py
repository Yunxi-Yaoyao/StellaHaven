"""Explicit, offline legacy JSON import; never overwrites existing PG rows.

Usage: PYTHONPATH=. python scripts/import_shared_state.py --database-url-file /private/dsn.txt
       --confirm-database stella_ha_integration --clients /snapshot/clients.json
       --smtp /snapshot/email_config.json [--runtime /snapshot/state.json]
Stop all writers first. The DSN file contains only a PostgreSQL URL, mode 0600.
Private signing keys are NOT imported; provision the same key file on all nodes.
"""
import argparse
import json
import os
from pathlib import Path
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from app.services.ha_state import state_table


def import_files(engine, *, clients=None, smtp=None, runtime=None):
    if engine.dialect.name != 'postgresql':
        raise ValueError('PostgreSQL required')
    payloads = {}
    for key, path in [('oidc.clients', clients), ('smtp.config', smtp), ('oidc.runtime', runtime)]:
        if path is None:
            continue
        value = json.loads(Path(path).read_text())
        if not isinstance(value, dict):
            raise ValueError('JSON objects required')
        if key == 'oidc.clients' and any(not isinstance(v, dict) or not isinstance(v.get('client_secret'), str) or not isinstance(v.get('redirect_uris'), list) for v in value.values()):
            raise ValueError('Invalid client records')
        if key == 'oidc.runtime':
            if set(value) != {'codes', 'tokens'} or any(not isinstance(value[k], dict) for k in value):
                raise ValueError('Invalid runtime state')
            if any(not isinstance(rec, dict) or not isinstance(rec.get('expires'), (int, float)) for group in value.values() for rec in group.values()):
                raise ValueError('Invalid runtime records')
        payloads[key] = value
    if not payloads:
        raise ValueError('Select at least one source file')
    with engine.begin() as conn:
        for key, value in payloads.items():
            result = conn.execute(insert(state_table).values(key=key, payload=value).on_conflict_do_nothing(index_elements=['key']))
            if result.rowcount != 1:
                raise ValueError('Target state already exists; refusing overwrite')
            actual = conn.execute(select(state_table.c.payload).where(state_table.c.key == key)).scalar_one()
            if actual != value:
                raise RuntimeError('Import verification failed')
    return list(payloads)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url-file', required=True, type=Path)
    parser.add_argument('--confirm-database', required=True)
    for name in ('clients', 'smtp', 'runtime'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    engine = None
    try:
        if args.database_url_file.stat().st_mode & 0o077:
            raise ValueError('DSN file must be private')
        url = make_url(args.database_url_file.read_text().strip())
        if url.database != args.confirm_database or url.get_backend_name() != 'postgresql':
            raise ValueError('Database confirmation mismatch')
        engine = create_engine(url, hide_parameters=True)
        with engine.connect() as conn:
            if conn.scalar(text('select current_database()')) != args.confirm_database:
                raise ValueError('Connected database mismatch')
        keys = import_files(engine, clients=args.clients, smtp=args.smtp, runtime=args.runtime)
        print('Imported and verified: ' + ', '.join(keys))
        return 0
    except Exception:
        # DB/JSON exception strings can contain credentials or full payloads.
        print('Import failed; transaction rolled back. Check private inputs, schema and existing keys.')
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
