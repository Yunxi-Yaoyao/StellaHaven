"""Deployment-owned management entry probes. No DNS or probes on the server."""
import hashlib
from urllib.parse import urlsplit


def applied_origins(db=None):
    """Saved owner selection authorizes probes; deployment private is not consent."""
    from app.services import access_entries
    if db is not None:
        from app.models.config import AppConfig
        saved = db.get(AppConfig, access_entries.KEY)
        value = access_entries.read(db) if saved else access_entries.bootstrap()
        return dict(public=value['public_origin'], private=value.get('private_origin') if saved else None)
    value = access_entries.current()
    if value is None:
        value = access_entries.bootstrap()
        return dict(public=value['public_origin'], private=None)
    return dict(public=value['public_origin'], private=value.get('private_origin'))


def effective_scope(cap):
    """Validate raw source consent before adding bounded deployment consent.

    This is entry-probe permission only, not permission for arbitrary Agent tasks.
    Missing deployment configuration grants no additional private destinations.
    """
    import json
    import os
    from app.services.entry_targets import _entry_scope
    _entry_scope(cap)  # Never let deployment consent repair an invalid raw scope.
    raw = os.environ.get('STELLA_ENTRY_APPROVED_RANGES')
    if raw is None:
        return cap
    if len(raw) > 4096:
        raise ValueError('invalid deployment entry ranges')
    try:
        ranges = json.loads(raw)
    except (ValueError, RecursionError):
        raise ValueError('invalid deployment entry ranges') from None
    # Validate the deployment channel independently, then the combined budget.
    _entry_scope({'approved_ranges': ranges})
    if any('/' not in value for value in ranges):
        raise ValueError('deployment entry ranges require CIDR prefixes')
    merged = dict(cap, approved_ranges=cap.get('approved_ranges', []) + ranges)
    _entry_scope(merged)
    return merged


def manifest(node=None, *, db=None, active_only=True):
    pair = applied_origins(db)
    components = getattr(node, 'components', None)
    cap = components.get('monitoring', {}) if isinstance(components, dict) else ({} if components is None else None)
    entries = []
    for lane in ('public', 'private'):
        origin = pair.get(lane)
        if origin:
            entries.append(dict(entry_id=lane, origin=origin, hostname=urlsplit(origin).hostname,
                version=hashlib.sha256(origin.encode()).hexdigest()[:24]))
    if db is not None and node is not None:
        import json
        from app.models.config import AppConfig
        from app.models.monitor import Monitor
        from app.services.monitor_management import effective_enabled
        row = db.get(AppConfig, LEDGER)
        state = json.loads(row.value) if row else {}
        selected = []
        for entry in entries:
            item = state.get(logical_key(node, entry['entry_id']))
            if item and item.get('lifecycle') == 2 and item.get('origin') == entry['origin']:
                entry['version'] = item['version']
            if not active_only or (item and not item.get('archived') and effective_enabled(db, db.get(Monitor, item['monitor_id']))):
                selected.append(entry)
        entries = selected
    try:
        cap = effective_scope(cap)
        targets = cap.get('targets')
        ranges = cap.get('approved_ranges', [])
        scope_valid = True
    except (ValueError, TypeError):
        # Invalid raw scope must close BOTH channels, never drop only bad members.
        scope_valid, targets, ranges, cap = False, [], [], {}
    return dict(entries=entries, interval=60, max_ips=4, deadline_seconds=12,
                icmp_available=scope_valid and cap.get('ready') is True and isinstance(cap.get('types'),list) and 'ping' in cap['types'],
                targets=targets, approved_ranges=ranges)


