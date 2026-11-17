"""MON-01/02/03: offline compatibility and retained ownership regressions."""
from datetime import datetime, timezone, timedelta
import pytest
from test_node_monitor_policy import db, node
from test_entry_monitor_groups import tables
from app.services import monitor as svc


@pytest.mark.parametrize('damage', ['none', 'name', 'target', 'type', 'source', 'install',
    'owner_source', 'owner_purpose', 'purpose', 'attached', 'claim', 'foreign_claim',
    'logical_claim', 'superseded', 'missing_owner'])
def test_removed_legacy_v1_requires_exact_uncontested_proof_without_writes(db, damage):
    import json
    from sqlalchemy import event
    from test_entry_monitor_migration import online, legacy, install_key
    from app.models.monitor import Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember
    from app.models.config import AppConfig
    from app.services import entry_monitoring as entry, entry_monitor_groups as owned, monitor_groups as groups
    # The autouse fixture creates history tables and original ownership, not a migration.
    n = online(db); group, ids, owner = legacy(db, n)
    manual = svc.create_monitor(db, 'old-0', 'ping', '192.168.160.3', 60, 5, n.id)
    db.add(MonitorGroupMember(group_id=group.id, monitor_id=manual.id, position=2))
    m = db.get(Monitor, ids[0])
    if damage == 'name': m.name = 'user renamed'
    elif damage == 'target': m.target = 'edited.example'
    elif damage == 'type': m.type = 'tcp'
    elif damage == 'source': m.node_id = node(db, name='other', token='other').id
    elif damage == 'install': n.token = 'new-installation'
    state = json.loads(db.get(AppConfig, entry.LEDGER).value)
    if damage == 'purpose': next(iter(state.values()))['purpose'] = 'user-owned'
    elif damage == 'superseded': next(iter(state.values()))['superseded_by'] = 999
    elif damage == 'logical_claim':
        state['logical:other:installation:public'] = dict(logical=True, purpose='management_entry_icmp', source_node_id=n.id, monitor_id=ids[0], entry_id='public', hostname='main.example')
    db.get(AppConfig, entry.LEDGER).value = json.dumps(state)
    owners = {install_key(n): owner} if damage != 'install' else json.loads(db.get(AppConfig, owned.KEY).value)
    proof = next(iter(owners.values()))
    if damage == 'owner_source': proof['source_node_id'] = 999
    elif damage == 'owner_purpose': proof['purpose'] = 'user-owned'
    elif damage == 'attached': proof['attached_ids'] = [ids[1]]
    elif damage in ('claim', 'foreign_claim'):
        owners['other-installation'] = owner | {'purpose': 'foreign' if damage == 'foreign_claim' else owned.PURPOSE}
    elif damage == 'missing_owner': owners = {}
    db.get(AppConfig, owned.KEY).value = json.dumps(owners)
    n.status = 'removed'; db.commit()
    def snapshot():
        return {model.__tablename__: [tuple(repr(getattr(row, c.name)) for c in model.__table__.columns)
                                     for row in db.query(model).order_by(*model.__table__.primary_key.columns)]
                for model in (Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember, AppConfig)}
    before = snapshot()
    statements = []
    def only_select(conn, cursor, statement, *args):
        statements.append(statement)
        assert statement.lstrip().upper().startswith('SELECT'), statement
    event.listen(db.get_bind(), 'before_cursor_execute', only_select)
    try:
        hidden = entry.removed_ids(db)
        should_hide = damage in ('none', 'name')
        assert (ids[0] in hidden) is should_hide
        visible = {v.id for v in svc.list_monitors(db)}
        assert (ids[0] not in visible) is (should_hide or damage == 'superseded')
        assert manual.id in visible and manual.id not in hidden
        projected = groups.list_groups(db)[0]
        assert set(projected['child_ids']) == ({manual.id, *ids} - hidden - entry.superseded_ids(db))
        assert projected['unknown_count'] == 0
        assert projected['down_count'] == len(projected['child_ids'])
        assert len(svc.list_checks(db, ids[0])) == 1
        assert snapshot() == before
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', only_select)
    assert statements
    # ACCEPTANCE:8-10 / INTERFACE:5-6,10: explicit bootstrap/removal is a write
    # hook, unlike GET. Only proven legacy relations may detach; no definition,
    # sample, manual membership, edited identity or competing claim may be lost.
    owned.reconcile(db, n); db.commit()
    after = snapshot()
    assert after['monitors'] == before['monitors']
    assert after['monitor_checks'] == before['monitor_checks']
    assert all(row in after['monitor_groups'] for row in before['monitor_groups'])
    assert len(after['monitor_groups']) == len(before['monitor_groups']) + 2
    new_owners = owned.owners(db)
    assert {key: new_owners[key] for key in owners} == owners
    assert set(new_owners) == set(owners) | {'entry:public', 'entry:private'}
    assert all(not new_owners['entry:' + lane]['attached_ids'] for lane in ('public', 'private'))
    # Exact proof oracle, kept distinct for each of the original damage controls.
    detached = set(ids) if damage in ('none', 'name', 'superseded') else {ids[1]} if damage == 'attached' else set()
    assert {(v.group_id, v.monitor_id, v.position) for v in db.query(MonitorGroupMember)} == {
        (group.id, mid, position) for position, mid in enumerate([*ids, manual.id]) if mid not in detached}
    new_state = json.loads(db.get(AppConfig, entry.LEDGER).value)
    expected_state = {}
    for key, item in state.items():
        if item['monitor_id'] in detached:
            expected_state[f"archive:{key}:{item['monitor_id']}"] = item | {'archived': 'legacy_generation'}
        else:
            expected_state[key] = item
    assert new_state == expected_state
    config_before = dict(before['app_config'])
    config_after = dict(after['app_config'])
    for key, value in config_before.items():
        if key not in {repr(owned.KEY), repr(entry.LEDGER), repr('monitors_version')}:
            assert config_after[key] == value
    assert set(config_after) - set(config_before) <= {repr('monitors_version')}
    # The now-reconciled removed node remains idempotent under the original guard.
    event.listen(db.get_bind(), 'before_cursor_execute', only_select)
    try:
        owned.reconcile(db, n)
        assert snapshot() == after
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', only_select)


