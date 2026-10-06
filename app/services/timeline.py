"""Read existing records, not synthetic event histories. Each source is bounded."""
from datetime import timezone
import json
from sqlalchemy import or_, String, cast, func
from app.models.node import NodeStatusEvent
from app.models.alert import AlertRule, AlertEvent
from app.models.monitor import Monitor
from app.models.task import IperfTask, MtrTask, ComponentTask, AgentCommand, NetTask
from app.models.document import Document
from app.models.config import AppConfig


def literal_like(term):
    return '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def timeline_records(db, node_id=None, workspace_id=None, limit=100, q=''):
    items = []
    like = literal_like(q)
    def add(kind, id_, label, ts, node, path=None, state=None):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        items.append({'kind': kind, 'id': str(id_), 'label': label, 'ts': ts,
                      'node_id': node, 'path': path or '/status/' + str(node), 'state': state})
    events = db.query(NodeStatusEvent.id, NodeStatusEvent.node_id, NodeStatusEvent.status, NodeStatusEvent.ts, NodeStatusEvent.reason)
    if node_id is not None:
        events = events.filter(NodeStatusEvent.node_id == node_id)
    if q:
        events = events.filter(or_(NodeStatusEvent.reason.ilike(like, escape='\\'), NodeStatusEvent.status.ilike(like, escape='\\')))
    for e in events.order_by(NodeStatusEvent.ts.desc(), NodeStatusEvent.id.desc()).limit(limit + 1).all():
        add('node_status', e.id, e.reason or e.status, e.ts, e.node_id, state=e.status)
    alerts = db.query(AlertEvent.id, AlertEvent.ts, AlertEvent.message, AlertEvent.event, AlertRule.target, AlertRule.link).join(AlertRule, AlertRule.id == AlertEvent.rule_id).filter(AlertRule.kind == 'node_offline')
    if node_id is not None:
        alerts = alerts.filter(AlertRule.target == str(node_id))
    if q:
        alerts = alerts.filter(AlertEvent.message.ilike(like, escape='\\'))
    for e in alerts.order_by(AlertEvent.ts.desc(), AlertEvent.id.desc()).limit(limit + 1).all():
        if e.target.isdecimal():
            add('alert', e.id, e.message, e.ts, int(e.target), state=e.event)
    monitor_alerts = db.query(AlertEvent.id, AlertEvent.ts, AlertEvent.message, AlertEvent.event, Monitor.node_id).join(AlertRule, AlertRule.id == AlertEvent.rule_id).join(Monitor, AlertRule.target == cast(Monitor.id, String)).filter(AlertRule.kind == 'monitor_down')
    if node_id is not None:
        monitor_alerts = monitor_alerts.filter(Monitor.node_id == node_id)
    if q:
        monitor_alerts = monitor_alerts.filter(AlertEvent.message.ilike(like, escape='\\'))
    for e in monitor_alerts.order_by(AlertEvent.ts.desc(), AlertEvent.id.desc()).limit(limit + 1).all():
        add('alert', e.id, e.message, e.ts, e.node_id, state=e.event)
    for model, kind, node_col, label_col in [(IperfTask, 'iperf_task', IperfTask.client_node_id, IperfTask.mode),
            (MtrTask, 'mtr_task', MtrTask.node_id, MtrTask.target),
            (ComponentTask, 'component_task', ComponentTask.node_id, ComponentTask.component),
            (AgentCommand, 'command_task', AgentCommand.node_id, AgentCommand.status),
            (NetTask, 'net_task', NetTask.node_id, NetTask.kind)]:
        query = db.query(model.id, node_col.label('node'), label_col.label('label'), model.created_at, model.status)
        if node_id is not None:
            query = query.filter(or_(node_col == node_id, IperfTask.server_node_id == node_id) if model is IperfTask else node_col == node_id)
        if q:
            query = query.filter(label_col.ilike(like, escape='\\'))
        for task in query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1).all():
            # Timestamp = creation, state = current status. Never invent finish events.
            add(kind, task.id, task.label, task.created_at, node_id or task.node, state=task.status)
    if workspace_id is not None and node_id is not None:
        # Only associations owned by this feature; no provider config or body reads.
        # Match canonical UUID keys in both PostgreSQL and isolated SQLite,
        # filtering valid workspace documents before applying the result budget.
        note_key = 'notenode:' + func.replace(cast(Document.id, String), '-', '')
        notes = db.query(Document.id, Document.title, Document.updated_at).join(
            AppConfig, func.replace(AppConfig.key, '-', '') == note_key).filter(
            AppConfig.value == json.dumps({'node_id': node_id}),
            Document.workspace_id == workspace_id, Document.deleted_at.is_(None))
        if q:
            notes = notes.filter(Document.title.ilike(like, escape='\\'))
        for note in notes.order_by(Document.updated_at.desc(), Document.id).limit(limit + 1).all():
            add('note_updated', note.id, note.title, note.updated_at, node_id, '/notes?doc=' + str(note.id))
    items.sort(key=lambda i: (i['ts'], i['kind'], i['id']), reverse=True)
    return {'items': items[:limit], 'has_more': len(items) > limit}
