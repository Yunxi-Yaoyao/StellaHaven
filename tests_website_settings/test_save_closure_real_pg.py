"""Real owner login/JWT/current_user/admin_user + owned PostgreSQL + ASGI HTTP.
Only get_db is rebound; no auth dependency overrides. Seeded owner, not full main.
"""
import json
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from tests_website_settings.test_save_light_navigation import factory
from tests_website_settings.test_website_settings import upstream


def test_real_pg_receipt_rechecks_owner_session_revocation_expiry_and_deactivation(factory,upstream,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers.auth import router as auth,current_user,admin_user
    from app.routers.website_settings import router as websites
    from app.routers.integrations import router as integrations
    from app.models.user import User,AuthSession
    from app.models.config import AppConfig
    from app.services.admin_security import STATE_KEY
    from app.services import integrations as store
    from app.security import hash_password,make_access_token,read_access_token
    engine=factory.kw['bind']
    User.__table__.create(engine,checkfirst=True);AuthSession.__table__.create(engine,checkfirst=True)
    with factory() as db:
        db.query(AppConfig).delete();db.commit()
        owner=User(username='save-owner-'+uuid4().hex,display_name='Save owner',password_hash=hash_password('fixture-daily-password'),is_active=True)
        foreign=User(username='save-foreign-'+uuid4().hex,display_name='Foreign',password_hash=hash_password('fixture-foreign-password'),is_active=True)
        db.add_all([owner,foreign]);db.flush();uid=owner.id;foreign_id=foreign.id;username=owner.username
        db.add(AppConfig(key=STATE_KEY,value=json.dumps(dict(owner_id=str(uid),enabled=True,version=1,grants={}))))
        foreign_session=AuthSession(user_id=foreign_id,refresh_hash=uuid4().hex,remember=True);db.add(foreign_session);db.flush()
        foreign_token=make_access_token(str(foreign_id),str(foreign_session.id));db.commit()
    def database():
        with factory() as db:
            try: yield db
            finally: db.rollback()
    app=FastAPI();app.include_router(auth);app.include_router(websites);app.include_router(integrations)
    app.dependency_overrides[get_db]=database
    assert current_user not in app.dependency_overrides and admin_user not in app.dependency_overrides
    monkeypatch.setenv('STELLA_COOKIE_SECURE','false')
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','http://stella.test')
    # Audit sink only: no auth/session/service substitution.
    monkeypatch.setattr(store,'record_change',lambda *a,**k:None)
    root,_,seen=upstream
    with TestClient(app,base_url='http://stella.test') as c:
        login=c.post('/auth/login',json=dict(username=username,password='fixture-daily-password',remember=True))
        assert login.status_code==200,login.text
        token=c.cookies.get('stella_at');sid=__import__('uuid').UUID(read_access_token(token)['sid'])
        saved=c.post('/website-settings',json=dict(address=root+'/real',idempotency_key='real-pg-create-1'))
        assert saved.status_code==201,saved.text
        mid=saved.json()['id']
        body=dict(address=root+'/real',name='Real session saved',expected_revision=saved.json()['navigation']['revision'],idempotency_key='real-pg-edit-1')
        ack=c.patch('/website-settings/'+mid,json=body)
        assert ack.status_code==200,ack.text
        path='/website-settings/'+mid+'/receipt?idempotency_key=real-pg-edit-1'
        assert c.get(path).json()==ack.json()
        with factory() as db:
            raw=db.get(AppConfig,store.KEY).value
            assert db.get(AuthSession,sid).user_id==uid
        seen.clear()
        c.cookies.clear();assert c.get(path).status_code==401
        c.cookies.set('stella_at',foreign_token);assert c.get(path).status_code==403
        c.cookies.set('stella_at',token)
        with factory() as db: db.get(AuthSession,sid).revoked=True;db.commit()
        assert c.get(path).status_code==401
        with factory() as db:
            s=db.get(AuthSession,sid);s.revoked=False;s.created_at=datetime.now(timezone.utc)-timedelta(days=40);s.last_seen=s.created_at;db.commit()
        assert c.get(path).status_code==401
        with factory() as db:
            s=db.get(AuthSession,sid);s.created_at=datetime.now(timezone.utc);s.last_seen=s.created_at
            db.get(User,uid).is_active=False;db.commit()
        assert c.get(path).status_code==401
        with factory() as db:
            db.get(User,uid).is_active=True
            row=db.get(AppConfig,STATE_KEY);state=json.loads(row.value);state['owner_id']=str(foreign_id);row.value=json.dumps(state);db.commit()
        assert c.get(path).status_code==403
        assert not seen
        with factory() as db: assert db.get(AppConfig,store.KEY).value==raw
