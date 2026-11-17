"""告警域 service：规则 CRUD、时间/样本评估与提交后派发。

节点中断由生命周期内独立 deadline tick 推进，报告路径仅评估本节点并确认恢复。
其它类型仍在探测/指标/地图样本落库时评估，使用各自 debounce。
firing 期间仅显式正数 repeat_minutes 才重复站内提醒，不发 reminder 邮件。
unknown / pending / 目标缺失不触发也不恢复；禁用/归档不是恢复。
"""
import threading
import logging
from html import escape
from sqlalchemy import event as sa_event
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.alert import AlertEvent, AlertRule, AlertState, Notification, RULE_KINDS, SEVERITIES
from app.models.node import Node
from app.models.monitor import Monitor
from app.models.user import User
from app.services.server_status import monitor_status

logger = logging.getLogger(__name__)

# ── CRUD ──

def create_node_interruption_rule(db: Session, node: Node) -> AlertRule:
    """Creation-only hook; never backfill/revive a user's disabled/archived rule.

    Node lock serializes same-ID calls; the existing active-rule unique index is
    the final database guard. No commit: inventory and initial rule are atomic.
    """
    db.flush()
    node = db.query(Node).filter_by(id=node.id).with_for_update().populate_existing().one()
    existing = (db.query(AlertRule).filter_by(kind="node_offline", target=str(node.id))
                .order_by(AlertRule.id).first())
    if existing is not None:
        return existing
    from sqlalchemy.exc import IntegrityError
    try:
        with db.begin_nested():
            rule = AlertRule(kind="node_offline", target=str(node.id),
                             label=f"{node.name[:118]} · 上报中断", link=f"/status/{node.id}",
                             schema_version=1, enabled=True, email=False,
                             severity="warning", debounce=1, repeat_minutes=0)
            db.add(rule); db.flush()
            db.add(AlertState(rule_id=rule.id)); db.flush()
        return rule
    except IntegrityError as exc:
        # A simultaneous manual creation need not take the Node lock. Limit
        # recovery to this exact uniqueness conflict; keep the caller's outer
        # inventory transaction and the winning user's configuration intact.
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) != "uq_alert_rule_legacy":
            raise
        return db.query(AlertRule).filter_by(kind="node_offline", target=str(node.id),
                                             schema_version=1, archived=False).one()

def create_rule(db: Session, kind: str, target: str, label: str = "",
                link: str = "", severity: str = "warning", debounce: int = 2,
                repeat_minutes: int = 0, email: bool = False, wg_manual: dict | None = None) -> AlertRule:
    if kind not in RULE_KINDS:
        raise ValueError(f"未知告警类型：{kind}")
    if severity not in SEVERITIES:
        raise ValueError(f"未知级别：{severity}")
    if (type(debounce) is not int or not 1 <= debounce <= 10 or
            type(repeat_minutes) is not int or not 0 <= repeat_minutes <= 24 * 60):
        raise ValueError("防抖次数或重复间隔超出范围")
    condition = None
    if wg_manual is not None:
        if kind != "wg_link" or target:
            raise ValueError("手动 WG 端点只适用于 WG 规则且不能同时指定发现链路")
        from app.services.wg_manual import prepare
        target, condition = prepare(db, wg_manual)
    elif kind == "wg_link" and target.startswith("manual:"):
        raise ValueError("手动端点必须通过安全配置字段创建")
    if db.query(AlertRule).filter_by(kind=kind, target=target, archived=False).first() is not None:
        raise ValueError("该目标的同类告警已存在")
    rule = AlertRule(kind=kind, target=target, label=label,
                     link=link or "/status", severity=severity,
                     debounce=debounce, repeat_minutes=repeat_minutes, email=email, condition=condition)
    db.add(rule)
    db.flush()
    db.add(AlertState(rule_id=rule.id))
    db.flush()
    return rule


def get_rule(db: Session, rule_id: int) -> AlertRule | None:
    return db.query(AlertRule).filter_by(id=rule_id, archived=False).first()


