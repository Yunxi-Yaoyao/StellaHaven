"""Real main middleware, auth, ticket and proxy lifecycle on isolated SQLite."""
import json,time
from uuid import uuid4
import pytest
from fastapi import HTTPException
from tests_isolated.test_dual_entry import registry, integration_env as base_integration_env, upstream, PUBLIC,PRIVATE,APP
from tests_isolated.test_owner_admin_security import DAILY


@pytest.fixture
def integration_env(base_integration_env):
    """Extend only this file's reduced SQLite schema for real entry apply.

    Reconcile creates MonitorGroups and scans Nodes (empty here). Adapt JSONB
    only on a private table copy, never mapped columns or a global compiler.
    """
    from sqlalchemy import JSON, MetaData
    from sqlalchemy.dialects.postgresql import JSONB
    from app.models.node import Node
    from app.models.monitor import MonitorGroup
    _, factory, *_ = base_integration_env
    metadata = MetaData()
    for original in (Node.__table__, MonitorGroup.__table__):
        table = original.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    metadata.create_all(factory.kw['bind'])
    return base_integration_env

def test_retired_switch_keeps_same_side_and_explicit_public_policy_retains_ticket_source(integration_env):
    c,f,app,uid,sid,mid,public,cookie,seen=integration_env
    logged=c.post(PRIVATE+'/auth/login',json={'username':'owner','password':DAILY},headers={'Origin':PRIVATE})
    assert logged.status_code==200,logged.text
    assert logged.json()['id']==str(uid)
    # An absent owner row inherits registry capabilities without a GET write.
    from app.models.config import AppConfig
    from app.services import access_entries
    initial_settings=c.get('/config/access-entries').json()['settings']
    assert initial_settings==dict(revision=0,enabled=False,public_origin=PUBLIC,private_origin=PRIVATE)
    with f() as db:
        assert db.get(AppConfig,access_entries.KEY) is None
    inherited=c.post(PRIVATE+'/external-modules/'+mid+'/launch',headers={'Origin':PRIVATE})
    assert inherited.status_code==200,inherited.text
    initial=inherited.json()
    assert initial['target_origin']==APP and initial['source_origin']==PRIVATE
    assert initial['entry_revision']==0 and initial['url']==APP+'/__stella/bootstrap'
    inherited_boot=c.post(initial['url'],data=initial['fields'],headers={'Origin':PRIVATE},follow_redirects=False)
    assert inherited_boot.status_code==303,inherited_boot.text
    inherited_cookie=inherited_boot.headers['set-cookie'].split(';')[0]
    assert c.get(APP+'/echo',headers={'Cookie':inherited_cookie}).status_code==200
    draft=initial_settings|{'enabled':True,'private_origin':PRIVATE}
    checked=c.post('/config/access-entries/check',json=draft)
    assert checked.status_code==200,checked.text
    assert checked.json()['can_apply'] is True
    applied=c.put('/config/access-entries',json=draft|{'checked_digest':checked.json()['digest']})
    assert applied.status_code==200,applied.text
    assert applied.json()['settings']==draft|{'revision':1}
    assert c.get('/config/access-entries').json()['settings']==applied.json()['settings']
    old_response=c.post(PRIVATE+'/external-modules/'+mid+'/launch',headers={'Origin':PRIVATE})
    assert old_response.status_code==200,old_response.text
    old=old_response.json()
    assert old['target_origin']==APP
    assert old['source_origin']==PRIVATE and old['entry_revision']==1
    # Legacy global false no longer overrides the applied private parent.
    draft=c.get('/config/access-entries').json()['settings']|{'enabled':False}
    checked=c.post('/config/access-entries/check',json=draft).json()
    saved=c.put('/config/access-entries',json=draft|{'checked_digest':checked['digest']})
    assert saved.status_code==200,saved.text
    assert saved.json()['settings']==draft|{'revision':2}
    assert c.get('/config/access-entries').json()['settings']==saved.json()['settings']
    same_side_response=c.post(PRIVATE+'/external-modules/'+mid+'/launch',headers={'Origin':PRIVATE})
    assert same_side_response.status_code==200,same_side_response.text
    same_side=same_side_response.json()
    assert same_side['target_origin']==APP
    assert same_side['source_origin']==PRIVATE and same_side['entry_revision']==2
    # Explicit per-website public policy remains supported, without rebinding
    # the previously issued private ticket or server credential target.
    from app.services import integrations as store
    with f() as db,store.edit(db) as config:
        config['modules'][mid]['entry_policy']='public'
    fresh_response=c.post(PRIVATE+'/external-modules/'+mid+'/launch',headers={'Origin':PRIVATE})
    assert fresh_response.status_code==200,fresh_response.text
    fresh=fresh_response.json()
    assert fresh['target_origin']==public
    assert fresh['source_origin']==PRIVATE and fresh['entry_revision']==2
    oldboot=c.post(old['url'],data=old['fields'],headers={'Origin':PRIVATE},follow_redirects=False)
    assert oldboot.status_code==303,oldboot.text
    oldcookie=oldboot.headers['set-cookie'].split(';')[0]
    assert c.get(APP+'/echo',headers={'Cookie':oldcookie}).status_code==200
    newboot=c.post(fresh['url'],data=fresh['fields'],headers={'Origin':PRIVATE},follow_redirects=False)
    assert newboot.status_code==303,newboot.text
    newcookie=newboot.headers['set-cookie'].split(';')[0]
    assert c.get(public+'/echo',headers={'Cookie':newcookie}).status_code==200
    assert c.post(fresh['url'],data=fresh['fields'],headers={'Origin':PUBLIC},follow_redirects=False).status_code in {401,403}
    assert c.get('https://evil.invalid/config/access-entries',headers={'X-Forwarded-Host':'stella.xiya.live'}).status_code==421


