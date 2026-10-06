"""Isolated real owner HTTP; never connect app PostgreSQL or SMTP.

Run in its own Python process (auth_env installs a deliberate PG connect guard).
"""
import json
import re
import pytest
from tests_isolated.test_owner_admin_security import auth_env, owner, DAILY, ADMIN
from app.models.user import User, EmailCode, AuthSession
from app.models.config import AppConfig
from fastapi.testclient import TestClient

MAIL = 'owner@email.invalid'

@pytest.fixture
def email_env(auth_env, monkeypatch):
    from app.routers import admin_email
    c, db, app = auth_env
    owner(c)
    user = db.query(User).one()
    user.email = MAIL
    user.email_verified = True
    db.commit()
    delivered = []
    monkeypatch.setattr(admin_email, '_load', lambda: {
        'enabled': True, 'host': 'smtp.invalid', 'username': 'fixture', 'password': 'fixture'})
    def send(cfg, email, subject, html):
        # Stub at the outbound boundary; no SMTP implementation runs.
        delivered.append((email, re.search(r'>\s*(\d{6})\s*</div>', html).group(1)))
    monkeypatch.setattr(admin_email, '_send', send)
    yield c, db, app, delivered

ISSUE = {'login':'/auth/login-code/send', 'reset':'/auth/forgot', 'bind':'/auth/email/send-code'}
VERIFY = {'login':'/auth/login-code', 'reset':'/auth/reset', 'bind':'/auth/email/verify'}

def issue(env, purpose, email=MAIL):
    c, db, app, delivered = env
    assert c.post(ISSUE[purpose], json={'email':email}).status_code == 200
    assert delivered and delivered[-1][0] == email
    return delivered[-1][1]

def verify(c, purpose, code, email=MAIL):
    payload = {'email':email, 'code':code}
    if purpose == 'reset':
        payload['new_password'] = DAILY + '-reset'
    return c.post(VERIFY[purpose], json=payload)

@pytest.mark.parametrize('purpose', ['login','reset','bind'])
def test_five_wrong_attempts_consume_code_and_prevent_correct_code(email_env, purpose):
    c, db, app, delivered = email_env
    code = issue(email_env, purpose)
    wrong = '000000' if code != '000000' else '999999'
    assert [verify(c,purpose,wrong).status_code for _ in range(5)] == [401]*5
    response = verify(c,purpose,code)
    assert response.status_code == 429
    assert 0 < int(response.headers['retry-after']) <= 300
    assert db.query(EmailCode).filter(EmailCode.email == MAIL).count() == 0
    assert c.post('/auth/email/resend',json={'email':MAIL,'purpose':purpose}).status_code == 429


def foreign(db):
    from app.security import hash_password
    user = User(username='legacy-foreign',display_name='legacy',email='foreign@email.invalid',
                email_verified=True,password_hash=hash_password(DAILY),is_admin=True)
    db.add(user)
    db.commit()
    return user

@pytest.mark.parametrize('purpose', ['login','reset'])
def test_non_owner_never_receives_new_code(email_env, purpose):
    c, db, app, delivered = email_env
    other = foreign(db)
    count = db.query(AuthSession).count()
    response = c.post(ISSUE[purpose],json={'email':other.email})
    assert response.status_code == (404 if purpose == 'login' else 200)
    assert not delivered
    assert db.query(EmailCode).count() == 0
    assert db.query(AuthSession).count() == count
    assert db.query(User).count() == 2

@pytest.mark.parametrize('purpose', ['bind','login','reset'])
def test_resend_cannot_repurpose_or_issue_for_foreign_account(email_env, purpose):
    c, db, app, delivered = email_env
    other = foreign(db)
    from datetime import datetime, timedelta, timezone
    db.add(EmailCode(email=other.email,code='legacy-fixture',expires_at=datetime.now(timezone.utc)+timedelta(minutes=10)))
    db.commit()
    before = db.query(EmailCode).one().code
    response = c.post('/auth/email/resend',json={'email':other.email,'purpose':purpose})
    assert response.status_code in (404,409)
    assert not delivered
    assert db.query(EmailCode).one().code == before


def test_binding_rechecks_global_identifier_ownership_before_redemption(email_env):
    c, db, app, delivered = email_env
    code = issue(email_env,'bind','new@email.invalid')
    other = foreign(db)
    other.username = 'new@email.invalid'
    db.commit()
    assert verify(c,'bind',code,'new@email.invalid').status_code == 409
    assert db.query(User).filter(User.username == 'owner').one().email == MAIL


def test_anonymous_binding_resend_denied(email_env):
    c, db, app, delivered = email_env
    code = issue(email_env,'bind')
    c.cookies.clear()
    assert c.post('/auth/email/resend',json={'email':MAIL,'purpose':'bind'}).status_code == 401
    assert len(delivered) == 1


