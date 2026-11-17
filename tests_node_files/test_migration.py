def test_file_journal_migration_owned_schema():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text
    from app.database import engine
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/nf20261023_node_files.py'
    assert path.is_file(), 'file journal migration missing'
    spec = importlib.util.spec_from_file_location('nf_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as conn:
        conn.execute(text('CREATE SCHEMA nf_migration_test'))
        conn.execute(text('SET LOCAL search_path TO nf_migration_test'))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert set(inspect(conn).get_table_names(schema='nf_migration_test')) == {'node_file_agents', 'node_file_jobs'}
            migration.downgrade()
            assert inspect(conn).get_table_names(schema='nf_migration_test') == []
        conn.execute(text('DROP SCHEMA nf_migration_test'))
