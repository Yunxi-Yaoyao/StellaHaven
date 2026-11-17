"""Real HTTP management flows with real owner/session dependencies (no overrides)."""
import json
import io
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import Depends,Request
from fastapi.testclient import TestClient
from app.models.user import User,AuthSession
from app.models.config import AppConfig
from app.routers.auth import current_user
from app.security import hash_password,make_access_token
from tests_isolated.test_owner_admin_security import auth_env,owner,DAILY
from tests_isolated.test_oidc_provider import oidc


def test_actual_client_secret_create_read_reveal_origin_rotate_and_revocation(auth_env,oidc,monkeypatch):
    c,db,app=auth_env
    from app.routers.auth_provider import router
    from app.services.request_security import MainSiteSecurityMiddleware
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','http://testserver')
    app.add_middleware(MainSiteSecurityMiddleware)
    app.include_router(router)
    url='/auth/provider/clients/photos'
    assert c.post(url+'/reveal-secret',headers={'origin':'http://testserver'}).status_code == 401
    owner(c)
    r=c.post('/auth/provider/clients',json={'client_id':'photos','name':'Photos','redirect_uris':['https://photos.test/cb']})
    assert r.status_code == 201,r.text
    secret=r.json()['client_secret']
    assert len(secret)>=32
    listed=c.get('/auth/provider/clients');assert listed.status_code == 200 and secret not in listed.text
    assert c.post(url+'/reveal-secret').status_code == 403
    assert c.post(url+'/reveal-secret',headers={'origin':'https://evil.test'}).status_code == 403
    assert c.post(url+'/reveal-secret',headers=[('origin','http://testserver'),('origin','http://testserver')]).status_code == 403
    r=c.post(url+'/reveal-secret',headers={'origin':'http://testserver'})
    assert r.status_code == 200 and r.json()['client_secret']==secret
    assert r.headers['cache-control']=='no-store'
    outsider=User(username='other',display_name='other',password_hash=hash_password(DAILY),is_admin=True)
    db.add(outsider);db.flush();outs=AuthSession(user_id=outsider.id,refresh_hash='outsider',remember=True);db.add(outs);db.commit()
    foreign=TestClient(app);foreign.cookies.set('stella_at',make_access_token(str(outsider.id),str(outs.id)))
    denied=foreign.post(url+'/reveal-secret',headers={'origin':'http://testserver'})
    assert denied.status_code == 403 and secret not in denied.text;foreign.close()
    r=c.post(url+'/rotate-secret');assert r.status_code == 200 and r.json()['client_secret']!=secret
    session=db.query(AuthSession).filter(AuthSession.user_id!=outsider.id).one();session.revoked=True;db.commit()
    assert c.post(url+'/reveal-secret',headers={'origin':'http://testserver'}).status_code == 401


def test_real_integration_write_readback_and_csrf_still_enforced(auth_env,monkeypatch):
    c,db,app=auth_env
    from app.routers.integrations import router
    from app.services.request_security import MainSiteSecurityMiddleware
    from app.services.integrations import KEY
    app.include_router(router);monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','http://testserver');app.add_middleware(MainSiteSecurityMiddleware)
    payload={'name':'Fixture link','mode':'link','browser_url':'https://example.test/'}
    assert c.post('/external-modules',json=payload).status_code == 401
    owner(c)
    assert c.post('/external-modules',json=payload,headers={'origin':'https://evil.test'}).status_code == 403
    assert db.get(AppConfig,KEY) is None
    r=c.post('/external-modules',json=payload,headers={'origin':'http://testserver'})
    assert r.status_code == 201,r.text
    mid=r.json()['id'];assert c.get('/external-modules/'+mid).json()['name']==payload['name']
    assert c.patch('/external-modules/'+mid,json={'name':'Renamed'},headers={'origin':'http://testserver'}).status_code == 200
    assert c.get('/external-modules/'+mid).json()['name']=='Renamed'
    assert c.get('/integration-targets').status_code == 200
    assert c.delete('/external-modules/'+mid,headers={'origin':'http://testserver'}).status_code == 204
    assert c.get('/external-modules/'+mid).status_code == 404
    assert c.post('/auth/logout').status_code == 200
    assert c.get('/integration-targets').status_code == 401


