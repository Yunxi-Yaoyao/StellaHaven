"""Real SQLite/router regressions. No configured DB, network or service startup."""
from datetime import datetime, timezone, timedelta
import json
import pytest
from sqlalchemy import Integer
from test_node_monitor_policy import db, node
from app.models.monitor import Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember
from app.models.config import AppConfig
from app.services import node_monitor_policy as policy, entry_monitoring as entry
from app.repositories.config import get_monitors_version


def seeded(db, monkeypatch):
    from app.services import entry_registry
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public': 'https://center.example', 'private': None}})
    monkeypatch.setattr(MonitorCheck.__table__.c.id, 'type', Integer())
    MonitorCheck.__table__.create(db.get_bind())
    source=node(db,'source','192.168.160.2',status='online',token='isolated-token',last_seen_at=datetime.now(timezone.utc),components={'monitoring':{'ready':True,'types':['ping'],'targets':['192.168.160.3','192.168.160.4']}})
    target=node(db,'target','192.168.160.3')
    policy.update(db,dict(revision=0,enabled=True,source_node_id=source.id,host_node_id=None,interval=60))
    item=db.query(Monitor).one()
    item.status='up';item.last_check_at=datetime.now(timezone.utc)-timedelta(days=1);item.last_latency_ms=3
    group=MonitorGroup(name='retained group');db.add(group);db.flush()
    db.add(MonitorGroupMember(group_id=group.id,monitor_id=item.id,position=0))
    db.add(MonitorCheck(monitor_id=item.id,ts=item.last_check_at,success=True,latency_ms=3,loss_pct=0));db.commit()
    entry.retire_legacy(db,source.id);db.commit()
    return source,target,item,group


