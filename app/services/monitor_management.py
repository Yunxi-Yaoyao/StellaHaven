"""Persisted scheduling gate shared by ordinary probes, entry plans and alerts.

Visibility never enters this predicate. A group's switch overlays, rather than
rewrites, each member's independently persisted switch. No writes on reads.
"""
from app.models.monitor import MonitorGroup, MonitorGroupMember


def effective_enabled(db, monitor):
    if monitor is None or not monitor.enabled:
        return False
    disabled_group = (db.query(MonitorGroup.id).join(MonitorGroupMember,
        MonitorGroupMember.group_id == MonitorGroup.id)
        .filter(MonitorGroupMember.monitor_id == monitor.id, MonitorGroup.enabled.is_(False)).first())
    return disabled_group is None
