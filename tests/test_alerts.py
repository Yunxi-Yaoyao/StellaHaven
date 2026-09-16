"""告警域测试：规则 CRUD + 状态机（防抖/触发/恢复/重复提醒）+ 三类惰性评估 + 派发。

TDD：先红后绿。DB 用 conftest 的真实 PG 测试库（自动回滚）。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.alert import AlertEvent, AlertRule, AlertState, Notification
from app.repositories import node as node_repo
from app.services import alerts
from app.services import monitor as monitor_svc

NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)


# ── helpers ──
def make_node(db, name="HK", *, status="online", seen=None):
    node = node_repo.create(db, name, "linux", "1.2.3.4")
    node.status = status
    node.last_seen_at = seen if seen is not None else NOW
    db.flush()
    return node


def add_rule(db, kind, target, **kw):
    kw.setdefault("link", f"/status/{target}" if kind in ("node_offline", "monitor_down") else "/status")
    return alerts.create_rule(db, kind, target, **kw)


def fired_events(db, rule_id):
    return [e for e in db.query(AlertEvent).filter_by(rule_id=rule_id).all()]


def notifications(db, rule_id=None):
    """按规则过滤：monitor 仓储内部 commit，测试间不能靠回滚隔离，只能按 rule_id 取自己的。"""
    q = db.query(Notification).order_by(Notification.id)
    if rule_id is not None:
        q = q.filter_by(rule_id=rule_id)
    return q.all()


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    """测试里不真发邮件/WS——记录调用即可。"""
    calls = {"email": [], "ws": []}
    monkeypatch.setattr(alerts, "_send_alert_email", lambda db, rule, event, msg: calls["email"].append((rule.id, event)))
    monkeypatch.setattr(alerts, "_push_ws", lambda payload: calls["ws"].append(payload))
    return calls


# ── CRUD ──
def test_create_rule_validates_and_rejects_duplicate(db_session):
    node = make_node(db_session)
    rule = add_rule(db_session, "node_offline", str(node.id), label="HK")
    assert rule.severity == "warning" and rule.debounce == 2 and rule.enabled is True

    with pytest.raises(ValueError):
        add_rule(db_session, "node_offline", str(node.id))  # 重复
    with pytest.raises(ValueError):
        add_rule(db_session, "bad_kind", str(node.id))
    with pytest.raises(ValueError):
        add_rule(db_session, "node_offline", str(node.id), severity="fatal")


def test_update_and_delete_rule_cascades_state(db_session):
    node = make_node(db_session)
    rule = add_rule(db_session, "node_offline", str(node.id), label="HK")
    alerts.evaluate_node_rules(db_session, now=NOW)
    state = db_session.get(AlertState, rule.id)
    assert state is not None and state.state == "ok"

    alerts.update_rule(db_session, rule.id, {"enabled": False, "severity": "critical"})
    assert alerts.get_rule(db_session, rule.id).enabled is False

    alerts.delete_rule(db_session, rule.id)
    assert alerts.get_rule(db_session, rule.id) is None
    assert db_session.get(AlertState, rule.id) is None


# ── 节点离线状态机 ──
def test_node_offline_debounce_then_fire_and_resolve(db_session, no_side_effects):
    node = make_node(db_session)
    rule = add_rule(db_session, "node_offline", str(node.id), label="HK")

    stale = NOW - timedelta(seconds=300)
    node.last_seen_at = stale
    alerts.evaluate_node_rules(db_session, now=NOW)          # 第 1 次异常：防抖中
    assert db_session.get(AlertState, rule.id).state == "ok"
    assert fired_events(db_session, rule.id) == []

    alerts.evaluate_node_rules(db_session, now=NOW)          # 第 2 次：触发
    state = db_session.get(AlertState, rule.id)
    assert state.state == "firing" and state.consecutive == 2
    assert [e.event for e in fired_events(db_session, rule.id)] == ["fired"]
    notes = notifications(db_session, rule.id)
    assert len(notes) == 1 and notes[0].kind == "alert" and "HK" in notes[0].title
    assert notes[0].link == f"/status/{node.id}"
    assert no_side_effects["email"] == [(rule.id, "fired")]
    assert len(no_side_effects["ws"]) == 1

    alerts.evaluate_node_rules(db_session, now=NOW)          # firing 中：不重复触发
    assert len(fired_events(db_session, rule.id)) == 1

    node.last_seen_at = NOW                                  # 恢复
    alerts.evaluate_node_rules(db_session, now=NOW)
    state = db_session.get(AlertState, rule.id)
    assert state.state == "ok" and state.consecutive == 0
    assert [e.event for e in fired_events(db_session, rule.id)] == ["fired", "resolved"]
    assert notifications(db_session, rule.id)[-1].kind == "alert_resolved"
    assert no_side_effects["email"][-1] == (rule.id, "resolved")


def test_firing_repeat_reminder_respects_interval(db_session, no_side_effects):
    node = make_node(db_session, seen=NOW - timedelta(seconds=300))
    rule = add_rule(db_session, "node_offline", str(node.id), label="HK",
                              repeat_minutes=30)
    alerts.evaluate_node_rules(db_session, now=NOW)
    alerts.evaluate_node_rules(db_session, now=NOW)          # fired
    assert len(notifications(db_session, rule.id)) == 1

    alerts.evaluate_node_rules(db_session, now=NOW + timedelta(minutes=10))  # 未到间隔
    assert len(notifications(db_session, rule.id)) == 1

    alerts.evaluate_node_rules(db_session, now=NOW + timedelta(minutes=31))  # 到点重复提醒
    notes = notifications(db_session, rule.id)
    assert len(notes) == 2 and "仍在告警" in notes[-1].title
    assert len(fired_events(db_session, rule.id)) == 1       # 提醒不写事件流水
    assert len(no_side_effects["email"]) == 1                # 提醒只站内，不轰炸邮箱


def test_disabled_rule_is_not_evaluated(db_session):
    node = make_node(db_session, seen=NOW - timedelta(seconds=300))
    rule = add_rule(db_session, "node_offline", str(node.id), label="HK")
    alerts.update_rule(db_session, rule.id, {"enabled": False})
    alerts.evaluate_node_rules(db_session, now=NOW)
    alerts.evaluate_node_rules(db_session, now=NOW)
    assert db_session.get(AlertState, rule.id).state == "ok"


def test_pending_or_removed_node_does_not_fire(db_session):
    pending = make_node(db_session, name="new", status="pending", seen=None)
    removed = make_node(db_session, name="old", status="removed", seen=NOW - timedelta(days=1))
    rules = [add_rule(db_session, "node_offline", str(n.id), label=n.name) for n in (pending, removed)]
    alerts.evaluate_node_rules(db_session, now=NOW)
    alerts.evaluate_node_rules(db_session, now=NOW)
    for r in rules:
        assert notifications(db_session, r.id) == []


def test_rule_on_deleted_target_resolves_and_stays_quiet(db_session):
    node = make_node(db_session, seen=NOW - timedelta(seconds=300))
    rule = add_rule(db_session, "node_offline", str(node.id), label="HK")
    alerts.evaluate_node_rules(db_session, now=NOW)
    alerts.evaluate_node_rules(db_session, now=NOW)          # firing
    node_repo.remove(db_session, node.id)                    # 目标被移除
    alerts.evaluate_node_rules(db_session, now=NOW)
    assert db_session.get(AlertState, rule.id).state == "ok"  # 静默复位，不发恢复通知
    assert len(notifications(db_session, rule.id)) == 1                # 只有触发那一条


# ── 监控项 down ──
def test_monitor_down_fires_and_recovers(db_session):
    node = make_node(db_session)
    monitor = monitor_svc.create_monitor(db_session, "blog", "http", "https://example.com",
                                         node_id=node.id, interval=60, timeout=5)
    rule = add_rule(db_session, "monitor_down", str(monitor.id), label="blog",
                    link=f"/status/{node.id}")

    for _ in range(2):                                       # 连续 2 次失败
        monitor_svc.record_check(db_session, monitor.id, NOW, success=False, latency_ms=None, loss_pct=None)
    state = db_session.get(AlertState, rule.id)
    assert state.state == "firing"
    assert notifications(db_session, rule.id)[0].link == f"/status/{node.id}"

    monitor_svc.record_check(db_session, monitor.id, NOW, success=True, latency_ms=12.0, loss_pct=0.0)
    assert db_session.get(AlertState, rule.id).state == "ok"
    assert notifications(db_session, rule.id)[-1].kind == "alert_resolved"


# ── WG 链路 ──
def _topology(health, link_id="ab" * 32):
    return {"links": [{"id": link_id, "health": health, "source": 1, "target": 2,
                       "peer_label": "TYO-AWS", "source_interface": "wg-netlab",
                       "target_interface": "wg-netlab"}]}


def test_wg_link_fires_on_failed_only_and_unknown_is_not_bad(db_session):
    rule = add_rule(db_session, "wg_link", "ab" * 32, label="Stella ↔ TYO-AWS · wg-netlab")

    alerts.evaluate_wg_rules(db_session, topology=_topology("degraded"), now=NOW)  # 橙：不触发
    alerts.evaluate_wg_rules(db_session, topology=_topology("degraded"), now=NOW)
    assert db_session.get(AlertState, rule.id).state == "ok"

    alerts.evaluate_wg_rules(db_session, topology=_topology("failed"), now=NOW)
    alerts.evaluate_wg_rules(db_session, topology=_topology("failed"), now=NOW)    # 红 ×2：触发
    assert db_session.get(AlertState, rule.id).state == "firing"
    assert notifications(db_session, rule.id)[0].link == "/status"

    alerts.evaluate_wg_rules(db_session, topology=_topology("unknown"), now=NOW)   # 灰：不当异常也不恢复
    assert db_session.get(AlertState, rule.id).state == "firing"

    alerts.evaluate_wg_rules(db_session, topology=_topology("ok"), now=NOW)        # 绿：恢复
    assert db_session.get(AlertState, rule.id).state == "ok"
    assert notifications(db_session, rule.id)[-1].kind == "alert_resolved"


def test_wg_link_missing_from_topology_is_neutral(db_session):
    rule = add_rule(db_session, "wg_link", "ab" * 32, label="l")
    alerts.evaluate_wg_rules(db_session, topology={"links": []}, now=NOW)
    alerts.evaluate_wg_rules(db_session, topology={"links": []}, now=NOW)
    assert db_session.get(AlertState, rule.id).state == "ok"
    assert notifications(db_session, rule.id) == []


# ── API 层 ──
def test_rules_api_crud(client):
    r = client.post("/alerts/rules", json={"kind": "node_offline", "target": "999999",
                                           "label": "X", "link": "/status/999999"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    mine = [x for x in client.get("/alerts/rules").json() if x["id"] == rid]
    assert mine and mine[0]["state"] == "ok" and mine[0]["label"] == "X"

    assert client.patch(f"/alerts/rules/{rid}", json={"enabled": False, "severity": "critical"}).status_code == 200
    assert client.post("/alerts/rules", json={"kind": "node_offline", "target": "999999"}).status_code == 400
    assert client.post("/alerts/rules", json={"kind": "nope", "target": "1"}).status_code == 400
    assert client.patch(f"/alerts/rules/{rid}", json={"severity": "fatal"}).status_code == 400

    assert client.delete(f"/alerts/rules/{rid}").status_code == 200
    assert client.delete(f"/alerts/rules/{rid}").status_code == 404


def test_notifications_api_flow(client, db_session, no_side_effects):
    node = make_node(db_session, name="API", seen=NOW - timedelta(seconds=300))
    rule = add_rule(db_session, "node_offline", str(node.id), label="API",
                    link=f"/status/{node.id}")
    alerts.evaluate_node_rules(db_session, now=NOW)
    alerts.evaluate_node_rules(db_session, now=NOW)          # fired → 通知落库

    mine = [n for n in client.get("/notifications").json() if n["rule_id"] == rule.id]
    assert len(mine) == 1 and mine[0]["read"] is False
    assert client.get("/notifications/unread-count").json()["count"] >= 1

    nid = mine[0]["id"]
    assert client.post(f"/notifications/{nid}/read").status_code == 200
    assert client.post(f"/notifications/{nid}/read").status_code == 200  # 幂等
    assert client.post("/notifications/999999999/read").status_code == 404
    r = client.post("/notifications/read-all")
    assert r.status_code == 200 and r.json()["marked"] >= 0
    assert [n for n in client.get("/notifications?unread=true").json() if n["rule_id"] == rule.id] == []

    events = [e for e in client.get(f"/alerts/events?rule_id={rule.id}").json()
              if e["rule_id"] == rule.id]
    assert [e["event"] for e in events] == ["fired"]


def test_rules_api_requires_login(client):
    """未登录访问被拒（依赖 current_user 全局挂在 router 上）。"""
    from main import app as _app
    from fastapi.testclient import TestClient as _TC
    with _TC(_app) as anon:
        assert anon.get("/alerts/rules").status_code in (401, 403)
        assert anon.get("/notifications").status_code in (401, 403)


def test_notifications_ws_route_not_shadowed_by_doc_ws(client):
    """回归：/ws/notifications 必须先于 /ws/{doc_id} 注册（str 路径参数会抢走它）。"""
    with client.websocket_connect("/ws/notifications"):
        pass  # 能建立连接即通过；被 doc 路由抢走会 403
