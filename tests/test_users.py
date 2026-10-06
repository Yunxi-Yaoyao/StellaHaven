"""Retired multi-user CRUD must never create/expose/delete legacy identities."""
from uuid import uuid4
from app.models.user import User


def test_create_user(client, db_session):
    before = db_session.query(User).count()
    r = client.post('/users/', json={'username':'second_'+uuid4().hex,'display_name':'Second'})
    assert r.status_code == 405  # no POST route; SPA only handles GET
    assert db_session.query(User).count() == before == 1


def test_get_user(client, db_session):
    owner = client.get('/auth/me').json()
    legacy = User(username='retained', display_name='Retained', password_hash='')
    db_session.add(legacy); db_session.commit(); old_id=legacy.id
    assert client.get(f'/users/{old_id}').status_code == 404
    assert client.get('/auth/me').json()['id'] == owner['id']
    assert db_session.get(User,old_id).display_name == 'Retained'


def test_list_users(client, db_session):
    assert client.get('/users/?limit=10000').status_code == 404
    assert db_session.query(User).count() == 1
