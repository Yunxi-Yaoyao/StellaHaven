"""Owned in-memory database only; no app startup or configured database."""
from datetime import datetime, timezone, timedelta
import json
import pytest
from test_node_monitor_policy import db, node
from app.models.monitor import Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember
from app.models.config import AppConfig
from app.schemas.control_channel import ControlChannel
from app.services import entry_monitoring as entry, entry_registry


@pytest.fixture(autouse=True)
def tables(db, monkeypatch):
    # Combined candidate creates the quiet interruption rule with each new node.
    from app.models.alert import AlertRule, AlertState
    for table in (MonitorGroup.__table__, MonitorGroupMember.__table__, AlertRule.__table__, AlertState.__table__):
        table.create(db.get_bind(), checkfirst=True)
    monkeypatch.setattr(MonitorCheck.__table__.c.id, 'type', __import__('sqlalchemy').Integer())
    MonitorCheck.__table__.create(db.get_bind())
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public': 'https://main.example', 'private': 'https://other.example'}})
    # V11 private probing requires an applied owner selection, not registry consent.
    from test_entry_lifecycle_v11 import save_origins
    save_origins(db, monkeypatch, 'https://other.example')
    db.commit()


def source(db):
    return node(db, components={'monitoring': {'ready': True, 'types': ['ping'], 'targets': ['192.168.160.3']}})


def connected_source(db, token=None):
    # These bodies exercise post-heartbeat groups; shared source() stays pending
    # for migration/scope suites which explicitly control lifecycle transitions.
    from app.services.entry_monitor_groups import reconcile
    n = source(db)
    if token is not None:
        n.token = token
    n.last_seen_at = datetime.now(timezone.utc)
    n.status = 'online'
    reconcile(db, n)
    db.commit()
    return n


def legacy_manual_child(db, group_id, n, name):
    # Historical mixed groups remain portable, but V11 API creation is forbidden.
    from app.services.monitor_groups import create_child
    from app.schemas.monitor import MonitorCreate
    before = db.query(Monitor).count()
    with pytest.raises(ValueError, match='系统'):
        create_child(db, group_id, MonitorCreate(name=name, target='owned:443', node_id=n.id))
    assert db.query(Monitor).count() == before
    child = Monitor(name=name, type='tcp', target='owned:443', node_id=n.id, interval=60, timeout=5)
    db.add(child); db.flush()
    db.add(MonitorGroupMember(group_id=group_id, monitor_id=child.id, position=99))
    db.commit()
    return child


def sample(n, lane='public', offset=0, status='complete'):
    from sqlalchemy.orm import object_session
    e = next(e for e in entry.manifest(n, db=object_session(n), active_only=False)['entries'] if e['entry_id'] == lane)
    return ControlChannel(icmp=[dict(entry_id=lane, version=e['version'], hostname=e['hostname'],
        sampled_at=datetime.now(timezone.utc)+timedelta(seconds=offset), status=status,
        results=[dict(ip='192.168.160.3', family=4, status='up', latency_ms=1.2, loss_pct=0)] if status == 'complete' else [])])


def test_node_create_has_pending_items_before_any_sample(db):
    from app.services.node import create_node
    n = create_node(db, 'new node', 'linux', 'not-the-center.example')
    from app.services.monitor_groups import list_groups
    result = list_groups(db)
    assert [g['name'] for g in result] == ['默认入口探测', '其他入口探测']
    assert [g['entry_id'] for g in result] == ['public', 'private']
    assert [g['visible'] for g in result] == [True, False]
    assert all(g['child_ids'] == [] and g['status'] is None and g['automatic'] for g in result)
    assert all(g['down_count'] == g['up_count'] == 0 for g in result)
    assert db.query(Monitor).count() == 0
    from app.services.node import get_agent_config
    from app.services.entry_monitor_groups import reconcile, owners
    get_agent_config(db, n.token)
    assert db.query(Monitor).count() == 0
    n.last_seen_at = datetime.now(timezone.utc); n.status = 'online'
    reconcile(db, n); db.commit()
    connected = list_groups(db)
    assert all(len(g['child_ids']) == 1 and g['status'] == 'down' for g in connected)
    assert all(g['down_count'] == 1 and g['up_count'] == 0 for g in connected)
    identity = owners(db)
    reconcile(db, n); db.commit()
    assert list_groups(db) == connected and owners(db) == identity
    assert {m.node_id for m in db.query(Monitor)} == {n.id}
    assert db.query(MonitorCheck).count() == 0


