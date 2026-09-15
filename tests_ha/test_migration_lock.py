"""Real PG migrations, scoped to a fresh schema; never load tests/conftest.py."""
import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import os
import time
import uuid

import pytest
from sqlalchemy import text
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from tests_ha.testdb_guard import build_test_engine, IDENTITY_SQL, verify_identity


@pytest.fixture
def db():
    source = os.environ.get('STELLA_TEST_DATABASE_URL')
    if not source and os.environ.get('CI') == 'true':
        from sqlalchemy.engine import URL
        expected = (os.environ.get('POSTGRES_HOST'), os.environ.get('POSTGRES_PORT'), os.environ.get('POSTGRES_USER'))
        if expected != ('postgres', '5432', 'stalla'):
            raise RuntimeError('Unexpected CI test database identity')
        source = URL.create('postgresql+psycopg2', username='stalla', password=os.environ.get('POSTGRES_PASSWORD'), host='postgres', port=5432, database='stella_test')
    if not source:
        pytest.skip('STELLA_TEST_DATABASE_URL required for guarded real PG tests')
    engine = build_test_engine(source)
    schema = 'migration_lock_' + uuid.uuid4().hex
    url, address, revalidate = engine._stella_test_identity
    with engine.begin() as conn:
        revalidate()
        verify_identity(conn.execute(text(IDENTITY_SQL)).one(), url, address)
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        yield engine, schema
    finally:
        with engine.begin() as conn:
            revalidate()
            verify_identity(conn.execute(text(IDENTITY_SQL)).one(), url, address)
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def runner(engine, schema, tmp_path, body):
    scripts = tmp_path / uuid.uuid4().hex
    (scripts / 'versions').mkdir(parents=True)
    (scripts / 'versions' / '001.py').write_text(
        'from alembic import op\nrevision="001"\ndown_revision=None\n'
        'def upgrade():\n' + ''.join('    ' + line + '\n' for line in body.splitlines())
        + 'def downgrade():\n    raise AssertionError("no automatic downgrade")\n')
    cfg = Config()
    cfg.set_main_option('script_location', str(scripts))
    script = ScriptDirectory.from_config(cfg)
    # Extract only online code: no app imports, production settings, or global
    # Alembic proxy installation. Each thread has its own real EnvironmentContext.
    tree = ast.parse((Path(__file__).parents[1] / 'alembic/env.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_migrations_online']
    code = compile(ast.Module(body=nodes, type_ignores=[]), 'alembic/env.py', 'exec')

    class ScopedEngine:
        def connect(self):
            connection = engine.connect()
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.execute(text("SET statement_timeout = '5s'"))
            connection.commit()
            return connection

        def dispose(self):
            pass

    def run():
        ctx = EnvironmentContext(cfg, script, fn=lambda rev, context: script._upgrade_revs('head', rev))
        namespace = dict(context=ctx, settings=SimpleNamespace(database_url='unused'),
                         engine_from_config=lambda *a, **k: ScopedEngine(),
                         pool=SimpleNamespace(NullPool=None), target_metadata=None, text=text)
        exec(code, namespace)
        namespace['run_migrations_online']()
    return run


def test_real_pg_concurrent_migrations_serialize_and_read_latest(db, tmp_path):
    engine, schema = db
    run = runner(engine, schema, tmp_path, 'op.execute("CREATE TABLE executed (id int)")\nop.execute("INSERT INTO executed VALUES (1)")\nop.execute("SELECT pg_sleep(1)")')
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(run)
        time.sleep(0.2)
        second = workers.submit(run)
        waiting = False
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            with engine.connect() as conn:
                waiting = conn.execute(text("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) AND NOT granted)")).scalar()
            if waiting:
                break
            time.sleep(0.02)
        # Resolve both workers even on the original (unlocked) implementation.
        outcomes = []
        for future in (first, second):
            try:
                future.result(timeout=6)
                outcomes.append(None)
            except Exception as exc:
                outcomes.append(type(exc).__name__)
    assert waiting, f'No real PostgreSQL advisory lock waiter; outcomes={outcomes}'
    assert outcomes == [None, None]
    with engine.connect() as conn:
        assert conn.execute(text(f'SELECT count(*) FROM "{schema}".executed')).scalar() == 1
        assert conn.execute(text(f'SELECT version_num FROM "{schema}".alembic_version')).scalar() == '001'


def test_failed_migration_rolls_back_ddl_version_and_releases_lock(db, tmp_path):
    engine, schema = db
    run = runner(engine, schema, tmp_path, 'op.execute("CREATE TABLE failed_ddl (id int)")\nraise RuntimeError("injected failure")')
    with pytest.raises(RuntimeError, match='injected failure'):
        run()
    with engine.connect() as conn:
        assert conn.execute(text('SELECT to_regclass(:name)'), {'name': schema + '.failed_ddl'}).scalar() is None
        assert conn.execute(text('SELECT to_regclass(:name)'), {'name': schema + '.alembic_version'}).scalar() is None
    with engine.begin() as conn:
        assert conn.execute(text('SELECT pg_try_advisory_xact_lock(1937007980, 1)')).scalar() is True
    runner(engine, schema, tmp_path, 'op.execute("CREATE TABLE success (id int)")')()
    with engine.connect() as conn:
        assert conn.execute(text(f'SELECT version_num FROM "{schema}".alembic_version')).scalar() == '001'


@pytest.mark.parametrize('role_result', ["true, 'off'", "false, 'on'"])
def test_refuses_standby_or_readonly_before_migration(db, tmp_path, role_result):
    from sqlalchemy import event
    engine, schema = db
    def fake_role(conn, cursor, statement, parameters, context, executemany):
        if 'pg_is_in_recovery()' in statement:
            return 'SELECT ' + role_result, parameters
        return statement, parameters
    event.listen(engine, 'before_cursor_execute', fake_role, retval=True)
    try:
        run = runner(engine, schema, tmp_path, 'op.execute("CREATE TABLE forbidden (id int)")')
        with pytest.raises(RuntimeError, match='writable PostgreSQL primary'):
            run()
    finally:
        event.remove(engine, 'before_cursor_execute', fake_role)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM information_schema.tables WHERE table_schema=:schema'), {'schema': schema}).scalar() == 0
