"""Legacy migration proofs: real services, owned in-memory SQLite only."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
from test_node_monitor_policy import db, node
from test_entry_monitor_groups import tables, source, sample
from app.models.config import AppConfig
from app.models.monitor import Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember
from app.services import entry_monitoring as entry
from app.services.entry_monitor_groups import KEY, PURPOSE, reconcile
from app.services.monitor import list_monitors, list_checks


def install_key(n):
    return f'{n.id}:' + hashlib.sha256((n.token or str(n.created_at)).encode()).hexdigest()


def legacy(db, n, *, owner_key=None, renamed=False):
    group = MonitorGroup(name='custom group' if renamed else 'owned → 中心')
    db.add(group); db.flush()
    state = {}
    ids = []
    ts = datetime.now(timezone.utc) - timedelta(seconds=2)
    for i, ip in enumerate(['192.168.160.3', '192.168.160.4']):
        m = Monitor(name=f'old-{i}', node_id=n.id, type='ping', target=ip,
                    interval=60, timeout=1, status='up', last_check_at=ts, last_latency_ms=1)
        db.add(m); db.flush(); ids.append(m.id)
        db.add(MonitorGroupMember(group_id=group.id, monitor_id=m.id, position=i))
        db.add(MonitorCheck(monitor_id=m.id, ts=ts, success=True, latency_ms=1, loss_pct=0))
        state[f'{n.id}:public:old:{ip}'] = dict(purpose='management_entry_icmp', source_node_id=n.id,
            entry_id='public', address_version='old', ip=ip, hostname='main.example', monitor_id=m.id)
    owner = dict(purpose=PURPOSE, source_node_id=n.id, owner_uuid=str(uuid4()),
                 group_id=group.id, attached_ids=ids)
    db.add(AppConfig(key=entry.LEDGER, value=json.dumps(state)))
    db.add(AppConfig(key=KEY, value=json.dumps({owner_key or install_key(n): owner})))
    db.commit()
    return group, ids, owner


def online(db):
    n = source(db); n.token = 'install-A'; n.status = 'online'
    n.last_seen_at = datetime.now(timezone.utc)
    n.components = {'monitoring': {'ready': True, 'types': ['ping'],
                                 'targets': ['192.168.160.3', '192.168.160.4']}}
    db.commit()
    return n


@pytest.mark.parametrize('renamed', [False, True])
@pytest.mark.parametrize('mixed_sample', [False, True])
def test_adoption_keeps_history_but_requires_new_logical_measurement(db, renamed, mixed_sample):
    n = online(db); group, ids, owner = legacy(db, n, renamed=renamed)
    history = [(c.monitor_id, c.ts, c.success, c.latency_ms, c.loss_pct) for c in db.query(MonitorCheck)]
    if mixed_sample:
        incoming = sample(n)
        incoming.icmp[0].results.append(incoming.icmp[0].results[0].model_copy(
            update={'ip': '192.168.160.4', 'status': 'down', 'latency_ms': None, 'loss_pct': 100}))
        n.control_channel = incoming.model_dump(mode='json'); db.commit()
    reconcile(db, n); db.commit()
    assert db.get(Monitor, ids[0]).target == '192.168.160.3'
    assert [(c.monitor_id, c.ts, c.success, c.latency_ms, c.loss_pct) for c in db.query(MonitorCheck)] == history
    assert list_checks(db, ids[1])[0].success is True
    assert not any(m.status == 'up' for m in list_monitors(db))
    assert entry.current_ids(db) == set()
    assert json.loads(db.get(AppConfig, KEY).value)[install_key(n)] == owner
    member = db.query(MonitorGroupMember).filter_by(monitor_id=ids[0]).first()
    assert (member is not None and member.group_id == group.id) is renamed
    current = next(m for m in list_monitors(db) if m.target == 'main.example')
    assert current.id not in ids and current.last_check_at is None
    entry.save_channel(db, n, sample(n)); db.commit()
    assert next(m for m in list_monitors(db) if m.id == current.id).status == 'up'
    assert len(list_checks(db, current.id)) == 1
    assert len(list_checks(db, ids[0])) == 1


def test_consumed_legacy_id_cannot_be_adopted_by_next_installation(db):
    n = online(db); group, ids, owner = legacy(db, n)
    original_key = install_key(n)
    reconcile(db, n); db.commit()
    old = next(v for v in json.loads(db.get(AppConfig, entry.LEDGER).value).values()
               if v.get('logical') and v['entry_id'] == 'public')
    assert old['monitor_id'] not in ids
    entry.save_channel(db, n, sample(n)); db.commit()
    n.token = 'install-B'; db.commit(); reconcile(db, n); db.commit()
    logical = [v for v in json.loads(db.get(AppConfig, entry.LEDGER).value).values() if v.get('logical')]
    assert len({v['monitor_id'] for v in logical}) == len(logical)
    current_id = json.loads(db.get(AppConfig, entry.LEDGER).value)[entry.logical_key(n, 'public')]['monitor_id']
    assert current_id not in {*ids, old['monitor_id']}
    current = next(m for m in list_monitors(db) if m.id == current_id)
    assert (current.status, current.status_reason) == ('down', 'stale')
    assert all(m.status == 'down' for m in list_monitors(db) if m.id in ids)
    assert json.loads(db.get(AppConfig, KEY).value)[original_key] == owner


def test_new_installation_without_legacy_has_distinct_id_and_waits_for_its_sample(db):
    n = online(db); reconcile(db, n); db.commit()
    entry.save_channel(db, n, sample(n)); db.commit()
    before = {m.id for m in db.query(Monitor)}
    n.token = 'install-B'; db.commit(); reconcile(db, n); db.commit()
    current = [m for m in list_monitors(db) if m.id not in before]
    assert len(current) == 2 and all(m.status == 'down' for m in current)
    assert {m.target: m.status_reason for m in current} == {'main.example': 'stale', 'other.example': 'scope_pending'}
    entry.save_channel(db, n, sample(n)); db.commit()
    assert next(m for m in list_monitors(db) if m.target == 'main.example' and m.id not in before).status == 'up'
    assert all(m.status == 'down' for m in list_monitors(db) if m.id in before)


@pytest.mark.parametrize('damage', ['target', 'type', 'node', 'owner_install', 'owner_source', 'purpose', 'missing'])
def test_unproven_or_edited_legacy_identity_never_changes_user_data(db, damage):
    n = online(db); group, ids, owner = legacy(db, n,
        owner_key=f'{n.id}:' + hashlib.sha256(b'older-install').hexdigest() if damage == 'owner_install' else None)
    m = db.get(Monitor, ids[0])
    if damage == 'target': m.target = 'user-owned-other.example'
    elif damage == 'type': m.type = 'tcp'
    elif damage == 'node': m.node_id = node(db, name='other', token='other').id
    elif damage == 'owner_source':
        row = db.get(AppConfig, KEY); state = json.loads(row.value)
        state[install_key(n)]['source_node_id'] = 999; row.value = json.dumps(state)
    elif damage == 'purpose':
        row = db.get(AppConfig, entry.LEDGER); state = json.loads(row.value)
        next(iter(state.values()))['purpose'] = 'not-entry-owned'; row.value = json.dumps(state)
    elif damage == 'missing': db.delete(m)
    db.commit()
    target = m.target
    members = [(v.group_id, v.monitor_id, v.position) for v in db.query(MonitorGroupMember)]
    checks = [(v.monitor_id, v.ts, v.success) for v in db.query(MonitorCheck)]
    reconcile(db, n); db.commit(); reconcile(db, n); db.commit()
    if damage != 'missing': assert db.get(Monitor, ids[0]).target == target
    assert [(v.group_id, v.monitor_id, v.position) for v in db.query(MonitorGroupMember).filter_by(group_id=group.id)] == members
    assert [(v.monitor_id, v.ts, v.success) for v in db.query(MonitorCheck)] == checks
    assert not any(v.get('logical') and v['monitor_id'] in ids
                   for v in json.loads(db.get(AppConfig, entry.LEDGER).value).values())


def test_logical_edited_target_is_not_overwritten_or_sampled(db):
    n = online(db); reconcile(db, n); db.commit()
    m = db.query(Monitor).filter_by(target='main.example').one()
    m.target = 'user-owned-other.example'; db.commit()
    entry.save_channel(db, n, sample(n)); db.commit()
    assert m.target == 'user-owned-other.example'
    assert db.query(MonitorCheck).count() == 0


def test_node_rename_conservatively_keeps_original_group_and_uuid(db):
    n = online(db); group, ids, owner = legacy(db, n)
    n.name = 'renamed node'; db.commit(); reconcile(db, n); db.commit()
    assert db.query(MonitorGroupMember).filter_by(monitor_id=ids[0]).one().group_id == group.id
    assert json.loads(db.get(AppConfig, KEY).value)[install_key(n)] == owner


def test_unproven_deleted_owner_is_negative_evidence_not_adoption_permission(db):
    n = online(db); group, ids, owner = legacy(db, n, owner_key='old')
    db.query(MonitorGroupMember).delete(); db.delete(group); db.commit()
    reconcile(db, n); db.commit()
    replacement = db.get(MonitorGroup, group.id)
    assert replacement is None or replacement.stable_uuid != group.stable_uuid
    assert db.query(MonitorGroupMember).filter(MonitorGroupMember.monitor_id.in_(ids)).count() == 0
    assert {g['entry_id'] for g in __import__('app.services.monitor_groups', fromlist=['list_groups']).list_groups(db)} == {'public', 'private'}
    assert json.loads(db.get(AppConfig, KEY).value)['old'] == owner
    assert [db.get(Monitor, mid).target for mid in ids] == ['192.168.160.3', '192.168.160.4']


def test_missing_installation_proof_preserves_old_group_ids_and_history(db):
    n = online(db); group, ids, owner = legacy(db, n, owner_key='old')
    reconcile(db, n); db.commit()
    assert db.get(Monitor, ids[0]).target == '192.168.160.3'
    assert db.query(MonitorGroupMember).filter_by(group_id=group.id).count() == 2
    assert json.loads(db.get(AppConfig, KEY).value)['old'] == owner
    assert all(list_checks(db, mid) for mid in ids)
    assert all(m.status == 'down' for m in list_monitors(db))


def test_consumption_blocks_reuse_even_with_another_installation_owner_receipt(db):
    n = online(db); group, ids, owner = legacy(db, n)
    reconcile(db, n); db.commit()
    n.token = 'install-B'; db.commit()
    row = db.get(AppConfig, KEY); state = json.loads(row.value)
    state[install_key(n)] = owner | {'owner_uuid': str(uuid4())}
    row.value = json.dumps(state); db.commit()
    reconcile(db, n); db.commit()
    logical = [v for v in json.loads(db.get(AppConfig, entry.LEDGER).value).values() if v.get('logical')]
    assert len({v['monitor_id'] for v in logical}) == len(logical)
    current = json.loads(db.get(AppConfig, entry.LEDGER).value)['logical:' + install_key(n) + ':public']
    assert current['monitor_id'] not in ids


def test_consumed_id_stays_reserved_when_only_new_install_owner_proof_remains(db):
    n = online(db); group, ids, owner = legacy(db, n)
    reconcile(db, n); db.commit()
    n.token = 'install-B'; db.commit()
    # Partial legacy import can omit old group ownership, but must not release
    # the logical identity's durable consumption receipt.
    db.get(AppConfig, KEY).value = json.dumps({install_key(n): owner | {'owner_uuid': str(uuid4())}})
    db.commit(); reconcile(db, n); db.commit()
    current = json.loads(db.get(AppConfig, entry.LEDGER).value)['logical:' + install_key(n) + ':public']
    assert current['monitor_id'] not in ids


def test_new_mixed_logical_sample_records_failure_without_rewriting_per_ip_history(db):
    n = online(db); group, ids, owner = legacy(db, n)
    reconcile(db, n); db.commit()
    incoming = sample(n)
    incoming.icmp[0].results.append(incoming.icmp[0].results[0].model_copy(
        update={'ip': '192.168.160.4', 'status': 'down', 'latency_ms': None, 'loss_pct': 100}))
    entry.save_channel(db, n, incoming); db.commit()
    current = next(m for m in list_monitors(db) if m.target == 'main.example')
    assert current.id not in ids
    assert (current.status, current.status_reason, current.last_latency_ms) == ('down', 'failure', None)
    checks = list_checks(db, current.id)
    assert len(checks) == 1 and not checks[0].success and checks[0].loss_pct == 50
    assert list_checks(db, ids[0])[0].success and list_checks(db, ids[0])[0].latency_ms == 1
    assert list_checks(db, ids[1])[0].success


def test_legacy_member_moved_to_custom_group_is_not_superseded_or_migrated(db):
    n = online(db); group, ids, owner = legacy(db, n)
    custom = MonitorGroup(name='my custom group'); db.add(custom); db.flush()
    db.query(MonitorGroupMember).filter_by(monitor_id=ids[1]).one().group_id = custom.id
    db.commit()
    before = [(m.group_id, m.monitor_id, m.position) for m in db.query(MonitorGroupMember)]
    reconcile(db, n); db.commit()
    assert [(m.group_id, m.monitor_id, m.position) for m in db.query(MonitorGroupMember)
            .filter(MonitorGroupMember.group_id.in_([group.id, custom.id]))] == before
    assert ids[1] in {m.id for m in list_monitors(db)}


def test_conflicting_installation_receipts_do_not_prove_legacy_ownership(db):
    n = online(db); group, ids, owner = legacy(db, n)
    row = db.get(AppConfig, KEY); state = json.loads(row.value)
    state[f'{n.id}:' + hashlib.sha256(b'other-install').hexdigest()] = owner | {'owner_uuid': str(uuid4())}
    row.value = json.dumps(state); db.commit()
    reconcile(db, n); db.commit()
    assert [db.get(Monitor, mid).target for mid in ids] == ['192.168.160.3', '192.168.160.4']
    assert db.query(MonitorGroupMember).filter_by(group_id=group.id).count() == 2
