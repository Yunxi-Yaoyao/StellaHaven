"""Explicit source/host roles + durable, idempotent node reachability monitoring.

AppConfig is the existing persistent store. A single PostgreSQL transaction lock
serializes policy CAS, creation and tombstones across workers; no schema change,
no backend probes, local installation or inferred host/NAT identity.
"""
import ipaddress
import json
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.config import AppConfig
from app.models.node import Node
from app.models.monitor import Monitor
from app.services.server_status import node_status

KEY = 'node_monitor_policy_v1'
LOCK = 1937006958
DEFAULT = {'revision': 0, 'enabled': True, 'source_node_id': None,
           'host_node_id': None, 'interval': 60, 'managed': {}}


def _load(db, *, locked=False):
    if locked and db.get_bind().dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK})
    row = db.scalar(select(AppConfig).where(AppConfig.key == KEY).execution_options(populate_existing=True))
    return json.loads(row.value) if row else {**DEFAULT, 'managed': {}}


def _save(db, state):
    row = db.get(AppConfig, KEY)
    if row is None:
        row = AppConfig(key=KEY, value=''); db.add(row)
    row.value = json.dumps(state, ensure_ascii=False)
    db.flush()


def _bump(db):
    from app.repositories.config import bump_monitors_version
    bump_monitors_version(db, commit=False)


def _node(db, identity):
    obj = db.get(Node, identity) if identity is not None else None
    return obj if obj is not None and obj.status != 'removed' else None


def capability(source):
    if source is None or node_status(source) != 'online':
        return None
    cap = (source.components or {}).get('monitoring')
    if not isinstance(cap, dict) or cap.get('ready') is not True:
        return None
    if not isinstance(cap.get('types'), list) or 'ping' not in cap['types']:
        return None
    # A restricted source must never silently become unrestricted on bad input.
    if 'targets' in cap and (not isinstance(cap['targets'], list) or
                            not all(isinstance(v, str) for v in cap['targets'])):
        return None
    return cap


def safe_target(value):
    # Do not resolve DNS or infer a target from a heartbeat/NAT source address.
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local)


def _reconcile(db, state):
    source = _node(db, state['source_node_id'])
    cap = capability(source)
    # Entry ICMP retirement never retires a different node-reachability target.
    # Invalidate already-cached empty Agent configs once, including after restart;
    # retain the retirement ledger for its entry ownership/history semantics.
    from app.services.entry_monitoring import retired_sources
    retired = retired_sources(db)
    changed = False
    marker = 'node_monitor_policy.dispatch.v2'
    if db.get(AppConfig, marker) is None and any(
            str(e['source_node_id']) in retired for e in state['managed'].values()):
        # Separate receipt: old backend readers forbid unknown policy fields.
        db.add(AppConfig(key=marker, value='1'))
        changed = True
    if not state['enabled'] or cap is None or source is None:
        return changed
    for target in db.scalars(select(Node).where(Node.status != 'removed').order_by(Node.id)):
        key = str(target.id)
        if target.id == source.id or key in state['managed'] or not safe_target(target.host):
            continue
        if 'targets' in cap and target.host not in cap['targets']:
            continue
        # Own a separate identity; never adopt/pause a user's manual monitor.
        item = Monitor(name=f'节点可达性 · {target.name}'[:64], node_id=source.id,
                       type='ping', target=target.host, interval=state['interval'],
                       timeout=2, status='unknown')
        db.add(item); db.flush()
        state['managed'][key] = {'target_node_id': target.id, 'source_node_id': source.id,
                                'monitor_id': item.id, 'suppressed': False}
        changed = True
    return changed


def reconcile(db: Session):
    state = _load(db, locked=True)
    if _reconcile(db, state):
        _save(db, state); _bump(db)
    db.commit()


