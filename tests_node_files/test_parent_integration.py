"""Parent integration checks: actual shared route mount and merged additive DDL."""
from pathlib import Path
from uuid import uuid4


def test_merged_navigation_file_ddl_preserves_existing_user(system):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text
    from app.database import engine
    root = Path(__file__).resolve().parents[1]
    # Resolve script_location explicitly: the child cwd is its owned scratch.
    config = Config(str(root / 'alembic.ini')); config.set_main_option('script_location', str(root / 'alembic'))
    graph = ScriptDirectory.from_config(config)
    assert graph.get_heads() == ['merge20261023navcat']
    revisions = list(graph.iterate_revisions('merge20261023navcat', 'ce20261021'))
    assert {r.revision for r in revisions} == {'merge20261023navcat', 'd020261023navcat', 'merge20261023nfnav', 'cf20261023nav', 'nf20261023'}
    schema = 'owned_combination_' + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
        conn.execute(text(f'SET LOCAL search_path TO {schema}'))
        conn.execute(text('CREATE TABLE users (id uuid PRIMARY KEY, name text NOT NULL)'))
        sentinel = str(uuid4()); conn.execute(text('INSERT INTO users VALUES (:id, :name)'), {'id': sentinel, 'name':'preserved'})
        with Operations.context(MigrationContext.configure(conn)):
            for revision in reversed(revisions):
                revision.module.upgrade()
            assert set(inspect(conn).get_table_names(schema=schema)) == {'users','nav_states','nav_assets','node_file_agents','node_file_jobs'}
            assert 'category' in {c['name'] for c in inspect(conn).get_columns('nav_assets', schema=schema)}
            assert conn.scalar(text('SELECT id::text FROM users')) == sentinel
            for revision in revisions:
                revision.module.downgrade()
            assert inspect(conn).get_table_names(schema=schema) == ['users']
            assert conn.scalar(text('SELECT count(*) FROM users')) == 1
        conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))


def test_main_site_actually_mounts_file_routes_and_blocks_spa_fallback(system, monkeypatch):
    # Current main source, not a handwritten route copy. Never enter its startup
    # lifecycle: all tables/identity are synthetic and owned by this netns fixture.
    from fastapi.testclient import TestClient
    monkeypatch.setenv('STELLA_MAIN_ORIGIN', 'https://stella.xiya.live')
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'https://stella.xiya.live')
    import main
    # FastAPI stores included routers lazily; public OpenAPI resolves the graph.
    paths = main.app.openapi()['paths']
    assert '/node-files/nodes' in paths and '/agent/files/claim' in paths
    assert '/node-files' in main.API_PREFIXES
    client = TestClient(main.app, base_url='https://stella.xiya.live')
    try:
        assert client.get('/node-files/nodes').status_code == 401
        assert client.post('/agent/files/claim', json={'roots':{}}, headers={'Origin':'https://stella.xiya.live'}).status_code == 401
        missing = client.get('/node-files/no-such-endpoint')
        assert missing.status_code == 404 and 'text/html' not in missing.headers.get('content-type','')
    finally:
        client.close()
