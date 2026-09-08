"""Read-only control-channel freshness. Never rewrite persisted status on GET."""
from datetime import datetime, timezone

HEARTBEAT_TTL = 120

def age_seconds(ts, now=None):
    if ts is None:
        return float('inf')
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - ts).total_seconds()

def node_status(node, now=None):
    if node is None:
        return 'offline'
    if node.status == 'online' and not 0 <= age_seconds(node.last_seen_at, now) <= HEARTBEAT_TTL:
        return 'offline'
    return node.status

def monitor_status(monitor, node, now=None):
    if node_status(node, now) != 'online' or not 0 <= age_seconds(monitor.last_check_at, now) <= max(120, monitor.interval * 3):
        return 'unknown'
    return monitor.status