def list_rules(db: Session) -> list[dict]:
    """规则 + 当前状态（槽位覆写读取，一规则一行）。"""
    rows = (db.query(AlertRule, AlertState)
            .outerjoin(AlertState, AlertState.rule_id == AlertRule.id)
            .filter(AlertRule.schema_version == 1, AlertRule.archived.is_(False)).order_by(AlertRule.id).all())
    manual_data = {}
    if any(r.target.startswith("manual:") for r, _ in rows):
        from app.services import wg_manual, server_map
        nodes, snapshots, _ = server_map._read_map_data(db)
        for r, _ in rows:
            if r.target.startswith("manual:"):
                manual_data[r.id] = {"wg_manual": wg_manual.binding_for(r),
                    "wg_observation": wg_manual.health(r, nodes, snapshots)}
    return [{
        **manual_data.get(r.id, {}),
        "id": r.id, "kind": r.kind, "target": r.target, "label": r.label, "link": r.link,
        "severity": r.severity, "debounce": r.debounce, "repeat_minutes": r.repeat_minutes,
        "email": r.email, "enabled": r.enabled, "created_at": r.created_at,
        "state": s.state if s else "ok",
        "last_change_at": s.last_change_at if s else None,
        "message": s.message if s else None,
    } for r, s in rows]


def update_rule(db: Session, rule_id: int, fields: dict) -> AlertRule:
    rule = db.query(AlertRule).filter_by(id=rule_id, archived=False).with_for_update().populate_existing().first()
    if rule is None:
        raise ValueError("告警规则不存在")
    if rule.schema_version != 1:
        raise ValueError("指标规则请通过 v2 API 编辑，不能丢弃条件")
    allowed = {"label", "severity", "debounce", "repeat_minutes", "email", "enabled"}
    clean = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "severity" in clean and clean["severity"] not in SEVERITIES:
        raise ValueError("未知级别")
    if "debounce" in clean and (type(clean["debounce"]) is not int or not 1 <= clean["debounce"] <= 10):
        raise ValueError("防抖次数超出范围")
    if "repeat_minutes" in clean and (type(clean["repeat_minutes"]) is not int or not 0 <= clean["repeat_minutes"] <= 24 * 60):
        raise ValueError("重复间隔超出范围")
    enabling = clean.get("enabled") is True and not rule.enabled
    for k, v in clean.items():
        setattr(rule, k, v)
    if enabling and rule.kind == "node_offline":
        state = _state_for(db, rule)
        state.consecutive = 0
        if state.state == "firing":
            # Re-enabling is not recovery and never catches up old reminders.
            state.last_notified_at = datetime.now(timezone.utc)
    db.flush()
    return rule


def delete_rule(db: Session, rule_id: int) -> None:
    # Same rule -> state ordering as edits and evaluators, including legacy rules.
    rule = db.query(AlertRule).filter_by(id=rule_id, archived=False).with_for_update().populate_existing().first()
    if rule is None:
        raise ValueError("告警规则不存在")
    # Archive the definition and frozen state; deletion is never recovery.
    rule.archived = True
    rule.enabled = False
    db.flush()


# ── 状态机 ──

def _state_for(db: Session, rule: AlertRule) -> AlertState:
    db.flush()
    state = db.query(AlertState).filter_by(rule_id=rule.id).with_for_update().populate_existing().first()
    if state is None:
        state = AlertState(rule_id=rule.id)
        db.add(state)
        db.flush()
    return state


