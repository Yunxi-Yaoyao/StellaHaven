"""V11 contract: actual SQLite only, never configured database or startup."""
from datetime import datetime, timezone
import json
import pytest
from test_node_monitor_policy import db, node
from app.models.monitor import Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember
from app.models.config import AppConfig
from app.services import entry_monitor_groups as lifecycle, entry_monitoring as entry
from app.services import entry_registry

@pytest.fixture(autouse=True)
def setup(db, monkeypatch):
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public':'https://main.example', 'private':'https://other.example'}})
    from app.models.task import MtrTask
    from sqlalchemy import Integer
    MtrTask.__table__.create(db.get_bind(),checkfirst=True)
    monkeypatch.setattr(MonitorCheck.__table__.c.id,'type',Integer())
    MonitorCheck.__table__.create(db.get_bind(),checkfirst=True)


def test_empty_bootstrap_stable_groups_and_private_hidden(db):
    lifecycle.bootstrap(db); db.commit()
    from app.services.monitor_groups import list_groups
    groups = list_groups(db)
    assert [g['entry_id'] for g in groups] == ['public','private']
    assert [g['visible'] for g in groups] == [True,False]
    assert all(g['child_ids'] == [] and g['status'] is None and g['down_count'] == g['up_count'] == 0 for g in groups)
    assert [g['availability_reason'] for g in groups] == ['no_connected_nodes','entry_not_configured']
    owners = lifecycle.owners(db)
    private = db.get(MonitorGroup,groups[1]['id']); private.visible = True; private.name = 'renamed'; db.commit()
    lifecycle.bootstrap(db); db.commit()
    assert lifecycle.owners(db) == owners
    assert private.visible and private.name == 'renamed'
    assert db.query(Monitor).count() == 0


def save_origins(db, monkeypatch, private=None):
    from app.services import access_entries
    monkeypatch.setattr(access_entries, 'pinned_owner', lambda _: 'fixture-owner')
    row = db.get(AppConfig, access_entries.KEY)
    value = json.dumps(dict(owner_id='fixture-owner', settings=dict(revision=1,enabled=True,public_origin='https://main.example',private_origin=private)))
    if row is None: db.add(AppConfig(key=access_entries.KEY,value=value))
    else: row.value = value
    db.flush()


def test_pending_config_read_connected_nodes_and_generation_lifecycle(db, monkeypatch):
    from app.services.node import get_agent_config, remove_node
    from app.services.monitor import list_monitors
    lifecycle.bootstrap(db); db.commit()
    pending = [node(db, token=f'token-{i}') for i in range(3)]
    for n in pending: get_agent_config(db,n.token)
    assert db.query(Monitor).count() == 0
    for n in pending:
        n.last_seen_at = datetime.now(timezone.utc); n.status = 'online'
        lifecycle.reconcile(db,n); db.commit()
    assert len(list_monitors(db)) == 3
    assert {m.target for m in db.query(Monitor)} == {'main.example'}
    save_origins(db,monkeypatch,'https://other.example')
    lifecycle.reconcile(db); db.commit()
    assert len(list_monitors(db)) == 6
    owner_before = lifecycle.owners(db)
    private_ids = {m.id for m in db.query(Monitor).filter_by(target='other.example')}
    save_origins(db,monkeypatch,'https://changed.example')
    lifecycle.reconcile(db); db.commit()
    assert len(list_monitors(db)) == 6
    assert {m.target for m in list_monitors(db)} == {'main.example','changed.example'}
    assert private_ids.isdisjoint({m.id for m in list_monitors(db)})
    save_origins(db,monkeypatch,None); lifecycle.reconcile(db); db.commit()
    assert len(list_monitors(db)) == 3
    assert all(m.monitor_id not in private_ids for m in db.query(MonitorGroupMember))
    save_origins(db,monkeypatch,'https://other.example'); lifecycle.reconcile(db); db.commit()
    assert len(list_monitors(db)) == 6
    assert private_ids.isdisjoint({m.id for m in list_monitors(db)})
    n = pending[0]; n.status = 'offline'; db.commit()
    lifecycle.bootstrap(db); db.commit()
    assert len(list_monitors(db)) == 6
    remove_node(db,n.id)
    assert len(list_monitors(db)) == 4
    assert db.query(MonitorGroupMember).count() == 4
    lifecycle.bootstrap(db); db.commit()
    assert len(list_monitors(db)) == 4
    assert {k:(v['group_id'],v['owner_uuid']) for k,v in lifecycle.owners(db).items()} == {k:(v['group_id'],v['owner_uuid']) for k,v in owner_before.items()}


