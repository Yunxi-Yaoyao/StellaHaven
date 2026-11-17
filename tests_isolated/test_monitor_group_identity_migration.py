"""Exercise only the new migration against an owned pre-migration SQLite table."""
import importlib.util
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_stable_group_identity_migration_backfills_and_roundtrips(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/cd20261020_monitor_group_identity.py'
    assert path.exists(), 'stable group identity needs a real migration, not only a model default'
    spec = importlib.util.spec_from_file_location('group_identity_migration', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.down_revision == 'cc20261020'
    engine = sa.create_engine('sqlite://')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE monitor_groups (id INTEGER PRIMARY KEY, name VARCHAR(64) NOT NULL, failure_policy VARCHAR(8) NOT NULL, rotation_seconds INTEGER NOT NULL)')
        conn.exec_driver_sql("INSERT INTO monitor_groups VALUES (1, 'before one', 'any', 0), (2, 'before two', 'all', 15)")
        old_rows = conn.exec_driver_sql('SELECT * FROM monitor_groups ORDER BY id').all()
        monkeypatch.setattr(module, 'op', Operations(MigrationContext.configure(conn)))
        module.upgrade()
        rows = conn.exec_driver_sql('SELECT id, name, failure_policy, rotation_seconds, stable_uuid FROM monitor_groups ORDER BY id').all()
        assert [tuple(r[:4]) for r in rows] == [tuple(r) for r in old_rows]
        assert len({UUID(r.stable_uuid) for r in rows}) == 2
        assert all(str(UUID(r.stable_uuid)) == r.stable_uuid for r in rows)
        with pytest.raises(sa.exc.IntegrityError):
            conn.exec_driver_sql("INSERT INTO monitor_groups VALUES (3, 'duplicate', 'any', 0, ?)", (rows[0].stable_uuid,))
        with pytest.raises(sa.exc.IntegrityError):
            conn.exec_driver_sql("INSERT INTO monitor_groups (id, name, failure_policy, rotation_seconds) VALUES (3, 'missing uuid', 'any', 0)")
        module.downgrade()
        assert conn.exec_driver_sql('SELECT * FROM monitor_groups ORDER BY id').all() == old_rows
    engine.dispose()