def save_channel(db, node, incoming):
    """Monotonic-by-sample merge, serialized with automatic monitor identities."""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select, text
    from app.models.node import Node
    if db.get_bind().dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(1937006960)'))
    node = db.scalar(select(Node).where(Node.id == node.id).with_for_update().execution_options(populate_existing=True))
    current = dict(node.control_channel or {})
    report = incoming.report
    if report is not None:
        known = {e['entry_id']:e for e in manifest(node, db=db, active_only=False)['entries']}
        if report.entry_id is not None and (report.entry_id not in known or known[report.entry_id]['origin'] != report.origin):
            raise ValueError('control entry mismatch')
        if report.sampled_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError('future sample')
        old = current.get('report')
        if old is None or report.sampled_at > datetime.fromisoformat(old['sampled_at']):
            current['report'] = report.model_dump(mode='json')
    # Validate the complete bounded submission before changing any sample.
    from app.services.entry_targets import _entry_ip_allowed
    if incoming.icmp:
        components = node.components
        if not isinstance(components, dict):
            raise ValueError('invalid source capability')
        effective_scope(components.get('monitoring', {}))
    plan = manifest(node, db=db, active_only=False)
    known = {e['entry_id']: e for e in plan['entries']}
    if len({e.entry_id for e in incoming.icmp}) != len(incoming.icmp):
        raise ValueError('duplicate entry')
    for sample in incoming.icmp:
        entry = known.get(sample.entry_id)
        if entry is None or sample.version != entry['version'] or sample.hostname != entry['hostname']:
            raise ValueError('stale entry manifest')
        if sample.sampled_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError('future sample')
        ips = [r.ip for r in sample.results]
        if len(set(ips)) != len(ips) or not all(_entry_ip_allowed(ip, plan['targets'], plan['approved_ranges']) for ip in ips):
            raise ValueError('outside source scope')
        if sample.status == 'complete' and not sample.results:
            raise ValueError('empty complete sample')
    from app.services.entry_monitor_groups import reconcile
    reconcile(db, node)
    latest = {s['entry_id']:s for s in current.get('icmp', [])}
    for sample in incoming.icmp:
        old = latest.get(sample.entry_id)
        if old is not None and sample.sampled_at <= datetime.fromisoformat(old['sampled_at']):
            continue
        _record_icmp(db, node, sample)
        latest[sample.entry_id] = sample.model_dump(mode='json')
    if latest:
        current['icmp'] = list(latest.values())
    node.control_channel = current or None
    if incoming.icmp:
        retire_legacy(db, node.id)


LEDGER = 'entry_monitoring.v1'
RETIRED = 'entry_monitoring.legacy_retired.v1'


def retired_sources(db):
    import json
    from app.models.config import AppConfig
    row=db.get(AppConfig,RETIRED,populate_existing=True)
    return set(json.loads(row.value)) if row else set()


def retire_legacy(db, node_id):
    import json
    from app.models.config import AppConfig
    from app.services import node_monitor_policy as legacy
    legacy._load(db,locked=True)
    retired=retired_sources(db)
    if str(node_id) not in retired:
        retired.add(str(node_id))
        row=db.get(AppConfig,RETIRED)
        if row is None:
            row=AppConfig(key=RETIRED,value='');db.add(row)
        row.value=json.dumps(sorted(retired))
        legacy._bump(db)
        db.flush()


def logical_key(node, entry_id):
    """Installation identity matches the original ownership ledger key."""
    identity = hashlib.sha256((node.token or str(node.created_at)).encode()).hexdigest()
    return f'logical:{node.id}:{identity}:{entry_id}'


def archive_logical(db, state, key, reason):
    """Detach active ownership, retaining the definition and every historical check."""
    from app.models.monitor import MonitorGroupMember
    item = state.pop(key)
    item['archived'] = reason
    item.pop('aggregate_sample', None)
    state[f"archive:{key}:{item['monitor_id']}"] = item
    db.query(MonitorGroupMember).filter_by(monitor_id=item['monitor_id']).delete(synchronize_session=False)


