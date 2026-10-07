"""Real HTTP + disposable PG auth/save/readback, no auth dependency stubs."""
import json
import httpx
from fastapi import FastAPI
from sqlalchemy.orm import Session
from tests_builtin.pg_fixture import pg_engine, pg_db
from tests_builtin.test_builtin_browser import local_server
from tests_service_settings.test_api import payload


def test_daily_then_elevated_real_http_save_readback_and_legacy_rollback(pg_engine,pg_db,monkeypatch,tmp_path):
    from app.database import get_db
    from app.models.user import User,AuthSession,EmailCode
    from app.models.config import AppConfig
    from app.routers.auth import router as auth
    from app.routers.service_settings import router
    from app.routers.builtin_injection import router as injection
    from app.services import oidc
    monkeypatch.delenv('STELLA_OWNER_ID',raising=False)
    monkeypatch.setenv('STELLA_COOKIE_SECURE','false')
    monkeypatch.setattr(oidc,'CLIENT_FILE',tmp_path/'clients.json')
    for table in (User.__table__,AuthSession.__table__,EmailCode.__table__):table.create(pg_engine)
    app=FastAPI();app.include_router(auth);app.include_router(router);app.include_router(injection)
    def database():
        with Session(pg_engine) as db:yield db
    app.dependency_overrides[get_db]=database
    with local_server(app) as origin, httpx.Client(base_url=origin,trust_env=False) as client:
        assert client.get('/service-settings/drive').status_code==401
        r=client.post('/auth/register',json={'username':'http-owner','password':'http-daily-synthetic-123'})
        assert r.status_code==201,r.text
        daily=client.get('/service-settings/drive')
        assert daily.status_code==200 and daily.headers['cache-control']=='no-store'
        assert client.put('/service-settings/drive',json=payload()).status_code==403
        assert client.post('/auth/admin/setup',json={'user_password':'http-daily-synthetic-123','new_password':'http-admin-synthetic-456'}).status_code==200
        assert client.post('/auth/admin/unlock',json={'password':'http-admin-synthetic-456'}).status_code==200
        draft={'enabled':True,'css':'body{color:blue}','js':'window.httpProof=1;'}
        for site in ('drive','gallery'):
            data=payload(site)|{'custom':draft}
            result=client.put('/service-settings/'+site,json=data)
            assert result.status_code==200,result.text
            assert client.get('/service-settings/'+site).json()==result.json()
            assert client.put('/service-settings/'+site,json=data).json()==result.json()
        bad=client.put('/service-settings/drive',json=payload()|{'custom':{'js':'const = syntax error'}})
        assert bad.status_code==422
        assert client.get('/service-settings/drive').json()['injection']['active']['js']=='window.httpProof=1;'
        assert client.post('/builtin-injections/drive/validate',json={'js':'window.draftOnly=1;'}).json()['valid']
        back=client.post('/builtin-injections/drive/rollback')
        assert back.status_code==200
        state=client.get('/service-settings/drive').json()['injection']
        assert state['active']['version']=='preset-v1' and state['draft']['js']=='window.draftOnly=1;'
        assert client.post('/auth/admin/lock').status_code==200
        assert client.get('/service-settings/gallery').status_code==200
        assert client.post('/builtin-injections/gallery/rollback').status_code==403
        token=client.cookies.get('stella_at');assert token
        assert client.post('/auth/logout').status_code==200
        assert client.get('/service-settings/gallery',headers={'Cookie':'stella_at='+token}).status_code==401
    with Session(pg_engine) as fresh:
        persisted=json.loads(fresh.get(AppConfig,'service_appearance_v1').value)
        assert persisted=={'drive':{'theme':'original','simplified':False},'gallery':{'logo':'original'}}