def test_system_crud_blocked_but_metadata_and_manual_work(db):
    from app.services import monitor_groups as groups, monitor as monitors
    from app.schemas.monitor import MonitorCreate
    n = node(db,status='online',last_seen_at=datetime.now(timezone.utc),token='actual')
    lifecycle.bootstrap(db); db.commit()
    system = groups.list_groups(db)[0]; mid = system['child_ids'][0]
    with pytest.raises(ValueError,match='系统'):
        groups.remove_group(db,system['id'])
    with pytest.raises(ValueError,match='系统'):
        groups.create_child(db,system['id'],MonitorCreate(name='bad',node_id=n.id,target='example:443'))
    with pytest.raises(ValueError,match='系统'):
        groups.save_group(db,system['id'],name='bad',child_ids=[])
    with pytest.raises(ValueError,match='自动入口|系统'):
        monitors.remove_monitor(db,mid)
    saved = groups.save_group(db,system['id'],name='renamed',visible=False,enabled=False,failure_policy='all',rotation_seconds=8)
    assert saved['name']=='renamed' and not saved['visible'] and not saved['enabled']
    private = groups.list_groups(db)[1]
    assert groups.save_group(db,private['id'],name='empty renamed')['child_ids']==[]
    with pytest.raises(ValueError,match='至少'):
        groups.save_group(db,None,name='manual',child_ids=[])
    manual = monitors.create_monitor(db,'ordinary','tcp','example:443',60,5,n.id)
    g = groups.save_group(db,None,name='manual',child_ids=[manual.id])
    groups.remove_group(db,g['id']); monitors.remove_monitor(db,manual.id)
    assert db.get(Monitor,mid) is not None