def _evaluate(db: Session, rule: AlertRule, bad: bool | None, message: str,
              now: datetime) -> None:
    """单规则评估。bad=None 表示未知：中断连续计数，不触发、不恢复。"""
    rule = db.query(AlertRule).filter_by(id=rule.id).with_for_update().populate_existing().first()
    if rule is None or rule.archived or not rule.enabled:
        return
    state = _state_for(db, rule)
    if rule.schema_version == 1:
        if state.watermark is not None and now <= state.watermark:
            return
        state.watermark = now
        state.evaluated_at = now
        state.preview = {"quality": "unknown" if bad is None else "valid", "bad": bad}
    if bad is None:
        state.consecutive = 0
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
            if rule.repeat_minutes > 0 and last is not None and (now - last) >= timedelta(minutes=rule.repeat_minutes):
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
    from app.services.alert_history import rule_snapshot
    transition = AlertEvent(rule_id=rule.id, event=event, message=message, ts=now,
                            snapshot=rule_snapshot(db, rule))
    db.add(transition)
    db.flush()
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
    from app.services.alert_history import rule_snapshot
    fired = db.query(AlertEvent).filter_by(rule_id=rule.id, event='fired').order_by(AlertEvent.ts.desc(), AlertEvent.id.desc()).first()
    context = {'event': event, 'incident_id': fired.id if fired else None, **rule_snapshot(db, rule)}
    note = Notification(rule_id=rule.id, title=title, body=body, ts=now, context=context,
                        link=rule.link or "/status", kind=kind,
                        severity=rule.severity if kind == "alert" else "info")
    db.add(note)
    db.flush()
    payload = {"type": "notification", "id": note.id, "title": note.title, "body": note.body,
              "severity": note.severity, "kind": note.kind, "link": note.link,
              "ts": now.isoformat(), "context": context, "rule_id": rule.id}
    mail = None
    if email:
        admin = db.query(User).filter(User.is_admin.is_(True), User.email != "").first()
        if admin is not None:
            mail = dict(rule_id=rule.id, address=admin.email, severity=rule.severity, label=rule.label,
                        kind=rule.kind, event=event, message=f"{title}：{body}")
    db.info.setdefault("alert_dispatch", []).append((payload, mail, db.get_nested_transaction()))


@sa_event.listens_for(Session, "after_commit")
def _after_alert_commit(db):
    if db.in_nested_transaction():
        return
    for payload, mail, _transaction in db.info.pop("alert_dispatch", []):
        try:
            _push_ws(payload)
        except Exception as exc:
            logger.warning("alert_dispatch_failed channel=ws error=%s", type(exc).__name__)
        if mail:
            try:
                _send_alert_email(mail)
            except Exception as exc:
                # COMMIT already succeeded. Best-effort delivery is not an outbox;
                # thread launch failure cannot turn durable success into an error.
                logger.warning("alert_dispatch_failed channel=email_start error=%s", type(exc).__name__)


@sa_event.listens_for(Session, "after_transaction_end")
def _after_alert_transaction_end(db, transaction):
    # close()/reset() end the root without Session rollback callbacks. Flush
    # subtransactions and released savepoints must retain the outer queue.
    if transaction.parent is None:
        db.info.pop("alert_dispatch", None)


@sa_event.listens_for(Session, "after_rollback")
def _after_alert_rollback(db):
    if db.in_nested_transaction():
        return
    db.info.pop("alert_dispatch", None)


@sa_event.listens_for(Session, "after_soft_rollback")
def _after_alert_savepoint_rollback(db, previous_transaction):
    # Retain outer-transaction intents, discard this savepoint and descendants.
    def retained(item):
        transaction = item[2]
        while transaction is not None:
            if transaction is previous_transaction:
                return False
            transaction = transaction.parent
        return True
    if previous_transaction.nested:
        db.info['alert_dispatch'] = [item for item in db.info.get('alert_dispatch', []) if retained(item)]


# ── 派发（可被测试替换）──

def _push_ws(payload: dict) -> None:
    """WS 实时推铃铛；任何失败都不许影响评估主路径。"""
    try:
        from app.routers.notify_ws import push_notification_sync
        push_notification_sync(payload)
    except Exception as exc:
        logger.warning("alert_dispatch_failed channel=ws error=%s", type(exc).__name__)


