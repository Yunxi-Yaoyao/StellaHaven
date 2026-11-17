"""User-selected WG probes reuse rule JSONB and map report transport.

Never configure host networking. Discovered identity, AllowedIPs and actual agent
kernel routing must all agree. This is a single direction, not a topology link.
"""
from datetime import datetime, timezone
import hashlib
import json
from app.services import server_map as m


def target_id(binding):
    return 'manual:' + hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def binding_for(rule):
    try:
        condition = rule.condition
        if not isinstance(condition, dict) or set(condition) != {'wg_manual'}:
            return None
        binding = m.ManualProbeBinding.model_validate(condition['wg_manual']).model_dump()
        return binding if rule.target == target_id(binding) else None
    except (ValueError, TypeError):
        return None


def _current(binding, nodes, snapshots, now):
    intent = {k: binding[k] for k in ('node_id', 'interface', 'target')}
    try:
        return m.bind_manual_probe(intent, nodes, snapshots, now=now) == binding
    except (ValueError, TypeError):
        return False


def probe_targets(rules, node_id, nodes, snapshots, *, now=None):
    now = now or datetime.now(timezone.utc)
    result = []
    snap = m._safe_snapshot(snapshots.get(node_id))
    if not snap or snap['wireguard'].get('manual_probe_version') != 1:
        return result  # Old agents must never receive targets needing the new route gate.
    for rule in rules:
        b = binding_for(rule)
        if (not b or b['node_id'] != node_id or not rule.enabled or rule.archived
                or not _current(b, nodes, snapshots, now)):
            continue
        result.append({k:b[k] for k in ('interface','interface_key_id','peer_key_id','target')} | {'manual':True})
    return result[:8]


def health(rule, nodes, snapshots, *, now=None):
    now = now or datetime.now(timezone.utc)
    result = dict(health='unknown', reason='missing_or_changed_discovery', checked_at=None)
    b = binding_for(rule)
    if not b or not _current(b, nodes, snapshots, now):
        return result
    snap = m._safe_snapshot(snapshots.get(b['node_id']))
    if snap['wireguard'].get('manual_probe_version') != 1:
        result['reason'] = 'agent_upgrade_required'
        return result
    iface = next(i for i in snap['wireguard']['interfaces'] if i['name'] == b['interface'])
    peer = next(p for p in iface['peers'] if p['public_key_id'] == b['peer_key_id'])
    matches = [p for p in peer.get('manual_probes',[]) if p['target'] == b['target']]
    result['reason'] = 'missing_or_expired_probe'
    if len(matches) != 1:
        return result
    probe = matches[0]
    age = (now-datetime.fromisoformat(probe['checked_at'].replace('Z','+00:00'))).total_seconds()
    created = getattr(rule, 'created_at', None)
    checked = datetime.fromisoformat(probe['checked_at'].replace('Z','+00:00'))
    if 0 <= age <= m.TTL and (created is None or checked >= created):
        result.update(health=probe['status'], reason=probe.get('reason'), checked_at=probe['checked_at'])
    return result


def node_rules(db, node_id):
    from app.models.alert import AlertRule
    return (db.query(AlertRule).filter(AlertRule.kind=='wg_link', AlertRule.schema_version==1,
        AlertRule.archived.is_(False), AlertRule.condition['wg_manual']['node_id'].as_integer()==node_id)
        .order_by(AlertRule.id).all())


def prepare(db, value, *, now=None):
    from sqlalchemy import text
    data = m.ManualProbeIntent.model_validate(value).model_dump()
    # Serialize per-node admission; disabled-but-unarchived rules retain capacity.
    db.execute(text('SELECT pg_advisory_xact_lock(:scope,:node)'), {'scope':130026,'node':data['node_id']})
    if len(node_rules(db,data['node_id'])) >= 8:
        raise ValueError('每个源节点最多配置 8 个手动 WG 端点')
    nodes, snapshots, _ = m._read_map_data(db)
    binding = m.bind_manual_probe(data,nodes,snapshots,now=now)
    return target_id(binding), {'wg_manual':binding}