@pytest.mark.parametrize('kind', ['tcp', 'udp'])
@pytest.mark.parametrize('zone', ['eth0', '1', '25eth0'])
def test_scoped_ipv6_rejected_by_parser_dtos_and_all_service_writes(db, kind, zone):
    from app.monitor_targets import parse_target
    from app.schemas.monitor import MonitorCreate, MonitorGroupItemCreate, MonitorGroupCreate, MonitorUpdate
    from app.services import monitor_groups as groups
    from app.models.monitor import Monitor, MonitorGroup
    target = f'[fe80::1%{zone}]:443'
    with pytest.raises(ValueError): parse_target(kind, target)
    for dto in (MonitorCreate, MonitorGroupItemCreate):
        with pytest.raises(ValueError): dto(name='1', type=kind, target=target, node_id=1)
    with pytest.raises(ValueError): MonitorUpdate(type=kind, target=target)
    n = node(db); group = MonitorGroup(name='g'); db.add(group); db.commit()
    m = svc.create_monitor(db, 'old', kind, 'nas:53', 60, 5, n.id)
    raw = MonitorCreate.model_construct(name='1', type=kind, target=target, node_id=n.id, interval=60, timeout=5)
    data = MonitorGroupCreate.model_construct(name='new', items=[raw], request_key='01234567-1234-1234-1234-012345678901', failure_policy='any', rotation_seconds=0)
    for operation in (lambda: svc.create_monitor(db, '1', kind, target, 60, 5, n.id),
                      lambda: groups.create_child(db, group.id, raw),
                      lambda: groups.create_group(db, data, session_id='owned'),
                      lambda: svc.update_monitor(db, m.id, {'target': target})):
        with pytest.raises(ValueError): operation()
        db.rollback()
    assert db.query(Monitor).count() == 1 and db.get(Monitor, m.id).target == 'nas:53'
    assert parse_target(kind, '[2001:db8::1]:443').host == '2001:db8::1'
    assert parse_target(kind, '例子.测试:443').host == 'xn--fsqu00a.xn--0zwm56d'
    assert parse_target(kind, 'nas:443').host == 'nas'


@pytest.mark.parametrize('kind', ['http', 'https', 'udp'])
@pytest.mark.parametrize('advertised', [['tcp'], ['tcp', 'ping']])
def test_legacy_core_advertisement_is_not_an_extended_protocol_denylist(db, kind, advertised):
    n = node(db, status='online', last_seen_at=datetime.now(timezone.utc),
             components={'monitoring': {'ready': True, 'types': advertised}})
    target = 'nas:53' if kind == 'udp' else kind + '://nas/health'
    m = svc.create_monitor(db, '1', kind, target, 60, 5, n.id)
    m.status = 'up'; m.last_check_at = datetime.now(timezone.utc); m.last_latency_ms = 3
    db.commit()
    assert (svc.present_monitor(db, m).status_reason, svc.present_monitor(db, m).last_latency_ms) == ('healthy', 3)
    m.last_check_at -= timedelta(seconds=181); db.commit()
    assert svc.present_monitor(db, m).status_reason == 'stale'
    n.components = {'monitoring': {'ready': False, 'types': advertised}}; db.commit()
    assert svc.present_monitor(db, m).status_reason == 'unavailable'
    n.components = {'monitoring': {'ready': True, 'types': advertised, 'targets': ['other']}}; db.commit()
    assert svc.present_monitor(db, m).status_reason == 'outside_scope'


@pytest.mark.parametrize('kind,advertised,target', [('ping', ['tcp'], 'nas'), ('tcp', ['ping'], 'nas:80')])
def test_core_capability_absence_remains_explicit_unavailability(db, kind, advertised, target):
    n = node(db, status='online', last_seen_at=datetime.now(timezone.utc),
             components={'monitoring': {'ready': True, 'types': advertised}})
    m = svc.create_monitor(db, '1', kind, target, 60, 5, n.id)
    m.status = 'up'; m.last_check_at = datetime.now(timezone.utc); db.commit()
    assert svc.present_monitor(db, m).status_reason == 'unsupported'