def read(db: Session):
    state = _load(db)
    source = _node(db, state['source_node_id'])
    managed = []
    for entry in state['managed'].values():
        item = db.get(Monitor, entry['monitor_id'])
        managed.append({**entry, 'exists': item is not None,
                        'paused': _paused(db, state, entry)})
    pending = []
    cap = capability(source)
    for obj in db.scalars(select(Node).where(Node.status != 'removed').order_by(Node.id)):
        if str(obj.id) in state['managed'] or obj.id == state['source_node_id']:
            continue
        reason = ('disabled' if not state['enabled'] else 'source_not_ready' if cap is None else
                  'numeric_target_required' if not safe_target(obj.host) else
                  'outside_source_scope' if 'targets' in cap and obj.host not in cap['targets'] else 'waiting')
        pending.append({'node_id': obj.id, 'reason': reason})
    from app.schemas.node_monitor_policy import ProbeTestTarget
    from pydantic import ValidationError
    test_targets = []
    if cap is not None and isinstance(cap.get('test_targets'), list):
        for raw in cap['test_targets'][:12]:
            try:
                target = ProbeTestTarget.model_validate(raw)
                host = target.target if target.type == 'ping' else target.target.rsplit(':', 1)[0]
                if 'targets' in cap and host not in cap['targets']:
                    continue
                test_targets.append(target.model_dump())
            except ValidationError:
                continue
    return {**state, 'managed': managed, 'pending': pending,
            'source_ready': cap is not None,
            'source_scope': cap.get('targets') if cap else None,
            'source_test_targets': test_targets}


def update(db: Session, fields):
    state = _load(db, locked=True)
    if fields['revision'] != state['revision']:
        db.rollback()
        raise HTTPException(409, '策略已变化，请重新读取后保存')
    for key in ('source_node_id', 'host_node_id'):
        identity = fields[key]
        if identity is not None and _node(db, identity) is None:
            db.rollback()
            raise HTTPException(422, '绑定节点不存在或已移除')
    host = _node(db, fields['host_node_id'])
    host_cap = (host.components or {}).get('monitoring') if host is not None else None
    if isinstance(host_cap, dict) and host_cap.get('scope') == 'container':
        db.rollback()
        raise HTTPException(422, '容器测试源不是宿主机，不能绑定为真实宿主节点')
    state.update({k: fields[k] for k in ('enabled', 'source_node_id', 'host_node_id', 'interval')})
    state['revision'] += 1
    _reconcile(db, state)
    _save(db, state); _bump(db); db.commit()
    return read(db)


def suppress(db: Session, target_node_id: int, suppressed: bool):
    state = _load(db, locked=True)
    entry = state['managed'].get(str(target_node_id))
    if entry is None:
        db.rollback(); raise HTTPException(404, '自动监控关联不存在')
    entry['suppressed'] = suppressed
    state['revision'] += 1
    _save(db, state); _bump(db); db.commit()
    return read(db)


def _paused(db, state, entry):
    """Validate the owned node measurement, not the source's entry lifecycle."""
    source = _node(db, entry['source_node_id'])
    target = _node(db, entry['target_node_id'])
    item = db.get(Monitor, entry['monitor_id'])
    cap = capability(source)
    from app.services.entry_monitoring import managed_ids
    return (not state['enabled'] or entry['suppressed'] or entry['monitor_id'] in managed_ids(db) or
            state['source_node_id'] != entry['source_node_id'] or
            target is None or source is None or target.id == source.id or
            item is None or item.type != 'ping' or not safe_target(item.target) or
            target.host != item.target or item.node_id != source.id or cap is None or
            ('targets' in cap and item.target not in cap['targets']))


def dispatched(db: Session, monitors):
    state = _load(db)
    paused = {e['monitor_id'] for e in state['managed'].values() if _paused(db, state, e)}
    from app.services.entry_monitoring import managed_ids
    paused.update(managed_ids(db))  # entry probes have a separate bounded scheduler
    from app.services.monitor_management import effective_enabled
    return [m for m in monitors if m.id not in paused and effective_enabled(db, m)]


def host_node(db: Session):
    return _node(db, _load(db)['host_node_id'])


def ensure_local_host(db: Session, platform: str):
    import secrets
    state = _load(db, locked=True)
    obj = _node(db, state['host_node_id'])
    if obj is None:
        obj = Node(name='Stella', platform=platform, host='127.0.0.1',
                   status='pending', token=secrets.token_urlsafe(32))
        db.add(obj); db.flush()
        from app.services.alerts import create_node_interruption_rule
        create_node_interruption_rule(db, obj)
        state['host_node_id'] = obj.id
        state['revision'] += 1
        _save(db, state)
    db.commit()
    return obj
