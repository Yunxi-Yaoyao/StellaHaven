"""Single owner authentication through real FastAPI dependencies and SQLite."""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
from app.models.user import AuthSession, User
from app.models.config import AppConfig
from app.security import hash_password, make_access_token
from app.services import admin_security
from tests_isolated.test_owner_admin_security import auth_env, owner, DAILY, ADMIN


def test_owner_can_manage_without_second_password_and_legacy_state_is_inactive(auth_env):
    c, db, app = auth_env
    owner(c)
    assert c.post('/danger').status_code == 200
    row = db.get(AppConfig, admin_security.STATE_KEY)
    state = json.loads(row.value)
    state.update(password_hash=hash_password(ADMIN), enabled=True, grants={'old': {'version': 1, 'expires_at': '2000-01-01T00:00:00+00:00'}})
    row.value = json.dumps(state)
    db.commit()
    before = row.value
    assert c.post('/danger').status_code == 200
    assert c.get('/auth/security').json() == {
        'enabled': False, 'configured': True, 'elevated': True,
        'expires_at': None, 'single_user': True, 'setup_required': False,
    }
    assert db.get(AppConfig, admin_security.STATE_KEY).value == before


@pytest.mark.parametrize('method,path,payload', [
    ('post', '/auth/admin/setup', {'user_password': DAILY, 'new_password': ADMIN}),
    ('post', '/auth/admin/unlock', {'password': ADMIN}),
    ('post', '/auth/admin/lock', {}),
    ('post', '/auth/admin/password', {'current_password': ADMIN, 'new_password': ADMIN+'2'}),
    ('put', '/auth/security', {'enabled': False, 'password': ADMIN}),
])
def test_old_management_apis_retired_without_mutation(auth_env, method, path, payload):
    c, db, app = auth_env
    owner(c)
    before = db.get(AppConfig, admin_security.STATE_KEY).value
    response = getattr(c, method)(path, json=payload)
    assert response.status_code == 410, response.text
    assert response.json()['detail']['code'] == 'management_password_retired'
    assert db.get(AppConfig, admin_security.STATE_KEY).value == before
    assert c.post('/danger').status_code == 200
    anonymous = TestClient(app)
    assert getattr(anonymous, method)(path, json=payload).status_code == 401
    anonymous.close()


@pytest.mark.parametrize('boundary', ['anonymous', 'wrong_owner', 'revoked', 'expired', 'inactive', 'mismatched_uid', 'missing_session'])
def test_route_and_service_boundaries(auth_env, boundary):
    c, db, app = auth_env
    uid = owner(c)
    session = db.query(AuthSession).one()
    if boundary == 'anonymous':
        c.cookies.clear()
    elif boundary == 'wrong_owner':
        outsider = User(username='outsider', display_name='out', password_hash=hash_password(DAILY), is_admin=True)
        db.add(outsider); db.flush()
        session = AuthSession(user_id=outsider.id, refresh_hash='outsider', remember=True)
        db.add(session); db.commit()
        c.cookies.clear(); c.cookies.set('stella_at', make_access_token(str(outsider.id), str(session.id)))
    elif boundary == 'revoked':
        session.revoked = True; db.commit()
    elif boundary == 'expired':
        session.remember = False
        session.last_seen = datetime.now(timezone.utc)-timedelta(hours=2)
        db.commit()
    elif boundary == 'inactive':
        db.get(User, session.user_id).is_active = False; db.commit()
    elif boundary == 'mismatched_uid':
        c.cookies.clear(); c.cookies.set('stella_at', make_access_token(str(uuid4()), str(session.id)))
    else:
        db.delete(session); db.commit()
    expected = 403 if boundary == 'wrong_owner' else 401
    assert c.post('/danger').status_code == expected
    assert c.get('/auth/security').status_code == expected
    if boundary not in {'anonymous', 'mismatched_uid'}:
        with pytest.raises(HTTPException) as exc:
            admin_security.require_admin(db, session)
        assert exc.value.status_code == expected


def test_service_guard_rejects_missing_session_and_reloads_persisted_session(auth_env):
    c, db, app = auth_env
    owner(c)
    with pytest.raises(HTTPException) as exc:
        admin_security.require_admin(db, None)
    assert exc.value.status_code == 401
    session = db.query(AuthSession).one()
    assert admin_security.require_admin(db, session) is None
    db.query(AuthSession).update({'revoked': True}, synchronize_session=False); db.commit()
    with pytest.raises(HTTPException) as exc:
        admin_security.require_admin(db, session)
    assert exc.value.status_code == 401


def test_user_password_change_uses_old_user_password_and_revokes_all_sessions(auth_env):
    c, db, app = auth_env
    owner(c)
    second = TestClient(app)
    assert second.post('/auth/login', json={'username':'owner', 'password':DAILY}).status_code == 200
    row = db.get(AppConfig, admin_security.STATE_KEY)
    state = json.loads(row.value); state['password_hash'] = hash_password(ADMIN)
    row.value = json.dumps(state); db.commit(); before = row.value
    assert c.post('/auth/password', json={'old_password':ADMIN, 'new_password':DAILY+'2'}).status_code == 401
    assert c.post('/danger').status_code == second.post('/danger').status_code == 200
    # A dormant historical admin hash must not constrain the one active user password.
    assert c.post('/auth/password', json={'old_password':DAILY, 'new_password':ADMIN}).status_code == 200
    assert c.post('/danger').status_code == second.post('/danger').status_code == 401
    assert all(s.revoked for s in db.query(AuthSession).all())
    assert db.get(AppConfig, admin_security.STATE_KEY).value == before
    c.cookies.clear()
    assert c.post('/auth/login', json={'username':'owner', 'password':ADMIN}).status_code == 200
    assert c.post('/danger').status_code == 200
    second.close()


def test_logout_retains_atomic_security_audit_without_touching_legacy_grants(auth_env):
    c,db,app=auth_env
    uid=owner(c)
    from app.services.backup_health import read_change_audit,AUDIT_KEY
    before=db.get(AppConfig,admin_security.STATE_KEY).value
    assert c.post('/auth/logout').status_code==200
    assert c.post('/danger').status_code==401
    events=read_change_audit(db)
    assert events[0]['action']=='security.logout' and events[0]['actor_id']==uid
    assert db.get(AppConfig,admin_security.STATE_KEY).value==before
    c.cookies.clear();assert c.post('/auth/login',json={'username':'owner','password':DAILY}).status_code==200
    row=db.get(AppConfig,AUDIT_KEY);row.value='invalid-json';db.commit()
    failing=TestClient(app,raise_server_exceptions=False);failing.cookies.update(c.cookies)
    assert failing.post('/auth/logout').status_code==500
    assert c.post('/danger').status_code==200  # audit/target revoke must roll back together
    failing.close()