def test_config_and_list_get_do_not_write(db):
    from app.services.node import get_agent_config
    from app.services.monitor_groups import list_groups
    n = node(db,token='pending')
    from sqlalchemy import event
    writes=[]
    def observe(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')): writes.append(statement)
    event.listen(db.get_bind(),'before_cursor_execute',observe)
    try:
        get_agent_config(db,n.token); list_groups(db)
    finally: event.remove(db.get_bind(),'before_cursor_execute',observe)
    assert writes==[]


def client_for(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.monitor import monitor_router, agent_router
    from app.routers.auth import current_user, admin_user
    from app.database import get_db
    app=FastAPI(); app.include_router(monitor_router); app.include_router(agent_router)
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[current_user]=lambda:object()
    app.dependency_overrides[admin_user]=lambda:object()
    return TestClient(app,raise_server_exceptions=True)


def test_http_empty_groups_readonly_actions_and_metadata(db):
    lifecycle.bootstrap(db); db.commit()
    c=client_for(db)
    r=c.get('/monitors/groups'); assert r.status_code==200,r.text
    groups=r.json(); assert len(groups)==2 and groups[0]['status'] is None
    n=node(db,token='valid',status='online',last_seen_at=datetime.now(timezone.utc))
    lifecycle.reconcile(db);db.commit()
    gid=groups[0]['id']; mid=db.query(Monitor).one().id
    assert c.delete(f'/monitors/groups/{gid}').status_code in (400,403)
    assert c.delete(f'/monitors/{mid}').status_code in (400,403)
    assert c.put(f'/monitors/groups/{gid}',json={'name':'system','child_ids':[]}).status_code in (400,403)
    assert c.post(f'/monitors/groups/{gid}/children',json=dict(name='manual',node_id=n.id,type='tcp',target='example:443')).status_code in (400,403)
    r=c.put(f'/monitors/groups/{groups[1]["id"]}',json={'name':'empty changed','visible':True})
    assert r.status_code==200,r.text
    assert r.json()['child_ids']==[] and r.json()['visible']


def test_access_apply_all_nodes_and_atomic_rollback(db,monkeypatch):
    from app.services import access_entries as access
    from app.repositories.config import get_monitors_version
    monkeypatch.setattr(access,'pinned_owner',lambda _:'fixture-owner')
    from app.services import request_security
    monkeypatch.setattr(request_security,'trusted_origins',lambda:{'https://main.example','https://other.example'})
    monkeypatch.setattr(access,'summary',lambda db,actor:access.read(db,actor))
    assert access.read(db)=={'revision':0,'enabled':False,'public_origin':'https://main.example','private_origin':'https://other.example'}
    for i in range(2): node(db,token=f'a{i}',status='offline',last_seen_at=datetime.now(timezone.utc))
    lifecycle.bootstrap(db);db.commit()
    before=get_monitors_version(db)
    settings=access.Settings(revision=0,enabled=True,public_origin='https://main.example',private_origin='https://other.example')
    checked=access.check(db,settings,'fixture-owner')
    assert checked['can_apply']
    incoming=access.ApplyInput(**settings.model_dump(),checked_digest=checked['digest'])
    access.apply(db,incoming,'fixture-owner')
    assert db.query(MonitorGroupMember).count()==4
    assert get_monitors_version(db)>before
    previous=access.read(db); counts=db.query(Monitor).count(); version=get_monitors_version(db)
    clear=access.Settings(**(previous|{'private_origin':None}))
    digest=access.check(db,clear,'fixture-owner')['digest']
    from app.repositories import config
    def fail(*_,**__): raise RuntimeError('injected version failure')
    monkeypatch.setattr(config,'bump_monitors_version',fail)
    with pytest.raises(RuntimeError):access.apply(db,access.ApplyInput(**clear.model_dump(),checked_digest=digest),'fixture-owner')
    assert access.read(db)==previous and db.query(Monitor).count()==counts
    assert db.query(MonitorGroupMember).count()==4 and get_monitors_version(db)==version


def test_authenticated_first_heartbeat_and_real_icmp_history_generation(db,monkeypatch):
    from app.models.node import NodeStatusEvent
    from sqlalchemy import Integer
    monkeypatch.setattr(NodeStatusEvent.__table__.c.id,'type',Integer())
    NodeStatusEvent.__table__.create(db.get_bind(),checkfirst=True)
    c=client_for(db)
    pending=node(db,token='bearer-token')
    assert c.get('/agent/config',headers={'Authorization':'Bearer bearer-token'}).json()['entry_monitoring']['entries']==[]
    assert c.post('/agent/report',json={},headers={'Authorization':'Bearer invalid'}).status_code==401
    assert db.query(Monitor).count()==0
    headers={'Authorization':'Bearer bearer-token'}
    r=c.post('/agent/report',json={'components':{'monitoring':{'ready':True,'types':['ping'],'targets':['192.168.160.3']}}},headers=headers)
    assert r.status_code==200,r.text
    assert db.query(Monitor).count()==1
    version=r.json()['monitors_version']
    assert c.post('/agent/report',json={},headers=headers).json()['monitors_version']==version
    save_origins(db,monkeypatch,'https://other.example');lifecycle.reconcile(db);db.commit()
    config=c.get('/agent/config',headers=headers).json()
    expected=next(e for e in config['entry_monitoring']['entries'] if e['entry_id']=='private')
    ts=datetime.now(timezone.utc).isoformat()
    sample=dict(entry_id='private',version=expected['version'],hostname=expected['hostname'],sampled_at=ts,status='complete',results=[dict(ip='192.168.160.3',family=4,status='up',latency_ms=1.2,loss_pct=0)])
    r=c.post('/agent/report',json={'control_channel':{'icmp':[sample]}},headers=headers)
    assert r.status_code==200,r.text
    assert db.query(MonitorCheck).count()==1
    old=db.query(Monitor).filter_by(target='other.example').one().id
    assert c.post('/agent/report',json={'control_channel':{'icmp':[sample]}},headers=headers).status_code==200
    assert db.query(MonitorCheck).count()==1
    save_origins(db,monkeypatch,None);lifecycle.reconcile(db);db.commit()
    save_origins(db,monkeypatch,'https://other.example');lifecycle.reconcile(db);db.commit()
    new=next(m for m in __import__('app.services.monitor',fromlist=['list_monitors']).list_monitors(db) if m.target=='other.example')
    assert new.id!=old and new.last_check_at is None
    expected2=next(e for e in c.get('/agent/config',headers=headers).json()['entry_monitoring']['entries'] if e['entry_id']=='private')
    assert expected2['version']!=expected['version']
    assert c.post('/agent/report',json={'control_channel':{'icmp':[sample]}},headers=headers).status_code==422
    assert db.query(MonitorCheck).filter_by(monitor_id=old).count()==1
    from app.services.monitor import update_monitor
    with pytest.raises(ValueError,match='归档'):
        update_monitor(db,old,{'name':'history immutable'})
    from app.services.monitor_groups import save_group
    with pytest.raises(ValueError,match='系统'):
        save_group(db,None,name='cannot adopt history',child_ids=[old])


def test_startup_bootstrap_hook_is_explicit():
    import ast
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    tree=ast.parse((root/'main.py').read_text())
    lifespan=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='backup_lifespan')
    assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='bootstrap_entry_groups' for n in ast.walk(lifespan))


