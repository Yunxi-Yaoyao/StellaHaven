"""No DNS or configured database: real DTO/service/HTTP boundaries."""
from datetime import datetime, timezone, timedelta
import json
import pytest
from test_node_monitor_policy import db, node
from app.schemas.monitor import MonitorCreate, MonitorGroupItemCreate, MonitorUpdate
from app.services import monitor as svc, monitor_groups as groups, entry_monitoring as entry
from app.models.monitor import Monitor, MonitorCheck, MonitorGroupMember, MonitorGroup
from app.models.config import AppConfig

BAD = [('tcp','1:1'),('udp','999.1.2.3:53'),('tcp','bad_host:80'),('tcp','::1:443'),
       ('tcp','host:0'),('ping','123'),('ping','host:80'),('ping','https://host'),
       ('ping','host/path'),('ping','ho\nst'),('https','http://host'),
       ('http','http://user:secret@host'),('http','http://1'),('https','https://host:65536'),
       ('http','http://host\\evil'),('tcp','host:4 43'),('tcp','[192.168.1.2]:443'),('ping','fe80::1%eth0')]
GOOD = [('tcp','nas:443'),('tcp','[2001:db8::1]:443'),('ping','2001:db8::1'),
        ('ping','192.168.1.2'),('ping','nas'),('ping','例子.测试'),
        ('https','https://[2001:db8::1]:8443/path?q=1'),('http','http://nas/path')]

@pytest.mark.parametrize('kind,target', BAD)
@pytest.mark.parametrize('dto',[MonitorCreate,MonitorGroupItemCreate])
def test_all_create_dtos_reject_invalid_target(dto, kind, target):
    with pytest.raises(ValueError): dto(name='1', type=kind, target=target, node_id=1)

@pytest.mark.parametrize('kind,target',GOOD)
def test_valid_targets_preserve_numeric_user_name(kind,target):
    assert MonitorCreate(name='1',type=kind,target=target,node_id=1).name == '1'

@pytest.mark.parametrize('path',['direct','child','group','update'])
def test_services_cannot_bypass_dto_validation(db,path):
    n=node(db); m=Monitor(name='old',type='tcp',target='nas:80',node_id=n.id,interval=60,timeout=5)
    g=MonitorGroup(name='g');db.add_all([m,g]);db.commit()
    before=db.query(Monitor).count()
    raw=MonitorCreate.model_construct(name='1',type='tcp',target='1:1',node_id=n.id,interval=60,timeout=5)
    with pytest.raises(ValueError):
        if path=='direct': svc.create_monitor(db,'1','tcp','1:1',60,5,n.id)
        elif path=='child': groups.create_child(db,g.id,raw)
        elif path=='update': svc.update_monitor(db,m.id,{'target':'1:1'})
        else:
            from app.schemas.monitor import MonitorGroupCreate
            data=MonitorGroupCreate.model_construct(name='new',items=[raw],request_key='01234567-1234-1234-1234-012345678901',failure_policy='any',rotation_seconds=0)
            groups.create_group(db,data,session_id='owned')
    db.rollback()
    assert db.query(Monitor).count()==before
    assert db.get(Monitor,m.id).target=='nas:80'

def test_legacy_bad_target_can_be_renamed_then_repaired(db):
    n=node(db,status='online',last_seen_at=datetime.now(timezone.utc))
    m=Monitor(name='1',type='tcp',target='1:1',node_id=n.id,interval=60,timeout=5);db.add(m);db.commit()
    svc.update_monitor(db,m.id,{'name':'2'})
    assert svc.list_monitors(db)[0].status_reason=='invalid_target'
    assert svc.list_monitors_for_node(db,n.id)==[]
    svc.update_monitor(db,m.id,{'target':'nas:80'})
    assert db.get(Monitor,m.id).name=='2'
    assert svc.list_monitors(db)[0].status_reason=='pending'

@pytest.mark.parametrize('kind,target,host,port',[('tcp','[2001:db8::1]:443','2001:db8::1',443),('https','https://[2001:db8::1]:8443/path?q=1','2001:db8::1',8443)])
def test_mtr_uses_same_parser(kind,target,host,port):
    assert svc.mtr_spec(kind,target)==(host,'tcp',port)


