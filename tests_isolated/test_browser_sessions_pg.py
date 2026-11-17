"""Opt-in dedicated-loopback PG proofs; never accepts a production DSN."""
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from tests_isolated.test_browser_sessions import api  # noqa: F401


@pytest.fixture
def pg(api):
    raw = os.getenv('STELLA_BROWSER_PG_TEST')
    if not raw:
        pytest.skip('explicit dedicated PG required')
    url = make_url(raw)
    assert (url.host, url.port, url.database, url.username) == ('127.0.0.1', 32858, 'stella_browser_test', 'postgres')
    assert not url.query
    assert not any(k.startswith('PG') for k in os.environ)
    engine = create_engine(raw)
    schema = 'browser_test_' + uuid4().hex
    with engine.begin() as c:
        assert c.scalar(text('select current_database()')) == 'stella_browser_test'
        c.execute(text(f'CREATE SCHEMA {schema}'))
    scoped = create_engine(raw, connect_args={'options': f'-csearch_path={schema}'})
    from app.models.config import AppConfig
    from app.services.admin_security import STATE_KEY
    import json
    with scoped.begin() as c:
        assert c.scalar(text('select current_database()')) == 'stella_browser_test'
        for t in (api.User.__table__, api.AuthSession.__table__, AppConfig.__table__):
            t.create(c)
    factory = sessionmaker(scoped)
    with api.factory() as source, factory() as target:
        owner = source.get(api.User, api.uid)
        target.add(api.User(id=api.uid, username=owner.username, display_name=owner.display_name, password_hash=owner.password_hash))
        target.add(AppConfig(key=STATE_KEY, value=json.dumps({'owner_id': str(api.uid)})))
        target.commit()
    try:
        yield api, factory, scoped
    finally:
        scoped.dispose()
        with engine.begin() as c:
            assert c.scalar(text('select current_database()')) == 'stella_browser_test'
            c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            assert c.scalar(text('select count(*) from information_schema.schemata where schema_name=:s'), {'s': schema}) == 0
        engine.dispose()


def test_pg_concurrent_same_browser_exactly_one_live_session(pg):
    from starlette.requests import Request
    from starlette.responses import Response
    api, factory, engine = pg
    bid = uuid4()
    gate = Barrier(2)
    def worker():
        with factory() as db:
            user = db.get(api.User, api.uid)
            request = Request({'type': 'http', 'scheme': 'https', 'server': ('one.test', 443),
                'path': '/auth/login', 'headers': [(b'host', b'one.test')], 'query_string': b'', 'client': ('8.8.8.8', 5000)})
            gate.wait(timeout=10)
            session = api.auth._create_session(db, user, request, Response(), False, browser_id=bid)
            db.commit()
            return session.id
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: worker(), range(2)))
    with factory() as db:
        rows = db.query(api.AuthSession).all()
        assert len(rows) == 2 and len(set(ids)) == 2
        assert sum(not r.revoked for r in rows) == 1


def test_pg_migration_upgrade_downgrade_keeps_legacy_row(pg):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from pathlib import Path
    api, factory, engine = pg
    path = Path('alembic/versions/c1d2e3f4a5b6_browser_session_metadata.py')
    assert path.exists(), 'additive browser metadata migration missing'
    spec = importlib.util.spec_from_file_location('browser_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == 'c0d1e2f3a4b5'
    sid = uuid4()
    with engine.begin() as c:
        migration.op = Operations(MigrationContext.configure(c))
        migration.downgrade()
        c.execute(text('INSERT INTO auth_sessions(id,user_id,refresh_hash,device,ip,remember,revoked) VALUES (:id,:uid,:hash,:device,:ip,false,false)'),
                  {'id': sid, 'uid': api.uid, 'hash': 'legacy', 'device': 'legacy-device', 'ip': '192.0.2.1'})
        migration.upgrade()
        row = c.execute(text('select device, browser_id, browser_name, os_name, login_origin from auth_sessions where id=:id'), {'id': sid}).one()
        assert tuple(row) == ('legacy-device', None, None, None, None)
        migration.downgrade()
        assert 'browser_id' not in {x['name'] for x in inspect(c).get_columns('auth_sessions')}
        assert c.scalar(text('select count(*) from auth_sessions')) == 1
        migration.upgrade()
        assert c.scalar(text('select count(*) from auth_sessions')) == 1