@pytest.mark.parametrize('service', ['website_policy','openlist_access'])
@pytest.mark.parametrize('boundary', ['owner','wrong_owner','revoked','expired','missing'])
def test_real_service_transport_calls_require_current_persisted_owner(auth_env,service,boundary):
    c,db,app=auth_env
    uid=owner(c);session=db.query(AuthSession).one()
    if boundary=='wrong_owner':
        user=User(username='other',display_name='other',password_hash=hash_password(DAILY));db.add(user);db.flush()
        session=AuthSession(user_id=user.id,refresh_hash='other',remember=True);db.add(session);db.commit()
    elif boundary=='revoked':session.revoked=True;db.commit()
    elif boundary=='expired':session.remember=False;session.last_seen=datetime.now(timezone.utc)-timedelta(hours=1);db.commit()
    sid=str(session.id)
    if boundary=='missing':db.delete(session);db.commit()
    # This route deliberately has no cookie dependency: the *real service* must
    # enforce its ticket's owner/session, not rely on admin_user at a UI route.
    @app.post('/fixture/transport')
    def transport():
        from app.services import website_policy,openlist_access
        grant={'sid':sid}
        if service=='website_policy':website_policy.require_grant(db,grant,{'request_policy':{'protect_other_writes':True}},'POST','/write')
        else:openlist_access.require_grant(db,grant,'POST','api/admin/update')
        return {'ok':True}
    expected={'owner':200,'wrong_owner':403,'revoked':401,'expired':401,'missing':401}[boundary]
    assert c.post('/fixture/transport').status_code == expected


def test_backup_actual_signed_zip_head_get_wrong_confirmation_and_delete(auth_env,tmp_path):
    c,db,app=auth_env
    from app.routers.backups import router
    from app.services.backup_storage import BackupDirectory
    app.include_router(router)
    store=BackupDirectory(tmp_path,'owned-backup-signing-fixture')
    record=store.create('settings',{'settings.json':io.BytesIO(b'{"fixture":true}')})
    app.state.backup_center=SimpleNamespace(store=lambda:store,delete=store.delete)
    path='/operations/backups/'+record['id']
    assert c.head(path+'/download').status_code == 401
    assert c.get(path+'/download').status_code == 401
    owner(c)
    assert c.head(path+'/download').status_code == 200
    r=c.get(path+'/download');assert r.status_code == 200 and r.content.startswith(b'PK')
    assert len(r.content)==record['bytes'] and r.headers['cache-control']=='no-store'
    assert c.request('DELETE',path,json={'confirm':'wrong.zip'}).status_code == 422
    assert store.records()==[record]
    assert c.request('DELETE',path,json={'confirm':record['filename']}).status_code == 204
    assert store.records()==[] and c.get(path+'/download').status_code == 404
    assert c.post('/auth/logout').status_code == 200
    assert c.head(path+'/download').status_code == 401


def test_legacy_injection_never_installs_management_unlock_interceptors():
    from app.services.builtin_injection import admin_notice_code,presets
    assert admin_notice_code()==''
    css,js=presets('drive')
    assert 'stella-admin-required' not in js and '此操作需要管理解锁' not in js


def test_actual_auth_openapi_documents_retirement_not_a_password_success(auth_env):
    c,db,app=auth_env
    from app.openapi_contract import install_openapi_contract
    install_openapi_contract(app)
    schema=c.get('/openapi.json').json()
    for method,path in [('put','/auth/security'),('post','/auth/admin/setup'),('post','/auth/admin/unlock'),('post','/auth/admin/password'),('post','/auth/admin/lock')]:
        operation=schema['paths'][path][method]
        assert '200' not in operation['responses']
        assert '410' in operation['responses'] and '401' in operation['responses']
        assert operation['x-stella-elevation']=='none'
        assert operation['security']==[{'StellaAccessCookie':[]}]