def ensure_generation(db, node, entry):
    import json
    from app.models.config import AppConfig
    from app.models.monitor import Monitor
    from app.services.entry_monitor_groups import owners, PURPOSE
    row = db.get(AppConfig, LEDGER)
    state = json.loads(row.value) if row else {}
    key = logical_key(node, entry['entry_id'])
    item = state.get(key)
    monitor = db.get(Monitor, item['monitor_id']) if item else None
    if item:
        # A deleted/edited old definition is a tombstone, not permission to revive.
        owner = owners(db).get(f"entry:{entry['entry_id']}", {})
        proven = (item.get('purpose') == 'management_entry_icmp' and item.get('logical')
                  and item.get('source_node_id') == node.id and monitor is not None
                  and monitor.node_id == node.id and monitor.type == 'ping'
                  and monitor.target == item.get('hostname')
                  and (item.get('lifecycle') == 2 or
                       (owner.get('purpose') == PURPOSE and monitor.id in owner.get('attached_ids', []))))
        if not proven:
            return None
        if item.get('origin') == entry['origin'] and item.get('lifecycle') == 2:
            return monitor
        archive_logical(db, state, key, 'origin_changed')
    if node.status == 'removed' or node.last_seen_at is None:
        return None
    monitor = Monitor(name=f"{node.name[:40]} → {'默认入口' if entry['entry_id']=='public' else '其他入口'}",
                      node_id=node.id, type='ping', target=entry['hostname'], interval=60, timeout=1, status='unknown')
    db.add(monitor); db.flush()
    state[key] = dict(purpose='management_entry_icmp', logical=True, lifecycle=2,
                      source_node_id=node.id, entry_id=entry['entry_id'], hostname=entry['hostname'],
                      origin=entry['origin'], version=hashlib.sha256(f"{entry['origin']}:{monitor.id}".encode()).hexdigest()[:24], monitor_id=monitor.id)
    if row is None:
        row = AppConfig(key=LEDGER, value=''); db.add(row)
    row.value = json.dumps(state, ensure_ascii=False); db.flush()
    return monitor


