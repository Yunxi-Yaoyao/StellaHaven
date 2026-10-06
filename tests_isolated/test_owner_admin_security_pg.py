"""Real PG proofs on a separately owned disposable localhost container ONLY.

No app settings DSN, production schema, files, emails, agents or remote tasks.
"""
import os
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4, UUID
import pytest
from tests_isolated.test_owner_admin_security import DAILY, ADMIN
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from app.database import get_db
from app.models.user import User, AuthSession
from app.models.config import AppConfig
from app.routers.auth import router, admin_user
from app.services.admin_security import STATE_KEY, locked_state, read_state

@pytest.fixture
def pg_security(monkeypatch):
    dsn = os.getenv('STELLA_SECURITY_TEST_DSN')
    if not dsn:
        pytest.skip('security-owned disposable PostgreSQL DSN not provided')
    for key in ('PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGUSER','PGPASSWORD','PGSERVICE','PGSERVICEFILE','PGOPTIONS'):
        assert key not in os.environ, 'ambient libpq overrides are forbidden'
    url = make_url(dsn)
    assert url.host == '127.0.0.1' and url.database == 'stella_security_test' and url.username == 'security'
    assert url.port == int(os.environ['STELLA_SECURITY_TEST_PORT']) and url.port > 1024
    assert url.port not in {5432,24532,24533,24534} and not url.query
    monkeypatch.delenv('STELLA_OWNER_ID',raising=False)
    engine = create_engine(url,connect_args={'connect_timeout':5})
    schema = 'security_' + uuid4().hex
    identity = ('stella_security_test','security','security-test-only')
    with engine.begin() as conn:
        assert conn.execute(text("SELECT current_database(),current_user,current_setting('stella.test_isolation',true)")).one() == identity
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    scoped = engine.execution_options(schema_translate_map={None:schema})
    for table in [User.__table__,AuthSession.__table__,AppConfig.__table__]:
        table.create(scoped)
    def db_session():
        with Session(scoped) as db:
            assert db.execute(text("SELECT current_database(),current_user,current_setting('stella.test_isolation',true)")).one() == identity
            yield db
    def make_app():
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = db_session
        @app.post('/danger')
        def danger(user=Depends(admin_user)):
            return {'ok':True}
        return app
    app = make_app()
    c0,c1 = TestClient(app),TestClient(app)
    assert c0.post('/auth/register',json={'username':'owner','password':DAILY}).status_code == 201
    assert c1.post('/auth/login',json={'username':'owner','password':DAILY}).status_code == 200
    try:
        yield scoped,c0,c1,make_app
    finally:
        c0.close(); c1.close()
        with engine.begin() as conn:
            assert conn.execute(text('SELECT current_database(),current_user')).one() == identity[:2]
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            assert not conn.execute(text('SELECT 1 FROM pg_namespace WHERE nspname=:name'),{'name':schema}).first()
        engine.dispose()


def test_pg_concurrent_management_setup_only_one_commits(pg_security):
    engine,c0,c1,_ = pg_security
    barrier = Barrier(2)
    def setup(c):
        barrier.wait(timeout=5)
        return c.post('/auth/admin/setup',json={'user_password':DAILY,'new_password':ADMIN}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(setup,[c0,c1]))
    assert sorted(results) == [200,409]
    with Session(engine) as db:
        assert db.query(User).count() == 1
        state = json.loads(db.get(AppConfig,STATE_KEY).value)
        assert state['password_hash'].startswith('$argon2id$')
        from app.services.backup_health import read_change_audit
        assert [event['action'] for event in read_change_audit(db)] == ['security.setup']


def test_pg_concurrent_unlocks_preserve_both_session_grants_and_invalidate_across_workers(pg_security):
    engine,c0,c1,make_app = pg_security
    assert c0.post('/auth/admin/setup',json={'user_password':DAILY,'new_password':ADMIN}).status_code == 200
    barrier = Barrier(2)
    def unlock(c):
        barrier.wait(timeout=5)
        return c.post('/auth/admin/unlock',json={'password':ADMIN}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(unlock,[c0,c1])) == [200,200]
    with Session(engine) as db:
        state = json.loads(db.get(AppConfig,STATE_KEY).value)
        assert len(state['grants']) == 2
        assert all(g['version'] == state['version'] for g in state['grants'].values())
    # Fresh app instance and fresh SQLAlchemy session: no process-local grant cache.
    second_worker = TestClient(make_app())
    second_worker.cookies.update(c1.cookies)
    assert second_worker.post('/danger').status_code == 200
    assert c0.post('/auth/admin/password',json={'current_password':ADMIN,'new_password':ADMIN+'2'}).status_code == 200
    assert second_worker.post('/danger').status_code == 403
    assert c1.post('/danger').status_code == 403
    second_worker.close()


def test_pg_authenticated_reads_do_not_wait_on_global_management_lock(pg_security):
    engine,c0,c1,_ = pg_security
    with Session(engine) as held:
        locked_state(held)
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(c0.get,'/auth/me').result(timeout=2)
        assert response.status_code == 200
        held.rollback()
