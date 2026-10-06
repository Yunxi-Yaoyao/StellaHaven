"""Real auth HTTP + SQLite state; no production DB/env/files or agent calls."""
import os
os.environ['STELLA_SECRET_KEY'] = 'isolated-auth-test-signing-key-not-production-0000'
os.environ['STELLA_COOKIE_SECURE'] = 'false'
os.environ['POSTGRES_DB'] = 'stella_test_isolated_security'
os.environ['POSTGRES_USER'] = 'isolated_test'
os.environ['POSTGRES_PASSWORD'] = 'isolated_fixture_only'

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import get_db, engine as unused_pg_engine
from app.models.user import User, AuthSession, Invite, EmailCode
from app.models.config import AppConfig
from app.routers.auth import router, admin_user
from app.security import hash_password

@event.listens_for(unused_pg_engine, 'do_connect')
def forbid_pg(*args, **kwargs):
    raise AssertionError('Isolated security tests must never connect PostgreSQL')

@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.delenv('STELLA_OWNER_ID', raising=False)
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    for table in [User.__table__, AuthSession.__table__, AppConfig.__table__, Invite.__table__, EmailCode.__table__]:
        table.create(engine)
    db = Session(engine)
    app = FastAPI()
    app.include_router(router)
    @app.post('/danger')
    def danger(user=Depends(admin_user)):
        return {'ok': True}
    def isolated_db():
        try:
            yield db
        finally:
            db.rollback()  # mirror real request cleanup, including rejected writes
    app.dependency_overrides[get_db] = isolated_db
    client = TestClient(app)
    yield client, db, app
    client.close()
    db.close()
    engine.dispose()

DAILY = 'daily-fixture-password'
ADMIN = 'independent-admin-fixture'

def owner(client):
    response = client.post('/auth/register', json={'username': 'owner', 'password': DAILY})
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_default_login_is_not_management_elevation(auth_env):
    c, db, app = auth_env
    owner(c)
    response = c.post('/danger')
    assert response.status_code == 403
    assert response.json()['detail']['code'] == 'admin_setup_required'
    assert c.get('/auth/security').json() == {
        'enabled': True, 'configured': False, 'elevated': False,
        'expires_at': None, 'single_user': True, 'setup_required': True,
    }


def test_setup_and_unlock_are_independent_session_bound_and_expiring(auth_env):
    c, db, app = auth_env
    owner(c)
    assert c.post('/auth/admin/setup', json={'user_password': 'wrong', 'new_password': ADMIN}).status_code == 401
    assert c.post('/auth/admin/setup', json={'user_password': DAILY, 'new_password': DAILY}).status_code == 400
    assert c.post('/auth/admin/setup', json={'user_password': DAILY, 'new_password': ADMIN}).status_code == 200
    assert c.post('/danger').status_code == 403  # setup does not implicitly unlock
    assert c.post('/auth/admin/unlock', json={'password': DAILY}).status_code == 401
    assert c.post('/auth/admin/unlock', json={'password': ADMIN}).status_code == 200
    assert c.post('/danger').status_code == 200
    info = c.get('/auth/security').json()
    assert info['elevated'] and info['expires_at']
    from app.services.admin_security import STATE_KEY
    import json
    row = db.get(AppConfig, STATE_KEY)
    state = json.loads(row.value)
    assert state['password_hash'].startswith('$argon2id$')
    assert ADMIN not in row.value and DAILY not in row.value
    for grant in state['grants'].values():
        grant['expires_at'] = '2000-01-01T00:00:00+00:00'
    row.value = json.dumps(state)
    db.commit()
    assert c.post('/danger').status_code == 403
    c.post('/auth/admin/unlock', json={'password': ADMIN})
    second = TestClient(app)
    assert second.post('/auth/login', json={'username': 'owner', 'password': DAILY}).status_code == 200
    assert second.post('/danger').status_code == 403
    assert c.post('/auth/admin/lock').status_code == 200
    assert c.post('/danger').status_code == 403
    second.close()


