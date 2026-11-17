import io
import os
import subprocess
import sys
from pathlib import Path
import pytest


def test_pg_tools_have_packaged_pg18_dependency():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'Dockerfile').read_text()
    assert 'postgres:18' in source and 'AS backup-pg-client' in source
    assert '--from=backup-pg-client /usr/lib/postgresql/18/bin/pg_dump' in source
    assert '--from=backup-pg-client /usr/lib/postgresql/18/bin/pg_restore' in source
    assert "pg_dump', '--version'" in source and "pg_restore', '--version'" in source


def test_pg_client_and_dump_do_not_accept_ambient_routing(engine,tmp_path,monkeypatch):
    from app.services.backup_postgres import export_all
    for key in ('PGHOST','PGHOSTADDR','PGDATABASE','PGUSER','PGSERVICE','PGSERVICEFILE','PGOPTIONS'):
        monkeypatch.setenv(key,'NOT-THE-TARGET')
    with engine.connect().execution_options(isolation_level='REPEATABLE READ',postgresql_readonly=True) as conn:
        with export_all(conn,tmp_path,tmp_path) as payload:
            assert payload.entries['database.dump'].read(5)==b'PGDMP'
