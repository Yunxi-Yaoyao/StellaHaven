"""V2 single-node metric rules. Event-driven, bounded, read-only preview."""
import hashlib,json
from time import monotonic
from datetime import datetime,timedelta,timezone
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from pydantic import Field
from app.alert_metrics import Condition,Fixed,Strict,evaluate,result,volume_result
from app.public_alert_metrics import public_metric_rule
from app.models.alert import AlertRule,AlertState
from app.models.node import Node,NodeMetric,NodeSysMetric
from app.services import alerts

class Intent(Strict):
    node_id: int = Field(gt=0)
    label: str = Field(default='',max_length=128)
    condition: Condition
    severity: str = Field(default='warning',pattern='^(warning|critical)$')
    debounce: int = Field(default=2,ge=1,le=10)
    repeat_minutes: int = Field(default=0,ge=0,le=1440)
    email: bool = False
    enabled: bool = True


def save(db, data, rule_id=None, revision=None, now=None):
    intent=Intent.model_validate(data)
    now=now or datetime.now(timezone.utc)
    node=db.query(Node).filter_by(id=intent.node_id).with_for_update().first()
    normalized=intent.condition.model_dump(mode='json')
    rule=None
    if rule_id is not None:
        rule=db.query(AlertRule).filter_by(id=rule_id,schema_version=2,archived=False).with_for_update().populate_existing().first()
        if rule is None: raise ValueError('规则不存在')
        if rule.target != str(intent.node_id): raise ValueError('不能更换已有规则的节点，请新增规则')
        if rule.revision!=revision: raise ValueError('revision 冲突，请保留草稿并重新读取规则')
    # Inventory may disappear; only a pure disable can retain that definition.
    # Disabled creations/edits still require valid live node/interface selection.
    disable_only=(rule is not None and not intent.enabled and normalized==rule.condition
                  and all(getattr(intent,k)==getattr(rule,k) for k in
                          ('label','severity','debounce','repeat_minutes','email')))
    if not disable_only and (node is None or node.status=='removed'):
        raise ValueError('节点不存在')
    if not disable_only and intent.condition.interface and intent.condition.interface not in (node.interfaces or {}):
        raise ValueError('请选择该节点当前存在的单一接口')
    if intent.enabled and isinstance(intent.condition.window,Fixed) and intent.condition.window.end <= now:
        raise ValueError('已结束日期仅可预览或保存停用草稿，不回放历史告警')
    fingerprint=hashlib.sha256(json.dumps([normalized,intent.severity,intent.debounce,intent.repeat_minutes],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    existing=db.query(AlertRule).filter_by(schema_version=2,archived=False,target=str(intent.node_id),fingerprint=fingerprint).first()
    if existing and existing.id!=rule_id:
        raise ValueError('相同条件规则已存在')
    if rule_id is None:
        if db.query(AlertRule).filter_by(schema_version=2,archived=False,target=str(intent.node_id)).count() >= 50:
            raise ValueError('每节点最多50条指标规则')
        rule=AlertRule(kind='node_metric',target=str(intent.node_id),schema_version=2,revision=1,link=f'/status/{intent.node_id}')
        db.add(rule)
    else:
        assert rule is not None
        rule.revision+=1
    for field in ('label','severity','debounce','repeat_minutes','email','enabled'):
        setattr(rule,field,getattr(intent,field))
    rule.condition=normalized;rule.fingerprint=fingerprint
    db.flush()
    state=alerts._state_for(db,rule)
    state.consecutive=0
    # Do not erase firing or turn an edit into a recovery. Require a NEW sample.
    state.watermark=now;state.evaluated_at=None;state.preview=None
    db.flush()
    return rule


def list_rules(db):
    rows=db.query(AlertRule,AlertState).outerjoin(AlertState,AlertState.rule_id==AlertRule.id).filter(AlertRule.schema_version==2,AlertRule.archived.is_(False)).order_by(AlertRule.id).all()
    return [public_metric_rule(r,s) for r,s in rows]


# Bounds on INPUT, not chart output. Existing (node,iface,ts) index is reused.
# Crossing intervals are queried up to the accepted maximum interval (300s).
_VOLUME_SQL = text('''
WITH raw AS (
 SELECT ts,interval_start,elapsed_seconds,quality,rx_delta,tx_delta
 FROM node_metrics WHERE node_id=:node AND iface=:iface AND ts>:start AND ts<=:stop
 ORDER BY ts LIMIT 600001
), checked AS (
 SELECT *, quality='valid' AND interval_start IS NOT NULL AND ts>interval_start AND elapsed_seconds>0 AND elapsed_seconds<=300
 AND abs(extract(epoch FROM ts-interval_start)-elapsed_seconds)<=greatest(0.1,elapsed_seconds*0.02)
 AND rx_delta>=0 AND tx_delta>=0 AS valid,
 lag(ts) OVER (ORDER BY ts) AS prev
 FROM raw WHERE interval_start<:end OR interval_start IS NULL
)
SELECT count(*) AS count, max(ts) AS watermark,
 coalesce(sum(CASE WHEN valid AND interval_start>=:start AND ts<=:end THEN
 CASE :direction WHEN 'in' THEN rx_delta WHEN 'out' THEN tx_delta ELSE rx_delta::numeric+tx_delta END ELSE 0 END),0) AS lower,
 coalesce(sum(CASE WHEN valid THEN CASE :direction WHEN 'in' THEN rx_delta WHEN 'out' THEN tx_delta ELSE rx_delta::numeric+tx_delta END ELSE 0 END),0) AS upper,
 coalesce(bool_and(coalesce(valid,false)),false) AND min(interval_start)<=:start AND max(ts)>=:end
 AND coalesce(bool_and(prev IS NULL OR interval_start=prev),false) AS complete,
 coalesce(bool_or(prev IS NOT NULL AND interval_start<prev),false) AS overlap
FROM checked
''')


def preview(db,node_id,condition,now=None):
    c=Condition.model_validate(condition)
    now=now or datetime.now(timezone.utc)
    node=db.get(Node,node_id)
    if node is None or node.status=='removed':return result(c,reason='target_missing')
    if c.interface and c.interface not in (node.interfaces or {}):return result(c,reason='interface_missing')
    if isinstance(c.window,Fixed):
        if now<=c.window.start:return result(c,reason='scheduled')
        end=min(c.window.end,now)
        # SAVEPOINT permits timeout recovery without rolling back caller's state.
        try:
            with db.begin_nested():
                old_timeout=db.execute(text('SHOW statement_timeout')).scalar_one()
                db.execute(text("SET LOCAL statement_timeout = '5s'"))
                row=db.execute(_VOLUME_SQL,dict(node=node_id,iface=c.interface,start=c.window.start,end=end,
                    stop=end+timedelta(seconds=300),direction=c.direction)).mappings().one()
                db.execute(text("SELECT set_config('statement_timeout',:value,true)"),{'value':old_timeout})
        except DBAPIError:
            return result(c,reason='query_unavailable')
        if row['count']>=600000:return result(c,reason='query_budget')
        if not row['count']:return result(c,reason='history_missing')
        if row['overlap']:return result(c,reason='overlapping_intervals')
        return volume_result(c,int(row['lower']),int(row['upper']) if row['complete'] else None,row['watermark'])
    cls=NodeMetric if c.metric.startswith('network.') else NodeSysMetric
    q=db.query(cls).filter(cls.node_id==node_id)
    if cls==NodeMetric:q=q.filter(cls.iface==c.interface)
    p=q.order_by(cls.ts.desc()).first()
    points=[p] if p else []
    if p is not None and p.ts > now + timedelta(seconds=5):
        # Quarantine future clock samples without scanning unbounded history.
        current=q.filter(cls.ts<=now+timedelta(seconds=5)).order_by(cls.ts.desc()).first()
        if current is not None:points.append(current)
    return evaluate(c,[{col.name:getattr(p,col.name) for col in cls.__table__.columns} for p in points],now)


def evaluate_node(db,node_id,now=None):
    now=now or datetime.now(timezone.utc)
    rules=db.query(AlertRule).filter_by(schema_version=2,target=str(node_id),enabled=True).order_by(AlertRule.id).with_for_update().populate_existing().all()
    cache={}
    deadline=monotonic()+2
    for rule in rules:
        state=alerts._state_for(db,rule)
        c=Condition.model_validate(rule.condition)
        # Fixed totals are at most once a minute per rule on incoming data.
        if isinstance(c.window,Fixed) and state.evaluated_at and (now-state.evaluated_at).total_seconds()<60:continue
        key=json.dumps({k:v for k,v in rule.condition.items() if k!='threshold'},sort_keys=True)
        if key not in cache:
            if monotonic()>=deadline:
                state.preview=result(c,reason='evaluation_lag')
                continue
            cache[key]=preview(db,node_id,rule.condition,now)
        observed=cache[key]
        p=result(c,value=observed['value'],lower=observed['lower'],upper=observed['upper'],
            quality=observed['quality'],reason=observed['reason'],
            watermark=datetime.fromisoformat(observed['watermark']) if observed['watermark'] else None)
        state.preview=p;state.evaluated_at=now
        if isinstance(c.window,Fixed) and now>=c.window.end:
            # Period closure isn't recovery or historical replay.
            continue
        watermark=datetime.fromisoformat(p['watermark']) if p['watermark'] else None
        if p['bad'] is None:
            state.consecutive=0
            continue
        if watermark is None or state.watermark and watermark<=state.watermark:continue
        if state.watermark and (watermark-state.watermark).total_seconds()>(180 if not c.metric.startswith('network.') else 90):state.consecutive=0
        state.watermark=watermark
        value=p['value'] if p['value'] is not None else f"至少 {p['lower']}"
        alerts._evaluate(db,rule,p['bad'],f"{rule.label or c.metric}：{value} {p['unit']}，阈值 ≥ {c.threshold} {p['unit']}",now)
    db.flush()