def test_real_saved_drive_token_only_authenticated_owner_can_reveal(auth_env,monkeypatch):
    c,db,app=auth_env
    from app.routers.drive import router
    from app.services.request_security import MainSiteSecurityMiddleware
    app.include_router(router);monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','http://testserver');app.add_middleware(MainSiteSecurityMiddleware)
    token='SYNTHETIC-SAVED-DRIVE-TOKEN'
    db.add(AppConfig(key='external_drive_connection',value=json.dumps({'browser_url':'http://127.0.0.1:5244/drive/openlist','auth_mode':'token','token':token})));db.commit()
    path='/drive/connection/token'
    anonymous=c.post(path);assert anonymous.status_code==401 and token not in anonymous.text
    owner(c)
    assert c.get('/drive/connection').status_code==200 and token not in c.get('/drive/connection').text
    denied=c.post(path,headers={'origin':'https://evil.test'});assert denied.status_code==403 and token not in denied.text
    response=c.post(path,headers={'origin':'http://testserver'})
    assert response.status_code==200 and response.json()=={'token':token}
    assert response.headers['cache-control']=='no-store'
    assert c.post('/auth/logout').status_code==200
    denied=c.post(path);assert denied.status_code==401 and token not in denied.text


@pytest.mark.parametrize('boundary',['anonymous','wrong_owner','revoked','expired'])
def test_every_actual_admin_dependency_route_rejects_invalid_identity_before_business(auth_env,monkeypatch,boundary,record_property):
    import importlib
    from pathlib import Path
    from fastapi import APIRouter
    from fastapi.routing import iter_route_contexts,APIRoute
    from app.openapi_contract import dependency_names
    c,db,app=auth_env
    uid=owner(c)
    if boundary=='anonymous':c.cookies.clear()
    elif boundary=='wrong_owner':
        user=User(username='other',display_name='other',password_hash=hash_password(DAILY),is_admin=True);db.add(user);db.flush()
        session=AuthSession(user_id=user.id,refresh_hash='outsider',remember=True);db.add(session);db.commit()
        c.cookies.clear();c.cookies.set('stella_at',make_access_token(str(user.id),str(session.id)))
    else:
        session=db.query(AuthSession).one()
        if boundary=='revoked':session.revoked=True
        else:session.remember=False;session.last_seen=datetime.now(timezone.utc)-timedelta(hours=1)
        db.commit()
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','http://testserver')
    seen=set()
    for file in sorted((Path(__file__).parents[1]/'app/routers').glob('*.py')):
        if file.stem=='auth' or 'admin_user' not in file.read_text():continue
        module=importlib.import_module('app.routers.'+file.stem)
        for router in vars(module).values():
            if isinstance(router,APIRouter) and id(router) not in seen:
                seen.add(id(router));app.include_router(router)
    records={}
    for route in iter_route_contexts(app.routes):
        if not isinstance(route.original_route,APIRoute):continue
        if 'app.routers.auth.admin_user' not in dependency_names(route.dependant):continue
        for method in route.methods:
            path=route.path_format
            for field in route.dependant.path_params:
                kind=field.field_info.annotation
                value='1' if kind is int else '00000000-0000-4000-8000-000000000001' if kind is UUID else 'fixture'
                path=path.replace('{'+field.name+'}',value)
            records[method,route.path_format]=path
    record_property('route_count',len(records))
    record_property('routes',json.dumps(sorted(method+' '+path for method,path in records)))
    assert len(records)>80, 'All real route/dependency declarations, not a selected family'
    expected=403 if boundary=='wrong_owner' else 401
    for (method,template),path in sorted(records.items()):
        response=c.request(method,path,headers={'origin':'http://testserver'},**({'json':{}} if method not in {'GET','HEAD','OPTIONS'} else {}))
        assert response.status_code==expected,(boundary,method,template,response.status_code,response.text)