def ensure_logical_monitor(db, node, entry):
    """One stable node/entry slot; each changed target starts a separate series."""
    from app.services.entry_monitor_groups import owners
    if owners(db).get(f"entry:{entry['entry_id']}", {}).get('lifecycle') == 2:
        return ensure_generation(db, node, entry)
    import json
    from app.models.config import AppConfig
    from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember
    from app.services.entry_monitor_groups import owners, PURPOSE
    row = db.get(AppConfig, LEDGER)
    state = json.loads(row.value) if row else {}
    key = logical_key(node, entry['entry_id'])
    item = state.get(key)
    if item is None:
        legacy = sorted((v for v in state.values() if not v.get('logical')
                         and v.get('source_node_id') == node.id and v.get('entry_id') == entry['entry_id']),
                        key=lambda v: v['monitor_id'])
        # The old group key, unlike node_id alone, proves the installation.
        owner_key = key[len('logical:'):].rsplit(':', 1)[0]
        ownership = owners(db)
        proof = ownership.get(owner_key)
        if not proof or proof.get('purpose') != PURPOSE or proof.get('source_node_id') != node.id:
            proof = None
        legacy_ids = {v['monitor_id'] for v in legacy}
        if any(k != owner_key and v.get('purpose') == PURPOSE
               and legacy_ids.intersection(v.get('attached_ids', [])) for k, v in ownership.items()):
            proof = None  # another installation also claims these old series
        consumed = {v['monitor_id'] for v in state.values() if v.get('logical')}
        # Unproven deleted owners cannot authorize adoption, but still forbid
        # recreating a group. Negative evidence is deliberately conservative.
        skip_group = any(v.get('purpose') == PURPOSE and v.get('source_node_id') == node.id
                         and db.get(MonitorGroup, v['group_id']) is None for v in ownership.values())
        adopt = bool(legacy and proof and not any(v['monitor_id'] in consumed or v.get('superseded_by') for v in legacy))
        if adopt and proof is not None:
            # Fail closed for the whole old entry on edited/deleted/foreign rows;
            # never take a different IP as a replacement for an identity tombstone.
            for v in legacy:
                m = db.get(Monitor, v['monitor_id'])
                if (v.get('purpose') != 'management_entry_icmp'
                        or v['monitor_id'] not in proof.get('attached_ids', [])
                        or m is None or m.node_id != node.id or m.type != 'ping'
                        or not v.get('ip') or m.target != v['ip']):
                    return None
            mid = legacy[0]['monitor_id']
            monitor = db.get(Monitor, mid)
            member = db.query(MonitorGroupMember).filter_by(monitor_id=mid).first()
            skip_group = skip_group or member is None
            if member is not None:
                group = db.get(MonitorGroup, member.group_id)
                mids = {m.monitor_id for m in db.query(MonitorGroupMember).filter_by(group_id=member.group_id)}
                if (member.group_id == proof['group_id'] and group
                        and group.name == f'{node.name[:57]} → 中心'
                        and legacy_ids <= mids
                        and mids <= set(proof['attached_ids'])):
                    migrated_ids = {v['monitor_id'] for v in legacy}
                    db.query(MonitorGroupMember).filter(MonitorGroupMember.group_id == group.id,
                        MonitorGroupMember.monitor_id.in_(migrated_ids)).delete(synchronize_session=False)
                    for v in legacy:
                        if v['monitor_id'] != mid:
                            v['superseded_by'] = mid
                    db.flush()
                else:
                    # Node rename is indistinguishable from group rename in v1.
                    skip_group = True
            monitor.target = entry['hostname']
        else:
            # No installation proof (or already consumed): retain old IDs/history
            # and start an independent unknown logical measurement.
            monitor = Monitor(name=f"{node.name[:40]} → {'默认入口' if entry['entry_id']=='public' else '内网入口'}",
                node_id=node.id, type='ping', target=entry['hostname'], interval=60, timeout=1, status='unknown')
            db.add(monitor); db.flush()
            mid = monitor.id
        item = dict(purpose='management_entry_icmp', logical=True, source_node_id=node.id,
                    entry_id=entry['entry_id'], hostname=entry['hostname'], monitor_id=mid, skip_group=skip_group)
        if adopt:
            item['legacy_owner_key'] = owner_key
        state[key] = item
        if row is None:
            row = AppConfig(key=LEDGER, value=''); db.add(row)
        row.value = json.dumps(state, ensure_ascii=False); db.flush()
    monitor = db.get(Monitor, item['monitor_id'])
    if (monitor is not None and item.get('purpose') == 'management_entry_icmp'
            and item.get('source_node_id') == node.id and item.get('entry_id') == entry['entry_id']
            and monitor.node_id == node.id and monitor.type == 'ping'
            and monitor.target == item['hostname']):
        if item['hostname'] != entry['hostname']:
            monitor.target = entry['hostname']
            item['hostname'] = entry['hostname']
            item.pop('aggregate_sample', None)
            row.value = json.dumps(state, ensure_ascii=False); db.flush()
        return monitor
    return None


def _record_icmp(db, node, sample):
    """Aggregate one entry sample; detailed per-IP evidence stays in control_channel.

    A complete sample is healthy only when every IP answered. Partial/unavailable
    evidence is not a measured success or a fabricated packet-loss measurement.
    """
    from sqlalchemy import select
    from app.models.monitor import MonitorCheck
    expected = next(e for e in manifest(node, db=db, active_only=False)['entries'] if e['entry_id'] == sample.entry_id)
    monitor = ensure_logical_monitor(db, node, expected)
    if monitor is None or sample.status != 'complete' or not sample.results:
        return
    if any(r.status == 'unavailable' for r in sample.results):
        return
    success = all(r.status == 'up' for r in sample.results)
    lats = [r.latency_ms for r in sample.results if r.status == 'up' and r.latency_ms is not None]
    losses = [r.loss_pct for r in sample.results if r.loss_pct is not None]
    latency = sum(lats)/len(lats) if lats and success else None
    loss = sum(losses)/len(losses) if len(losses) == len(sample.results) else None
    duplicate = db.scalar(select(MonitorCheck.id).where(MonitorCheck.monitor_id == monitor.id,
                                                       MonitorCheck.ts == sample.sampled_at))
    if duplicate is None:
        db.add(MonitorCheck(monitor_id=monitor.id, ts=sample.sampled_at,
                            success=success, latency_ms=latency, loss_pct=loss))
    monitor.last_check_at = sample.sampled_at
    monitor.last_latency_ms = latency
    monitor.status = 'up' if success else 'down'
    # Old per-IP checks at this ID are history, not proof of logical health.
    import json
    from app.models.config import AppConfig
    row = db.get(AppConfig, LEDGER)
    state = json.loads(row.value)
    evidence = sample.model_dump(mode='json')
    state[logical_key(node, sample.entry_id)]['aggregate_sample'] = {
        k: evidence[k] for k in ('version', 'hostname', 'sampled_at')}
    row.value = json.dumps(state, ensure_ascii=False)
    db.flush()


