"""Bounded explicit monitor groups: presentation metadata, never probe scheduling."""

from sqlalchemy.orm import Session
from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember
from app.services import monitor as monitor_svc


def aggregate_status(states: list[str], policy: str) -> str:
    # Empty groups are hidden by list_groups; only fresh success is normal.
    if policy == 'any':
        return 'up' if states and all(s == 'up' for s in states) else 'down'
    if policy == 'all':
        return 'up' if 'up' in states else 'down'
    raise ValueError('未知聚合规则')


def list_groups(db: Session, *, include_empty: bool = False) -> list[dict]:
    from app.services.entry_monitor_groups import owned_groups
    owners = owned_groups(db)
    monitors = {m.id: m for m in monitor_svc.list_monitors(db)}
    memberships: dict[int, list[int]] = {}
    for member in db.query(MonitorGroupMember).order_by(MonitorGroupMember.position).all():
        memberships.setdefault(member.group_id, []).append(member.monitor_id)
    result = []
    for group in db.query(MonitorGroup).order_by(MonitorGroup.id).all():
        # Display filtering only: preserve durable membership/UUID/tombstones.
        ids = [mid for mid in memberships.get(group.id, []) if mid in monitors]
        owner = owners.get(group.id, {})
        system = owner.get('lifecycle') == 2
        if not ids and not system and not include_empty:
            continue
        from app.services.entry_monitoring import applied_origins
        origin = applied_origins(db).get(owner.get('entry_id')) if system else None
        eligible = [mid for mid in ids if monitors[mid].visible and monitors[mid].effective_enabled and group.enabled]
        states = [monitors[mid].status for mid in eligible]
        result.append(dict(id=group.id, name=group.name, child_ids=ids, eligible_child_ids=eligible,
                           visible=group.visible, enabled=group.enabled,
                           automatic=system, source_node_id=owners.get(group.id, {}).get('source_node_id'),
                           failure_policy=group.failure_policy, rotation_seconds=group.rotation_seconds,
                           entry_id=owner.get('entry_id') if system else None, target_origin=origin,
                           availability_reason=('entry_not_configured' if not origin else 'no_connected_nodes') if system and not ids else None,
                           status=aggregate_status(states, group.failure_policy) if ids else None,
                           down_count=states.count('down'), up_count=states.count('up'), unknown_count=states.count('unknown')))
    return result


