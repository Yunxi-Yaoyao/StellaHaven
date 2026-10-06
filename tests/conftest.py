"""Guarded PostgreSQL, real single owner/auth/elevation, disposable schemas.

Run from an isolated scratch cwd with explicit STELLA_COOKIE_SECURE=false and
STELLA_MAIN_ORIGIN=STELLA_TRUSTED_ORIGINS=http://testserver.
Never bypass current_user/admin_user.
"""
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

@pytest.fixture(scope='session')
def test_db():
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
                assert r.status_code == 200, r.text
                assert c.get('/auth/security').json()['elevated'] is False
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
    previous = dict(app.dependency_overrides)
    try:
        guarded_metadata(scoped, Base.metadata, 'create_all')
        session = TestingSessionLocal(bind=scoped)
        app.dependency_overrides[get_db] = lambda: session
        with TestClient(app, headers={'Origin':'http://testserver'}) as c:
            assert c.post('/auth/register', json={'username':OWNER_USERNAME,'password':OWNER_PASSWORD}).status_code == 201
            assert c.post('/auth/admin/setup', json={'user_password':OWNER_PASSWORD,'new_password':ADMIN_PASSWORD}).status_code == 200
            assert c.post('/auth/logout').status_code == 200
        yield session
    finally:
        if 'session' in locals():
            session.rollback()
            session.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        scoped.dispose()
        with engine.begin() as conn:
            revalidate()
            verify_identity(conn.execute(text(IDENTITY_SQL)).one(), url, address)
            conn.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
            assert conn.execute(text('SELECT 1 FROM pg_namespace WHERE nspname=:s'), {'s':schema}).first() is None

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
            assert r.status_code == 200, r.text
            assert c.get('/auth/security').json()['elevated'] is True
            yield c
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
