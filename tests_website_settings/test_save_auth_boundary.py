"""Real mounted admin dependencies must end their auth transaction before saving.

Only remote checker transport/audit sink are synthetic. Authentication, JWT,
owner locking, the save service and PostgreSQL transactions are real.
"""
import asyncio
import json
import threading
import time
from uuid import uuid4

import pytest
from tests_website_settings.test_save_light_navigation import factory

CHECK = dict(normalized_url='https://site.fixture.test/', name_suggestion='Fixture',
    access=dict(status='reachable', http_status=200),
    embedding=dict(status='allowed', reason_code='allowed', reason='Synthetic transport'),
    injection=dict(status='supported', reason='Synthetic transport'), help=None,
    can_save=True, recommended_behavior='embedded', issues=[])


@pytest.fixture
def real_app(factory, monkeypatch):
    from fastapi import FastAPI, Depends
    from sqlalchemy import text
    from app.database import get_db
    from app.models.user import User, AuthSession
    from app.models.config import AppConfig
    from app.routers.auth import current_user, admin_user
    from app.routers.website_settings import router
    from app.services import website_settings as service, integrations as store
    from app.services.admin_security import STATE_KEY
    from app.security import make_access_token
    engine = factory.kw['bind']
    for table in (User.__table__, AuthSession.__table__): table.create(engine, checkfirst=True)
    with factory() as db:
        db.query(AppConfig).delete()
        user = User(username='boundary-'+uuid4().hex, display_name='Unchanged', password_hash='not-a-login', is_active=True)
        db.add(user); db.flush(); uid = user.id
        session = AuthSession(user_id=uid, refresh_hash=uuid4().hex)
        db.add(session); db.flush(); sid = session.id
        db.add(AppConfig(key=STATE_KEY, value=json.dumps(dict(owner_id=str(uid), enabled=True, version=1, grants={}))))
        db.commit()
    requests = []
    def database():
        with factory() as db:
            requests.append(db)
            # Observation bound only; no application timeout is changed.
            db.execute(text("SET LOCAL statement_timeout='150ms'"))
            yield db
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = database
    @app.get('/real-admin-probe')
    def probe(user=Depends(admin_user)): return {'id': str(user.id)}
    assert current_user not in app.dependency_overrides and admin_user not in app.dependency_overrides
    async def checked(*a, **kw): return dict(CHECK)
    monkeypatch.setattr(service, 'check_draft', checked)
    monkeypatch.setattr(store, 'record_change', lambda *a, **kw: None)
    return app, engine, uid, sid, make_access_token(str(uid), str(sid)), requests


@pytest.mark.parametrize('mode', ['create-check', 'update-check', 'metadata-worker'])
def test_mounted_admin_releases_auth_checkout_and_owner_lock(real_app, factory, monkeypatch, mode):
    import httpx
    from contextlib import contextmanager
    from sqlalchemy import text
    from app.services import website_settings as service, integrations as store
    app, engine, uid, sid, token, requests = real_app
    async def exercise():
        loop_thread = threading.get_ident()
        entered, release = threading.Event(), threading.Event()
        rollback_threads = []
        from sqlalchemy import event
        from sqlalchemy.orm import Session
        def rolled_back(session):
            if requests and session is requests[0]: rollback_threads.append(threading.get_ident())
        event.listen(Session, 'after_rollback', rolled_back)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://stella.test', cookies={'stella_at': token}) as wire:
            mid = None
            if mode != 'create-check':
                first = await wire.post('/website-settings', json=dict(address=CHECK['normalized_url'], idempotency_key='boundary-initial'))
                assert first.status_code == 201, first.text
                mid = first.json()['id']
            requests.clear(); rollback_threads.clear()
            if mode == 'metadata-worker':
                original = store.edit
                @contextmanager
                def held(db):
                    entered.set(); assert release.wait(5)
                    with original(db) as state: yield state
                monkeypatch.setattr(store, 'edit', held)
                async def forbidden(*a, **kw): raise AssertionError('metadata must not probe')
                monkeypatch.setattr(service, 'check_draft', forbidden)
            else:
                async def held(*a, **kw):
                    entered.set()
                    for _ in range(5000):
                        if release.is_set(): return dict(CHECK) | {'normalized_url': 'https://changed.fixture.test/' if mid else CHECK['normalized_url']}
                        await asyncio.sleep(.001)
                    raise AssertionError('checker not released')
                monkeypatch.setattr(service, 'check_draft', held)
            body = dict(address='https://changed.fixture.test/' if mode == 'update-check' else CHECK['normalized_url'], name='Saved', idempotency_key='boundary-held-'+mode)
            task = asyncio.create_task(wire.request('PATCH' if mid else 'POST', '/website-settings'+('/'+mid if mid else ''), json=body))
            try:
                for _ in range(3000):
                    if entered.is_set(): break
                    if task.done(): await task
                    await asyncio.sleep(.001)
                assert entered.is_set(), 'save did not reach observation boundary'
                checkout_count = engine.pool.checkedout()
                auth_transaction = requests[0].in_transaction()
                with factory() as probe:
                    owner_free = probe.execute(text('SELECT pg_try_advisory_xact_lock(1836289001)')).scalar()
                # Exercise the unchanged real mounted admin dependency again.
                start = time.monotonic()
                try:
                    second = await asyncio.wait_for(wire.get('/real-admin-probe'), .5)
                    second_ok = second.status_code == 200 and second.json()['id'] == str(uid)
                except Exception:
                    second_ok = False
                elapsed = time.monotonic() - start
            finally:
                release.set()
                response = await asyncio.wait_for(task, 5)
                event.remove(Session, 'after_rollback', rolled_back)
            print(dict(mode=mode, checkouts=checkout_count, auth_transaction=auth_transaction,
                owner_free=owner_free, second_admin_ok=second_ok, second_admin_seconds=elapsed), flush=True)
            assert response.status_code == (200 if mid else 201), response.text
            assert checkout_count == 0, 'request auth checkout retained across save boundary'
            assert not auth_transaction, 'request auth transaction retained across save boundary'
            assert owner_free, 'owner advisory lock retained across save boundary'
            assert second_ok and elapsed < .5, 'second real admin authentication blocked'
            assert rollback_threads and loop_thread not in rollback_threads, 'auth rollback ran on event loop'
        assert engine.pool.checkedout() == 0
    asyncio.run(exercise())


