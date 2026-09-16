"""告警域 service：规则 CRUD + 惰性评估 + 派发（站内/WS/邮件）。

惰性判断：不开独立轮询进程，评估挂在已有数据落库路径上——
- agent 心跳上报（handle_report）→ 节点离线规则 + WG 链路规则（快照保存时）
- 探测结果入库（record_check）→ 监控项 down 规则

状态机：ok →（连续 debounce 次异常）→ firing →（一次正常）→ ok。
firing 期间按 repeat_minutes 重复站内提醒（不发邮件、不写事件流水）。
unknown / pending / 目标缺失都是「中性」：不触发也不恢复，避免flapping。
"""
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.alert import AlertEvent, AlertRule, AlertState, Notification, RULE_KINDS, SEVERITIES
from app.models.node import Node
from app.models.monitor import Monitor
from app.models.user import User
from app.services.server_status import node_status

# ── CRUD ──

def create_rule(db: Session, kind: str, target: str, label: str = "",
                link: str = "", severity: str = "warning", debounce: int = 2,
                repeat_minutes: int = 30, email: bool = True) -> AlertRule:
    if kind not in RULE_KINDS:
        raise ValueError(f"未知告警类型：{kind}")
    if severity not in SEVERITIES:
        raise ValueError(f"未知级别：{severity}")
    if not (1 <= debounce <= 10) or not (1 <= repeat_minutes <= 24 * 60):
        raise ValueError("防抖次数或重复间隔超出范围")
    if db.query(AlertRule).filter_by(kind=kind, target=target).first() is not None:
        raise ValueError("该目标的同类告警已存在")
    rule = AlertRule(kind=kind, target=target, label=label,
                     link=link or "/status", severity=severity,
                     debounce=debounce, repeat_minutes=repeat_minutes, email=email)
    db.add(rule)
    db.flush()
    db.add(AlertState(rule_id=rule.id))
    db.flush()
    return rule


def get_rule(db: Session, rule_id: int) -> AlertRule | None:
    return db.get(AlertRule, rule_id)


def list_rules(db: Session) -> list[dict]:
    """规则 + 当前状态（槽位覆写读取，一规则一行）。"""
    rows = (db.query(AlertRule, AlertState)
            .outerjoin(AlertState, AlertState.rule_id == AlertRule.id)
            .order_by(AlertRule.id).all())
    return [{
        "id": r.id, "kind": r.kind, "target": r.target, "label": r.label, "link": r.link,
        "severity": r.severity, "debounce": r.debounce, "repeat_minutes": r.repeat_minutes,
        "email": r.email, "enabled": r.enabled, "created_at": r.created_at,
        "state": s.state if s else "ok",
        "last_change_at": s.last_change_at if s else None,
        "message": s.message if s else None,
    } for r, s in rows]


def update_rule(db: Session, rule_id: int, fields: dict) -> AlertRule:
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise ValueError("告警规则不存在")
    allowed = {"label", "severity", "debounce", "repeat_minutes", "email", "enabled"}
    clean = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "severity" in clean and clean["severity"] not in SEVERITIES:
        raise ValueError("未知级别")
    if "debounce" in clean and not 1 <= clean["debounce"] <= 10:
        raise ValueError("防抖次数超出范围")
    if "repeat_minutes" in clean and not 1 <= clean["repeat_minutes"] <= 24 * 60:
        raise ValueError("重复间隔超出范围")
    for k, v in clean.items():
        setattr(rule, k, v)
    db.flush()
    return rule


def delete_rule(db: Session, rule_id: int) -> None:
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise ValueError("告警规则不存在")
    db.query(AlertState).filter_by(rule_id=rule_id).delete()
    db.query(AlertEvent).filter_by(rule_id=rule_id).delete()
    db.delete(rule)
    db.flush()


# ── 状态机 ──

def _state_for(db: Session, rule: AlertRule) -> AlertState:
    state = db.get(AlertState, rule.id)
    if state is None:
        state = AlertState(rule_id=rule.id)
        db.add(state)
        db.flush()
    return state


