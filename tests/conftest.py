"""Guarded PostgreSQL, real single owner authentication, disposable schemas.

Run from an isolated scratch cwd with explicit STELLA_COOKIE_SECURE=false and
STELLA_MAIN_ORIGIN=STELLA_TRUSTED_ORIGINS=http://testserver.
Never bypass current_user/admin_user.
"""
from contextlib import contextmanager
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from app.config import settings
from tests_ha.testdb_guard import build_test_engine, guarded_metadata

engine = build_test_engine(settings.database_url)
TEST_DATABASE_URL = engine.url
from app.database import Base, get_db
from main import app

TestingSessionLocal = sessionmaker(bind=engine, autoflush=False)
OWNER_USERNAME = 'test_owner'
OWNER_PASSWORD = 'testpass123'
ADMIN_PASSWORD = 'test-management-independent-2026'

@pytest.fixture(scope='session', autouse=True)
def initial_host_install_tasks():
    # Registration/owner/session/host preparation remain real. Only the queued
    # OS installer boundary is intercepted: schema tests must never install an
    # Agent on the test runner (including when pytest runs as host root).
    from app.services import node
    tasks = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(node, '_run_initial_host_install',
                      lambda engine, node_id, attempt_id=None: tasks.append((engine, node_id, attempt_id)))
        yield tasks


@contextmanager
def runtime_database(target, factory=None):
    """Bind startup, imported sessionmaker aliases and fresh workers together."""
    from app import database
    from app.services.node_deadlines import NodeDeadlineWatcher
    previous_bind = database.sessionLocal.kw['bind']

    def deadlines(cls, url):
        # The product constructor opens a separate engine from just the URL,
        # losing fixture connect_args/search_path. Keep the real worker and its
        # start/stop lifecycle, but give its private pool the same guarded scope.
        if url != target.url:
            raise ValueError('Unexpected deadline database URL')
        return cls(build_test_engine(settings.database_url, factory=factory), owns_engine=True)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(database, 'engine', target)
        patch.setattr(NodeDeadlineWatcher, 'from_url', classmethod(deadlines))
        database.sessionLocal.configure(bind=target)
        try:
            yield
        finally:
            database.sessionLocal.configure(bind=previous_bind)


@pytest.fixture(scope='session')
def test_db(initial_host_install_tasks):
    # Root fixture also runs the real startup against its guarded test DB,
    # never the source settings DB (which CI deliberately leaves empty).
    with runtime_database(engine):
        yield from _test_db()


def _test_db():
    guarded_metadata(engine, Base.metadata, 'create_all')
    previous = dict(app.dependency_overrides)
    try:
        with TestingSessionLocal() as db:
            def private_db():
                yield db
            app.dependency_overrides[get_db] = private_db
            with TestClient(app, headers={'Origin':'http://testserver'}) as c:
                r = c.post('/auth/register', json={'username':OWNER_USERNAME,'password':OWNER_PASSWORD})
                assert r.status_code == 201, r.text
                r = c.post('/auth/admin/setup', json={'user_password':OWNER_PASSWORD,'new_password':ADMIN_PASSWORD})
                assert r.status_code == 410, r.text
                assert c.get('/auth/security').json()['elevated'] is True
                assert c.post('/auth/logout').status_code == 200
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        guarded_metadata(engine, Base.metadata, 'drop_all')

@pytest.fixture
def db_session(test_db):
    # Streaming blobs open fresh sessions: use a guarded per-test schema so
    # real commits are visible to them, while the entire schema is disposable.
    from uuid import uuid4
    from sqlalchemy import create_engine, text
    from tests_ha.testdb_guard import IDENTITY_SQL, verify_identity
    schema = 'upgrade_test_' + uuid4().hex
    url, address, revalidate = engine._stella_test_identity
    with engine.begin() as conn:
        revalidate()
        verify_identity(conn.execute(text(IDENTITY_SQL)).one(), url, address)
        conn.exec_driver_sql(f'CREATE SCHEMA {schema}')
    def schema_engine(url, connect_args):
        connect_args['options'] += f' -csearch_path={schema}'
        return create_engine(url, connect_args=connect_args)
    scoped = build_test_engine(settings.database_url, factory=schema_engine)
    try:
        with runtime_database(scoped, schema_engine):
            yield from _schema_session(scoped)
    finally:
        scoped.dispose()
        with engine.begin() as conn:
            revalidate()
            verify_identity(conn.execute(text(IDENTITY_SQL)).one(), url, address)
            conn.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
            assert conn.execute(text('SELECT 1 FROM pg_namespace WHERE nspname=:s'), {'s':schema}).first() is None

def _schema_session(scoped):
    previous = dict(app.dependency_overrides)
    try:
        guarded_metadata(scoped, Base.metadata, 'create_all')
        session = TestingSessionLocal(bind=scoped)
        app.dependency_overrides[get_db] = lambda: session
        with TestClient(app, headers={'Origin':'http://testserver'}) as c:
            assert c.post('/auth/register', json={'username':OWNER_USERNAME,'password':OWNER_PASSWORD}).status_code == 201
            assert c.post('/auth/admin/setup', json={'user_password':OWNER_PASSWORD,'new_password':ADMIN_PASSWORD}).status_code == 410
            assert c.post('/auth/logout').status_code == 200
        yield session
    finally:
        if 'session' in locals():
            session.rollback()
            session.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.fixture
def client(db_session):
    previous = dict(app.dependency_overrides)
    def private_db():
        yield db_session
    app.dependency_overrides[get_db] = private_db
    try:
        with TestClient(app, headers={'Origin':'http://testserver'}) as c:
            r = c.post('/auth/login', json={'username':OWNER_USERNAME,'password':OWNER_PASSWORD})
            assert r.status_code == 200, r.text
            r = c.post('/auth/admin/unlock', json={'password':ADMIN_PASSWORD})
            assert r.status_code == 410, r.text
            assert c.get('/auth/security').json()['elevated'] is True
            yield c
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
