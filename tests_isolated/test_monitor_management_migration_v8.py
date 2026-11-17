"""Run real Alembic operations on an owned pre-v8 SQLite database."""
import importlib.util
from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_management_migration_keeps_existing_rows_and_guards_downgrade(monkeypatch):
    path=Path(__file__).resolve().parents[1]/'alembic/versions/ce20261021_monitor_management.py'
    assert path.exists(), 'persist flags through a real non-destructive migration'
    spec=importlib.util.spec_from_file_location('v8_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.down_revision=='cd20261020'
    engine=sa.create_engine('sqlite://')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE monitors (id INTEGER PRIMARY KEY, target TEXT NOT NULL)')
        conn.exec_driver_sql('CREATE TABLE monitor_groups (id INTEGER PRIMARY KEY, stable_uuid TEXT NOT NULL)')
        conn.exec_driver_sql("INSERT INTO monitors VALUES (7,'retained.example')")
        conn.exec_driver_sql("INSERT INTO monitor_groups VALUES (3,'retained-uuid')")
        monkeypatch.setattr(module,'op',Operations(MigrationContext.configure(conn)))
        module.upgrade()
        assert tuple(conn.exec_driver_sql('SELECT * FROM monitors').one())==(7,'retained.example',1,1)
        assert tuple(conn.exec_driver_sql('SELECT * FROM monitor_groups').one())==(3,'retained-uuid',1,1)
        conn.exec_driver_sql('UPDATE monitors SET enabled=0 WHERE id=7')
        with pytest.raises(RuntimeError,match='disabled|隐藏|停用'):
            module.downgrade()
        assert conn.exec_driver_sql('SELECT enabled FROM monitors').scalar()==0
        conn.exec_driver_sql('UPDATE monitors SET enabled=1 WHERE id=7')
        module.downgrade()
        assert tuple(conn.exec_driver_sql('SELECT * FROM monitors').one())==(7,'retained.example')
    engine.dispose()
