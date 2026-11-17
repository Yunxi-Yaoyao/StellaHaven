"""Separate finite bulk I/O deadlines from small metadata query limits."""
from argparse import Namespace
import importlib.util
from pathlib import Path
import pytest
from sqlalchemy.engine import make_url


def test_bulk_budget_is_explicit_finite_and_rejects_invalid_values():
    from app.services import backup_archive
    validate = getattr(backup_archive, 'bulk_timeout', None)
    assert callable(validate), 'backup bulk operations need a shared bounded deadline validator'
    assert validate(None, default=3600) == 3600
    assert validate('900', default=3600) == 900
    for value in (True, False, 0, -1, '0', 'NaN', '1.5', '14401', 14401, ''):
        with pytest.raises(ValueError):
            validate(value, default=3600)


def test_pg_snapshot_dump_uses_its_own_bounded_bulk_budget(engine, tmp_path, monkeypatch):
    from app.services import backup_postgres
    monkeypatch.setenv('STELLA_BACKUP_TIMEOUT_SECONDS', '900')
    calls = []
    original = backup_postgres.subprocess.run
    def observed(args, **kwargs):
        if '--format=custom' in args:
            calls.append({'timeout': kwargs['timeout'], 'pgoptions': kwargs['env'].get('PGOPTIONS')})
        return original(args, **kwargs)
    monkeypatch.setattr(backup_postgres.subprocess, 'run', observed)
    with engine.connect().execution_options(isolation_level='REPEATABLE READ', postgresql_readonly=True) as conn:
        with backup_postgres.export_all(conn, tmp_path, tmp_path / 'data') as payload:
            assert payload.entries['database.dump'].read(5) == b'PGDMP'
    assert calls == [{'timeout': 900, 'pgoptions': '-c statement_timeout=900000'}]


def test_default_dump_budget_is_not_the_metadata_three_minute_timeout(monkeypatch):
    from app.services.backup_postgres import pg_environment
    monkeypatch.delenv('STELLA_BACKUP_TIMEOUT_SECONDS', raising=False)
    env = pg_environment(make_url('postgresql://fixture:fixture@127.0.0.1/fixture'))
    assert env['PGOPTIONS'] == '-c statement_timeout=3600000'


def test_offline_restore_rejects_invalid_budget_before_any_file_or_db_access(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'tools/backup_restore.py'
    spec = importlib.util.spec_from_file_location('parent_backup_budget_cli', path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    args = Namespace(maintenance=True, confirm_target='fixture:5432/empty', host='fixture',
                     port=5432, database='empty', user='fixture', data_directory='/must-not-touch',
                     password_file='/must-not-read', timeout_seconds=0)
    monkeypatch.setattr(cli, 'safe_parent', lambda *a: (_ for _ in ()).throw(AssertionError('file path checked before invalid budget rejected')))
    with pytest.raises(ValueError, match='budget'):
        cli.restore(args)
