"""告警与通知 API：规则 CRUD + 站内通知（铃铛）+ 事件历史。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Literal
from app.services import alert_history

from app.database import get_db
from app.models.user import User
from app.routers.auth import current_user, admin_user
from app.services import alerts
from app.services.server_map import ManualProbeIntent

router = APIRouter(dependencies=[Depends(current_user)], tags=["alerts"])


# ── 告警规则 ──

class RuleCreate(BaseModel):
    kind: str
    target: str = Field(max_length=128)
    label: str = Field(default="", max_length=128)
    link: str = Field(default="", max_length=128)
    severity: str = "warning"
    debounce: int = Field(default=2, ge=1, le=10, strict=True)
    repeat_minutes: int = Field(default=0, ge=0, le=1440, strict=True)
    email: bool = False
    wg_manual: ManualProbeIntent | None = None


class RulePatch(BaseModel):
    label: str | None = Field(default=None, max_length=128)
    severity: str | None = None
    debounce: int | None = Field(default=None, ge=1, le=10, strict=True)
    repeat_minutes: int | None = Field(default=None, ge=0, le=1440, strict=True)
    email: bool | None = None
    enabled: bool | None = None


@router.get("/alerts/rules")
def list_rules(db: Session = Depends(get_db)):
    return alerts.list_rules(db)


@router.post("/alerts/rules", status_code=201, dependencies=[Depends(admin_user)])
def create_rule(data: RuleCreate, db: Session = Depends(get_db)):
    try:
        rule = alerts.create_rule(db, data.kind, data.target, label=data.label,
                                  link=data.link, severity=data.severity,
                                  debounce=data.debounce,
                                  repeat_minutes=data.repeat_minutes, email=data.email,
                                  wg_manual=data.wg_manual.model_dump() if data.wg_manual else None)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    return {"id": rule.id}


@router.patch("/alerts/rules/{rule_id}", dependencies=[Depends(admin_user)])
def patch_rule(rule_id: int, data: RulePatch, db: Session = Depends(get_db)):
    try:
        alerts.update_rule(db, rule_id, data.model_dump(exclude_none=True))
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(404 if "不存在" in str(e) else 400, str(e))
    return {"ok": True}


@router.delete("/alerts/rules/{rule_id}", dependencies=[Depends(admin_user)])
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    try:
        alerts.delete_rule(db, rule_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.get("/alerts/events")
def list_events(rule_id: int | None = None, limit: int = Query(100, le=500),
                db: Session = Depends(get_db)):
    return [{"id": e.id, "rule_id": e.rule_id, "event": e.event, "ts": e.ts, "message": e.message}
            for e in alerts.list_events(db, rule_id, limit)]


@router.get('/alerts/incidents')
def incident_list(status: Literal['unresolved','resolved','incomplete'] | None = None,
                  node_id: int | None = Query(None, gt=0), kind: str | None = None,
                  since: datetime | None = None, until: datetime | None = None,
                  rule_id: int | None = Query(None, gt=0), limit: int = Query(30,ge=1,le=100),
                  offset: int = Query(0,ge=0), db: Session = Depends(get_db)):
    if any(t is not None and t.tzinfo is None for t in (since,until)):
        raise HTTPException(422,'日期必须含时区')
    if since is not None and until is not None and since >= until:
        raise HTTPException(422,'结束必须晚于开始')
    return alert_history.list_incidents(db,status=status,node_id=node_id,kind=kind,since=since,
        until=until,rule_id=rule_id,limit=limit,offset=offset)


@router.get('/alerts/incidents/{incident_id}')
def incident_detail(incident_id: int, db: Session = Depends(get_db)):
    try:
        return alert_history.incident_detail(db,incident_id)
    except ValueError as exc:
        raise HTTPException(404,str(exc))


# ── Typed metric rules; legacy clients only see schema_version=1 ──
from app.services import alert_metrics
from app.alert_metrics import Condition, Strict
from sqlalchemy.exc import IntegrityError


class MetricPreview(Strict):
    node_id: int = Field(gt=0)
    condition: Condition


class MetricUpdate(alert_metrics.Intent):
    revision: int = Field(gt=0)


@router.get('/alerts/v2/rules')
def metric_rules(db: Session = Depends(get_db)):
    return alert_metrics.list_rules(db)


@router.post('/alerts/v2/preview')
def metric_preview(data: MetricPreview, db: Session = Depends(get_db)):
    return alert_metrics.preview(db, data.node_id, data.condition)


def _save_metric(db, data, rule_id=None, revision=None):
    try:
        rule = alert_metrics.save(db, data, rule_id, revision)
        response = {'id': rule.id, 'revision': rule.revision}
        db.commit()
        return response
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else '相同条件规则已存在')


@router.post('/alerts/v2/rules', status_code=201, dependencies=[Depends(admin_user)])
def create_metric_rule(data: alert_metrics.Intent, db: Session = Depends(get_db)):
    return _save_metric(db, data)


@router.put('/alerts/v2/rules/{rule_id}', dependencies=[Depends(admin_user)])
def update_metric_rule(rule_id: int, data: MetricUpdate, db: Session = Depends(get_db)):
    return _save_metric(db, data.model_dump(exclude={'revision'}), rule_id, data.revision)


# ── 站内通知 ──

def _note_out(n):
    return alert_history.notification_out(n)


@router.get("/notifications")
def list_notifications(limit: int = Query(50, le=200), unread: bool = False,
                       db: Session = Depends(get_db)):
    return [_note_out(n) for n in alerts.list_notifications(db, limit, unread)]


@router.get("/notifications/unread-count")
def unread_count(db: Session = Depends(get_db)):
    return {"count": alerts.unread_count(db)}


@router.get('/notifications/{notification_id}')
def notification_detail(notification_id: int, db: Session = Depends(get_db)):
    from app.models.alert import Notification
    from app.models.node import Node
    note = db.get(Notification,notification_id)
    if note is None:
        raise HTTPException(404,'通知不存在')
    result = _note_out(note)
    context = note.context or {}
    ids = context.get('node_ids',[]) if isinstance(context.get('node_ids',[]),list) else []
    if type(context.get('node_id')) is int:
        ids = [context['node_id'],*ids]
    result['entities'] = []
    for node_id in dict.fromkeys(n for n in ids if type(n) is int and n>0):
        node = db.get(Node,node_id)
        result['entities'].append({'type':'node','id':node_id,
            'label':node.name if node else context.get('label') or f'节点 #{node_id}',
            'available':node is not None and node.status!='removed'})
    return result


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db)):
    try:
        alerts.mark_read(db, notification_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db)):
    n = alerts.mark_all_read(db)
    db.commit()
    return {"ok": True, "marked": n}