def _send_alert_email(snapshot: dict) -> None:
    """Best-effort post-commit email; failures are logged, not durably retried."""
    def _run():
        try:
            from app.routers.admin_email import _load, _send
            cfg = _load()
            if not cfg.get("enabled") or not cfg.get("host"):
                return
            severity, label, kind, message = (escape(str(snapshot[k])) for k in ('severity', 'label', 'kind', 'message'))
            color = {"critical": "#e5605c", "warning": "#d9a03f"}.get(severity, "#5cb88a")
            badge = {"fired": "告警", "resolved": "已恢复"}.get(snapshot['event'], "提醒")
            html = f"""
            <div style="font-family:Georgia,serif;background:#0d1017;padding:32px;border-radius:16px;color:#e8ecf4">
              <div style="font-size:22px;color:#c9d4e8;letter-spacing:3px">✦ StellaHaven</div>
              <div style="margin-top:14px;display:inline-block;padding:2px 10px;border-radius:8px;
                          background:{color}22;color:{color};font-size:13px">{badge} · {severity}</div>
              <div style="margin-top:14px;font-size:14px;color:#9aa3b5;line-height:1.9">{message}</div>
              <div style="margin-top:18px;font-size:12px;color:#5c6474">
                规则：{kind} · {label}　—— Stella 告警系统喵~</div>
            </div>"""
            _send(cfg, snapshot['address'], f"[Stella {badge}] {snapshot['label']}", html)
        except Exception as exc:
            logger.warning("alert_dispatch_failed channel=email_send error=%s", type(exc).__name__)
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

def _utc(value: datetime) -> datetime:
    # SQLite fixtures discard tzinfo; PostgreSQL timestamptz remains aware.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def evaluate_node_rules(db: Session, now: datetime | None = None, *,
                        node_id: int | None = None, heartbeat_node_id: int | None = None) -> None:
    """Time-based TTL, not report-count debounce. Lock order Node → Rule → State.

    Timer never infers recovery from a cached healthy timestamp. Only the
    authenticated own-report path may resolve; unknown/disabled/archive freeze.
    Explicit now is a test clock; production reads time AFTER acquiring locks.
    """
    from sqlalchemy import String, cast
    from app.services.server_status import HEARTBEAT_TTL
    db.flush()
    q = db.query(Node)
    if node_id is not None:
        q = q.filter(Node.id == node_id)
    else:
        q = q.filter(db.query(AlertRule.id).filter(
            AlertRule.kind == "node_offline", AlertRule.schema_version == 1,
            AlertRule.enabled.is_(True), AlertRule.archived.is_(False),
            AlertRule.target == cast(Node.id, String)).exists())
    for node in q.order_by(Node.id).with_for_update().populate_existing().all():
        rules = (db.query(AlertRule).filter_by(kind="node_offline", schema_version=1,
                    target=str(node.id), enabled=True, archived=False)
                 .order_by(AlertRule.id).with_for_update().populate_existing().all())
        for rule in rules:
            state = _state_for(db, rule)
            current = _utc(now or datetime.now(timezone.utc))
            if state.watermark is not None and current <= _utc(state.watermark):
                continue
            state.watermark = state.evaluated_at = current
            seen = _utc(node.last_seen_at) if node.last_seen_at is not None else None
            reason = None
            if node.status not in ("online", "offline") or seen is None:
                reason = "pending" if node.status == "pending" or seen is None else "target_unavailable"
            elif not node.installed or node.uninstall_status in ("pending", "running", "done"):
                reason = "unmanaged"
            elif seen > current:
                reason = "future_heartbeat"
            if reason:
                state.preview = {"quality": "unknown", "reason": reason}
                state.consecutive = 0
                continue
            assert seen is not None
            deadline = seen + timedelta(seconds=HEARTBEAT_TTL)
            bad = current > deadline  # exactly TTL is still fresh, matching node_status
            state.preview = {"quality": "valid", "bad": bad,
                             "last_seen_at": seen.isoformat(), "deadline": deadline.isoformat()}
            state.consecutive = 0
            if bad:
                message = f"节点 {rule.label or node.name} 已超过 2 分钟没有上报；原因未确认"
                if state.state == "ok":
                    state.state, state.last_change_at = "firing", deadline
                    state.message = message
                    # Timeout boundary, not a claimed machine failure time.
                    _record(db, rule, "fired", message, deadline)
                    state.last_notified_at = current
                else:
                    state.message = message
                    last = state.last_notified_at
                    if rule.repeat_minutes > 0 and last is not None and current - _utc(last) >= timedelta(minutes=rule.repeat_minutes):
                        _notify(db, rule, "alert", f"「{rule.label}」仍在告警", message,
                                current, event="remind", email=False)
                        state.last_notified_at = current
            elif (heartbeat_node_id == node.id and state.state == "firing"
                  and state.last_change_at is not None and seen > _utc(state.last_change_at)):
                state.state, state.last_change_at = "ok", seen
                state.message = f"节点 {rule.label or node.name} 已收到新的认证上报"
                _record(db, rule, "resolved", state.message, seen)
    db.flush()