def test_pending_restricted_unsupported_and_stale_are_not_target_failures(db,monkeypatch):
    from app.services import entry_registry
    from app.services.entry_monitor_groups import reconcile
    monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':'https://main.example','private':None}})
    n=node(db,status='online',last_seen_at=datetime.now(timezone.utc),components={'monitoring':{'ready':True,'types':['ping'],'targets':['192.168.160.3']}})
    reconcile(db,n);db.commit()
    assert svc.list_monitors(db)[0].status_reason=='scope_pending'
    m=svc.create_monitor(db,'1','tcp','nas:80',60,5,n.id)
    assert next(v for v in svc.list_monitors(db) if v.id==m.id).status_reason=='unsupported'
    n.components={'monitoring':{'ready':True,'types':['tcp'],'targets':['nas']}};db.commit()
    assert next(v for v in svc.list_monitors(db) if v.id==m.id).status_reason=='pending'
    n.components={'monitoring':{'ready':True,'types':['tcp'],'targets':['other']}};db.commit()
    assert next(v for v in svc.list_monitors(db) if v.id==m.id).status_reason=='outside_scope'
    n.components=None;m.status='up';m.last_check_at=datetime.now(timezone.utc)-timedelta(seconds=181);m.last_latency_ms=4;db.commit()
    projected=next(v for v in svc.list_monitors(db) if v.id==m.id)
    assert (projected.status,projected.status_reason,projected.last_latency_ms)==('down','stale',None)
    assert (db.get(Monitor,m.id).status,db.get(Monitor,m.id).last_latency_ms)==('up',4)
    n.status='offline';db.commit()
    assert next(v for v in svc.list_monitors(db) if v.id==m.id).status_reason=='source_offline'


def test_removed_auto_hidden_from_mixed_group_without_identity_history_writes(db,monkeypatch):
    from app.services import entry_registry
    from app.services.entry_monitor_groups import reconcile
    from sqlalchemy import Integer
    monkeypatch.setattr(MonitorCheck.__table__.c.id,'type',Integer())
    MonitorCheck.__table__.create(db.get_bind())
    monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':'https://main.example','private':None}})
    n=node(db,status='online',last_seen_at=datetime.now(timezone.utc));reconcile(db,n);db.commit()
    auto=db.query(Monitor).one()
    assert db.query(MonitorGroup).count()==2  # V11 includes the empty private system group
    g=db.get(MonitorGroup,db.query(MonitorGroupMember).filter_by(monitor_id=auto.id).one().group_id)
    g.name='用户改名的混组'
    # New insertion is forbidden; the direct relation below represents a retained
    # pre-V11 mixed group, not permission to create a new system member via API.
    db.commit()
    with pytest.raises(ValueError,match='系统'):
        groups.create_child(db,g.id,MonitorCreate(name='forbidden',type='tcp',target='nas:80',node_id=n.id))
    assert db.query(Monitor).count()==1
    manual=svc.create_monitor(db,'用户项','tcp','nas:80',60,5,n.id)
    db.add(MonitorGroupMember(group_id=g.id,monitor_id=manual.id,position=1))
    db.add(MonitorCheck(monitor_id=auto.id,ts=datetime.now(timezone.utc),success=True,latency_ms=3));db.commit()
    owner=db.get(AppConfig,'entry_monitoring.groups.v1').value
    ledger=db.get(AppConfig,entry.LEDGER).value
    memberships=[(v.group_id,v.monitor_id,v.position) for v in db.query(MonitorGroupMember)]
    identity=g.stable_uuid
    n.status='removed';db.commit()
    from sqlalchemy import event
    statements=[]
    def only_select(conn,cursor,statement,*args):
        statements.append(statement)
        assert statement.lstrip().upper().startswith('SELECT'),statement
    event.listen(db.get_bind(),'before_cursor_execute',only_select)
    try:
        assert [m.id for m in svc.list_monitors(db)]==[manual.id]
        result=groups.list_groups(db)
        mixed=next(item for item in result if item['id']==g.id)
        assert mixed['child_ids']==[manual.id] and mixed['unknown_count']==0 and mixed['down_count']==1
        assert mixed['name']=='用户改名的混组'
        assert svc.get_monitor(db,auto.id) is auto and len(svc.list_checks(db,auto.id))==1
        assert db.get(AppConfig,'entry_monitoring.groups.v1').value==owner
        assert db.get(AppConfig,entry.LEDGER).value==ledger
        assert db.get(MonitorGroup,g.id).stable_uuid==identity
        assert [(v.group_id,v.monitor_id,v.position) for v in db.query(MonitorGroupMember)]==memberships
    finally:
        event.remove(db.get_bind(),'before_cursor_execute',only_select)
    assert statements
    # Explicit removal reconciliation detaches active automatic relations only.
    reconcile(db,n);db.commit()
    assert db.query(Monitor).count()==2
    assert db.get(Monitor,auto.id) is auto and len(svc.list_checks(db,auto.id))==1
    assert db.query(MonitorGroupMember).filter_by(monitor_id=auto.id).count()==0
    assert [(v.group_id,v.monitor_id,v.position) for v in db.query(MonitorGroupMember)]==[(g.id,manual.id,1)]
    assert db.get(MonitorGroup,g.id).stable_uuid==identity
    archived=next(v for v in json.loads(db.get(AppConfig,entry.LEDGER).value).values() if v['monitor_id']==auto.id)
    assert archived['archived']=='node_removed'
    before=(db.get(AppConfig,entry.LEDGER).value,db.get(AppConfig,'entry_monitoring.groups.v1').value)
    reconcile(db,n);db.commit()
    assert (db.get(AppConfig,entry.LEDGER).value,db.get(AppConfig,'entry_monitoring.groups.v1').value)==before