def test_config_and_samples_keep_two_logical_items_without_name_adoption(db):
    from app.services.node import get_agent_config
    n = connected_source(db, token='owned-token')
    manual = MonitorGroup(name='默认入口探测', failure_policy='all', rotation_seconds=15)
    db.add(manual); db.commit()
    get_agent_config(db, n.token)
    before = json.loads(db.get(AppConfig, 'entry_monitoring.groups.v1').value)
    entry.save_channel(db, n, sample(n, status='dns_error')); db.commit()
    assert db.query(Monitor).count() == 2
    for lane in ('public', 'private'):
        entry.save_channel(db, n, sample(n, lane)); db.commit()
    assert db.query(MonitorGroupMember).filter_by(group_id=manual.id).count() == 0
    assert (manual.failure_policy, manual.rotation_seconds) == ('all', 15)
    n.name = 'renamed'; n.host = 'different.example'; db.commit()
    get_agent_config(db, n.token)
    assert json.loads(db.get(AppConfig, 'entry_monitoring.groups.v1').value) == before


def test_auto_group_edit_delete_are_not_reverted(db):
    from app.services.monitor_groups import save_group, remove_group
    from app.services.entry_monitor_groups import reconcile
    n = connected_source(db); entry.save_channel(db, n, sample(n)); db.commit()
    g = db.query(MonitorGroup).filter_by(name='默认入口探测').one()
    mid = db.query(Monitor).filter_by(target='main.example').one().id
    save_group(db, g.id, name='my name', child_ids=[mid], failure_policy='all', rotation_seconds=8)
    with pytest.raises(ValueError, match='只读'):
        save_group(db, g.id, name='my name', child_ids=[])
    entry.save_channel(db, n, sample(n)); db.commit()
    assert db.get(MonitorGroup, g.id).name == 'my name'
    gid, uuid = g.id, g.stable_uuid
    with pytest.raises(ValueError, match='系统'):
        remove_group(db, gid)
    reconcile(db,n); db.commit()
    assert db.get(MonitorGroup, gid).stable_uuid == uuid
    assert db.query(MonitorGroupMember).filter_by(group_id=gid).one().monitor_id == mid
    assert db.query(Monitor).count() == 2


def test_automatic_edit_rejects_ignored_sampling_fields_but_keeps_name_and_history(db):
    from app.services.monitor import update_monitor, list_monitors
    entry.save_channel(db, n := connected_source(db), sample(n)); db.commit()
    m = db.query(Monitor).filter_by(target='main.example').one()
    for field, value in [('target', '8.8.8.8'), ('interval', 10), ('type', 'tcp'), ('node_id', 999), ('timeout', 5)]:
        with pytest.raises(ValueError, match='自动入口'):
            update_monitor(db, m.id, {field: value})
    update_monitor(db, m.id, {'name': 'renamed'})
    entry.save_channel(db, n, sample(n, offset=1)); db.commit()
    assert db.get(Monitor, m.id).name == 'renamed'
    assert db.query(MonitorCheck).count() == 2
    # Replay exactly the same receipt, not a newly timestamped helper sample.
    receipt = sample(n, offset=2)
    entry.save_channel(db, n, receipt); db.commit()
    assert db.query(MonitorCheck).count() == 3
    entry.save_channel(db, n, receipt); db.commit()
    assert db.query(MonitorCheck).count() == 3
    assert list_monitors(db)[0].management == 'entry_icmp'


def test_create_child_is_atomic_preserves_manual_members_and_dispatches(db):
    from app.services import monitor_groups as groups
    from app.services.monitor import list_monitors_for_node, update_monitor
    from app.schemas.monitor import MonitorCreate
    n = connected_source(db)
    entry.save_channel(db, n, sample(n)); db.commit()
    g = db.query(MonitorGroup).filter_by(name='默认入口探测').one()
    before = db.query(Monitor).count()
    with pytest.raises(ValueError, match='系统'):
        groups.create_child(db, g.id, MonitorCreate(name='forbidden', type='tcp', target='192.168.160.3:443', node_id=n.id))
    assert db.query(Monitor).count() == before
    from app.services.monitor import create_monitor
    first = create_monitor(db, 'existing manual', 'tcp', '192.168.160.3:443', 60, 5, n.id)
    manual = groups.save_group(db, None, name='ordinary group', child_ids=[first.id])
    child = groups.create_child(db, manual['id'], MonitorCreate(name='manual', type='tcp', target='192.168.160.3:443', node_id=n.id, interval=30))
    assert {m.id for m in list_monitors_for_node(db, n.id)} == {first.id, child.id}
    update_monitor(db, child.id, {'name': 'changed', 'target': '192.168.160.3:8443', 'interval': 45})
    entry.save_channel(db, n, sample(n, 'private', 2)); db.commit()
    members = db.query(MonitorGroupMember).filter_by(group_id=manual['id']).order_by(MonitorGroupMember.position).all()
    assert [m.monitor_id for m in members] == [first.id, child.id]
    assert child.name == 'changed' and child.interval == 45
    with pytest.raises(ValueError):
        groups.create_child(db, 999, MonitorCreate(name='lost', target='8.8.8.8', node_id=n.id))
    assert db.query(Monitor).count() == 4