def test_pages_grants_pin_actual_source_and_target_across_selection_changes(integration_env,monkeypatch):
    """Real Host/resource and session checks; synthetic project bytes/state only."""
    from app.services import web_project_runtime as runtime
    from app.models.config import AppConfig
    from app.routers.web_project_host import WebProjectHostMiddleware
    from app.services.entry_registry import records
    c,f,app,uid,sid,*_=integration_env
    rows=[dict(service_id=k,**v) for k,v in records().items()]
    rows.append(dict(service_id='web-project-runtime',public='https://pages.test',private='https://pages.p.test'))
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps(rows))
    for m in app.user_middleware:
        if m.cls is WebProjectHostMiddleware:monkeypatch.setitem(m.kwargs,'db_factory',f)
    app.middleware_stack=None
    monkeypatch.setattr(runtime.projects,'read_state',lambda *a:{'epoch':0,'revision':0,'data':{}})
    monkeypatch.setattr(runtime.projects,'read_file',lambda *a:(b'<html><head></head><body>synthetic pages</body></html>','text/html'))
    caps={target:('p' if target=='https://pages.test' else 's')*43 for target in ['https://pages.test','https://pages.p.test']}
    for target,cap in caps.items():
        with f() as db:
            grant=dict(owner=str(uid),root=str(uuid4()),sid=sid,source=PRIVATE,target=target,epoch=0,expires=time.time()+900)
            db.add(AppConfig(key=runtime.key(cap),value=json.dumps(grant)));db.commit()
    draft=c.get('/config/access-entries').json()['settings']|{'enabled':False}
    digest=c.post('/config/access-entries/check',json=draft).json()['digest']
    assert c.put('/config/access-entries',json=draft|{'checked_digest':digest}).status_code==200
    for target,cap in caps.items():
        response=c.get(target+'/p/'+cap+'/index.html')
        assert response.status_code==200,response.text
        assert 'frame-ancestors '+PRIVATE in response.headers['content-security-policy']
        with f() as db:
            runtime.authorize(db,cap,source=PRIVATE)
            with pytest.raises(HTTPException):runtime.authorize(db,cap,source=PUBLIC)
        other='https://pages.p.test' if target=='https://pages.test' else 'https://pages.test'
        assert c.get(other+'/p/'+cap+'/index.html').status_code==403