def evaluate_monitor(db: Session, monitor_id: int, now: datetime | None = None) -> None:
    """监控项 down 规则：探测结果入库后顺带评估。"""
    from app.services.monitor_management import effective_enabled
    monitor = db.get(Monitor, monitor_id)
    if monitor is not None and not effective_enabled(db, monitor):
        return  # preserve rule, firing state, watermark and history; no fake recovery
    now = now or datetime.now(timezone.utc)
    rules = db.query(AlertRule).filter_by(kind="monitor_down", target=str(monitor_id),
                                          enabled=True).order_by(AlertRule.id).with_for_update().populate_existing().all()
    if not rules:
        return
    monitor = db.get(Monitor, monitor_id)
    for rule in rules:
        if monitor is None:
            _evaluate(db, rule, None, "", now)
            continue
        status = monitor_status(monitor, db.get(Node, monitor.node_id), now)
        bad = None if status not in ('up', 'down') else status == 'down'
        _evaluate(db, rule, bad, f"监控项 {rule.label or monitor.name} 探测失败",
                  monitor.last_check_at or now)


def evaluate_wg_rules(db: Session, topology: dict | None = None,
                      now: datetime | None = None) -> None:
    """WG 链路规则：只在 health=failed（红）触发；degraded（橙）/unknown（灰）不触发。"""
    now = now or datetime.now(timezone.utc)
    rules = db.query(AlertRule).filter_by(kind="wg_link", enabled=True).order_by(AlertRule.id).with_for_update().populate_existing().all()
    if not rules:
        return
    if topology is None:
        from app.services.server_map import get_topology
        topology = get_topology(db)
    links = {l["id"]: l for l in topology.get("links", [])}
    manual_context = None
    for rule in rules:
        if rule.target.startswith("manual:"):
            from app.services import wg_manual, server_map
            if manual_context is None:
                manual_context = server_map._read_map_data(db)
            nodes, snapshots, _ = manual_context
            observation = wg_manual.health(rule, nodes, snapshots, now=now)
            health = observation["health"]
            sample_at = (datetime.fromisoformat(observation['checked_at'].replace('Z', '+00:00'))
                         if observation['checked_at'] is not None else now)
            _evaluate(db, rule, None if health == "unknown" else health == "failed",
                f"WG 手动方向 {rule.label} ICMP 探测失败", sample_at)
            continue
        link = links.get(rule.target)
        if link is None:
            _evaluate(db, rule, None, "", now)           # 链路消失：中性
            continue
        health = link.get("health")
        if health in ("unknown", None):
            _evaluate(db, rule, None, "keep", now)       # 数据缺失：中性
            continue
        bad = health == "failed"
        _evaluate(db, rule, bad, f"WG 链路 {rule.label} 存在有效方向 ICMP 探测失败", now)