def test_settings_projection_keeps_manual_probes_and_groups_not_auto_memberships(db):
    from app.services.backup_projection import project_monitor_tables
    from app.services.monitor_groups import create_child, save_group
    from app.schemas.monitor import MonitorCreate
    n = connected_source(db)
    entry.save_channel(db, n, sample(n)); db.commit()
    auto = db.query(MonitorGroup).filter_by(name='默认入口探测').one()
    first = legacy_manual_child(db, auto.id, n, 'manual in auto')
    second = Monitor(name='other', type='tcp', target='other:443', node_id=n.id, interval=60, timeout=5)
    third = Monitor(name='third', type='tcp', target='third:443', node_id=n.id, interval=60, timeout=5)
    db.add_all([second, third]); db.commit()
    manual = save_group(db, None, name='manual group', child_ids=[second.id, third.id])
    tables={'monitors':[{'id':m.id} for m in db.query(Monitor)]}
    project_monitor_tables(db, tables)
    assert [m['id'] for m in tables['monitors']] == [first.id, second.id, third.id]
    assert [g['id'] for g in tables['monitor_groups']] == [manual['id']]
    assert {m['monitor_id'] for m in tables['monitor_group_members']} == {second.id, third.id}
    from app.services.backup_projection import restore_monitor_groups
    db.query(MonitorGroupMember).filter_by(group_id=manual['id']).delete();db.query(MonitorGroup).filter_by(id=manual['id']).delete();db.commit()
    restore_monitor_groups(db, tables);db.commit()
    assert db.get(MonitorGroup, manual['id']).name == 'manual group'
    assert db.query(MonitorGroupMember).filter_by(group_id=auto.id).count() == 2


