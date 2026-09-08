"""Session contract tests: private in-memory SQLite, no shared DB access."""
from datetime import datetime, timedelta, timezone
from uuid import UUID
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import get_db
from app.models.user import User, AuthSession
from app.routers.auth import router
from app.security import hash_password

@pytest.fixture
def isolated():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    User.__table__.create(engine)
    AuthSession.__table__.create(engine)
    with Session(engine) as db:
        user = User(username='policy-user', display_name='Policy', password_hash=hash_password('secret123'), is_admin=False)
        db.add(user)
        db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            client.post('/auth/login', json={'username': user.username, 'password': 'secret123'})
            row = db.query(AuthSession).one()
            yield client, db, row
    engine.dispose()

@pytest.mark.parametrize('remember,age', [(True, timedelta(days=30)), (False, timedelta(minutes=30))])
def test_expired_session_rejected_by_access_and_refresh(isolated, remember, age):
    client, db, row = isolated
    now = datetime.now(timezone.utc)
    row.remember = remember
    row.created_at = now - age
    row.last_seen = now if remember else now - age
    db.commit()
    assert client.get('/auth/me').status_code == 401
    assert client.post('/auth/refresh').status_code == 401
    assert db.query(AuthSession).count() == 1  # history is retained


def test_refresh_does_not_count_as_activity_and_cookie_has_remaining_lifetime(isolated):
    client, db, row = isolated
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row.last_seen = now - timedelta(minutes=10)
    row.created_at = now - timedelta(days=29)
    row.remember = True
    db.commit()
    previous = row.last_seen
    response = client.post('/auth/refresh')
    assert response.status_code == 200
    assert row.last_seen == previous
    from http.cookies import SimpleCookie
    cookie = SimpleCookie()
    for header in response.headers.get_list('set-cookie'):
        cookie.load(header)
    assert 86390 <= int(cookie['stella_rt']['max-age']) <= 86400


def test_activity_updates_idle_but_cannot_resurrect(isolated):
    client, db, row = isolated
    previous = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
    row.last_seen = previous
    db.commit()
    assert client.get('/auth/me').status_code == 200
    assert row.last_seen == previous
    assert client.post('/auth/activity').status_code == 200
    assert utc_for_test(row.last_seen) > utc_for_test(previous)
    row.last_seen = previous - timedelta(minutes=30)
    db.commit()
    assert client.post('/auth/activity').status_code == 401


def utc_for_test(value):
    return value.replace(tzinfo=timezone.utc)


def test_logout_revokes_access_without_refresh_cookie(isolated):
    client, db, row = isolated
    token = client.cookies.get('stella_at')
    client.cookies.delete('stella_rt')
    assert client.post('/auth/logout').status_code == 200
    assert row.revoked
    client.cookies.set('stella_at', token)
    assert client.get('/auth/me').status_code == 401


def test_same_browser_login_replaces_only_presented_session(isolated):
    client, db, row = isolated
    other = AuthSession(user_id=row.user_id, refresh_hash='other-device', device=row.device, ip=row.ip)
    db.add(other)
    db.commit()
    assert client.post('/auth/login', json={'username': 'policy-user', 'password': 'secret123'}).status_code == 200
    assert row.revoked
    assert not other.revoked
    assert db.query(AuthSession).count() == 3


def test_history_paginated_and_active_excludes_expired(isolated):
    client, db, row = isolated
    for i in range(23):
        db.add(AuthSession(user_id=row.user_id, refresh_hash=f'old-{i}', revoked=i % 2 == 0,
            created_at=datetime.now() - timedelta(days=40), last_seen=datetime.now() - timedelta(days=40)))
    stranger = User(username='stranger', display_name='Stranger', password_hash='x')
    db.add(stranger)
    db.flush()
    db.add(AuthSession(user_id=stranger.id, refresh_hash='stranger-history', revoked=True))
    db.commit()
    first = client.get('/auth/sessions/history?page=1&page_size=20')
    assert first.status_code == 200
    assert first.json()['total'] == 23
    second = client.get('/auth/sessions/history?page=2&page_size=20').json()
    assert len(first.json()['items']) == 20
    assert len(second['items']) == 3
    assert not ({s['id'] for s in first.json()['items']} & {s['id'] for s in second['items']})
    assert {s['state'] for s in first.json()['items']} == {'expired', 'revoked'}
    assert len(client.get('/auth/sessions').json()) == 1
    assert client.get('/auth/sessions/history?page=0').status_code == 422


@pytest.mark.parametrize('case', ['test_invite_flow', 'test_invite_bad_token', 'test_invite_expired', 'test_legacy_claim', 'test_login_ok_and_wrong_password'])
def test_existing_auth_regressions_in_private_database(isolated, case):
    from tests import test_auth
    from app.models.user import Invite, EmailCode
    client, db, row = isolated
    Invite.__table__.create(db.get_bind())
    EmailCode.__table__.create(db.get_bind())
    user = db.get(User, row.user_id)
    user.is_admin = True
    db.commit()
    import inspect
    function = getattr(test_auth, case)
    kwargs = {'client': client, 'db_session': db}
    function(**{key: kwargs[key] for key in inspect.signature(function).parameters})


@pytest.mark.parametrize('sid', [None, 'not-a-uuid'])
def test_missing_or_malformed_session_cannot_bypass_expiry(isolated, sid):
    from app.security import make_access_token
    client, db, row = isolated
    client.cookies.clear()
    client.cookies.set('stella_at', make_access_token(str(row.user_id), sid))
    assert client.get('/auth/me').status_code == 401


def test_unremembered_access_cookie_is_session_scoped(isolated):
    client, db, row = isolated
    response = client.post('/auth/login', json={'username':'policy-user','password':'secret123','remember':False})
    from http.cookies import SimpleCookie
    cookies = SimpleCookie()
    for header in response.headers.get_list('set-cookie'): cookies.load(header)
    assert not cookies['stella_at']['max-age']
    assert not cookies['stella_rt']['max-age']


def test_websocket_rejects_expired_session_before_accept(isolated):
    from app.routers.ws import router as ws_router
    from starlette.websockets import WebSocketDisconnect
    client, db, row = isolated
    client.app.include_router(ws_router)
    row.last_seen = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    db.commit()
    for path in ('/ws/00000000-0000-0000-0000-000000000001','/ws/list/00000000-0000-0000-0000-000000000001'):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(path) as ws:
                ws.close()
