"""v8 management: actual router and owned SQLite only."""
from datetime import datetime, timezone
import pytest
from test_node_monitor_policy import db, node
from test_entry_monitor_groups import tables
from test_monitor_basics_v7 import client_for
from app.models.monitor import Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember
from app.services import monitor as svc, monitor_groups as groups
from app.repositories.config import get_monitors_version


def ordinary(db):
    n = node(db, status='online', last_seen_at=datetime.now(timezone.utc))
    c = client_for(db)
    r = c.post('/monitors/', json=dict(name='owned', type='ping', target='192.168.160.3', node_id=n.id))
    assert r.status_code == 201, r.text
    return c, n, r.json()


def test_hide_keeps_dispatch_history_and_excludes_group_aggregation(db):
    c,n,m = ordinary(db)
    assert m['visible'] is True and m['enabled'] is True and m['effective_enabled'] is True
    g = groups.save_group(db,None,name='owned',child_ids=[m['id']])
    before = get_monitors_version(db)
    r=c.patch(f"/monitors/{m['id']}",json={'visible':False})
    assert r.status_code==200, r.text
    assert r.json()['visible'] is False
    assert [x.id for x in svc.list_monitors_for_node(db,n.id)]==[m['id']]
    g=c.get('/monitors/groups').json()[0]
    assert g['child_ids']==[m['id']] and g['eligible_child_ids']==[]
    assert (g['status'],g['up_count'],g['down_count'])==('down',0,0)
    assert get_monitors_version(db)>before
    assert next(x for x in c.get('/monitors/').json() if x['id']==m['id'])['visible'] is False


def test_disable_and_reenable_preserve_exact_identity_history_and_member_switch(db):
    c,n,m = ordinary(db)
    g=groups.save_group(db,None,name='owned',child_ids=[m['id']])
    obj=db.get(Monitor,m['id']); obj.status='down'; obj.last_check_at=datetime.now(timezone.utc)
    db.add(MonitorCheck(id=41,monitor_id=obj.id,ts=obj.last_check_at,success=False));db.commit()
    uuid=db.get(MonitorGroup,g['id']).stable_uuid
    before=(obj.id,obj.target,obj.last_check_at)
    body={k:g[k] for k in ('name','failure_policy','rotation_seconds')}
    assert c.put(f"/monitors/groups/{g['id']}",json=body|{'enabled':False}).status_code==200
    assert svc.list_monitors_for_node(db,n.id)==[]
    assert c.get('/monitors/').json()[0]['effective_enabled'] is False
    assert db.get(Monitor,obj.id).enabled is True
    assert c.patch(f'/monitors/{obj.id}',json={'enabled':False}).status_code==200
    assert c.put(f"/monitors/groups/{g['id']}",json=body|{'enabled':True}).status_code==200
    assert svc.list_monitors_for_node(db,n.id)==[]
    assert c.patch(f'/monitors/{obj.id}',json={'enabled':True}).status_code==200
    assert [x.id for x in svc.list_monitors_for_node(db,n.id)]==[obj.id]
    assert (obj.id,obj.target,obj.last_check_at)==before
    assert db.get(MonitorGroup,g['id']).stable_uuid==uuid
    assert len(c.get(f'/monitors/{obj.id}/checks').json())==1


def test_automatic_entry_config_excludes_disabled_but_not_hidden(db):
    from test_entry_monitor_groups import source
    from app.services import entry_monitoring as entry
    from app.services.node import get_agent_config
    n=source(db);n.token='isolated';n.status='online';n.last_seen_at=datetime.now(timezone.utc);db.commit()
    from app.services.entry_monitor_groups import reconcile
    reconcile(db,n);db.commit();get_agent_config(db,n.token)
    c=client_for(db)
    obj=db.query(Monitor).filter_by(target='main.example').one()
    assert c.patch(f'/monitors/{obj.id}',json={'visible':False}).status_code==200
    assert {e['entry_id'] for e in entry.manifest(n, db=db)['entries']}=={'public','private'}
    assert c.patch(f'/monitors/{obj.id}',json={'enabled':False}).status_code==200
    assert {e['entry_id'] for e in entry.manifest(n, db=db)['entries']}=={'private'}
    assert c.patch(f'/monitors/{obj.id}',json={'target':'8.8.8.8'}).status_code==400
    get_agent_config(db,n.token)
    assert db.get(Monitor,obj.id).enabled is False


def test_version_failure_rolls_back_monitor_edit(db,monkeypatch):
    c,n,m=ordinary(db)
    before=get_monitors_version(db)
    def fail(*a,**k): raise RuntimeError('injected version failure')
    monkeypatch.setattr('app.repositories.config.bump_monitors_version',fail)
    with pytest.raises(RuntimeError,match='injected'):
        c.patch(f"/monitors/{m['id']}",json={'enabled':False})
    db.rollback();db.expire_all()
    assert db.get(Monitor,m['id']).enabled is True
    assert get_monitors_version(db)==before