def client_for(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.monitor import agent_router, monitor_router, node_router
    from app.routers.auth import current_user, admin_user
    from app.database import get_db
    app=FastAPI();app.include_router(agent_router);app.include_router(monitor_router);app.include_router(node_router)
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[current_user]=lambda:object()
    app.dependency_overrides[admin_user]=lambda:object()
    return TestClient(app)


def test_retired_entry_source_keeps_valid_node_probe_identity_and_router_config(db,monkeypatch):
    source,target,item,group=seeded(db,monkeypatch)
    identity=(item.id,item.name,item.target,item.last_check_at,item.status,group.stable_uuid)
    assert policy.read(db)['managed'][0]['paused'] is False
    client=client_for(db)
    payload=client.get('/agent/config',headers={'Authorization':'Bearer isolated-token'})
    assert payload.status_code==200,payload.text
    assert [(m['id'],m['target']) for m in payload.json()['monitors']]==[(item.id,target.host)]
    assert (item.id,item.name,item.target,item.last_check_at,item.status,group.stable_uuid)==identity
    assert db.query(MonitorCheck).count()==1
    assert db.query(MonitorGroupMember).filter_by(group_id=group.id).one().monitor_id==item.id
    assert entry.retired_sources(db)=={str(source.id)}
    # Entry-managed probes remain exclusive to the bounded entry scheduler.
    assert entry.managed_ids(db).isdisjoint({m.id for m in policy.dispatched(db,db.query(Monitor).all())})


def test_reconcile_retired_source_creates_new_node_and_invalidates_cached_config_once(db,monkeypatch):
    source,target,item,group=seeded(db,monkeypatch)
    client=client_for(db)
    old=get_monitors_version(db)
    original_policy=db.get(AppConfig,policy.KEY).value
    response=client.post('/agent/report',headers={'Authorization':'Bearer isolated-token'},json={'components':source.components})
    assert response.status_code==200,response.text
    assert response.json()['monitors_version']>old
    assert db.get(AppConfig,policy.KEY).value==original_policy
    refreshed=response.json()['monitors_version']
    assert [m['id'] for m in client.get('/agent/config',headers={'Authorization':'Bearer isolated-token'}).json()['monitors']]==[item.id]
    # A distinct DB session sees the durable receipt, not a process/RAM flag.
    from sqlalchemy.orm import Session
    components=source.components
    db.commit()
    with Session(db.get_bind()) as restarted:
        fresh_client=client_for(restarted)
        response=fresh_client.post('/agent/report',headers={'Authorization':'Bearer isolated-token'},json={'components':components})
        assert response.status_code==200,response.text
        assert response.json()['monitors_version']==refreshed
        read=fresh_client.get('/nodes/monitoring-policy')
        assert read.status_code==200,read.text
        assert read.json()['managed'][0]['paused'] is False
        assert 'dispatch_revision' not in read.json()
    db.expire_all()
    extra=node(db,'new target','192.168.160.4')
    policy.reconcile(db)
    assert db.query(Monitor).filter_by(target=extra.host,node_id=source.id).count()==1
    assert get_monitors_version(db)>refreshed


@pytest.mark.parametrize('success',[True,False])
def test_resumed_id_accepts_authenticated_fixture_samples_without_replacing_history(db,monkeypatch,success):
    source,target,item,group=seeded(db,monkeypatch)
    client=client_for(db)
    payload={'monitor_id':item.id,'ts':datetime.now(timezone.utc).isoformat(),'success':success,'latency_ms':2 if success else None,'loss_pct':0 if success else 100}
    response=client.post('/agent/monitor-check',headers={'Authorization':'Bearer isolated-token'},json=payload)
    assert response.status_code==200,response.text
    projected=next(m for m in client.get('/monitors/').json() if m['id']==item.id)
    assert (projected['status'],projected['status_reason'])==('up' if success else 'down','healthy' if success else 'failure')
    assert db.query(MonitorCheck).filter_by(monitor_id=item.id).count()==2
    assert db.query(MonitorCheck).filter_by(monitor_id=item.id).order_by(MonitorCheck.ts).first().success is True
    assert (db.get(Monitor,item.id).target,db.get(MonitorGroup,group.id).stable_uuid)==(target.host,group.stable_uuid)


@pytest.mark.parametrize('invalid',['disabled','suppressed','removed','changed','foreign_source','wrong_type','self','no_capability','outside_scope','malformed_scope','unsafe','source_changed','source_offline','missing','entry_owned'])
def test_resumed_policy_keeps_all_identity_and_permission_negative_controls(db,monkeypatch,invalid):
    source,target,item,_=seeded(db,monkeypatch)
    state=policy._load(db)
    if invalid=='disabled':state['enabled']=False
    if invalid=='suppressed':state['managed'][str(target.id)]['suppressed']=True
    if invalid=='removed':target.status='removed'
    if invalid=='changed':target.host='192.168.160.9'
    if invalid=='foreign_source':item.node_id=target.id
    if invalid=='wrong_type':item.type='tcp'
    if invalid=='self':state['managed'][str(target.id)]['target_node_id']=source.id;item.target=source.host
    if invalid=='no_capability':source.components={'monitoring':{'ready':True,'types':[]}}
    if invalid=='outside_scope':source.components={'monitoring':{'ready':True,'types':['ping'],'targets':[]}}
    if invalid=='malformed_scope':source.components={'monitoring':{'ready':True,'types':['ping'],'targets':[target.host,3]}}
    if invalid=='unsafe':target.host='127.0.0.1';item.target=target.host
    if invalid=='source_changed':state['source_node_id']=target.id
    if invalid=='source_offline':source.status='offline'
    if invalid=='missing':db.delete(item)
    if invalid=='entry_owned':db.add(AppConfig(key=entry.LEDGER,value=json.dumps({'old':{'monitor_id':item.id}})))
    policy._save(db,state);db.commit()
    assert policy.dispatched(db,[item])==[]
    assert policy.read(db)['managed'][0]['paused'] is True
    assert db.query(MonitorCheck).count()==1
