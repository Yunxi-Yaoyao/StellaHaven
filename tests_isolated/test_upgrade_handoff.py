"""Integration handoff contracts with real owner/session/admin checks."""
import json
import pytest
from tests_isolated.test_owner_admin_security import auth_env, owner, configure, DAILY, ADMIN
from app.models.config import AppConfig
from app.models.user import User


def test_openlist_launch_uses_server_side_token_not_elevation(auth_env, monkeypatch):
    c, db, app = auth_env
    owner(c)
    from app.routers.integrations import router
    from app.services import integrations as service
    monkeypatch.setattr(service, 'get_module', lambda db, mid: {'id':mid,'enabled':True,'mode':'openlist','adapter':'openlist'})
    app.include_router(router)
    db.add(AppConfig(key='external_drive_connection', value=json.dumps({'browser_url':'http://127.0.0.1:5244/drive/openlist','upstream_url':'http://127.0.0.1:5244/drive/openlist','use_proxy':True,'auth_mode':'token','token':'SYNTHETIC-INSTALL-TOKEN'})))
    db.commit()
    r=c.post('/external-modules/test/launch')
    assert r.status_code==200 and r.json()['url']=='/drive/openlist/', r.text
    assert 'SYNTHETIC-INSTALL-TOKEN' not in r.text
    c.post('/auth/admin/setup', json={'user_password':DAILY,'new_password':ADMIN})
    c.post('/auth/admin/unlock', json={'password':ADMIN})
    r=c.post('/external-modules/test/launch')
    assert r.status_code==200 and r.json()['url']=='/drive/openlist/'
    assert 'SYNTHETIC-INSTALL-TOKEN' not in r.text
    c.post('/auth/admin/lock')
    assert c.post('/external-modules/test/launch').json()['url']=='/drive/openlist/'


def test_openlist_manual_launch_keeps_daily_access(auth_env, monkeypatch):
    c,db,app=auth_env
    owner(c)
    from app.routers.integrations import router
    from app.services import integrations as service
    monkeypatch.setattr(service,'get_module',lambda db,mid:{'id':mid,'enabled':True,'mode':'openlist','adapter':'openlist'})
    app.include_router(router)
    db.add(AppConfig(key='external_drive_connection',value=json.dumps({'browser_url':'http://127.0.0.1:5244/drive/openlist','auth_mode':'manual'})));db.commit()
    assert c.post('/external-modules/test/launch').json()['url']=='/drive/openlist/'
    from app.routers.drive import router as drive_router
    app.include_router(drive_router)
    assert c.get('/drive/login-url').status_code == 200
    assert c.get('/drive/login-url').json()['url'] == '/drive/openlist/'


def test_docker_json_contract_has_no_stray_query_and_reaches_service(auth_env, monkeypatch):
    c,db,app=auth_env
    configure(c)
    from app.routers.monitor import node_router, task_svc
    app.include_router(node_router)
    calls=[]
    def fake(db,node_id,action,container):
        calls.append((node_id,action,container))
        raise ValueError('sentinel-no-task-dispatched')
    monkeypatch.setattr(task_svc,'create_docker_ctl',fake)
    r=c.post('/nodes/19/docker-ctl',json={'action':'restart','container':'synthetic-test'})
    assert r.status_code==409 and calls==[(19,'restart','synthetic-test')],r.text
    params=app.openapi()['paths']['/nodes/{node_id}/docker-ctl']['post'].get('parameters',[])
    assert not any(p['name']=='DockerContainerAction' for p in params)
    c.post('/auth/admin/lock')
    assert c.post('/nodes/19/docker-ctl',json={'action':'restart','container':'synthetic-test'}).status_code==403
    assert len(calls)==1


def test_public_background_uses_pinned_owner_not_legacy_admin(auth_env):
    c,db,app=auth_env
    uid=owner(c)
    from uuid import UUID
    pinned=db.get(User,UUID(uid));pinned.home_bg='/assets/homebg/owner.png';pinned.is_admin=False
    db.add(User(username='legacy',display_name='legacy',password_hash='',is_admin=True,home_bg='/assets/homebg/legacy.png'))
    db.commit()
    from app.routers.config import public_router
    app.include_router(public_router)
    assert c.get('/config/site-background').json()['value']=='/assets/homebg/owner.png'


