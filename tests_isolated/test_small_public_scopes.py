"""Real owner/elevation dependencies with SQLite; run in a separate process."""
import json

from tests_isolated.test_owner_admin_security import auth_env, owner, DAILY, ADMIN  # noqa: F401


def test_small_public_reads_preserve_auth_and_independent_management_scopes(auth_env, tmp_path, monkeypatch):
    from app.routers import admin_email, operations_status, oidc
    from app.services import oidc as oidc_svc
    from app.models.user import User
    from authlib.jose import JsonWebKey

    client, db, app = auth_env
    monkeypatch.delenv('STELLA_SHARED_STATE', raising=False)
    monkeypatch.delenv('STELLA_OIDC_PRIVATE_KEY_FILE', raising=False)
    monkeypatch.setattr(admin_email, 'CONFIG_FILE', tmp_path / 'smtp.json')
    monkeypatch.setattr(oidc_svc, 'PRIVATE_KEY_PATH', tmp_path / 'private.json')
    key = JsonWebKey.generate_key('RSA', 2048, is_private=True).as_dict(is_private=True)
    oidc_svc.PRIVATE_KEY_PATH.write_text(json.dumps(key))
    for router in (admin_email.router, operations_status.router, oidc.router):
        app.include_router(router)

    protected = ('/auth/avatars', '/admin/email/config', '/operations/change-audit')
    for path in protected:
        assert client.get(path).status_code == 401
    assert client.get('/oauth/jwks').status_code == 200  # protocol public, not admin-scoped

    owner(client)
    user = db.query(User).one()
    user.avatar_history = json.dumps(['/assets/avatars/fixture.png', {'password': 'object-secret'}])
    user.is_admin = True  # legacy flag is not a management grant
    db.commit()
    assert client.get('/auth/avatars').json() == ['/assets/avatars/fixture.png']
    for path in protected[1:]:
        assert client.get(path).status_code == 200

    assert client.post('/auth/admin/setup', json={'user_password': DAILY, 'new_password': ADMIN}).status_code == 410
    for path in protected[1:]:
        assert client.get(path).status_code == 200
    assert client.post('/auth/admin/unlock', json={'password': ADMIN}).status_code == 410
    assert client.get('/admin/email/config').json() == admin_email.DEFAULTS
    audit = client.get('/operations/change-audit')
    assert audit.status_code == 200 and audit.json()['limit'] == 200
    assert audit.json()['events']==[]  # retired setup/unlock never write audit/grants
    assert all(set(event) == {'timestamp', 'action', 'actor_id', 'resource_id', 'changed_fields'}
               for event in audit.json()['events'])
    assert client.post('/auth/admin/lock').status_code == 410
    for path in protected[1:]:
        assert client.get(path).status_code == 200
    assert client.get('/auth/avatars').status_code == 200