def test_legacy_empty_password_cannot_be_claimed_and_invites_users_are_gone(auth_env):
    c, db, app = auth_env
    legacy = User(username='legacy', display_name='Legacy', password_hash='')
    db.add(legacy)
    db.commit()
    before = legacy.id
    assert c.post('/auth/register', json={'username': 'legacy', 'password': DAILY}).status_code == 403
    assert db.get(User, before).password_hash == ''
    for method, path in [('post','/auth/register-invite'), ('post','/auth/invites'), ('get','/auth/invites')]:
        assert getattr(c, method)(path, **({'json': {}} if method == 'post' else {})).status_code in (404, 410)
    from app.routers.user import router as user_router
    app.include_router(user_router)
    assert c.get('/users/').status_code in (404, 410)
    assert db.query(User).count() == 1


def test_owner_pin_preserves_uuid_and_multiple_records_fail_closed(auth_env, monkeypatch):
    c, db, app = auth_env
    users = [User(username=name, display_name=name, password_hash=hash_password(DAILY), is_admin=True)
             for name in ['original', 'other']]
    db.add_all(users)
    db.commit()
    assert c.post('/auth/login', json={'username':'original', 'password':DAILY}).status_code == 503
    monkeypatch.setenv('STELLA_OWNER_ID', str(users[0].id))
    response = c.post('/auth/login', json={'username':'original', 'password':DAILY})
    assert response.status_code == 200
    assert response.json()['id'] == str(users[0].id)
    monkeypatch.delenv('STELLA_OWNER_ID')  # persisted pin survives process/env changes
    c.cookies.clear()
    assert c.post('/auth/login', json={'username':'other', 'password':DAILY}).status_code == 403
    assert db.query(User).count() == 2


def test_existing_non_owner_session_cannot_access_owner_or_management(auth_env, monkeypatch):
    c, db, app = auth_env
    uid = owner(c)
    outsider = User(username='outsider', display_name='out', password_hash=hash_password(DAILY), is_admin=True)
    db.add(outsider)
    db.flush()
    from app.security import make_access_token
    session = AuthSession(user_id=outsider.id, refresh_hash='outsiderfixture', remember=True)
    db.add(session)
    db.commit()
    c.cookies.set('stella_at', make_access_token(str(outsider.id), str(session.id)))
    assert c.get('/auth/me').status_code == 403
    assert c.post('/danger').status_code == 403


def configure(c):
    owner(c)
    assert c.post('/auth/admin/setup', json={'user_password': DAILY, 'new_password': ADMIN}).status_code == 200
    assert c.post('/auth/admin/unlock', json={'password': ADMIN}).status_code == 200


def test_security_toggle_and_password_rotation_reverify_and_invalidate_all_grants(auth_env):
    c, db, app = auth_env
    configure(c)
    assert c.put('/auth/security', json={'enabled':False}).status_code == 401
    assert c.put('/auth/security', json={'enabled':False, 'password':DAILY}).status_code == 401
    assert c.put('/auth/security', json={'enabled':False, 'password':ADMIN}).status_code == 200
    assert c.post('/danger').status_code == 200
    anonymous = TestClient(app)
    assert anonymous.post('/danger').status_code == 401
    anonymous.close()
    assert c.put('/auth/security', json={'enabled':True, 'password':ADMIN}).status_code == 200
    assert c.post('/danger').status_code == 403
    c.post('/auth/admin/unlock', json={'password':ADMIN})
    second = TestClient(app)
    second.post('/auth/login', json={'username':'owner','password':DAILY})
    second.post('/auth/admin/unlock', json={'password':ADMIN})
    assert c.post('/auth/admin/password', json={'current_password':DAILY,'new_password':ADMIN+'2'}).status_code == 401
    assert c.post('/auth/admin/password', json={'current_password':ADMIN,'new_password':ADMIN+'2'}).status_code == 200
    assert c.post('/danger').status_code == 403
    assert second.post('/danger').status_code == 403
    assert c.post('/auth/admin/unlock', json={'password':ADMIN}).status_code == 401
    assert c.post('/auth/admin/unlock', json={'password':ADMIN+'2'}).status_code == 200
    second.close()


