"""Real admin guard and public client-code projection on disposable PostgreSQL."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from tests_builtin.pg_fixture import pg_engine, pg_db


def make_app(engine):
    from app.database import get_db
    from app.routers.auth import router as auth
    from app.routers.builtin_injection import router, assets_router
    app = FastAPI()
    app.include_router(auth)
    app.include_router(router)
    app.include_router(assets_router)
    def get_test_db():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = get_test_db
    return app


def test_real_admin_guard_and_client_projection(pg_db, pg_engine, monkeypatch):
    from app.models.user import User, AuthSession, EmailCode
    from app.models.config import AppConfig
    from app.services import builtin_injection as builtin
    monkeypatch.delenv('STELLA_OWNER_ID', raising=False)
    for table in (User.__table__, AuthSession.__table__, EmailCode.__table__):
        table.create(pg_engine, checkfirst=True)
    app = make_app(pg_engine)
    with TestClient(app, base_url='https://testserver') as c:
        assert c.get('/builtin-injections/gallery').status_code == 401
        assert c.post('/auth/register', json={'username':'builtin-owner','password':'builtin-daily-fixture'}).status_code == 201
        assert c.get('/builtin-injections/gallery').status_code == 403
        assert c.post('/auth/admin/setup', json={'user_password':'builtin-daily-fixture','new_password':'builtin-independent-admin-fixture'}).status_code == 200
        assert c.post('/auth/admin/unlock', json={'password':'builtin-independent-admin-fixture'}).status_code == 200
        initial = c.get('/builtin-injections/gallery').json()
        assert initial['source'] == 'preset'
        assert c.post('/builtin-injections/gallery/validate',json={'headers':{'Authorization':'SYNTHETIC'}}).status_code==422
        assert not c.post('/builtin-injections/gallery/validate',json={'enabled':True,'js':'const = syntax error;'}).json()['valid']
        assert c.post('/builtin-injections/gallery/apply').status_code==422
        assert c.get('/builtin-injections/gallery').json()['active']['version']=='preset-v1'
        draft = {'enabled':True,'css':'h1{color:rgb(12,34,56)}','js':'window.galleryClient=73;','timing':'dom_ready','csp_policy':'reject'}
        assert c.post('/builtin-injections/gallery/validate', json=draft).json()['valid']
        assert 'galleryClient' not in c.get('/integration-assets/gallery.js').text
        applied = c.post('/builtin-injections/gallery/apply').json()
        assert c.get('/builtin-injections/gallery').json()['active']['version'] == applied['active']['version']
        owner_asset=c.get('/integration-assets/gallery.js')
        assert 'galleryClient=73' in owner_asset.text
        assert owner_asset.headers['x-stella-injection-version']==applied['active']['version']
        pg_db.add(AppConfig(key='unrelated-private-config', value='SYNTHETIC-SECRET-DO-NOT-PROJECT')); pg_db.commit()
        with TestClient(app, base_url='https://testserver') as anonymous:
            asset = anonymous.get('/integration-assets/gallery.js')
            assert asset.status_code == 200 and 'galleryClient' not in asset.text
            assert 'SYNTHETIC-SECRET' not in asset.text
            assert 'builtin-independent-admin-fixture' not in asset.text
            assert asset.headers['cache-control'] == 'no-store'
            assert asset.headers['x-stella-injection-version'] == 'preset-v1'
            assert 'access-control-allow-origin' not in asset.headers
            assert asset.headers['vary']=='Cookie'
            assert 'galleryClient' not in anonymous.get('/integration-assets/gallery.js?claimtoken=fake').text
            anonymous.cookies.set('stella_at','invalid')
            assert 'galleryClient' not in anonymous.get('/integration-assets/gallery.js').text
            assert anonymous.get('/integration-assets/drive.js').status_code == 404
            assert anonymous.get('/builtin-injections/gallery').status_code == 401
        assert c.post('/auth/admin/lock').status_code == 200
        for path in ('validate','apply','rollback'):
            assert c.post('/builtin-injections/gallery/'+path, json=draft).status_code == 403
        assert c.get('/builtin-injections/gallery').status_code == 403
        assert 'galleryClient=73' in c.get('/integration-assets/gallery.js').text # daily session, not elevation
        token=c.cookies.get('stella_at')
        assert c.post('/auth/logout').status_code==200
        c.cookies.set('stella_at',token)
        assert 'galleryClient' not in c.get('/integration-assets/gallery.js').text # revoked session