def entry_reason(db, monitor):
    """Read-only, specific health evidence; missing data is never normal."""
    import json
    from datetime import datetime
    from app.models.config import AppConfig
    from app.models.node import Node
    from app.services.server_status import node_status, age_seconds
    row = db.get(AppConfig, LEDGER)
    state = json.loads(row.value) if row else {}
    managed = [v for v in state.values() if v['monitor_id'] == monitor.id]
    from app.monitor_targets import parse_stored_target
    try:
        parsed = parse_stored_target(monitor.type, monitor.target)
    except ValueError:
        return 'invalid_target'
    source = db.get(Node, monitor.node_id)
    if node_status(source) != 'online':
        return 'source_pending' if source is not None and source.status == 'pending' else 'source_offline'
    if managed:
        item = next((v for v in managed if v.get('logical')
                     and state.get(logical_key(source, v['entry_id'])) is v), None)
        if (item is None or item.get('source_node_id') != source.id
                or item.get('purpose') != 'management_entry_icmp' or monitor.type != 'ping'
                or monitor.target != item['hostname']):
            return 'pending'
        plan = manifest(source, db=db, active_only=False)
        expected = next((e for e in plan['entries'] if e['entry_id'] == item['entry_id']), None)
        if expected is None:
            return 'entry_removed'
        sample = next((s for s in (source.control_channel or {}).get('icmp', [])
                       if s['entry_id'] == item['entry_id']), None)
        if sample is not None:
            if (sample['version'] != expected['version'] or sample['hostname'] != expected['hostname']
                    or not 0 <= age_seconds(datetime.fromisoformat(sample['sampled_at'])) <= 180):
                return 'stale'
            if sample['status'] != 'complete':
                return sample['status']
            from app.services.entry_targets import _entry_ip_allowed
            if not all(_entry_ip_allowed(r['ip'], plan['targets'], plan['approved_ranges']) for r in sample['results']):
                return 'outside_scope'
            if any(r['status'] == 'unavailable' for r in sample['results']):
                return 'unavailable'
        if not plan['icmp_available']:
            cap = (source.components or {}).get('monitoring')
            if isinstance(cap, dict) and isinstance(cap.get('types'), list) and 'ping' not in cap['types']:
                return 'unsupported'
            return 'restricted'
        if sample is None and (plan['targets'] is not None or plan['approved_ranges']):
            # DNS must be resolved and scope checked by the source, never by GET.
            return 'scope_pending'
        if (sample is None or not sample['results']
                or item.get('aggregate_sample') != {k: sample[k] for k in ('version', 'hostname', 'sampled_at')}
                or monitor.last_check_at is None
                or age_seconds(monitor.last_check_at, datetime.fromisoformat(sample['sampled_at'])) != 0):
            return 'pending'
        # Never allow a stored per-IP status to contradict the complete evidence.
        expected_status = 'up' if all(r['status'] == 'up' for r in sample['results']) else 'down'
        if monitor.status != expected_status:
            return 'pending'
    if not managed:
        cap = (source.components or {}).get('monitoring')
        if isinstance(cap, dict):
            # Historical Agent types covers tcp/ping availability only, not
            # its implemented HTTP(S)/UDP probes. No versioned exhaustive
            # protocol is deployed here; do not invent one from a version or
            # turn this read projection into a broader worker permission.
            if (isinstance(cap.get('types'), list) and monitor.type in ('tcp', 'ping')
                    and monitor.type not in cap['types']):
                return 'unsupported'
            if cap.get('ready') is not True:
                return 'unavailable'
            targets = cap.get('targets')
            if targets is not None and (not isinstance(targets, list) or parsed.host not in targets):
                return 'outside_scope'
    if monitor.last_check_at is None:
        return 'pending'
    if not 0 <= age_seconds(monitor.last_check_at) <= max(120, monitor.interval*3):
        return 'stale'
    return 'healthy' if monitor.status == 'up' else 'failure' if monitor.status == 'down' else 'pending'