def test_logout_and_daily_password_change_revoke_elevation(auth_env):
    c, db, app = auth_env
    configure(c)
    old_at = c.cookies.get('stella_at')
    assert c.post('/auth/logout').status_code == 200
    c.cookies.set('stella_at', old_at)
    assert c.post('/danger').status_code == 401
    c.cookies.clear()
    c.post('/auth/login', json={'username':'owner','password':DAILY})
    c.post('/auth/admin/unlock', json={'password':ADMIN})
    assert c.post('/auth/password', json={'old_password':DAILY,'new_password':ADMIN}).status_code == 400
    assert c.post('/auth/password', json={'old_password':DAILY,'new_password':DAILY+'2'}).status_code == 200
    assert c.post('/danger').status_code == 401


def test_management_password_failures_have_bounded_shared_cooldown(auth_env):
    c, db, app = auth_env
    configure(c)
    c.post('/auth/admin/lock')
    for _ in range(5):
        assert c.post('/auth/admin/unlock', json={'password':'wrong'}).status_code == 401
    limited = c.post('/auth/admin/unlock', json={'password':ADMIN})
    assert limited.status_code == 429
    assert 0 < int(limited.headers['retry-after']) <= 60
    # Persisted cooldown expires; no permanent account lock or clock sleeps.
    from app.services.admin_security import STATE_KEY
    import json
    row = db.get(AppConfig, STATE_KEY)
    state = json.loads(row.value)
    state['failures'] = [0.0] * 5
    row.value = json.dumps(state)
    db.commit()
    assert c.post('/auth/admin/unlock', json={'password':ADMIN}).status_code == 200


def test_invalid_password_hash_is_failed_auth_not_server_error(auth_env):
    c, db, app = auth_env
    owner(c)
    user = db.query(User).one()
    user.password_hash = ''
    db.commit()
    c.cookies.clear()
    assert c.post('/auth/login', json={'username':'owner','password':DAILY}).status_code == 401


DANGEROUS = [
    ('post','/nodes/'), ('post','/nodes/host/install'), ('post','/nodes/1/uninstall'),
    ('delete','/nodes/1'), ('patch','/nodes/1'), ('patch','/nodes/1/net-type'),
    ('patch','/nodes/1/map-location'), ('post','/nodes/1/ip-change'), ('post','/nodes/1/docker-ctl'),
    ('post','/iperf-tasks'), ('post','/iperf-tasks/1/cancel'), ('post','/commands'),
    ('post','/component-installs'), ('post','/monitors/'), ('patch','/monitors/1'), ('delete','/monitors/1'),
    ('post','/alerts/rules'), ('patch','/alerts/rules/1'), ('delete','/alerts/rules/1'),
    ('put','/config/public-host'), ('put','/config/prometheus'),
    ('get','/drive/connection'), ('put','/drive/connection'), ('post','/drive/connection/test'),
    ('post','/drive/connection/token'), ('get','/gallery/connection'), ('put','/gallery/connection'),
    ('post','/gallery/connection/test'),
]


@pytest.mark.parametrize('method,path', DANGEROUS)
def test_every_management_route_denies_without_elevation_before_any_service_call(auth_env, method, path):
    c, db, app = auth_env
    from app.routers.monitor import node_router, monitor_router
    from app.routers.task import router as tasks
    from app.routers.alerts import router as alerts
    from app.routers.config import router as config
    from app.routers.drive import router as drive
    from app.routers.gallery import router as gallery
    from app.routers.metrics_source import router as metrics
    for r in [node_router, monitor_router, tasks, alerts, config, drive, gallery, metrics]:
        app.include_router(r)
    owner(c)
    response = getattr(c, method)(path, **({'json':{}} if method not in ('get','delete') else {}))
    assert response.status_code == 403, (method, path, response.text)
    assert response.json()['detail']['code'] == 'admin_setup_required'


def test_nodes_do_not_disclose_tokens_to_daily_or_elevated_readers(auth_env, monkeypatch):
    c, db, app = auth_env
    from app.routers.monitor import node_router, node_svc
    from app.schemas.monitor import NodeRead, NodeDetail
    from datetime import datetime
    n = NodeRead(id=1, name='fixture',platform='linux',host='fixture',status='online',
                 token='synthetic-node-secret',created_at=datetime.now())
    monkeypatch.setattr(node_svc,'list_nodes',lambda db:[n])
    monkeypatch.setattr(node_svc,'get_node_detail',lambda db,id:NodeDetail(**n.model_dump()))
    app.include_router(node_router)
    configure(c)
    for path in ['/nodes/','/nodes/1']:
        response = c.get(path)
        assert response.status_code == 200
        assert 'synthetic-node-secret' not in response.text
        payload = response.json()
        assert 'token' not in (payload[0] if isinstance(payload,list) else payload)