def _evaluate(db: Session, rule: AlertRule, bad: bool | None, message: str,
              now: datetime) -> None:
    """单规则评估。bad=None 表示中性（unknown/目标缺失）：不动计数、不触发不恢复。"""
    state = _state_for(db, rule)
    if bad is None:
        # 目标消失且正在告警 → 静默复位（对象已删，恢复通知没意义）
        if state.state == "firing" and not message:
            state.state, state.consecutive = "ok", 0
            state.last_change_at = now
        return
    if bad:
        state.consecutive += 1
        if state.state == "ok" and state.consecutive >= rule.debounce:
            state.state, state.last_change_at = "firing", now
            state.message = message
            _record(db, rule, "fired", message, now)
        elif state.state == "firing":
            state.message = message
            last = state.last_notified_at
            if last is not None and (now - last) >= timedelta(minutes=rule.repeat_minutes):
                _notify(db, rule, "alert", f"「{rule.label}」仍在告警",
                        f"{message}，已经持续一段时间了，记得看看喵~", now,
                        event="remind", email=False)
                state.last_notified_at = now
    else:
        if state.state == "firing":
            state.state, state.last_change_at = "ok", now
            _record(db, rule, "resolved", message, now)
        state.consecutive = 0


def _record(db: Session, rule: AlertRule, event: str, message: str, now: datetime) -> None:
    db.add(AlertEvent(rule_id=rule.id, event=event, message=message))
    state = _state_for(db, rule)
    if event == "fired":
        _notify(db, rule, "alert", f"「{rule.label}」触发告警",
                f"{message}，去看看喵~", now, event=event, email=rule.email)
    else:
        _notify(db, rule, "alert_resolved", f"「{rule.label}」已恢复",
                f"{message}，告警解除喵~", now, event=event, email=rule.email)
    state.last_notified_at = now
    db.flush()


_RULE_DEFAULT_LINKS = {"node_offline": "/status", "monitor_down": "/status", "wg_link": "/status"}


def _notify(db: Session, rule: AlertRule, kind: str, title: str, body: str,
            now: datetime, event: str, email: bool) -> None:
    note = Notification(rule_id=rule.id, title=title, body=body,
                        link=rule.link or "/status", kind=kind,
                        severity=rule.severity if kind == "alert" else "info")
    db.add(note)
    db.flush()
    _push_ws({"type": "notification", "id": note.id, "title": note.title, "body": note.body,
              "severity": note.severity, "kind": note.kind, "link": note.link,
              "ts": now.isoformat()})
    if email:
        _send_alert_email(db, rule, event, f"{title}：{body}")


# ── 派发（可被测试替换）──

def _push_ws(payload: dict) -> None:
    """WS 实时推铃铛；任何失败都不许影响评估主路径。"""
    try:
        from app.routers.notify_ws import push_notification_sync
        push_notification_sync(payload)
    except Exception:
        pass


def _send_alert_email(db: Session, rule: AlertRule, event: str, message: str) -> None:
    """后台线程发邮件，SMTP 配置缺失/发送失败静默降级（站内通知已落库）。"""
    def _run():
        try:
            from app.routers.admin_email import _load, _send
            cfg = _load()
            if not cfg.get("enabled") or not cfg.get("host"):
                return
            admin = db.query(User).filter(User.is_admin.is_(True), User.email != "").first()
            if admin is None:
                return
            color = {"critical": "#e5605c", "warning": "#d9a03f"}.get(rule.severity, "#5cb88a")
            badge = {"fired": "告警", "resolved": "已恢复"}.get(event, "提醒")
            html = f"""
            <div style="font-family:Georgia,serif;background:#0d1017;padding:32px;border-radius:16px;color:#e8ecf4">
              <div style="font-size:22px;color:#c9d4e8;letter-spacing:3px">✦ StellaHaven</div>
              <div style="margin-top:14px;display:inline-block;padding:2px 10px;border-radius:8px;
                          background:{color}22;color:{color};font-size:13px">{badge} · {rule.severity}</div>
              <div style="margin-top:14px;font-size:14px;color:#9aa3b5;line-height:1.9">{message}</div>
              <div style="margin-top:18px;font-size:12px;color:#5c6474">
                规则：{rule.kind} · {rule.label}　—— Stella 告警系统喵~</div>
            </div>"""
            _send(cfg, admin.email, f"[Stella {badge}] {rule.label}", html)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