def save_group(db: Session, group_id: int | None, *, name: str, child_ids: list[int] | None = None,
               failure_policy: str = 'any', rotation_seconds: int = 0,
               visible: bool | None = None, enabled: bool | None = None) -> dict:
    if not name.strip() or len(name) > 64:
        raise ValueError('名称需为 1–64 个字符')

    if failure_policy not in ('any', 'all') or rotation_seconds not in (0, 8, 15, 30):
        raise ValueError('聚合规则或轮转周期不正确')
    try:
        from app.services.entry_monitor_groups import lock, owned_groups
        lock(db)
        automatic = owned_groups(db).get(group_id, {}).get('lifecycle') == 2
        existing_ids = [m.monitor_id for m in db.query(MonitorGroupMember).filter_by(group_id=group_id).order_by(MonitorGroupMember.position)] if group_id else []
        if automatic and child_ids is not None and child_ids != existing_ids:
            raise ValueError('系统入口监控组成员只读，由实际接入节点和入口设置管理')
        if child_ids is None:
            child_ids = existing_ids
        from app.services.entry_monitoring import managed_ids
        if not automatic and set(child_ids).intersection(managed_ids(db)) - set(existing_ids):
            raise ValueError('系统入口监控项及归档不可手动加入其他监控组')
        if not (0 if automatic else 1) <= len(child_ids) <= (10000 if automatic else 12) or len(set(child_ids)) != len(child_ids):
            raise ValueError('监控组至少需要 1 个不同监控项，普通监控组最多 12 个')
        group = db.query(MonitorGroup).filter_by(id=group_id).with_for_update().populate_existing().first() if group_id else MonitorGroup()
        if group is None:
            raise ValueError('监控组不存在')
        children = db.query(Monitor).filter(Monitor.id.in_(child_ids)).with_for_update().all()
        if len(children) != len(child_ids):
            raise ValueError('所选监控项不存在，请刷新后重试')
        conflict = db.query(MonitorGroupMember).filter(MonitorGroupMember.monitor_id.in_(child_ids))
        if group_id:
            conflict = conflict.filter(MonitorGroupMember.group_id != group_id)
        if conflict.count():
            raise ValueError('监控项已属于其他监控组，请先从原分组移出')
        group.name = name.strip()
        group.failure_policy = failure_policy
        group.rotation_seconds = rotation_seconds
        if visible is not None:
            group.visible = visible
        if enabled is not None:
            group.enabled = enabled
        db.add(group)
        db.flush()
        gid = group.id
        existing = db.query(MonitorGroupMember).filter_by(group_id=gid).order_by(MonitorGroupMember.position).all()
        if [member.monitor_id for member in existing] != child_ids:
            # A visibility/scheduling switch must never recreate relations.
            db.query(MonitorGroupMember).filter(MonitorGroupMember.group_id == gid).delete(synchronize_session=False)
            db.add_all([MonitorGroupMember(group_id=gid, monitor_id=mid, position=i) for i,mid in enumerate(child_ids)])
        from app.repositories.config import bump_monitors_version
        bump_monitors_version(db)
    except Exception:
        db.rollback()
        raise
    return next(g for g in list_groups(db) if g['id'] == gid)


class GroupScopeConflict(ValueError):
    """The explicit confirmation no longer matches the transaction's scope."""


def _delete_protected(db, group, ids):
    # Refresh ownership ledgers after acquiring the existing lifecycle locks;
    # a reused Session must not decide ownership from a stale identity map.
    from app.models.config import AppConfig
    from app.services.entry_monitor_groups import KEY, owned_groups
    from app.services.entry_monitoring import LEDGER, managed_ids
    for key in (KEY, LEDGER):
        db.get(AppConfig, key, populate_existing=True)
    return (owned_groups(db).get(group.id, {}).get('lifecycle') == 2
            or bool(set(ids).intersection(managed_ids(db))))


def deletion_state(db: Session, group_id: int, expected_child_ids: list[int], expected_stable_uuid: str | None = None) -> dict:
    """Bounded, read-only preview/readback; never infer deletion from list pagination."""
    group = db.get(MonitorGroup, group_id, populate_existing=True)
    children = (db.query(Monitor).join(MonitorGroupMember, MonitorGroupMember.monitor_id == Monitor.id)
                .filter(MonitorGroupMember.group_id == group_id)
                .order_by(MonitorGroupMember.position).limit(13).populate_existing().all()) if group else []
    ids = [m.id for m in children]
    protected = bool(group and (_delete_protected(db, group, ids) or len(ids) > 12))
    remaining = [mid for (mid,) in db.query(Monitor.id).filter(Monitor.id.in_(expected_child_ids)).order_by(Monitor.id)] if expected_child_ids else []
    return dict(stable_uuid=group.stable_uuid if group else None,
                identity_matches=bool(group and group.stable_uuid == expected_stable_uuid) if expected_stable_uuid is not None else None,
                group_exists=group is not None, name=group.name if group else None,
                children=[dict(id=m.id, name=m.name, type=m.type, target=m.target) for m in children],
                protected=protected, remaining_child_ids=remaining)


