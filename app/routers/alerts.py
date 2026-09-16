"""告警与通知 API：规则 CRUD + 站内通知（铃铛）+ 事件历史。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.auth import current_user
from app.services import alerts

router = APIRouter(dependencies=[Depends(current_user)], tags=["alerts"])


# ── 告警规则 ──

class RuleCreate(BaseModel):
    kind: str
    target: str = Field(max_length=128)
    label: str = Field(default="", max_length=128)
    link: str = Field(default="", max_length=128)
    severity: str = "warning"
    debounce: int = 2
    repeat_minutes: int = 30
    email: bool = True


class RulePatch(BaseModel):
    label: str | None = Field(default=None, max_length=128)
    severity: str | None = None
    debounce: int | None = None
    repeat_minutes: int | None = None
    email: bool | None = None
    enabled: bool | None = None


@router.get("/alerts/rules")
def list_rules(db: Session = Depends(get_db)):
    return alerts.list_rules(db)


@router.post("/alerts/rules", status_code=201)
def create_rule(data: RuleCreate, db: Session = Depends(get_db)):
    try:
        rule = alerts.create_rule(db, data.kind, data.target, label=data.label,
                                  link=data.link, severity=data.severity,
                                  debounce=data.debounce,
                                  repeat_minutes=data.repeat_minutes, email=data.email)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    return {"id": rule.id}


@router.patch("/alerts/rules/{rule_id}")
def patch_rule(rule_id: int, data: RulePatch, db: Session = Depends(get_db)):
    try:
        alerts.update_rule(db, rule_id, data.model_dump(exclude_none=True))
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(404 if "不存在" in str(e) else 400, str(e))
    return {"ok": True}


@router.delete("/alerts/rules/{rule_id}")
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


# ── 站内通知 ──

def _note_out(n):
    return {"id": n.id, "rule_id": n.rule_id, "title": n.title, "body": n.body,
            "severity": n.severity, "kind": n.kind, "link": n.link,
            "read": n.read, "ts": n.ts}


@router.get("/notifications")
def list_notifications(limit: int = Query(50, le=200), unread: bool = False,
                       db: Session = Depends(get_db)):
    return [_note_out(n) for n in alerts.list_notifications(db, limit, unread)]


@router.get("/notifications/unread-count")
def unread_count(db: Session = Depends(get_db)):
    return {"count": alerts.unread_count(db)}


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
