"""Fifth-round behavior contracts; isolated SQLite, no configured application."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
import pytest
from test_entry_monitor_groups import tables, source, sample
from test_node_monitor_policy import db, node
from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember, MonitorCheck
from app.models.config import AppConfig
from app.services import entry_monitoring as entry
from app.services.entry_monitor_groups import reconcile


def connected(db, n=None):
    # Only these post-heartbeat scenarios connect locally; shared source stays pending.
    n = source(db) if n is None else n
    n.status = 'online'; n.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return n


def test_entries_exist_before_samples_and_nodes_share_entry_groups(db):
    first = source(db)
    reconcile(db, first); db.commit()
    groups = db.query(MonitorGroup).order_by(MonitorGroup.id).all()
    assert [g.name for g in groups] == ['默认入口探测', '其他入口探测']
    assert db.query(Monitor).count() == db.query(MonitorGroupMember).count() == 0
    connected(db, first); reconcile(db, first); db.commit()
    assert [m.target for m in db.query(Monitor).order_by(Monitor.id)] == ['main.example', 'other.example']
    assert all(m.last_check_at is None and m.status == 'unknown' for m in db.query(Monitor))
    second = node(db, 'second', token='second-installation')
    reconcile(db, second); db.commit()
    assert db.query(Monitor).count() == 2  # pending second node does not participate
    connected(db, second); reconcile(db, second); db.commit()
    assert db.query(MonitorGroup).count() == 2
    assert db.query(Monitor).count() == 4
    assert [db.query(MonitorGroupMember).filter_by(group_id=g.id).count() for g in groups] == [2, 2]
    before = [(m.id, m.target) for m in db.query(Monitor)]
    reconcile(db, first); db.commit()
    assert [(m.id, m.target) for m in db.query(Monitor)] == before


def test_multiple_ip_samples_update_one_stable_history_and_keep_per_ip_evidence(db):
    n = connected(db); reconcile(db, n); db.commit()
    mid = db.query(Monitor).filter_by(target='main.example').one().id
    incoming = sample(n)
    incoming.icmp[0].results.append(incoming.icmp[0].results[0].model_copy(update={'ip':'192.168.160.4','latency_ms':3.0}))
    n.components = {'monitoring':{'ready':True,'types':['ping'],'targets':['192.168.160.3','192.168.160.4']}}
    db.commit()
    entry.save_channel(db, n, incoming); db.commit()
    assert db.query(Monitor).count() == 2
    check = db.query(MonitorCheck).one()
    assert check.monitor_id == mid and check.success and check.latency_ms == 2.1
    assert len(n.control_channel['icmp'][0]['results']) == 2
    incoming.icmp[0].sampled_at += timedelta(seconds=1)
    incoming.icmp[0].results = [incoming.icmp[0].results[1]]
    entry.save_channel(db, n, incoming); db.commit()
    assert db.query(Monitor).count() == 2
    assert {c.monitor_id for c in db.query(MonitorCheck)} == {mid}


def test_specific_facts_never_count_missing_samples_as_normal(db):
    from app.services.monitor import list_monitors
    from app.services.monitor_groups import list_groups
    n = source(db); n.status = 'online'; n.last_seen_at = datetime.now(timezone.utc)
    reconcile(db, n); db.commit()
    assert {m.status_reason for m in list_monitors(db)} == {'scope_pending'}
    entry.save_channel(db, n, sample(n, status='dns_error')); db.commit()
    m = next(m for m in list_monitors(db) if m.target == 'main.example')
    assert m.status == 'down' and m.status_reason == 'dns_error'
    assert list_groups(db)[0]['up_count'] == 0
    entry.save_channel(db, n, sample(n)); db.commit()
    assert next(m for m in list_monitors(db) if m.target == 'main.example').status == 'up'
    n.last_seen_at = datetime.now(timezone.utc)-timedelta(minutes=10); db.commit()
    assert {m.status_reason for m in list_monitors(db)} == {'source_offline'}


def test_atomic_creation_rolls_back_invalid_second_item_and_receipt_is_bounded(db):
    from app.services.monitor_groups import create_group
    from app.schemas.monitor import MonitorGroupCreate
    n = source(db)
    def payload(nid):
        return MonitorGroupCreate(name='new', items=[dict(name='one', type='ping', target='one.example', node_id=n.id),
            dict(name='two', type='tcp', target='two.example:443', node_id=nid)], request_key='11111111-1111-4111-8111-111111111111')
    with pytest.raises(ValueError, match='节点'):
        create_group(db, payload(999), session_id='fixture-session')
    assert db.query(MonitorGroup).count() == db.query(Monitor).count() == 0
    result = create_group(db, payload(n.id), session_id='fixture-session')
    assert len(result['child_ids']) == 2
    assert create_group(db, payload(n.id), session_id='fixture-session')['id'] == result['id']
    assert db.query(Monitor).count() == 2
    changed = payload(n.id); changed.name = 'conflicting'
    with pytest.raises(ValueError, match='请求'):
        create_group(db, changed, session_id='fixture-session')
    from app.services.monitor_groups import creation_receipt
    assert creation_receipt(db, payload(n.id).request_key, 'other-session') is None
    assert creation_receipt(db, payload(n.id).request_key, 'fixture-session')['group_id'] == result['id']
    assert len(db.get(AppConfig, 'monitor_group.create_receipts.v1').value) < 4096


def test_http_atomic_create_readback_receipt_and_one_item_archive(db):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.routers.monitor import monitor_router
    from app.routers.auth import current_user, admin_user
    from app.database import get_db
    from app.services.backup_projection import project_monitor_tables, restore_monitor_groups
    app = FastAPI(); app.include_router(monitor_router)
    app.dependency_overrides[get_db] = lambda: db
    def authenticated(request: Request):
        request.state.auth_session = SimpleNamespace(id='isolated-session')
        return object()
    app.dependency_overrides[current_user] = authenticated
    app.dependency_overrides[admin_user] = lambda: object()
    client = TestClient(app); n = source(db)
    body = dict(name='one item', items=[dict(name='one', type='ping', target='one.example', node_id=n.id)], request_key='22222222-2222-4222-8222-222222222222')
    response = client.post('/monitors/groups', json=body)
    assert response.status_code == 201, response.text
    group = response.json()
    assert client.get('/monitors/groups/receipts/'+body['request_key']).json() == {'group_id':group['id'],'monitor_ids':group['child_ids']}
    assert client.post('/monitors/groups', json=body).json()['id'] == group['id']
    assert client.post('/monitors/groups', json=body | {'items':[]}).status_code == 422
    assert client.put('/monitors/groups/'+str(group['id']), json=dict(name='renamed',child_ids=group['child_ids'])).status_code == 200
    tables = {'monitors':[{'id':group['child_ids'][0]}]}
    project_monitor_tables(db, tables)
    assert len(tables['monitor_groups']) == 1
    assert tables['monitor_groups'][0]['stable_uuid'] == db.get(MonitorGroup, group['id']).stable_uuid
    restore_monitor_groups(db, tables); db.commit()
    assert db.query(MonitorGroup).count() == 1


@pytest.mark.parametrize('customized', [False, True])
def test_legacy_group_migration_preserves_history_custom_names_manual_and_tombstones(db, customized):
    from uuid import uuid4
    from app.services.entry_monitor_groups import KEY, PURPOSE
    n = connected(db)
    old = Monitor(name='user probe name',node_id=n.id,type='ping',target='192.168.160.3',interval=60,timeout=1)
    manual = Monitor(name='manual',node_id=n.id,type='tcp',target='owned:443',interval=60,timeout=5)
    g = MonitorGroup(name='my renamed group' if customized else 'owned → 中心')
    db.add_all([old, manual, g]); db.flush()
    db.add(MonitorGroupMember(group_id=g.id, monitor_id=old.id, position=0))
    if customized: db.add(MonitorGroupMember(group_id=g.id, monitor_id=manual.id, position=1))
    owner_uuid = str(uuid4())
    # Positive adoption fixture: original v1 reconcile (a75755c) keyed ownership
    # by node ID AND installation hash, never by name or a bare node ID.
    owner_key = f'{n.id}:' + hashlib.sha256((n.token or str(n.created_at)).encode()).hexdigest()
    db.add(AppConfig(key=KEY, value=json.dumps({owner_key:dict(purpose=PURPOSE,owner_uuid=owner_uuid,source_node_id=n.id,group_id=g.id,attached_ids=[old.id])})))
    db.add(AppConfig(key=entry.LEDGER,value=json.dumps({'old-ip':dict(purpose='management_entry_icmp',source_node_id=n.id,entry_id='public',address_version='oldversion',ip=old.target,hostname='main.example',monitor_id=old.id)})))
    db.add(MonitorCheck(monitor_id=old.id,ts=datetime.now(timezone.utc),success=True,latency_ms=2,loss_pct=0)); db.commit()
    gid, mid, identity = g.id, old.id, g.stable_uuid
    history = [(c.monitor_id, c.ts, c.success, c.latency_ms, c.loss_pct) for c in db.query(MonitorCheck)]
    reconcile(db, n); db.commit()
    assert db.query(MonitorCheck).one().monitor_id == mid
    assert db.get(Monitor, mid).name == 'user probe name'
    # V11 archives an intact per-IP generation; never rewrites it into logical history.
    assert db.get(Monitor, mid).target == '192.168.160.3'
    current = db.query(Monitor).filter_by(target='main.example').one()
    cid = current.id
    assert cid != mid and current.last_check_at is None and current.status == 'unknown'
    assert db.query(MonitorCheck).filter_by(monitor_id=cid).count() == 0
    member = db.query(MonitorGroupMember).filter_by(monitor_id=mid).first()
    if customized:
        assert member is not None
        assert member.group_id == gid
        assert db.get(MonitorGroup,gid).name == 'my renamed group'
        assert db.query(MonitorGroupMember).filter_by(monitor_id=manual.id).one().group_id == gid
    else:
        assert member is None
    assert db.get(MonitorGroup,gid).stable_uuid == identity
    assert json.loads(db.get(AppConfig,KEY).value)[owner_key]['owner_uuid'] == owner_uuid
    assert [(c.monitor_id, c.ts, c.success, c.latency_ms, c.loss_pct) for c in db.query(MonitorCheck)] == history
    from app.services.monitor import remove_monitor
    from app.models.task import MtrTask
    MtrTask.__table__.create(db.get_bind(),checkfirst=True)
    with pytest.raises(ValueError, match='自动入口|系统'):
        remove_monitor(db,cid)
    # Retain the original persisted-deletion negative control, without API permission.
    db.query(MonitorGroupMember).filter_by(monitor_id=mid).delete(); db.delete(db.get(Monitor,mid)); db.commit()
    reconcile(db,n); db.commit()
    assert db.get(Monitor,mid) is None
    assert db.query(Monitor).filter_by(target='main.example').one().id == cid
    db.query(MonitorGroupMember).filter_by(monitor_id=cid).delete(); db.delete(db.get(Monitor,cid)); db.commit()
    reconcile(db,n); db.commit()
    assert db.query(Monitor).filter_by(target='main.example').count() == 0
    assert json.loads(db.get(AppConfig,entry.LEDGER).value)[entry.logical_key(n,'public')]['monitor_id'] == cid
    assert [(c.monitor_id, c.ts, c.success, c.latency_ms, c.loss_pct) for c in db.query(MonitorCheck)] == history
    # A deleted ordinary probe is not resurrected by any later system reconciliation.
    manual_id = manual.id
    remove_monitor(db,manual_id); reconcile(db,n); db.commit()
    assert db.get(Monitor,manual_id) is None


def test_no_name_takeover_no_empty_cards_or_resurrection(db):
    from app.services.monitor_groups import list_groups, remove_group
    n = source(db)
    manual = MonitorGroup(name='默认入口探测'); db.add(manual); db.commit()
    reconcile(db,n); db.commit()
    assert db.query(MonitorGroupMember).filter_by(group_id=manual.id).count() == 0
    auto = next(g for g in list_groups(db) if g['name']=='默认入口探测')
    assert auto['id'] != manual.id
    from app.services.entry_monitor_groups import owners
    identity = db.get(MonitorGroup,auto['id']).stable_uuid
    ownership = owners(db)
    with pytest.raises(ValueError, match='系统'):
        remove_group(db,auto['id'])
    reconcile(db,n); db.commit()
    assert db.get(MonitorGroup,auto['id']).stable_uuid == identity
    assert owners(db) == ownership
    assert {g['id'] for g in list_groups(db)} == {v['group_id'] for v in ownership.values()}
    assert all(g['id'] != manual.id for g in list_groups(db))
    assert db.query(Monitor).count() == 0  # empty fixed groups are not fabricated samples


def test_legacy_deleted_group_does_not_resurrect_unsampled_entries(db):
    from app.services.entry_monitor_groups import KEY, PURPOSE
    from uuid import uuid4
    n=source(db)
    tombstone=dict(purpose=PURPOSE,owner_uuid=str(uuid4()),source_node_id=n.id,group_id=999,attached_ids=[])
    db.add(AppConfig(key=KEY,value=json.dumps({'old':tombstone})));db.commit()
    reconcile(db,n);db.commit()
    assert db.query(MonitorGroup).count()==2
    assert db.get(MonitorGroup,999) is None
    assert db.query(Monitor).count()==db.query(MonitorGroupMember).count()==0
    assert json.loads(db.get(AppConfig,KEY).value)['old']==tombstone
    before=db.get(AppConfig,KEY).value
    reconcile(db,n);db.commit()
    assert db.get(AppConfig,KEY).value==before


def test_scope_revocation_cannot_leave_an_old_logical_sample_green(db):
    from app.services.monitor import list_monitors
    n=connected(db);reconcile(db,n);db.commit()
    entry.save_channel(db,n,sample(n));db.commit()
    assert next(m for m in list_monitors(db) if m.target=='main.example').status=='up'
    n.components={'monitoring':{'ready':True,'types':['ping'],'targets':['192.168.160.200']}};db.commit()
    monitor=next(m for m in list_monitors(db) if m.target=='main.example')
    assert monitor.status=='down' and monitor.status_reason=='outside_scope'


def test_changed_entry_version_keeps_logical_id_and_history(db, monkeypatch):
    from app.services import entry_registry, access_entries
    from app.services.monitor import list_monitors
    n=connected(db);reconcile(db,n);db.commit()
    mid=db.query(Monitor).filter_by(target='main.example').one().id
    original=sample(n)
    entry.save_channel(db,n,original);db.commit()
    history=[(c.monitor_id,c.ts,c.success,c.latency_ms,c.loss_pct) for c in db.query(MonitorCheck)]
    from app.services.entry_monitor_groups import owners
    identity=owners(db)
    monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':'https://changed.example','private':'https://other.example'}})
    reconcile(db,n);db.commit()
    # Deployment records alone cannot overwrite an already applied owner selection.
    assert db.query(Monitor).filter_by(target='main.example').one().id==mid
    assert db.query(Monitor).filter_by(target='changed.example').count()==0
    applied=db.get(AppConfig,access_entries.KEY)
    settings=json.loads(applied.value)
    settings['settings']['public_origin']='https://changed.example'
    settings['settings']['revision']+=1
    applied.value=json.dumps(settings);db.commit()
    reconcile(db,n);db.commit()
    current=db.query(Monitor).filter_by(target='changed.example').one()
    assert current.id!=mid and current.last_check_at is None
    assert db.get(Monitor,mid).target=='main.example'
    assert mid not in {m.id for m in list_monitors(db)}
    assert current.id in {m.id for m in list_monitors(db)}
    assert db.query(MonitorGroupMember).filter_by(monitor_id=mid).count()==0
    assert [(c.monitor_id,c.ts,c.success,c.latency_ms,c.loss_pct) for c in db.query(MonitorCheck)]==history
    fresh=sample(n)
    assert fresh.icmp[0].version!=original.icmp[0].version
    with pytest.raises(ValueError,match='stale entry manifest'):
        entry.save_channel(db,n,original)
    entry.save_channel(db,n,sample(n));db.commit()
    assert db.query(MonitorCheck).filter_by(monitor_id=mid).count()==1
    assert db.query(MonitorCheck).filter_by(monitor_id=current.id).count()==1
    assert {k:(v['group_id'],v['group_uuid'],v['owner_uuid']) for k,v in owners(db).items()}=={k:(v['group_id'],v['group_uuid'],v['owner_uuid']) for k,v in identity.items()}
    assert [(c.monitor_id,c.ts,c.success,c.latency_ms,c.loss_pct) for c in db.query(MonitorCheck).filter_by(monitor_id=mid)]==history


def test_multi_ip_legacy_group_migrates_once_without_duplicate_cards_or_erasing_history(db):
    from app.services.entry_monitor_groups import KEY, PURPOSE
    from app.services.monitor import list_monitors
    from uuid import uuid4
    n=source(db);g=MonitorGroup(name='owned → 中心');db.add(g);db.flush()
    state={};ids=[]
    for i,ip in enumerate(['192.168.160.3','192.168.160.4']):
        m=Monitor(name='legacy '+ip,node_id=n.id,type='ping',target=ip,interval=60,timeout=1)
        db.add(m);db.flush();ids.append(m.id)
        db.add(MonitorGroupMember(group_id=g.id,monitor_id=m.id,position=i))
        db.add(MonitorCheck(monitor_id=m.id,ts=datetime.now(timezone.utc),success=True,latency_ms=2,loss_pct=0))
        state[ip]=dict(purpose='management_entry_icmp',source_node_id=n.id,entry_id='public',address_version='old',ip=ip,hostname='main.example',monitor_id=m.id)
    db.add(AppConfig(key=entry.LEDGER,value=json.dumps(state)))
    # Same-installation v1 receipt makes this a positive migration control;
    # unproven 'old' receipts remain negative controls in test_entry_monitor_migration.
    owner_key = f'{n.id}:' + hashlib.sha256((n.token or str(n.created_at)).encode()).hexdigest()
    db.add(AppConfig(key=KEY,value=json.dumps({owner_key:dict(purpose=PURPOSE,owner_uuid=str(uuid4()),source_node_id=n.id,group_id=g.id,attached_ids=ids)})));db.commit()
    reconcile(db,n);db.commit();before=db.get(AppConfig,entry.LEDGER).value
    assert db.query(MonitorCheck).count()==2
    assert ids[1] not in {m.id for m in list_monitors(db)}
    assert db.query(MonitorGroupMember).filter_by(group_id=g.id).count()==0
    reconcile(db,n);db.commit()
    assert db.get(AppConfig,entry.LEDGER).value==before


def test_group_metadata_save_keeps_members_appended_since_editor_opened(db):
    from app.services.monitor_groups import save_group
    n=connected(db);reconcile(db,n);db.commit()
    group=db.query(MonitorGroup).filter_by(name='默认入口探测').one()
    second=connected(db,node(db,'second',token='second-installation'));reconcile(db,second);db.commit()
    before=[m.monitor_id for m in db.query(MonitorGroupMember).filter_by(group_id=group.id).order_by(MonitorGroupMember.position)]
    result=save_group(db,group.id,name='renamed group')
    assert result['child_ids']==before and len(before)==2


@pytest.mark.parametrize('change', [{'name':''},{'name':'x'*65},{'type':'exec'},{'target':''},{'target':'x'*257},{'interval':0},{'timeout':0},{'node_id':0},{'target':'one.example'},{'target':'one:0'},{'target':'one:65536'}])
def test_new_group_item_validation_is_a_client_error(change):
    from pydantic import ValidationError
    from app.schemas.monitor import MonitorGroupCreate
    item=dict(name='one',type='tcp',target='one:443',node_id=1,interval=60,timeout=5)
    with pytest.raises(ValidationError):
        MonitorGroupCreate(name='group',items=[item|change],request_key='44444444-4444-4444-8444-444444444444')