def test_agent_bearer_header_priority_and_json_command_results_keep_legacy_query(auth_env, monkeypatch):
    c, db, app = auth_env
    from app.routers.task import agent_task_router, task_svc
    app.include_router(agent_task_router)
    calls = []
    monkeypatch.setattr(task_svc, 'poll_tasks', lambda db,token: {'seen': token})
    monkeypatch.setattr(task_svc, 'authorize_agent_task', lambda *args,**kwargs: calls.append((args,kwargs)))
    monkeypatch.setattr(task_svc, 'finish_command', lambda *args: calls.append(args))
    assert c.get('/agent/tasks',headers={'Authorization':'Bearer fixture-header'}).json() == {'seen':'fixture-header'}
    assert c.get('/agent/tasks?token=fixture-query',headers={'Authorization':'Bearer fixture-header'}).json() == {'seen':'fixture-header'}
    assert c.get('/agent/tasks?token=fixture-query').json() == {'seen':'fixture-query'}
    assert c.get('/agent/tasks?token=fixture-query',headers={'Authorization':'Basic wrong'}).status_code == 401
    assert c.get('/agent/tasks').status_code == 401
    result = c.post('/agent/commands/1/result', headers={'Authorization':'Bearer fixture-header'},
                    json={'status':'done','stdout':'body output','stderr':'body error','exit_code':7})
    assert result.status_code == 200, result.text
    assert calls[-1][1:] == (1,'done','body output','body error',7)
    calls.clear()
    assert c.post('/agent/commands/1/result?token=fixture-query&status=done&stdout=legacy&stderr=legacy-error&exit_code=2').status_code == 200
    assert calls[-1][1:] == (1,'done','legacy','legacy-error',2)


def test_access_log_redacts_old_query_and_result_output_before_formatting():
    import logging
    from app import security
    assert hasattr(security, 'install_log_redaction')
    security.install_log_redaction()
    record = logging.LogRecord('uvicorn.access',logging.INFO,'fixture',1,
        '%s - "%s %s HTTP/%s" %d', ('client','POST','/agent/commands/1/result?token=synthetic-secret&stdout=output-secret&stderr=error-secret','1.1',200), None)
    for filt in logging.getLogger('uvicorn.access').filters:
        assert filt.filter(record)
    assert '/agent/commands/1/result' in record.getMessage()
    assert 'synthetic-secret' not in record.getMessage()
    assert 'output-secret' not in record.getMessage()
    assert 'error-secret' not in record.getMessage()


def test_node_install_credentials_are_only_available_by_explicit_elevated_action(auth_env, monkeypatch):
    c, db, app = auth_env
    from app.routers.monitor import node_router
    from app.repositories import node as repo
    from types import SimpleNamespace
    node = SimpleNamespace(id=1, token="fixture-node-secret",platform='linux',status='pending')
    monkeypatch.setattr(repo,'get_by_id',lambda db,id:node if id == 1 else None)
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','http://testserver')
    app.include_router(node_router)
    owner(c)
    assert c.post('/nodes/1/install-command').status_code == 403
    assert c.post('/auth/admin/setup',json={'user_password':DAILY,'new_password':ADMIN}).status_code == 200
    assert c.post('/nodes/1/install-command').status_code == 403
    c.post('/auth/admin/unlock',json={'password':ADMIN})
    response = c.post('/nodes/1/install-command')
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    payload = response.json()
    assert payload['token'] == node.token and node.token in payload['command']
    assert payload['url'] == 'http://testserver'
    assert c.post('/nodes/99/install-command').status_code == 404
    c.post('/auth/admin/lock')
    assert c.post('/nodes/1/install-command').status_code == 403