def test_session_records_expose_explicit_utc_timezone(auth_env):
    from datetime import datetime
    from app.models.user import AuthSession
    c, db, app = auth_env
    owner(c)
    row = db.query(AuthSession).first()
    row.created_at = datetime(2026, 10, 5, 20, 44)
    row.last_seen = datetime(2026, 10, 5, 20, 45)
    db.commit()
    r = c.get('/auth/sessions')
    assert r.status_code == 200
    item = r.json()[0]
    assert item['created_at'].endswith('+00:00'), item
    assert item['last_seen'].endswith('+00:00'), item


def test_agent_rollout_can_hold_version_until_helpers_are_seeded(auth_env, monkeypatch):
    c, db, app = auth_env
    from app.routers.monitor import agent_router
    app.include_router(agent_router)
    monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION', '0.6.9')
    assert c.get('/agent/version').json()['version'] == '0.6.9'
    monkeypatch.delenv('STELLA_AGENT_ROLLOUT_VERSION')
    assert c.get('/agent/version').json()['version'] == '0.6.10'


def test_retired_invitation_routes_are_explicit_gone(auth_env):
    c, db, app = auth_env
    for method, path in [('get', '/auth/invites'), ('post', '/auth/invites'), ('post', '/auth/register-invite')]:
        r = getattr(c, method)(path, **({'json': {}} if method == 'post' else {}))
        assert r.status_code == 410, r.text


def test_database_password_has_no_embedded_fallback():
    from app.config import Settings
    assert Settings.model_fields['postgres_password'].default == ''
    explicit = Settings(_env_file=None, postgres_user='fixture', postgres_password='fixture-only', postgres_host='127.0.0.1', postgres_port=9, postgres_db='fixture')
    assert 'fixture-only' in explicit.database_url


def test_builtin_adapters_have_one_managed_injection_authority(auth_env, monkeypatch):
    c, db, app = auth_env
    configure(c)
    from app.services import integrations as service
    from app.routers.integrations import router
    app.include_router(router)
    for adapter in ('openlist', 'immich'):
        item = {'id': 'a'*32, 'mode': 'isolated_proxy', 'adapter': adapter}
        rendered = service.present(item)
        assert rendered['capabilities']['injection'] is False
        expected_site = 'drive' if adapter == 'openlist' else 'gallery'
        assert rendered['capabilities']['managed_settings'].endswith('module='+expected_site)
        monkeypatch.setattr(service,'get_module',lambda db,mid,item=item:item)
        assert c.post('/external-modules/'+item['id']+'/injection/apply').status_code == 409


def test_workspace_bulk_delete_requires_management_grant(auth_env, monkeypatch):
    from app.models.workspace import Workspace
    from uuid import UUID
    c, db, app = auth_env
    configure(c)
    Workspace.__table__.create(db.get_bind())
    uid = UUID(c.get('/auth/me').json()['id'])
    ws = Workspace(name='synthetic deletion guard', user_id=uid)
    db.add(ws); db.commit()
    from app.routers import workspace as routes
    app.include_router(routes.router)
    calls = []
    monkeypatch.setattr(routes, 'delete_workspace', lambda db,wid,force: calls.append((wid,force)) or 'not_empty')
    c.post('/auth/admin/lock')
    r = c.delete('/workspaces/'+str(ws.id)+'?force=true')
    assert r.status_code == 403 and not calls, r.text
    c.post('/auth/admin/unlock', json={'password': ADMIN})
    assert c.delete('/workspaces/'+str(ws.id)+'?force=true').status_code == 409
    assert len(calls) == 1


def test_runtime_openapi_registers_all_new_modules_and_query_budgets(monkeypatch):
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','http://testserver')
    from main import app
    paths=app.openapi()['paths']
    for p in ['/navigation','/external-modules','/search','/timeline','/notes-tools/quick-record','/auth/security','/website-templates','/website-assets/{mid}.js']:
        assert p in paths,p
    params=paths['/nodes/{node_id}/metrics']['get']['parameters']
    limit=next(p for p in params if p['name']=='limit')['schema']
    assert limit.get('minimum')==1 and limit.get('maximum')==5000