def test_real_router_rejects_all_bad_inputs_and_preserves_legacy_identity(db,monkeypatch):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from app.routers.monitor import monitor_router
    from app.routers.auth import current_user,admin_user
    from app.database import get_db
    from types import SimpleNamespace
    app=FastAPI();app.include_router(monitor_router)
    app.dependency_overrides[get_db]=lambda:db
    def signed(request:Request):
        request.state.auth_session=SimpleNamespace(id='owned');return object()
    app.dependency_overrides[current_user]=signed;app.dependency_overrides[admin_user]=signed
    n=node(db,status='online',last_seen_at=datetime.now(timezone.utc))
    m=Monitor(name='1',type='tcp',target='1:1',node_id=n.id,interval=60,timeout=5)
    g=MonitorGroup(name='g');db.add_all([m,g]);db.commit();uuid=g.stable_uuid
    client=TestClient(app)
    for kind,target in BAD:
        data=dict(name='1',type=kind,target=target,node_id=n.id)
        for path in ['/monitors/',f'/monitors/groups/{g.id}/children']:
            response=client.post(path,json=data);assert response.status_code==422,response.text
        response=client.post('/monitors/groups',json=dict(name='new',items=[data],request_key='01234567-1234-1234-1234-012345678901'))
        assert response.status_code==422,response.text
        response=client.patch(f'/monitors/{m.id}',json={'type':kind,'target':target})
        assert response.status_code==422,response.text
    assert client.post(f'/monitors/{m.id}/mtr').status_code==400
    assert client.patch(f'/monitors/{m.id}',json={'target':'1:1'}).status_code==400
    response=client.patch(f'/monitors/{m.id}',json={'name':'2'})
    assert response.status_code==200,response.text
    assert response.json()['status_reason']=='invalid_target'
    response=client.patch(f'/monitors/{m.id}',json={'target':'nas:80'})
    assert response.status_code==200 and response.json()['status_reason']=='pending'
    assert db.query(Monitor).count()==1 and db.get(MonitorGroup,g.id).stable_uuid==uuid
    assert client.post('/monitors/',json=dict(name='1',type='tcp',target='nas:80',node_id=n.id)).status_code==201


def test_target_edit_does_not_reuse_previous_health_or_delete_history(db,monkeypatch):
    from sqlalchemy import Integer
    monkeypatch.setattr(MonitorCheck.__table__.c.id,'type',Integer());MonitorCheck.__table__.create(db.get_bind())
    n=node(db,status='online',last_seen_at=datetime.now(timezone.utc))
    m=svc.create_monitor(db,'1','tcp','nas:80',60,5,n.id)
    m.status='up';m.last_check_at=datetime.now(timezone.utc);m.last_latency_ms=4
    db.add(MonitorCheck(monitor_id=m.id,ts=m.last_check_at,success=True,latency_ms=4));db.commit()
    svc.update_monitor(db,m.id,{'target':'nas:81'})
    assert (svc.list_monitors(db)[0].status, svc.list_monitors(db)[0].status_reason)==('down','pending')
    assert svc.list_monitors(db)[0].status_reason=='pending'
    assert len(svc.list_checks(db,m.id))==1