def test_resend_purpose_is_allowlisted_before_state_mutation(email_env):
    c, db, app, delivered = email_env
    issue(email_env,'login')
    assert c.post('/auth/email/resend',json={'email':MAIL,'purpose':'arbitrary'}).status_code == 422
    assert len(delivered) == 1


def test_send_endpoints_share_two_deliveries_per_five_minute_budget(email_env):
    c, db, app, delivered = email_env
    issue(email_env,'login')
    issue(email_env,'reset')
    response = c.post('/auth/email/send-code',json={'email':'new@email.invalid'})
    assert response.status_code == 429
    assert 0 < int(response.headers['retry-after']) <= 300
    assert len(delivered) == 2


def test_resend_requires_same_issued_purpose(email_env):
    c, db, app, delivered = email_env
    issue(email_env,'login')
    assert c.post('/auth/email/resend',json={'email':MAIL,'purpose':'reset'}).status_code == 404
    assert len(delivered) == 1


def test_binding_slot_replacement_removes_old_email_code(email_env, monkeypatch):
    from app.services import email_attempts as guard
    from datetime import timedelta
    c, db, app, delivered = email_env
    started = guard.now()
    issue(email_env,'bind','first@email.invalid')
    monkeypatch.setattr(guard,'now',lambda:started+timedelta(seconds=301))
    issue(email_env,'bind','second@email.invalid')
    assert db.query(EmailCode).count() == 1
    assert db.query(EmailCode).one().email == 'second@email.invalid'


@pytest.mark.parametrize('mutation', [
    {'failures':[True]*5}, {'failures':[float('nan')]}, {'failures':[0]*6},
    {'slots':{'unexpected':{}}}, {'slots':{'login':{}}}, {'version':True},
    {'deliveries':[0]*3}, {'slots':{'login':{'attempts':-1}}},
])
def test_malformed_persisted_guard_state_fails_closed(email_env, mutation):
    from app.services.email_attempts import STATE_KEY
    c, db, app, delivered = email_env
    issue(email_env,'login')
    row = db.get(AppConfig,STATE_KEY)
    state = json.loads(row.value)
    state.update(mutation)
    row.value = json.dumps(state)
    db.commit()
    probe = TestClient(app,raise_server_exceptions=False)
    response = probe.post('/auth/login-code',json={'email':MAIL,'code':'wrong'})
    assert response.status_code == 503
    probe.close()


@pytest.mark.parametrize('purpose', ['login','reset','bind'])
def test_non_ascii_wrong_code_is_counted_not_server_error(email_env, purpose):
    c, db, app, delivered = email_env
    issue(email_env,purpose)
    probe = TestClient(app,raise_server_exceptions=False)
    probe.cookies.update(c.cookies)
    assert verify(probe,purpose,'错误验证码').status_code == 401
    probe.close()


@pytest.mark.parametrize('mutation', [
    {'failures':[1e50]*5}, {'slots':{'login':{'id':123,'email':'a'*64,'code':'b'*64,'attempts':0}}},
])
def test_corruption_cannot_create_unbounded_lock_or_500(email_env,mutation):
    from app.services.email_attempts import STATE_KEY
    c, db, app, delivered = email_env
    issue(email_env,'login')
    row = db.get(AppConfig,STATE_KEY)
    state = json.loads(row.value)
    state.update(mutation)
    row.value = json.dumps(state)
    db.commit()
    probe = TestClient(app,raise_server_exceptions=False)
    assert verify(probe,'login','wrong').status_code == 503
    probe.close()


def test_db_guard_error_has_no_fallback_or_exception_message(email_env,monkeypatch):
    from sqlalchemy.exc import OperationalError
    c, db, app, delivered = email_env
    code = issue(email_env,'login')
    def broken(*args,**kwargs):
        raise OperationalError('synthetic-secret-query',{},Exception('synthetic-secret-db'))
    # Fail ONLY the guard lookup after the owner was resolved normally.
    from app.services import email_attempts as guard
    locked = guard.locked_state
    def failing_guard(session):
        with monkeypatch.context() as local:
            local.setattr(session,'query',broken)
            return locked(session)
    monkeypatch.setattr(guard,'locked_state',failing_guard)
    response = verify(c,'login',code)
    assert response.status_code == 503
    assert 'synthetic-secret' not in response.text
    assert db.query(EmailCode).count() == 1


@pytest.mark.parametrize('purpose', ['login','reset','bind'])
def test_oversized_codes_are_rejected_before_guard_access(email_env,purpose):
    c, db, app, delivered = email_env
    issue(email_env,purpose)
    assert verify(c,purpose,'x'*65).status_code == 422


