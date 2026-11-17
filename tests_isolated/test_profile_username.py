"""Real router / HTTP, exclusive SQLite; PostgreSQL connections forbidden."""
from test_owner_admin_security import auth_env, DAILY
from app.models.user import User, AuthSession
from app.security import read_access_token


def register(client, name='before'):
    r = client.post('/auth/register', json={'username': name, 'display_name': 'nickname', 'password': DAILY})
    assert r.status_code == 201, r.text
    return r.json()


def test_rename_preserves_owner_sid_cookies_and_new_login(auth_env):
    c, db, app = auth_env
    original = register(c)
    cookie = c.cookies.get('stella_at')
    claims = read_access_token(cookie)
    assert claims is not None
    sid = claims['sid']
    r = c.patch('/auth/me', json={'username': '  after  '})
    assert r.status_code == 200, r.text
    assert r.json()['username'] == 'after'
    assert r.json()['id'] == original['id']
    assert c.cookies.get('stella_at') == cookie
    assert c.get('/auth/me').json()['username'] == 'after'
    sessions = c.get('/auth/sessions?current_only=true').json()
    assert sessions[0]['id'] == sid
    assert db.query(AuthSession).count() == 1
    from fastapi.testclient import TestClient
    with TestClient(app) as fresh:
        assert fresh.post('/auth/login', json={'username': 'before', 'password': DAILY}).status_code == 401
        r = fresh.post('/auth/login', json={'username': 'after', 'password': DAILY})
        assert r.status_code == 200 and r.json()['id'] == original['id']
    # Neither identity rename nor a separate login revokes the current access SID.
    assert c.get('/auth/me').status_code == 200


def test_rename_rejects_blank_and_cross_field_collision_atomically(auth_env):
    c, db, app = auth_env
    original = register(c)
    db.add(User(username='reserved', display_name='other-nickname', email='other@example.test', password_hash=''))
    db.commit()
    for name in ['reserved', 'other-nickname', 'other@example.test', 'nickname']:
        r = c.patch('/auth/me', json={'username': name, 'home_bg': 'should-not-write'})
        assert r.status_code == 409, (name, r.text)
        assert c.get('/auth/me').json()['username'] == 'before'
        assert c.get('/auth/me').json()['home_bg'] == ''
    assert c.patch('/auth/me', json={'username': '   '}).status_code == 400
    assert c.patch('/auth/me', json={'username': 'x'*255}).status_code == 422
    # Existing register-default username == nickname remains a compatible no-op.
    assert c.patch('/auth/me', json={'username': original['username']}).status_code == 200
    assert c.patch('/auth/me', json={'username':'new', 'display_name':'new'}).status_code == 409
    # A nickname cannot shadow the resulting username in the other direction either.
    assert c.patch('/auth/me', json={'display_name':'before'}).status_code == 409


def test_unrelated_profile_edit_does_not_revalidate_legacy_unchanged_identifiers(auth_env):
    c, db, app = auth_env
    register(c)
    owner = db.query(User).one()
    owner.email = 'legacy-invalid'
    db.add(User(username='historical', display_name='before', password_hash=''))
    db.commit()
    assert c.patch('/auth/me', json={'home_bg':'/assets/unchanged-fixture.png'}).status_code == 200
    r = c.patch('/auth/me', json={'username':'future-login'})
    assert r.status_code == 200, r.text
    assert r.json()['username'] == 'future-login'
    assert r.json()['email'] == 'legacy-invalid'


def test_legacy_same_nickname_keeps_old_identifier_as_nickname(auth_env):
    c, db, app = auth_env
    r = c.post('/auth/register', json={'username':'legacy','password':DAILY})
    assert r.status_code == 201
    assert c.patch('/auth/me', json={'username':'renamed'}).json()['username'] == 'renamed'
    # Three-in-one login deliberately retains independent nickname access.
    from fastapi.testclient import TestClient
    with TestClient(app) as fresh:
        assert fresh.post('/auth/login', json={'username':'legacy','password':DAILY}).status_code == 200
