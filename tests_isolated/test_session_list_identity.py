"""Session-list identity regressions, using the private SQLite HTTP fixture."""
import pytest
from tests_isolated.test_browser_sessions import api, login

@pytest.mark.parametrize('refresh_cookie', ['absent', 'stale', 'other_session'])
def test_current_session_is_validated_access_sid_not_refresh_cookie(api, refresh_cookie):
    assert login(api, remember=True).status_code == 200
    first_access = api.client.cookies.get('stella_at')
    first_id = api.client.get('/auth/sessions').json()[0]['id']
    api.client.cookies.clear()
    assert login(api, remember=True).status_code == 200
    other_refresh = api.client.cookies.get('stella_rt')
    api.client.cookies.clear()
    api.client.cookies.set('stella_at', first_access, domain='one.test', path='/')
    if refresh_cookie != 'absent':
        api.client.cookies.set('stella_rt', other_refresh if refresh_cookie == 'other_session' else 'not-a-valid-refresh', domain='one.test', path='/')
    response = api.client.get('/auth/sessions')
    assert response.status_code == 200
    rows = response.json()
    assert [s['id'] for s in rows if s['current']] == [first_id]
    with api.factory() as db:
        assert db.query(api.AuthSession).count() == 2
        assert db.query(api.AuthSession).filter_by(revoked=False).count() == 2


@pytest.mark.parametrize('remember', [False, True])
def test_active_list_exposes_actual_policy_expiry_without_extending_it(api, remember):
    from app.services.session_policy import expires_at
    assert login(api, remember=remember).status_code == 200
    with api.factory() as db:
        row = db.query(api.AuthSession).one()
        expected = expires_at(row).isoformat()
        before = (row.created_at, row.last_seen, row.refresh_hash)
    for _ in range(2):
        response = api.client.get('/auth/sessions')
        assert response.status_code == 200
        assert response.json()[0]['expires_at'] == expected
    with api.factory() as db:
        row = db.query(api.AuthSession).one()
        assert (row.created_at, row.last_seen, row.refresh_hash) == before


def test_refresh_rotates_same_session_without_new_rows_or_activity(api):
    assert login(api, remember=True).status_code == 200
    with api.factory() as db:
        row = db.query(api.AuthSession).one()
        sid, created, seen, original_hash = row.id, row.created_at, row.last_seen, row.refresh_hash
    for _ in range(3):
        assert api.client.post('/auth/refresh').status_code == 200
    with api.factory() as db:
        row = db.query(api.AuthSession).one()
        assert row.id == sid
        assert (row.created_at, row.last_seen) == (created, seen)
        assert row.refresh_hash != original_hash


def test_fresh_browser_login_never_revokes_unknown_other_context(api):
    assert login(api, remember=True).status_code == 200
    api.client.cookies.clear()  # Simulates a new context, NOT server logout.
    assert login(api, remember=True).status_code == 200
    with api.factory() as db:
        assert db.query(api.AuthSession).filter_by(revoked=False).count() == 2
    assert api.client.post('/auth/logout').status_code == 200
    with api.factory() as db:
        assert db.query(api.AuthSession).count() == 2
        assert db.query(api.AuthSession).filter_by(revoked=False).count() == 1


def test_current_only_is_independent_of_recent_activity_pagination(api):
    from datetime import datetime, timedelta, timezone
    assert login(api, remember=True).status_code == 200
    current_id = api.client.get('/auth/sessions').json()[0]['id']
    with api.factory() as db:
        row = db.query(api.AuthSession).one()
        row.last_seen = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        for i in range(25):
            db.add(api.AuthSession(user_id=row.user_id, refresh_hash=f'synthetic-list-{i}', remember=True))
        db.commit()
    first_page = api.client.get('/auth/sessions?page=1&page_size=20').json()
    assert len(first_page) == 20 and all(not s['current'] for s in first_page)
    pinned = api.client.get('/auth/sessions?current_only=true&page=99&page_size=1').json()
    assert len(pinned) == 1 and pinned[0]['id'] == current_id and pinned[0]['current']
    assert 'expires_at' in pinned[0]
    # A fixed current row must not consume an index in the other-session pages.
    others = [s for page in (1, 2) for s in api.client.get(f'/auth/sessions?exclude_current=true&page={page}&page_size=20').json()]
    assert len(others) == 25 and len({s['id'] for s in others}) == 25
    assert all(not s['current'] and s['id'] != current_id for s in others)
    assert not {'refresh_hash', 'refresh_token', 'password_hash', 'access_token'} & pinned[0].keys()