def test_drive_login_url_cannot_bypass_token_reveal_with_legacy_admin_metadata(auth_env):
    c, db, app = auth_env
    from app.routers.drive import router as drive
    app.include_router(drive)
    owner(c)
    import json
    db.add(AppConfig(key='external_drive_connection', value=json.dumps({
        'browser_url':'http://127.0.0.1:5244/drive/openlist',
        'auth_mode':'token', 'token':'SYNTHETIC-PRIVILEGED-TOKEN'})))
    db.commit()
    r = c.get('/drive/login-url')
    assert r.status_code == 403
    assert 'SYNTHETIC-PRIVILEGED-TOKEN' not in r.text


def test_single_owner_initialization_does_not_depend_on_legacy_admin_flag(auth_env, monkeypatch):
    c, db, app = auth_env
    from app.routers import admin_email
    monkeypatch.setattr(admin_email,'_load',lambda:{})
    legacy = User(username='legacy',display_name='legacy',password_hash=hash_password(DAILY),is_admin=False)
    db.add(legacy)
    db.commit()
    assert c.get('/auth/status').json()['initialized'] is True
    assert c.post('/auth/login',json={'username':'legacy','password':DAILY}).status_code == 200
    assert c.post('/auth/admin/setup',json={'user_password':DAILY,'new_password':ADMIN}).status_code == 200
    assert c.post('/auth/admin/unlock',json={'password':ADMIN}).status_code == 200
    assert c.post('/danger').status_code == 200


@pytest.mark.parametrize('invalid_enabled', [0, None, 'false'])
def test_corrupted_security_state_fails_closed_not_disabled_protection(auth_env, invalid_enabled):
    c, db, app = auth_env
    configure(c)
    from app.services.admin_security import STATE_KEY
    import json
    row = db.get(AppConfig, STATE_KEY)
    state = json.loads(row.value)
    state['enabled'] = invalid_enabled
    row.value = json.dumps(state)
    db.commit()
    assert c.post('/danger').status_code == 503


def test_security_changes_are_atomically_audited_without_password_values(auth_env):
    c, db, app = auth_env
    from app.routers.operations_status import router as operations
    from app.services.backup_health import AUDIT_KEY, read_change_audit
    app.include_router(operations)
    configure(c)
    uid = c.get('/auth/me').json()['id']
    c.post('/auth/admin/lock')
    assert c.put('/auth/security',json={'enabled':False,'password':ADMIN}).status_code == 200
    assert c.post('/auth/admin/password',json={'current_password':ADMIN,'new_password':ADMIN+'2'}).status_code == 200
    events = read_change_audit(db)
    assert [e['action'] for e in events] == ['security.password_change','security.update','security.lock','security.unlock','security.setup']
    assert all(e['actor_id'] == uid for e in events)
    row = db.get(AppConfig,AUDIT_KEY)
    assert row is not None and DAILY not in row.value and ADMIN not in row.value
    assert 'password_hash' not in row.value
    response = c.get('/operations/change-audit')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'


def test_audit_failure_rolls_back_security_mutation(auth_env):
    c, db, app = auth_env
    from app.services.admin_security import STATE_KEY
    from app.services.backup_health import AUDIT_KEY
    configure(c)
    audit = db.get(AppConfig,AUDIT_KEY)
    if audit is None:
        db.add(AppConfig(key=AUDIT_KEY,value='invalid-json'))
    else:
        audit.value = 'invalid-json'
    db.commit()
    before = db.get(AppConfig,STATE_KEY).value
    failure_client = TestClient(app,raise_server_exceptions=False)
    failure_client.cookies.update(c.cookies)
    assert failure_client.put('/auth/security',json={'enabled':False,'password':ADMIN}).status_code == 500
    assert db.get(AppConfig,STATE_KEY).value == before
    failure_client.close()


def test_logout_revokes_the_access_bound_elevation_even_if_refresh_cookie_is_from_another_session(auth_env):
    c, db, app = auth_env
    configure(c)
    old_at = c.cookies.get('stella_at')
    other = TestClient(app)
    assert other.post('/auth/login',json={'username':'owner','password':DAILY}).status_code == 200
    c.cookies.set('stella_rt',other.cookies.get('stella_rt'))
    assert c.post('/auth/logout').status_code == 200
    c.cookies.set('stella_at',old_at)
    assert c.post('/danger').status_code == 401
    other.close()