@pytest.mark.parametrize('identity,status', [('anonymous',401),('foreign',403),('owner',200)])
def test_entry_apply_keeps_real_identity_and_private_schema(integration_env, identity, status):
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.exc import CompileError
    from sqlalchemy.schema import CreateTable
    from app.database import get_db
    from app.models.config import AppConfig
    from app.models.node import Node
    from app.models.monitor import MonitorGroup
    from app.models.user import User, AuthSession
    from app.security import make_access_token
    from app.services import access_entries, entry_monitor_groups, integrations
    c,f,app,uid,sid,mid,*_=integration_env
    assert set(app.dependency_overrides)=={get_db}  # no owner/admin override
    # DDL adaptation stays on the private copy, including after real HTTP apply.
    def unchanged_production_types():
        assert isinstance(Node.__table__.c.interfaces.type,JSONB)
        with pytest.raises(CompileError):
            str(CreateTable(Node.__table__).compile(dialect=sqlite.dialect()))
    unchanged_production_types()
    draft=c.get('/config/access-entries').json()['settings']|{'private_origin':PRIVATE}
    checked=c.post('/config/access-entries/check',json=draft)
    assert checked.status_code==200,checked.text
    assert checked.json()['can_apply'] is True
    token=None
    with f() as db:
        assert db.query(Node).count()==0
        assert db.query(MonitorGroup).count()==0
        before=db.get(AppConfig,integrations.KEY).value
        if identity=='foreign':
            foreign=User(username='foreign',display_name='foreign',is_active=True,is_admin=True)
            db.add(foreign);db.flush()
            session=AuthSession(user_id=foreign.id,refresh_hash='synthetic-foreign',remember=True)
            db.add(session);db.commit()
            token=make_access_token(str(foreign.id),str(session.id))
    if identity!='owner':
        c.cookies.clear()
        if identity=='foreign':
            assert token is not None
            c.cookies.set('stella_at',token,domain='stella.xiya.live',path='/')
        assert c.get('/config/access-entries').status_code==status
        assert c.post('/config/access-entries/check',json=draft).status_code==status
        assert c.post('/external-modules/'+mid+'/launch',headers={'Origin':PUBLIC}).status_code==status
    applied=c.put('/config/access-entries',json=draft|{'checked_digest':checked.json()['digest']})
    assert applied.status_code==status,applied.text
    with f() as db:
        assert db.query(Node).count()==0
        assert db.get(AppConfig,integrations.KEY).value==before
        if identity=='owner':
            assert applied.json()['settings']==draft|{'revision':1}
            assert c.get('/config/access-entries').json()['settings']==applied.json()['settings']
            stored=json.loads(db.get(AppConfig,access_entries.KEY).value)
            assert stored=={'owner_id':str(uid),'settings':draft|{'revision':1}}
            owners=entry_monitor_groups.owners(db)
            assert set(owners)=={'entry:public','entry:private'}
            assert db.query(MonitorGroup).count()==2
            for lane in ('public','private'):
                group=db.get(MonitorGroup,owners['entry:'+lane]['group_id'])
                assert group.stable_uuid==owners['entry:'+lane]['group_uuid']
                assert group.visible is (lane=='public')
        else:
            assert db.get(AppConfig,access_entries.KEY) is None
            assert db.get(AppConfig,entry_monitor_groups.KEY) is None
            assert db.query(MonitorGroup).count()==0
    unchanged_production_types()


def test_explicit_null_private_override_denies_new_launch_without_public_fallback(integration_env):
    from app.models.config import AppConfig
    from app.services import access_entries, integrations
    c, factory, _, uid, _, mid, public, *_ = integration_env
    logged = c.post(PRIVATE+'/auth/login', json={'username':'owner','password':DAILY}, headers={'Origin':PRIVATE})
    assert logged.status_code == 200, logged.text
    draft = c.get('/config/access-entries').json()['settings'] | {'private_origin':None}
    checked = c.post('/config/access-entries/check', json=draft)
    assert checked.status_code == 200 and checked.json()['can_apply'] is True
    saved = c.put('/config/access-entries', json=draft | {'checked_digest':checked.json()['digest']})
    assert saved.status_code == 200, saved.text
    expected = draft | {'revision':1}
    assert saved.json()['settings'] == expected
    assert c.get('/config/access-entries').json()['settings'] == expected
    with factory() as db:
        assert json.loads(db.get(AppConfig,access_entries.KEY).value) == {'owner_id':str(uid),'settings':expected}
        before = db.get(AppConfig,integrations.KEY).value
    denied = c.post(PRIVATE+'/external-modules/'+mid+'/launch', headers={'Origin':PRIVATE})
    assert denied.status_code == 409, denied.text
    assert 'url' not in denied.json()
    assert c.post('https://evil.invalid/external-modules/'+mid+'/launch', headers={'Origin':'https://evil.invalid'}).status_code == 403
    assert c.post(PUBLIC+'/external-modules/'+mid+'/launch', headers={'Origin':'https://evil.invalid'}).status_code == 403
    with factory() as db:
        assert db.get(AppConfig,integrations.KEY).value == before  # no tickets/grants on refusal
        assert json.loads(db.get(AppConfig,access_entries.KEY).value) == {'owner_id':str(uid),'settings':expected}
    launch = c.post(PUBLIC+'/external-modules/'+mid+'/launch', headers={'Origin':PUBLIC})
    assert launch.status_code == 200, launch.text
    info = launch.json()
    assert info['target_origin'] == public and info['source_origin'] == PUBLIC
    assert info['entry_revision'] == 1
    boot = c.post(info['url'], data=info['fields'], headers={'Origin':PUBLIC}, follow_redirects=False)
    assert boot.status_code == 303, boot.text
    cookie = boot.headers['set-cookie'].split(';')[0]
    assert c.get(public+'/echo', headers={'Cookie':cookie}).status_code == 200
    assert c.get(APP+'/echo', headers={'Cookie':cookie}).status_code == 401