def test_disabled_alert_does_not_mutate_firing_state_or_evaluate(db,monkeypatch):
    from app.models.alert import AlertRule
    from app.services import alerts
    c,n,m=ordinary(db)
    db.add(AlertRule(kind='monitor_down',target=str(m['id']),label='owned',enabled=True));db.commit()
    evaluated=[]
    monkeypatch.setattr(alerts,'_evaluate',lambda *a,**k:evaluated.append(a))
    c.patch(f"/monitors/{m['id']}",json={'visible':False})
    alerts.evaluate_monitor(db,m['id']);assert len(evaluated)==1
    c.patch(f"/monitors/{m['id']}",json={'enabled':False})
    alerts.evaluate_monitor(db,m['id']);assert len(evaluated)==1


def test_stale_session_version_never_overwrites_newer_config(db):
    from app.models.config import AppConfig
    from sqlalchemy.orm import Session
    c,n,m=ordinary(db)
    held=db.get(AppConfig,'monitors_version')
    with Session(db.get_bind()) as other:
        other.get(AppConfig,'monitors_version').value='55';other.commit()
    assert held.value!='55'
    assert c.patch(f"/monitors/{m['id']}",json={'visible':False}).status_code==200
    assert get_monitors_version(db)==56


def test_group_failure_and_omitted_flags_preserve_relations_and_switches(db,monkeypatch):
    c,n,m=ordinary(db)
    g=groups.save_group(db,None,name='owned',child_ids=[m['id']],enabled=False,visible=False)
    group=db.get(MonitorGroup,g['id']);uuid=group.stable_uuid
    statements=[]
    from sqlalchemy import event
    def record(conn,cursor,stmt,*args): statements.append(stmt)
    event.listen(db.get_bind(),'before_cursor_execute',record)
    try:
        body={k:g[k] for k in ('name','failure_policy','rotation_seconds')}
        assert c.put(f"/monitors/groups/{g['id']}",json=body).status_code==200
        assert not any('DELETE FROM monitor_group_members' in s for s in statements)
        result=c.get('/monitors/groups').json()[0]
        assert result['enabled'] is False and result['visible'] is False
        def fail(*a,**k): raise RuntimeError('injected version failure')
        monkeypatch.setattr('app.repositories.config.bump_monitors_version',fail)
        with pytest.raises(RuntimeError):c.put(f"/monitors/groups/{g['id']}",json=body|{'enabled':True})
        db.expire_all()
        assert db.get(MonitorGroup,g['id']).enabled is False
        assert db.get(MonitorGroup,g['id']).stable_uuid==uuid
        assert db.query(MonitorGroupMember).one().monitor_id==m['id']
    finally:event.remove(db.get_bind(),'before_cursor_execute',record)


def test_management_gets_have_no_writes_and_flags_are_strict(db):
    c,n,m=ordinary(db)
    version=get_monitors_version(db)
    statements=[]
    from sqlalchemy import event
    def record(conn,cursor,stmt,*args): statements.append(stmt.lstrip().upper())
    event.listen(db.get_bind(),'before_cursor_execute',record)
    try:
        assert c.get('/monitors/').status_code==200
        assert c.get('/monitors/groups').status_code==200
        assert c.get(f"/monitors/{m['id']}/checks").status_code==200
    finally:event.remove(db.get_bind(),'before_cursor_execute',record)
    assert not any(s.startswith(('INSERT','UPDATE','DELETE','CREATE','ALTER')) for s in statements)
    assert c.patch(f"/monitors/{m['id']}",json={'enabled':'false'}).status_code==422
    assert get_monitors_version(db)==version


def test_actual_router_rejects_unauthenticated_management(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.monitor import monitor_router
    from app.database import get_db
    app=FastAPI();app.include_router(monitor_router);app.dependency_overrides[get_db]=lambda:db
    c=TestClient(app)
    assert c.get('/monitors/').status_code==401
    assert c.patch('/monitors/1',json={'enabled':False}).status_code==401
    assert c.put('/monitors/groups/1',json={'name':'x','enabled':False}).status_code==401


def test_dissolve_disabled_group_refreshes_config_and_preserves_children(db):
    c,n,m=ordinary(db)
    g=groups.save_group(db,None,name='stopped',child_ids=[m['id']],enabled=False)
    assert svc.list_monitors_for_node(db,n.id)==[]
    before=get_monitors_version(db)
    groups.remove_group(db,g['id'])
    assert get_monitors_version(db)==before+1
    assert [x.id for x in svc.list_monitors_for_node(db,n.id)]==[m['id']]
    assert db.get(Monitor,m['id']).enabled is True
    assert db.query(MonitorGroupMember).count()==0


def test_dissolve_version_failure_rolls_back_group_and_members(db,monkeypatch):
    c,n,m=ordinary(db)
    g=groups.save_group(db,None,name='stopped',child_ids=[m['id']],enabled=False)
    original=db.get(MonitorGroup,g['id']).stable_uuid
    from app.repositories import config
    def fail(*a,**kw):raise RuntimeError('injected-version')
    monkeypatch.setattr(config,'bump_monitors_version',fail)
    with pytest.raises(RuntimeError,match='injected-version'):
        groups.remove_group(db,g['id'])
    assert db.get(MonitorGroup,g['id']).stable_uuid==original
    assert db.query(MonitorGroupMember).filter_by(group_id=g['id'],monitor_id=m['id']).count()==1
    assert svc.list_monitors_for_node(db,n.id)==[]