def test_upgrade_archives_only_proven_system_members_and_keeps_tombstones(db,monkeypatch):
    from app.services.monitor import list_monitors
    n=node(db,token='old-connected',status='offline',last_seen_at=datetime.now(timezone.utc))
    manual=Monitor(name='same label',node_id=n.id,type='ping',target='other.example',interval=60,timeout=1)
    deleted_id=999
    old=Monitor(name='old system',node_id=n.id,type='ping',target='other.example',interval=60,timeout=1)
    db.add_all([manual,old]);db.flush()
    group=MonitorGroup(name='same label',failure_policy='any',rotation_seconds=0,visible=True)
    db.add(group);db.flush()
    db.add(MonitorGroupMember(group_id=group.id,monitor_id=old.id,position=0))
    owner={'entry:private':dict(purpose=lifecycle.PURPOSE,entry_id='private',group_id=group.id,owner_uuid='exact-owner',attached_ids=[old.id])}
    ledger={entry.logical_key(n,'private'):dict(purpose='management_entry_icmp',logical=True,source_node_id=n.id,entry_id='private',hostname='other.example',monitor_id=old.id),
            'manual-deleted-ledger':dict(purpose='unrelated',monitor_id=deleted_id)}
    db.add_all([AppConfig(key=lifecycle.KEY,value=json.dumps(owner)),AppConfig(key=entry.LEDGER,value=json.dumps(ledger))]);db.commit()
    lifecycle.bootstrap(db);db.commit()
    assert old.id not in {m.id for m in list_monitors(db)}
    assert manual.id in {m.id for m in list_monitors(db)}
    assert db.query(MonitorGroupMember).filter_by(group_id=group.id).count()==0
    assert db.get(MonitorGroup,group.id).visible
    assert json.loads(db.get(AppConfig,entry.LEDGER).value)['manual-deleted-ledger']==ledger['manual-deleted-ledger']
    assert db.get(Monitor,old.id) is not None and db.get(Monitor,deleted_id) is None


