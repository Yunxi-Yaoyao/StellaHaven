"""Read-only incident projection of the original transition log, before pagination.

No second evaluator and no inferred recovery from a rule's current state. IDs are
original event IDs; old rows without snapshots are explicitly labelled as such.
"""
from datetime import datetime, timezone
from sqlalchemy import text
from app.models.alert import AlertEvent, AlertRule, Notification

# Window functions run BEFORE any date/status/page filter. Adjacent transitions
# alone can pair: fired/fired and resolved/resolved retain their missing evidence.
_CTE = '''WITH ordered AS (
 SELECT e.*, lead(event) OVER w AS next_event, lead(ts) OVER w AS next_ts,
 lead(id) OVER w AS next_id, lag(event) OVER w AS prev_event
 FROM alert_events e WINDOW w AS (PARTITION BY rule_id ORDER BY ts,id)
), incidents AS (
 SELECT *, CASE WHEN event='fired' THEN ts END AS started_at,
 CASE WHEN event='resolved' THEN ts WHEN next_event='resolved' THEN next_ts END AS resolved_at,
 CASE WHEN event='resolved' THEN 'incomplete'
      WHEN next_event='resolved' THEN 'resolved'
      WHEN next_id IS NOT NULL THEN 'incomplete' ELSE 'unresolved' END AS status
 FROM ordered WHERE event='fired' OR (event='resolved' AND prev_event IS DISTINCT FROM 'fired')
), projected AS (
 SELECT i.*, coalesce(snapshot->>'label',r.label,'历史告警') AS label,
 coalesce(snapshot->>'kind',r.kind,'unknown') AS kind,
 coalesce(snapshot->>'severity',r.severity,'warning') AS severity,
 coalesce(snapshot->>'node_id',CASE WHEN r.kind IN ('node_offline','node_metric') THEN r.target END) AS node_id,
 s.evaluated_at,s.watermark,s.state AS rule_state,s.preview,r.enabled,r.archived,r.condition
 FROM incidents i LEFT JOIN alert_rules r ON r.id=i.rule_id
 LEFT JOIN alert_states s ON s.rule_id=i.rule_id
)
'''


def rule_snapshot(db, rule):
    from app.models.monitor import Monitor
    node_id = None
    if rule.kind in ('node_offline', 'node_metric') and rule.target.isdecimal():
        node_id = int(rule.target)
    elif rule.kind == 'monitor_down' and rule.target.isdecimal():
        monitor = db.get(Monitor, int(rule.target))
        node_id = monitor.node_id if monitor else None
    return dict(label=rule.label, kind=rule.kind, severity=rule.severity, node_id=node_id)


def notification_out(note):
    return {k: getattr(note, k) for k in ('id','rule_id','title','body','severity','kind','link','read','ts','context')}


def _out(row, now):
    r = dict(row)
    start, end = r['started_at'], r['resolved_at']
    r['duration_seconds'] = max(0, int(((end or now)-start).total_seconds())) if start and r['status'] != 'incomplete' else None
    r['metadata_source'] = 'snapshot' if r['snapshot'] else 'legacy_rule'
    r['start_missing'] = start is None
    r['recovery_unconfirmed'] = r['event'] == 'fired' and end is None
    r['node_id'] = int(r['node_id']) if str(r['node_id']).isdecimal() else None
    # last evaluation is evidence, not proof a still-open incident is healthy.
    observed = r['evaluated_at'] or r['watermark']
    condition = r['condition'] if isinstance(r['condition'],dict) else {}
    metric = condition.get('metric')
    max_age = 120 if metric == 'network.volume' else 45 if metric in ('network.rate','network.utilization') else 180
    sample = r['watermark']
    r['observation'] = 'unknown' if (not observed or (now-observed).total_seconds() > max_age or
        (sample is not None and ((now-sample).total_seconds() > max_age or (now-sample).total_seconds() < -5)) or
        (now-observed).total_seconds() < -5 or not r['enabled'] or
        not r['preview'] or r['preview'].get('quality') != 'valid') else 'recent'
    return {k: r[k] for k in ('id','rule_id','label','kind','severity','node_id','message','started_at','resolved_at',
        'duration_seconds','status','metadata_source','start_missing','recovery_unconfirmed','evaluated_at','watermark','enabled','archived','observation')}


def list_incidents(db, *, status=None, node_id=None, kind=None, since=None, until=None, rule_id=None,
                   limit=30, offset=0, now=None):
    now = now or datetime.now(timezone.utc)
    terms = ['true']; params = {'limit': min(max(limit,1),100), 'offset': max(offset,0)}
    for name, value, expression in [('status',status,'status=:status'),('node_id',node_id,'node_id=:node_id'),
            ('kind',kind,'kind=:kind'),('since',since,'ts>=:since'),('until',until,'ts<:until'),('rule_id',rule_id,'rule_id=:rule_id')]:
        if value is not None:
            params[name] = str(value) if name == 'node_id' else value
            terms.append(expression)
    where = ' WHERE ' + ' AND '.join(terms)
    total = db.execute(text(_CTE+'SELECT count(*) FROM projected'+where),params).scalar_one()
    rows = db.execute(text(_CTE+'SELECT * FROM projected'+where+' ORDER BY ts DESC,id DESC LIMIT :limit OFFSET :offset'),params).mappings()
    items = [_out(r,now) for r in rows]
    untracked = []
    if status == 'unresolved' and since is None and until is None:
        gap_terms = ["s.state='firing'", "NOT EXISTS (SELECT 1 FROM projected p WHERE p.rule_id=r.id AND p.status='unresolved')"]
        if rule_id is not None: gap_terms.append('r.id=:rule_id')
        if kind is not None: gap_terms.append('r.kind=:kind')
        if node_id is not None: gap_terms.append("r.kind IN ('node_offline','node_metric') AND r.target=:node_id")
        gaps = db.execute(text(_CTE+'SELECT r.id AS rule_id,r.label FROM alert_rules r JOIN alert_states s ON s.rule_id=r.id WHERE '+' AND '.join(gap_terms)),params).mappings()
        untracked = [dict(rule_id=g['rule_id'],label=g['label'],message='起始事件记录缺失；未确认恢复') for g in gaps]
    return {'items': items, 'total':total, 'limit':params['limit'], 'offset':params['offset'], 'untracked':untracked}


def incident_detail(db, incident_id, *, now=None):
    now = now or datetime.now(timezone.utc)
    row = db.execute(text(_CTE+'SELECT * FROM projected WHERE id=:id'),{'id':incident_id}).mappings().first()
    if row is None:
        raise ValueError('告警记录不存在')
    result = _out(row,now)
    ids = [row['id']]
    if row['event'] == 'fired' and row['next_event'] == 'resolved':
        ids.append(row['next_id'])
    events = db.query(AlertEvent).filter(AlertEvent.id.in_(ids)).order_by(AlertEvent.ts,AlertEvent.id).all()
    result['timeline'] = [dict(id=e.id,event=e.event,ts=e.ts,message=e.message) for e in events]
    # New notifications have exact attribution, including reminders. Old notes
    # stay in the bell; do not guess incident membership from title or read state.
    notes = db.query(Notification).filter(Notification.context['incident_id'].astext == str(incident_id)).order_by(Notification.ts,Notification.id).all()
    result['notifications'] = [notification_out(n) for n in notes]
    return result