@pytest.mark.parametrize('purpose',['login','reset','bind'])
def test_happy_path_is_single_use_and_never_grants_management(email_env,purpose):
    c, db, app, delivered = email_env
    code = issue(email_env,purpose)
    response = verify(c,purpose,code)
    assert response.status_code == 200
    assert code not in response.text
    assert verify(c,purpose,code).status_code == 404
    assert c.post('/danger').status_code in (401,403)


def test_email_reset_changes_only_daily_password_and_revokes_grants(email_env):
    from app.services.admin_security import STATE_KEY
    from app.security import verify_password
    c, db, app, delivered = email_env
    assert c.post('/auth/admin/setup',json={'user_password':DAILY,'new_password':ADMIN}).status_code == 200
    assert c.post('/auth/admin/unlock',json={'password':ADMIN}).status_code == 200
    assert c.post('/danger').status_code == 200
    before = json.loads(db.get(AppConfig,STATE_KEY).value)['password_hash']
    code = issue(email_env,'reset')
    assert verify(c,'reset',code).status_code == 200
    state = json.loads(db.get(AppConfig,STATE_KEY).value)
    assert state['password_hash'] == before
    assert state['grants'] == {}
    assert all(s.revoked for s in db.query(AuthSession).all())
    assert c.post('/auth/login',json={'username':'owner','password':DAILY+'-reset'}).status_code == 200
    assert c.post('/danger').status_code == 403
    assert c.post('/auth/admin/unlock',json={'password':DAILY+'-reset'}).status_code == 401
    assert c.post('/auth/admin/unlock',json={'password':ADMIN}).status_code == 200


@pytest.mark.parametrize('purpose',['login','reset','bind'])
def test_legacy_unscoped_codes_fail_closed_without_deleting_user_data(email_env,purpose):
    from datetime import datetime,timedelta,timezone
    c, db, app, delivered = email_env
    legacy = EmailCode(email=MAIL,code='legacy-fixture',expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))
    db.add(legacy)
    db.commit()
    assert verify(c,purpose,'legacy-fixture').status_code == 404
    assert db.query(User).count() == 1
    assert db.query(EmailCode).count() == 1


@pytest.mark.parametrize('purpose',['login','reset','bind'])
def test_expired_codes_cannot_be_used_but_new_issuance_recovers(email_env,purpose,monkeypatch):
    from app.services import email_attempts as guard
    from datetime import timedelta
    c, db, app, delivered = email_env
    start = guard.now()
    monkeypatch.setattr(guard,'now',lambda:start)
    code = issue(email_env,purpose)
    monkeypatch.setattr(guard,'now',lambda:start+timedelta(seconds=601))
    assert verify(c,purpose,code).status_code == 410
    new = issue(email_env,purpose)
    assert verify(c,purpose,new).status_code == 200


@pytest.mark.parametrize('issued,target',[('bind','login'),('bind','reset'),('login','reset'),('reset','login')])
def test_codes_cannot_cross_purposes(email_env,issued,target):
    c, db, app, delivered = email_env
    code = issue(email_env,issued)
    assert verify(c,target,code).status_code == 404
    assert verify(c,issued,code).status_code == 200


@pytest.mark.parametrize('purpose',['login','reset','bind'])
def test_fifth_failure_blocks_all_new_issuance_paths(email_env,purpose):
    c, db, app, delivered = email_env
    issue(email_env,purpose)
    assert [verify(c,purpose,'wrong').status_code for _ in range(5)] == [401]*5
    for endpoint in ISSUE.values():
        assert c.post(endpoint,json={'email':MAIL}).status_code == 429
    assert c.post('/auth/email/send-code',json={'email':'another@email.invalid'}).status_code == 429
    assert len(delivered) == 1


@pytest.mark.parametrize('operation',['issue','consume'])
def test_guard_write_failure_is_503_and_rolls_back_atomically(email_env,monkeypatch,operation):
    from sqlalchemy.exc import OperationalError
    from app.services import email_attempts as guard
    c, db, app, delivered = email_env
    saved = guard.save
    code = issue(email_env,'login') if operation == 'consume' else None
    def failed_save(session,row,state):
        def broken():
            raise OperationalError('synthetic-sensitive-query',{},Exception('synthetic-sensitive-data'))
        with monkeypatch.context() as local:
            local.setattr(session,'flush',broken)
            return saved(session,row,state)
    monkeypatch.setattr(guard,'save',failed_save)
    probe = TestClient(app,raise_server_exceptions=False)
    response = verify(probe,'login',code) if operation == 'consume' else probe.post(ISSUE['login'],json={'email':MAIL})
    assert response.status_code == 503
    assert 'synthetic-sensitive' not in response.text
    monkeypatch.setattr(guard,'save',saved)
    assert db.query(EmailCode).count() == (1 if operation == 'consume' else 0)
    if operation == 'consume':
        assert verify(c,'login',code).status_code == 200
    else:
        issue(email_env,'login')
    probe.close()