@pytest.mark.parametrize('scope,ip,accepted',[
    ({},'8.8.8.8',True),
    ({'targets':['192.168.160.3']},'8.8.8.8',False),
    ({'approved_ranges':['192.168.160.0/24']},'192.168.160.3',True),
    ({'targets':['bad']},'8.8.8.8',False),
    ({'approved_ranges':['192.168.160.1/24']},'192.168.160.3',False),
    ({'targets':None},'8.8.8.8',False),
])
def test_scope_real_http_storage_remains_fail_closed(db,monkeypatch,scope,ip,accepted):
    n=node(db,token='scope-token',status='online',last_seen_at=datetime.now(timezone.utc),components={'monitoring':{'ready':True,'types':['ping'],**scope}})
    lifecycle.bootstrap(db);db.commit()
    c=client_for(db);headers={'Authorization':'Bearer scope-token'}
    config=c.get('/agent/config',headers=headers).json()
    e=config['entry_monitoring']['entries'][0]
    sample=dict(entry_id='public',version=e['version'],hostname=e['hostname'],sampled_at=datetime.now(timezone.utc).isoformat(),status='complete',results=[dict(ip=ip,family=4,status='up',latency_ms=1.,loss_pct=0)])
    r=c.post('/agent/report',json={'control_channel':{'icmp':[sample]}},headers=headers)
    assert r.status_code==(200 if accepted else 422),r.text
    assert db.query(MonitorCheck).count()==int(accepted)


def test_missing_system_group_recreated_not_manual_name_adoption(db):
    lifecycle.bootstrap(db);db.commit()
    owner=lifecycle.owners(db)['entry:private'];gid=owner['group_id']
    db.query(MonitorGroup).filter_by(id=gid).delete();db.commit()
    manual=MonitorGroup(name='其他入口探测');db.add(manual);db.commit()
    lifecycle.bootstrap(db);db.commit()
    new=lifecycle.owners(db)['entry:private']
    assert new['group_id']!=manual.id
    assert db.get(MonitorGroup,new['group_id']) is not None
    assert new['owner_uuid']==owner['owner_uuid']



def test_legacy_per_ip_archive_requires_installation_owner_not_name(db):
    n=node(db,token='old-install',status='offline',last_seen_at=datetime.now(timezone.utc))
    old=Monitor(name='old',node_id=n.id,type='ping',target='192.168.160.3',interval=60,timeout=1)
    manual=Monitor(name='old',node_id=n.id,type='ping',target='192.168.160.3',interval=60,timeout=1)
    db.add_all([old,manual]);db.flush()
    group=MonitorGroup(name=f'{n.name[:57]} → 中心');db.add(group);db.flush()
    db.add(MonitorGroupMember(group_id=group.id,monitor_id=old.id,position=0))
    ownerkey=entry.logical_key(n,'public')[len('logical:'):].rsplit(':',1)[0]
    owners={ownerkey:dict(purpose=lifecycle.PURPOSE,source_node_id=n.id,group_id=group.id,owner_uuid='original-owner',attached_ids=[old.id])}
    ledger={'old-per-ip':dict(purpose='management_entry_icmp',source_node_id=n.id,entry_id='public',ip='192.168.160.3',monitor_id=old.id)}
    db.add_all([AppConfig(key=lifecycle.KEY,value=json.dumps(owners)),AppConfig(key=entry.LEDGER,value=json.dumps(ledger))]);db.commit()
    lifecycle.bootstrap(db);db.commit()
    from app.services.monitor import list_monitors
    assert old.id not in {m.id for m in list_monitors(db)}
    assert manual.id in {m.id for m in list_monitors(db)}
    assert db.get(Monitor,old.id).target=='192.168.160.3'
    assert db.query(MonitorGroupMember).filter_by(group_id=group.id).count()==0