def current_ids(db):
    import json
    from app.models.config import AppConfig
    from app.models.monitor import Monitor
    from app.services.monitor_management import effective_enabled
    row = db.get(AppConfig, LEDGER)
    return {v['monitor_id'] for v in json.loads(row.value).values()
            if (m := db.get(Monitor, v['monitor_id'])) is not None
            and effective_enabled(db, m)
            and entry_reason(db, m) in ('healthy', 'failure')} if row else set()


def superseded_ids(db):
    """Historical per-IP series remain addressable, but are not duplicate cards."""
    import json
    from app.models.config import AppConfig
    row = db.get(AppConfig, LEDGER)
    return {v['monitor_id'] for v in json.loads(row.value).values() if v.get('superseded_by') or v.get('archived')} if row else set()


def removed_ids(db):
    """Hide only proven automatic definitions, never delete history/relations.

    Names and group membership are user-owned and not ownership proof. Edited
    targets/types or foreign/reused node IDs must remain visible for repair.
    """
    import json
    from app.models.config import AppConfig
    from app.models.monitor import Monitor
    from app.models.node import Node
    from app.services.entry_monitor_groups import owners, PURPOSE
    row = db.get(AppConfig, LEDGER)
    state = json.loads(row.value) if row else {}
    ownership = owners(db)
    hidden = set()
    for key, item in state.items():
        source = db.get(Node, item['source_node_id']) if item.get('source_node_id') is not None else None
        monitor = db.get(Monitor, item['monitor_id'])
        if not (source is not None and source.status == 'removed' and monitor is not None
                and item.get('purpose') == 'management_entry_icmp'
                and monitor.node_id == source.id and monitor.type == 'ping'):
            continue
        if item.get('logical'):
            if (key == logical_key(source, item['entry_id'])
                    and monitor.target == item.get('hostname')):
                hidden.add(monitor.id)
        elif (item.get('entry_id') in ('public', 'private') and item.get('ip')
                and monitor.target == item['ip'] and not item.get('superseded_by')):
            # A v1 per-IP row has no installation token. Only its retained
            # original group-owner key can prove that installation. Read the
            # receipt, never migrate a removed node or rewrite its tombstones.
            owner_key = logical_key(source, item['entry_id'])[len('logical:'):].rsplit(':', 1)[0]
            proof = ownership.get(owner_key)
            if (proof and proof.get('purpose') == PURPOSE
                    and proof.get('source_node_id') == source.id
                    and monitor.id in proof.get('attached_ids', [])
                    and not any(k != owner_key and monitor.id in v.get('attached_ids', [])
                                for k, v in ownership.items())
                    and not any(k != key and v.get('monitor_id') == monitor.id
                                for k, v in state.items())):
                hidden.add(monitor.id)
    return hidden


def managed_ids(db):
    import json
    from app.models.config import AppConfig
    row=db.get(AppConfig,LEDGER)
    return {item['monitor_id'] for item in json.loads(row.value).values()} if row else set()
