"""Atomic item batches; reuse group lifecycle lock and bounded receipt storage."""
import hashlib
import json
from app.models.config import AppConfig
from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember
from app.models.node import Node
from app.schemas.monitor import MonitorCreate
from app.services.monitor_groups import RECEIPTS, MAX_RECEIPTS, _receipt_slot
from app.services.entry_monitor_groups import lock
from app.repositories.config import bump_monitors_version


class BatchConflict(ValueError):
    pass


def receipt(db, key, session_id):
    row = db.get(AppConfig, RECEIPTS, populate_existing=True)
    found = json.loads(row.value).get(_receipt_slot('batch:'+key, session_id)) if row else None
    return {k: found[k] for k in ('group_id', 'monitor_ids')} if found else None


def create(db, data, *, session_id):
    slot = _receipt_slot('batch:'+data.request_key, session_id)
    digest = hashlib.sha256(data.model_dump_json(exclude={'request_key'}).encode()).hexdigest()
    try:
        lock(db)
        row = db.get(AppConfig, RECEIPTS, populate_existing=True)
        receipts = json.loads(row.value) if row else {}
        old = receipts.get(slot)
        if old:
            if old['digest'] != digest:
                raise BatchConflict('同一创建请求不能更换内容')
            # Missing/deleted original rows never authorize recreation.
            return {k: old[k] for k in ('group_id', 'monitor_ids')}
        position = 0
        if data.group_id is not None:
            from app.services.entry_monitor_groups import owned_groups
            group = db.query(MonitorGroup).filter_by(id=data.group_id).populate_existing().with_for_update().one_or_none()
            if group is None or not data.expected_group_uuid or group.stable_uuid != data.expected_group_uuid:
                raise BatchConflict('监控组身份已变化，请重新读取')
            if owned_groups(db).get(group.id, {}).get('lifecycle') == 2:
                raise ValueError('系统入口监控组不能手动添加成员')
            members = db.query(MonitorGroupMember).filter_by(group_id=group.id).all()
            if len(members)+len(data.items) > 12:
                raise ValueError('监控组最多 12 个监控项')
            position = max((m.position for m in members), default=-1)+1
        elif data.expected_group_uuid is not None:
            raise ValueError('独立监控不能指定组身份')
        ids = []
        for item in data.items:
            validated = MonitorCreate.model_validate(item.model_dump())
            source = db.get(Node, validated.node_id)
            if source is None or source.status == 'removed':
                raise ValueError('探测节点不存在')
            monitor = Monitor(**validated.model_dump(), status='unknown')
            db.add(monitor); db.flush(); ids.append(monitor.id)
            if data.group_id is not None:
                db.add(MonitorGroupMember(group_id=data.group_id, monitor_id=monitor.id, position=position))
                position += 1
        result = dict(group_id=data.group_id, monitor_ids=ids)
        receipts[slot] = dict(digest=digest, **result)
        while len(receipts) > MAX_RECEIPTS:
            del receipts[next(iter(receipts))]
        if row is None:
            row = AppConfig(key=RECEIPTS, value=''); db.add(row)
        row.value = json.dumps(receipts)
        bump_monitors_version(db)
        return result
    except Exception:
        db.rollback()
        raise
