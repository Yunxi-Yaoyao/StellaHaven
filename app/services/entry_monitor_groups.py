"""System entry ownership. All writes share the caller's transaction, no network."""
import json
from uuid import uuid4
from sqlalchemy import text
from app.models.config import AppConfig
from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember

KEY = 'entry_monitoring.groups.v1'
PURPOSE = 'node_to_center'


def lock(db):
    if db.get_bind().dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(1937006960)'))
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 0x5354454C475250})


def owners(db):
    row = db.get(AppConfig, KEY)
    return json.loads(row.value) if row else {}


def owned_groups(db):
    return {v['group_id']: v for v in owners(db).values()
            if v.get('purpose') == PURPOSE
            and (group := db.get(MonitorGroup, v['group_id'])) is not None
            and (not v.get('group_uuid') or v['group_uuid'] == group.stable_uuid)}


def bootstrap(db):
    """Explicit startup/registration hook; caller owns commit and rollback."""
    return reconcile(db)


def reconcile(db, node=None):
    lock(db)
    row = db.get(AppConfig, KEY, populate_existing=True)
    state = json.loads(row.value) if row else {}
    original = json.dumps(state, sort_keys=True)
    for lane in ('public', 'private'):
        key = f'entry:{lane}'
        owner = state.get(key)
        if owner is None:
            group = MonitorGroup(name='默认入口探测' if lane == 'public' else '其他入口探测',
                                 visible=lane == 'public', failure_policy='any', rotation_seconds=0)
            db.add(group); db.flush()
            state[key] = dict(purpose=PURPOSE, owner_uuid=str(uuid4()), entry_id=lane,
                              group_id=group.id, group_uuid=group.stable_uuid, attached_ids=[], lifecycle=2)
        elif owner.get('purpose') == PURPOSE:
            group = db.get(MonitorGroup, owner['group_id'])
            if group is None or (owner.get('group_uuid') and owner['group_uuid'] != group.stable_uuid):
                # Reused numeric IDs/names are not ownership; never adopt a manual group.
                replacement = MonitorGroup(name='默认入口探测' if lane == 'public' else '其他入口探测',
                    visible=lane == 'public', failure_policy='any', rotation_seconds=0,
                    stable_uuid=owner.get('group_uuid') or str(uuid4()))
                if group is None:
                    replacement.id = owner['group_id']
                db.add(replacement); db.flush(); group = replacement
                owner['group_id'] = group.id
            owner.setdefault('group_uuid', group.stable_uuid)
            owner['lifecycle'] = 2
    changed = original != json.dumps(state, sort_keys=True)
    if changed:
        if row is None:
            row = AppConfig(key=KEY, value=''); db.add(row)
        row.value = json.dumps(state, ensure_ascii=False)
        db.flush()
    from app.models.node import Node
    from app.services.entry_monitoring import LEDGER, manifest, ensure_logical_monitor, archive_logical, logical_key
    # All hooks share the same bounded pass, including newly applied private origins.
    nodes = db.query(Node).order_by(Node.id).limit(10001).all()
    if len(nodes) > 10000:
        raise ValueError('入口对账节点数量超过上限')
    ledger_row = db.get(AppConfig, LEDGER)
    before = ledger_row.value if ledger_row else None
    ledger = json.loads(before) if before else {}
    origins = {e['entry_id']:e for e in manifest(db=db, active_only=False)['entries']}
    node_by_id = {n.id:n for n in nodes}
    legacy_intact = {}
    for key, item in list(ledger.items()):
        if item.get('archived'):
            continue
        source = node_by_id.get(item.get('source_node_id'))
        if item.get('lifecycle') != 2:
            # v1 per-IP rows require the original installation-keyed receipt.
            if source is not None and not item.get('logical') and item.get('purpose') == 'management_entry_icmp':
                owner_key = logical_key(source, item.get('entry_id'))[len('logical:'):].rsplit(':', 1)[0]
                proof = state.get(owner_key, {})
                old = db.get(Monitor, item['monitor_id'])
                member = db.query(MonitorGroupMember).filter_by(monitor_id=item['monitor_id']).first()
                original_group = db.get(MonitorGroup, proof.get('group_id')) if proof.get('group_id') is not None else None
                group_intact = original_group is not None and original_group.name == f'{source.name[:57]} → 中心'
                # One edited/deleted/moved sibling makes the legacy group user-owned.
                # Never partially migrate another sibling out of that group.
                for mid in proof.get('attached_ids', []):
                    claims = [v for v in ledger.values() if v.get('monitor_id') == mid and not v.get('archived')]
                    sibling = db.get(Monitor, mid)
                    relation = db.query(MonitorGroupMember).filter_by(monitor_id=mid).first()
                    if not (len(claims) == 1 and claims[0].get('purpose') == 'management_entry_icmp'
                            and claims[0].get('source_node_id') == source.id and claims[0].get('ip')
                            and sibling is not None and sibling.node_id == source.id and sibling.type == 'ping'
                            and sibling.target == claims[0]['ip'] and relation is not None
                            and relation.group_id == proof.get('group_id')):
                        group_intact = False
                group_intact = legacy_intact.setdefault(owner_key, group_intact)
                if (group_intact and proof.get('purpose') == PURPOSE and proof.get('source_node_id') == source.id
                        and item['monitor_id'] in proof.get('attached_ids', [])
                        and old is not None and old.node_id == source.id and old.type == 'ping'
                        and item.get('ip') and old.target == item['ip']
                        and member is not None and member.group_id == proof['group_id']
                        and not any(k != owner_key and old.id in v.get('attached_ids', []) for k,v in state.items())
                        and not any(k != key and old.id == v.get('monitor_id') for k,v in ledger.items())):
                    archive_logical(db, ledger, key, 'legacy_generation')
                continue
            # Upgrade only exact installation + ledger + recorded system ownership.
            owner = state.get(f"entry:{item.get('entry_id')}", {})
            monitor = db.get(Monitor, item['monitor_id'])
            if not (source is not None and item.get('logical')
                    and key == logical_key(source, item.get('entry_id'))
                    and item.get('purpose') == 'management_entry_icmp'
                    and owner.get('purpose') == PURPOSE and owner.get('owner_uuid')
                    and monitor is not None and monitor.id in owner.get('attached_ids', [])
                    and monitor.node_id == source.id and monitor.type == 'ping'
                    and monitor.target == item.get('hostname')):
                continue
        if source is None or source.status == 'removed' or source.last_seen_at is None or item['entry_id'] not in origins:
            archive_logical(db, ledger, key, 'node_removed' if source is None or source.status == 'removed' else 'entry_removed')
    if ledger_row is not None and ledger != json.loads(before):
        ledger_row.value = json.dumps(ledger, ensure_ascii=False); db.flush()
    for source in nodes:
        if source.status == 'removed' or source.last_seen_at is None:
            continue
        for entry in origins.values():
            monitor = ensure_logical_monitor(db, source, entry)
            if monitor is None:
                continue
            owner = state[f"entry:{entry['entry_id']}"]
            occupied = db.query(MonitorGroupMember).filter_by(monitor_id=monitor.id).first()
            if occupied is None:
                db.add(MonitorGroupMember(group_id=owner['group_id'],monitor_id=monitor.id,position=source.id))
                changed = True
            if monitor.id not in owner['attached_ids']:
                owner['attached_ids'].append(monitor.id)
    if row is not None:
        row.value = json.dumps(state, ensure_ascii=False)
    db.flush()
    ledger_row = db.get(AppConfig, LEDGER)
    changed = changed or (ledger_row.value if ledger_row else None) != before
    if changed:
        from app.repositories.config import bump_monitors_version
        bump_monitors_version(db, commit=False)
    return state