def test_http_child_crud_membership_auth_and_deleted_identity_tombstone(db, monkeypatch):
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.testclient import TestClient
    from app.routers.monitor import monitor_router
    from app.routers.auth import current_user, admin_user
    from app.database import get_db
    from app.models.task import MtrTask
    MtrTask.__table__.create(db.get_bind())
    app = FastAPI(); app.include_router(monitor_router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    assert client.get('/monitors/groups').status_code == 401
    def signed_in(request: Request):
        request.state.auth_session = object()
        return object()
    app.dependency_overrides[current_user] = signed_in
    from app.services import admin_security
    def locked(*_):
        raise HTTPException(403, 'fixture locked grant')
    monkeypatch.setattr(admin_security, 'require_admin', locked)
    assert client.post('/monitors/groups/1/children', json={}).status_code == 403
    app.dependency_overrides[admin_user] = lambda: object()
    n = connected_source(db)
    entry.save_channel(db, n, sample(n)); db.commit()
    group = client.get('/monitors/groups').json()[0]
    assert group['automatic'] and len(group['child_ids']) == 1
    auto_id = group['child_ids'][0]
    payload = dict(name='manual', type='tcp', target='owned:443', node_id=n.id, interval=30, timeout=5)
    assert client.post(f"/monitors/groups/{group['id']}/children", json=payload).status_code == 400
    assert client.delete(f'/monitors/{auto_id}').status_code == 400
    assert client.delete(f"/monitors/groups/{group['id']}").status_code == 400
    assert client.put(f"/monitors/groups/{group['id']}", json={'name': 'bad', 'child_ids': []}).status_code == 400
    assert next(g for g in client.get('/monitors/groups').json() if g['id'] == group['id']) == group
    from app.services.monitor import create_monitor
    from app.services.monitor_groups import save_group
    first = create_monitor(db, 'ordinary first', 'tcp', 'owned:443', 60, 5, n.id)
    ordinary = save_group(db, None, name='ordinary', child_ids=[first.id])
    response = client.post(f"/monitors/groups/{ordinary['id']}/children", json=payload)
    assert response.status_code == 201, response.text
    mid = response.json()['id']
    response = client.patch(f'/monitors/{mid}', json={'name':'edited', 'interval':45})
    assert response.status_code == 200 and response.json()['interval'] == 45
    assert client.patch(f'/monitors/{auto_id}', json={'target':'8.8.8.8'}).status_code >= 400
    assert client.delete(f'/monitors/{auto_id}').status_code == 400
    assert next(g for g in client.get('/monitors/groups').json() if g['id'] == ordinary['id'])['child_ids'] == [first.id, mid]
    entry.save_channel(db, n, sample(n, offset=2)); db.commit()
    auto_ids = {m.id for m in db.query(Monitor) if m.id not in (first.id, mid)}
    assert len(auto_ids) == 2 and auto_id in auto_ids
    assert {m['id'] for m in client.get('/monitors/').json()} == {first.id, mid} | auto_ids
    assert client.delete(f'/monitors/{mid}').status_code == 204
    entry.save_channel(db, n, sample(n, offset=3)); db.commit()
    assert db.get(Monitor, mid) is None
    assert next(g for g in client.get('/monitors/groups').json() if g['id'] == ordinary['id'])['child_ids'] == [first.id]
    assert client.delete(f'/monitors/{first.id}').status_code == 204
    final_groups = client.get('/monitors/groups').json()
    assert all(g['id'] != ordinary['id'] for g in final_groups)
    assert next(g for g in final_groups if g['id'] == group['id'])['child_ids'] == [auto_id]


def test_report_transaction_is_not_a_ping_or_parent_success(db):
    from app.services.monitor_groups import list_groups
    n = connected_source(db)
    entry.save_channel(db, n, ControlChannel.model_validate({'report':dict(entry_id='public',origin='https://main.example',duration_ms=25,status='ok',http_status=200,sampled_at=datetime.now(timezone.utc))}));db.commit()
    assert db.query(Monitor).count() == 2 and db.query(MonitorCheck).count() == 0
    assert list_groups(db)[0]['status'] == 'down'
    assert n.control_channel['report']['duration_ms'] == 25


def test_two_nodes_get_distinct_stable_owner_uuids_and_no_name_adoption(db):
    from app.services.node import create_node, get_agent_config
    from uuid import UUID
    first = create_node(db, 'same', 'linux', 'first.example')
    second = create_node(db, 'same', 'linux', 'second.example')
    owners = json.loads(db.get(AppConfig, 'entry_monitoring.groups.v1').value)
    assert len({v['group_id'] for v in owners.values()}) == 2
    assert len({UUID(v['owner_uuid']) for v in owners.values()}) == 2
    get_agent_config(db, first.token);get_agent_config(db, second.token)
    assert json.loads(db.get(AppConfig, 'entry_monitoring.groups.v1').value) == owners


def test_membership_limits_conflicts_and_invalid_source_do_not_create_or_steal(db):
    from app.services.monitor_groups import save_group, create_child
    from app.schemas.monitor import MonitorCreate
    n = connected_source(db)
    entry.save_channel(db, n, sample(n));db.commit()
    system = db.query(MonitorGroup).filter_by(name='默认入口探测').one()
    system_members = [m.monitor_id for m in db.query(MonitorGroupMember).filter_by(group_id=system.id)]
    with pytest.raises(ValueError, match='系统'):
        create_child(db, system.id, MonitorCreate(name='forbidden', target='owned:443', node_id=n.id))
    with pytest.raises(ValueError, match='至少'):
        save_group(db, None, name='empty forbidden', child_ids=[])
    from app.services.monitor import create_monitor
    first = create_monitor(db, 'manual first', 'tcp', 'owned:443', 60, 5, n.id)
    ordinary = save_group(db, None, name='ordinary', child_ids=[first.id])
    g = db.get(MonitorGroup, ordinary['id'])
    # Check invalid sources before the cap, so capacity rejection cannot mask them.
    initial_count = db.query(Monitor).count()
    for gid, nid, reason in [(999, n.id, '不存在'), (g.id, 999, '节点')]:
        with pytest.raises(ValueError, match=reason):
            create_child(db, gid, MonitorCreate(name='rejected early', target='owned:443', node_id=nid))
        assert db.query(Monitor).count() == initial_count
        assert db.query(MonitorGroupMember).filter_by(group_id=g.id).one().monitor_id == first.id
    for i in range(11):
        create_child(db, g.id, MonitorCreate(name=f'manual {i}', target='owned:443', node_id=n.id))
    before = db.query(Monitor).count()
    for gid, nid in [(g.id, n.id), (999, n.id), (g.id, 999)]:
        with pytest.raises(ValueError):
            create_child(db, gid, MonitorCreate(name='rejected', target='owned:443', node_id=nid))
    assert db.query(Monitor).count() == before
    ids = [m.monitor_id for m in db.query(MonitorGroupMember).filter_by(group_id=g.id).order_by(MonitorGroupMember.position)]
    assert len(ids) == 12
    with pytest.raises(ValueError, match='至少'):
        save_group(db, g.id, name='empty forbidden', child_ids=[])
    with pytest.raises(ValueError, match='不同'):
        save_group(db, g.id, name='duplicate', child_ids=[ids[0], ids[0]])
    with pytest.raises(ValueError, match='其他监控组'):
        save_group(db, None, name='cannot steal', child_ids=ids[:2])
    with pytest.raises(ValueError, match='系统'):
        save_group(db, None, name='cannot adopt automatic', child_ids=system_members)
    assert db.get(MonitorGroup, g.id).name == 'ordinary'
    assert [m.monitor_id for m in db.query(MonitorGroupMember).filter_by(group_id=system.id)] == system_members


def test_backup_restore_rejects_auto_parent_and_auto_probe_adoption(db):
    from app.services.backup_projection import restore_monitor_groups
    from app.services.backup_archive import InvalidArchive
    n = connected_source(db);entry.save_channel(db, n, sample(n));db.commit()
    g = db.query(MonitorGroup).filter_by(name='默认入口探测').one();mid = db.query(Monitor).filter_by(target='main.example').one().id
    manual = Monitor(name='manual', node_id=n.id, type='tcp', target='owned:443', interval=60, timeout=5)
    db.add(manual);db.commit()
    for gid in (g.id, 999):
        data={'monitor_groups':[dict(id=gid,name='not adopted',failure_policy='any',rotation_seconds=0)],'monitor_group_members':[dict(group_id=gid,monitor_id=mid,position=0),dict(group_id=gid,monitor_id=manual.id,position=1)]}
        with pytest.raises(InvalidArchive):restore_monitor_groups(db,data)
        db.rollback()
    assert db.get(MonitorGroup, g.id).name == '默认入口探测'


def test_real_settings_archive_roundtrip_keeps_manual_and_derived_boundaries(db, monkeypatch, tmp_path):
    from app.services import backup_projection as backup
    from app.services.backup_archive import create_archive
    from app.models.user import User
    from app.models.alert import AlertRule
    from app.models.blob import BlobObject
    from app.services.monitor_groups import create_child, save_group
    from app.schemas.monitor import MonitorCreate
    monkeypatch.setattr(backup, 'require_settings_mode', lambda: None)
    engine = db.get_bind()
    for table in (User.__table__, AlertRule.__table__, BlobObject.__table__):table.create(engine, checkfirst=True)
    with engine.connect() as conn:conn.connection.driver_connection.create_function('octet_length', 1, lambda x:len(x.encode()))
    n = connected_source(db);entry.save_channel(db, n, sample(n));db.commit()
    auto = db.query(MonitorGroup).filter_by(name='默认入口探测').one(); auto_id = db.query(Monitor).filter_by(target='main.example').one().id
    child = legacy_manual_child(db, auto.id, n, 'kept standalone on restore')
    one = Monitor(name='one',node_id=n.id,type='tcp',target='one:443',interval=60,timeout=5)
    two = Monitor(name='two',node_id=n.id,type='tcp',target='two:443',interval=60,timeout=5)
    db.add_all([one,two]);db.commit()
    manual = save_group(db,None,name='saved manual parent',child_ids=[one.id,two.id])
    with engine.connect() as conn, backup.export_settings(conn, str(tmp_path)) as payload:
        raw=json.loads(payload.entries['settings.json'].getvalue())
        assert auto_id not in {m['id'] for m in raw['tables']['monitors']}
        assert child.id in {m['id'] for m in raw['tables']['monitors']}
        path=tmp_path/'settings.zip';create_archive(path,scope='settings',entries=payload.entries)
    child.name='changed';db.query(MonitorGroupMember).filter_by(group_id=manual['id']).delete();db.query(MonitorGroup).filter_by(id=manual['id']).delete();db.commit()
    backup.restore_settings(engine,path)
    db.expire_all()
    assert db.get(Monitor,child.id).name=='kept standalone on restore'
    assert db.get(MonitorGroup,manual['id']).name=='saved manual parent'
    assert db.query(MonitorGroupMember).filter_by(group_id=auto.id).count()==2
    assert db.query(MonitorCheck).filter_by(monitor_id=auto_id).count()==1
