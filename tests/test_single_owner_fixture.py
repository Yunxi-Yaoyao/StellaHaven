"""Full main-app PG proofs of the new fixtures/security, no auth override."""
from uuid import uuid4
from sqlalchemy import text
from app.models.user import User
from app.models.config import AppConfig
from app.services.admin_security import STATE_KEY


def test_fixture_is_real_single_owner_with_disposable_schema(client, db_session):
    assert db_session.execute(text('SELECT current_schema()')).scalar().startswith('upgrade_test_')
    assert db_session.query(User).count() == 1
    from main import app
    from app.routers.auth import current_user, admin_user
    assert current_user not in app.dependency_overrides
    assert admin_user not in app.dependency_overrides
    assert client.get('/auth/security').json()['elevated'] is True
    db_session.add(AppConfig(key='regression-durable-commit',value='synthetic'))
    db_session.commit()


def test_repository_commits_do_not_pollute_next_schema(client, db_session):
    assert db_session.get(AppConfig,'regression-durable-commit') is None
    assert db_session.query(User).count() == 1


def test_unconfigured_management_fails_closed_in_actual_main(client, db_session):
    state=db_session.get(AppConfig,STATE_KEY)
    db_session.delete(state); db_session.commit()
    security=client.get('/auth/security')
    assert security.status_code == 200
    assert security.json()['setup_required'] is True
    response=client.post('/nodes/',json={'name':'must-not-create','host':'192.0.2.1','platform':'linux'})
    assert response.status_code == 403
    assert response.json()['detail']['code'] == 'admin_setup_required'
    assert client.get('/workspaces/').status_code == 200
    assert client.get('/assets/homebg/no-such-upload.png').status_code == 404


def test_retained_second_account_cannot_log_in_or_access_owner_data(client, db_session):
    from app.security import hash_password
    foreign=User(username='retained-'+uuid4().hex,display_name='Retained',password_hash=hash_password('foreign-daily-123'),is_admin=True)
    db_session.add(foreign);db_session.commit(); foreign_id=foreign.id
    me=client.get('/auth/me').json()
    denied=client.post('/auth/login',json={'username':foreign.username,'password':'foreign-daily-123'})
    assert denied.status_code == 403
    assert client.get('/auth/me').json()['id'] == me['id']
    assert db_session.get(User,foreign_id) is not None


def test_approved_alternate_main_origin_is_not_rejected_by_integration_dispatch(client, monkeypatch):
    from tests.conftest import OWNER_USERNAME, OWNER_PASSWORD
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','http://testserver,http://approved-alternate.fixture')
    response=client.post('/auth/login',json={'username':OWNER_USERNAME,'password':OWNER_PASSWORD},
                         headers={'Host':'approved-alternate.fixture','Origin':'http://approved-alternate.fixture'})
    assert response.status_code == 200, response.text


def test_actual_main_exact_origin_and_secure_default(client, monkeypatch):
    from tests.conftest import OWNER_USERNAME, OWNER_PASSWORD
    credentials={'username':OWNER_USERNAME,'password':OWNER_PASSWORD}
    assert client.post('/auth/login',json=credentials,headers={'Origin':'https://foreign.invalid'}).status_code == 403
    assert client.get('/auth/me',headers={'Host':'foreign.invalid'}).status_code == 421
    monkeypatch.delenv('STELLA_COOKIE_SECURE',raising=False)
    response=client.post('/auth/login',json=credentials)
    assert response.status_code == 200
    assert all('Secure' in h and 'HttpOnly' in h and 'Domain=' not in h for h in response.headers.get_list('set-cookie'))