def delete_group(db: Session, group_id: int, expected_child_ids: list[int], expected_stable_uuid: str) -> None:
    """Delete the confirmed group and children atomically, NOT the dissolve contract.

    Lock order matches membership writers: entry/group advisory locks, group row,
    then monitor rows ordered by ID. FK parent locks fence concurrent checks/MTR.
    Every history/reference query is scoped to the confirmed <=12 IDs.
    """
    from app.services.entry_monitor_groups import lock
    from app.models.monitor import MonitorCheck
    from app.models.task import MtrTask
    from app.repositories.config import bump_monitors_version
    try:
        if (len(expected_child_ids) > 12 or len(set(expected_child_ids)) != len(expected_child_ids)
                or any(type(mid) is not int or mid <= 0 for mid in expected_child_ids)):
            raise ValueError('确认成员范围不正确')
        lock(db)
        group = db.query(MonitorGroup).filter_by(id=group_id).with_for_update().populate_existing().first()
        if group is None:
            raise GroupScopeConflict('监控组已不存在，请重新读取核对')
        # Check immutable identity under the row lock, before any write or scope
        # expansion: restore may explicitly reuse an ordinary numeric ID.
        if group.stable_uuid != expected_stable_uuid:
            raise GroupScopeConflict('监控组身份已变化，请重新读取并确认')
        ids = [mid for (mid,) in db.query(MonitorGroupMember.monitor_id).filter_by(group_id=group_id).order_by(MonitorGroupMember.monitor_id).limit(13)]
        if _delete_protected(db, group, ids):
            raise ValueError('系统入口监控组或 entry_icmp 监控项不可手动删除')
        if set(ids) != set(expected_child_ids):
            raise GroupScopeConflict('组成员范围已变化，请重新读取并确认全部成员')
        children = db.query(Monitor).filter(Monitor.id.in_(ids)).order_by(Monitor.id).with_for_update().populate_existing().all() if ids else []
        if len(children) != len(ids):
            raise GroupScopeConflict('组成员范围已变化，请重新读取并确认全部成员')
        # Same lifecycle as item deletion: detach (do not erase) MTR, erase
        # checks and memberships before parents; no per-item commit/replay.
        if ids:
            db.query(MtrTask).filter(MtrTask.monitor_id.in_(ids)).update({'monitor_id': None}, synchronize_session=False)
            db.query(MonitorCheck).filter(MonitorCheck.monitor_id.in_(ids)).delete(synchronize_session=False)
        db.query(MonitorGroupMember).filter_by(group_id=group_id).delete(synchronize_session=False)
        for child in children:
            db.delete(child)
        db.delete(group)
        bump_monitors_version(db)  # sole commit: group/members/checks/MTR/version
    except Exception:
        db.rollback()
        raise


RECEIPTS = 'monitor_group.create_receipts.v1'
MAX_RECEIPTS = 128


def _receipt_slot(request_key, session_id):
    import hashlib
    return hashlib.sha256((str(session_id)+':'+request_key).encode()).hexdigest()


def creation_receipt(db, request_key, session_id):
    import json
    from app.models.config import AppConfig
    row = db.get(AppConfig, RECEIPTS, populate_existing=True)
    receipt = json.loads(row.value).get(_receipt_slot(request_key, session_id)) if row else None
    return {k: receipt[k] for k in ('group_id', 'monitor_ids')} if receipt else None