# ── 站内通知（铃铛）──

def list_notifications(db: Session, limit: int = 50, unread: bool = False) -> list[Notification]:
    q = db.query(Notification).order_by(Notification.id.desc())
    if unread:
        q = q.filter(Notification.read.is_(False))
    return q.limit(min(limit, 200)).all()


def unread_count(db: Session) -> int:
    return db.query(Notification).filter(Notification.read.is_(False)).count()


def mark_read(db: Session, notification_id: int) -> None:
    note = db.get(Notification, notification_id)
    if note is None:
        raise ValueError("通知不存在")
    note.read = True
    db.flush()


def mark_all_read(db: Session) -> int:
    n = db.query(Notification).filter(Notification.read.is_(False)).update({"read": True})
    db.flush()
    return n


def list_events(db: Session, rule_id: int | None = None, limit: int = 100) -> list[AlertEvent]:
    q = db.query(AlertEvent).order_by(AlertEvent.id.desc())
    if rule_id is not None:
        q = q.filter_by(rule_id=rule_id)
    return q.limit(min(limit, 500)).all()


# ── 惰性评估入口 ──

def evaluate_node_rules(db: Session, now: datetime | None = None) -> None:
    """节点离线规则。挂在 agent 心跳上报路径：有心跳才有评估，全灭时无评估（本就失联）。"""
    now = now or datetime.now(timezone.utc)
    rules = db.query(AlertRule).filter_by(kind="node_offline", enabled=True).all()
    if not rules:
        return
    nodes = {n.id: n for n in db.query(Node).all()}
    for rule in rules:
        try:
            node_id = int(rule.target)
        except ValueError:
            continue
        node = nodes.get(node_id)
        if node is None or node.status == "removed":
            _evaluate(db, rule, None, "", now)          # 目标消失：静默复位
            continue
        if node.status == "pending":
            _evaluate(db, rule, None, "keep", now)       # 从未报到：中性
            continue
        bad = node_status(node, now) == "offline"
        _evaluate(db, rule, bad, f"节点 {rule.label or node.name} 已超过 2 分钟没有心跳", now)


def evaluate_monitor(db: Session, monitor_id: int, now: datetime | None = None) -> None:
    """监控项 down 规则：探测结果入库后顺带评估。"""
    now = now or datetime.now(timezone.utc)
    rules = db.query(AlertRule).filter_by(kind="monitor_down", target=str(monitor_id),
                                          enabled=True).all()
    if not rules:
        return
    monitor = db.get(Monitor, monitor_id)
    for rule in rules:
        if monitor is None:
            _evaluate(db, rule, None, "", now)
            continue
        bad = monitor.status == "down"
        _evaluate(db, rule, bad, f"监控项 {rule.label or monitor.name} 探测失败", now)


def evaluate_wg_rules(db: Session, topology: dict | None = None,
                      now: datetime | None = None) -> None:
    """WG 链路规则：只在 health=failed（红）触发；degraded（橙）/unknown（灰）不触发。"""
    now = now or datetime.now(timezone.utc)
    rules = db.query(AlertRule).filter_by(kind="wg_link", enabled=True).all()
    if not rules:
        return
    if topology is None:
        from app.services.server_map import get_topology
        topology = get_topology(db)
    links = {l["id"]: l for l in topology.get("links", [])}
    for rule in rules:
        link = links.get(rule.target)
        if link is None:
            _evaluate(db, rule, None, "", now)           # 链路消失：中性
            continue
        health = link.get("health")
        if health in ("unknown", None):
            _evaluate(db, rule, None, "keep", now)       # 数据缺失：中性
            continue
        bad = health == "failed"
        _evaluate(db, rule, bad, f"WG 链路 {rule.label} 探测失败（双向不可达或严重丢包）", now)