@pytest.mark.parametrize('ownership', ['dirty', 'new', 'deleted', 'connection-session', 'connection'])
def test_service_rejects_session_or_connection_before_any_sql(real_app, factory, ownership):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from app.models.user import User
    from app.services import website_settings as service
    app, engine, uid, sid, token, requests = real_app
    body = service.WebsiteInput(address=CHECK['normalized_url'], idempotency_key='foreign-owner-'+ownership)
    with engine.connect() as connection, Session(bind=connection if ownership == 'connection-session' else engine, autoflush=True) as db:
        user = db.get(User, uid)
        original = user.display_name
        if ownership == 'dirty': user.display_name = 'Must remain pending'
        if ownership == 'new': db.add(User(username='pending-'+uuid4().hex, display_name='Pending', password_hash='not-a-login'))
        if ownership == 'deleted': db.delete(user)
        pending = (set(db.new), set(db.dirty), set(db.deleted))
        transaction = db.get_transaction()
        sql = []
        def forbidden(conn, cursor, statement, *args):
            sql.append(statement)
            raise AssertionError('service performed SQL before rejecting foreign ownership')
        event.listen(engine, 'before_cursor_execute', forbidden)
        try:
            with pytest.raises(TypeError, match='requires an Engine'):
                asyncio.run(service.save_website(connection if ownership == 'connection' else db, body, uid, parent_origin='http://stella.test'))
            assert not sql
            assert db.get_transaction() is transaction
            assert (set(db.new), set(db.dirty), set(db.deleted)) == pending
            assert user.display_name == ('Must remain pending' if ownership == 'dirty' else original)
        finally: event.remove(engine, 'before_cursor_execute', forbidden)
        with factory() as other: assert other.get(User, uid).display_name == original


@pytest.mark.parametrize('pending', ['dirty', 'new', 'deleted', 'savepoint', 'connection'])
def test_request_context_rejects_unowned_or_pending_transaction(real_app, factory, pending):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from app.models.user import User
    from app.routers.website_settings import website_write_context
    app, engine, uid, sid, token, requests = real_app
    with engine.connect() as connection, Session(bind=connection if pending == 'connection' else engine, autoflush=True) as db:
        user = db.get(User, uid)
        if pending == 'dirty': user.display_name = 'Pending context edit'
        if pending == 'new': db.add(User(username='pending-'+uuid4().hex, password_hash='not-a-login'))
        if pending == 'deleted': db.delete(user)
        if pending == 'savepoint': db.begin_nested()
        before = (set(db.new), set(db.dirty), set(db.deleted), db.get_transaction(), db.get_nested_transaction())
        def forbidden(*args): raise AssertionError('context guard must not execute SQL')
        event.listen(engine, 'before_cursor_execute', forbidden)
        try:
            with pytest.raises((TypeError, RuntimeError)):
                website_write_context(user, db)
            assert (set(db.new), set(db.dirty), set(db.deleted), db.get_transaction(), db.get_nested_transaction()) == before
        finally: event.remove(engine, 'before_cursor_execute', forbidden)


@pytest.mark.parametrize('change, status', [('revoked', 401), ('expired', 401), ('inactive', 401), ('owner', 403)])
def test_mounted_save_still_reloads_auth_state(real_app, factory, monkeypatch, change, status):
    import httpx
    from datetime import datetime, timedelta, timezone
    from app.models.user import User, AuthSession
    from app.models.config import AppConfig
    from app.services.admin_security import STATE_KEY
    from app.services import website_settings as service
    app, engine, uid, sid, token, requests = real_app
    with factory() as db:
        if change == 'revoked': db.get(AuthSession, sid).revoked = True
        if change == 'expired':
            session = db.get(AuthSession, sid)
            session.created_at = session.last_seen = datetime.now(timezone.utc) - timedelta(days=400)
        if change == 'inactive': db.get(User, uid).is_active = False
        if change == 'owner':
            other = User(username='foreign-'+uuid4().hex, display_name='Foreign', password_hash='not-a-login', is_active=True)
            db.add(other); db.flush()
            db.get(AppConfig, STATE_KEY).value = json.dumps(dict(owner_id=str(other.id), enabled=True, version=1, grants={}))
        db.commit()
    async def forbidden(*a, **kw): raise AssertionError('rejected auth must not reach validation')
    monkeypatch.setattr(service, 'check_draft', forbidden)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://stella.test', cookies={'stella_at': token}) as wire:
            for method, path in [('POST', '/website-settings'), ('PATCH', '/website-settings/missing')]:
                response = await wire.request(method, path, json=dict(address=CHECK['normalized_url'], idempotency_key='rejected-auth'))
                assert response.status_code == status, response.text
    asyncio.run(exercise())