def create_group(db, data, *, session_id):
    """New items + relation + idempotency receipt commit together or not at all.

    One bounded application-config value stores hashes/IDs only (no targets,
    request body or session credential). An absent/evicted receipt is inconclusive.
    """
    import hashlib
    import json
    from app.models.config import AppConfig
    from app.models.node import Node
    from app.services.entry_monitor_groups import lock
    from app.repositories.config import bump_monitors_version
    slot = _receipt_slot(data.request_key, session_id)
    digest = hashlib.sha256(data.model_dump_json(exclude={'request_key'}).encode()).hexdigest()
    try:
        lock(db)
        row = db.get(AppConfig, RECEIPTS, populate_existing=True)
        receipts = json.loads(row.value) if row else {}
        old = receipts.get(slot)
        if old:
            if old['digest'] != digest:
                raise ValueError('同一创建请求不能更换内容')
            group = next((g for g in list_groups(db) if g['id'] == old['group_id']), None)
            if group is None:
                raise ValueError('原创建请求对应监控组已被移除，请核对记录')
            return group
        if not data.name.strip():
            raise ValueError('名称不能为空')
        group = MonitorGroup(name=data.name.strip(), failure_policy=data.failure_policy, rotation_seconds=data.rotation_seconds)
        db.add(group); db.flush()
        ids = []
        for position, item in enumerate(data.items):
            source = db.get(Node, item.node_id)
            if source is None or source.status == 'removed':
                raise ValueError('探测节点不存在')
            if not item.name.strip() or not item.target.strip() or item.type not in ('ping','tcp','udp','http','https') or not 10 <= item.interval <= 86400 or not 1 <= item.timeout <= 120:
                raise ValueError('监控项名称、目标、类型或采样周期不正确')
            from app.schemas.monitor import MonitorCreate
            validated = MonitorCreate.model_validate(item.model_dump())
            monitor = Monitor(**(validated.model_dump() | {'name':item.name.strip()}), status='unknown')
            db.add(monitor); db.flush(); ids.append(monitor.id)
            db.add(MonitorGroupMember(group_id=group.id, monitor_id=monitor.id, position=position))
        gid = group.id
        receipts[slot] = dict(digest=digest, group_id=gid, monitor_ids=ids)
        while len(receipts) > MAX_RECEIPTS:
            del receipts[next(iter(receipts))]
        if row is None:
            row = AppConfig(key=RECEIPTS, value=''); db.add(row)
        row.value = json.dumps(receipts)
        bump_monitors_version(db)  # the only commit: all new definitions/receipt/version
        return next(g for g in list_groups(db) if g['id'] == gid)
    except Exception:
        db.rollback()
        raise


def create_child(db: Session, group_id: int, data) -> Monitor:
    """Create an ordinary scheduled probe and attach it in ONE transaction."""
    from app.services.entry_monitor_groups import lock
    from app.models.node import Node
    from app.repositories.config import bump_monitors_version
    try:
        lock(db)
        from app.services.entry_monitor_groups import owned_groups
        if owned_groups(db).get(group_id, {}).get('lifecycle') == 2:
            raise ValueError('系统入口监控组不能手动添加成员或解散')
        if db.get(MonitorGroup, group_id) is None:
            raise ValueError('监控组不存在')
        members = db.query(MonitorGroupMember).filter_by(group_id=group_id).all()
        if len(members) >= 12:
            raise ValueError('监控组最多 12 个监控项')
        source = db.get(Node, data.node_id)
        if source is None or source.status == 'removed':
            raise ValueError('探测节点不存在')
        from app.schemas.monitor import MonitorCreate
        validated = MonitorCreate.model_validate(data.model_dump())
        monitor = Monitor(**validated.model_dump(), status='unknown')
        db.add(monitor)
        db.flush()
        db.add(MonitorGroupMember(group_id=group_id, monitor_id=monitor.id,
                                  position=max((m.position for m in members), default=-1)+1))
        bump_monitors_version(db)  # commits probe + membership together
        return monitor
    except Exception:
        db.rollback()
        raise


def remove_group(db: Session, group_id: int) -> None:
    # Dissolving a parent removes membership only; children/checks/MTR remain untouched.
    try:
        from app.services.entry_monitor_groups import lock
        lock(db)
        from app.services.entry_monitor_groups import owned_groups
        if owned_groups(db).get(group_id, {}).get('lifecycle') == 2:
            raise ValueError('系统入口监控组不能手动添加成员或解散')
        db.query(MonitorGroupMember).filter_by(group_id=group_id).delete(synchronize_session=False)
        db.query(MonitorGroup).filter(MonitorGroup.id == group_id).delete(synchronize_session=False)
        # Removing the group's scheduling overlay can re-enable retained probes.
        # Definition changes and Agent config invalidation must commit together.
        from app.repositories.config import bump_monitors_version
        bump_monitors_version(db)
    except Exception:
        db.rollback()
        raise
