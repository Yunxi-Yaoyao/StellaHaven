"""监控项测试：CRUD + agent 探测结果上报（无中心探测）。"""
from datetime import datetime, timezone
from uuid import uuid4


def _mk_node(client):
    return client.post("/nodes/", json={
        "name": f"node_{uuid4().hex[:8]}",
        "platform": "linux",
        "host": "10.0.0.1",
    }).json()


def _mk_monitor(client, node_id, target="127.0.0.1:22", mtype="tcp", interval=3600):
    return client.post("/monitors/", json={
        "name": f"mon_{uuid4().hex[:8]}",
        "type": mtype,
        "target": target,
        "interval": interval,
        "timeout": 2,
        "node_id": node_id,
    }).json()


def test_create_monitor_requires_node(client):
    """没传 node_id → 422（Pydantic 校验必填）"""
    resp = client.post("/monitors/", json={
        "name": "no_node", "type": "tcp", "target": "1.1.1.1:80",
    })
    assert resp.status_code == 422


def test_create_monitor_bad_node(client):
    """node_id 不存在 → 404"""
    resp = client.post("/monitors/", json={
        "name": "bad", "type": "tcp", "target": "1.1.1.1:80", "node_id": 999999,
    })
    assert resp.status_code == 404


def test_create_monitor(client):
    n = _mk_node(client)
    m = _mk_monitor(client, n["id"])
    assert m["status"] == "unknown"
    assert m["node_id"] == n["id"]
    assert m["type"] == "tcp"


def test_list_monitors(client):
    n = _mk_node(client)
    m = _mk_monitor(client, n["id"])
    ids = {x["id"] for x in client.get("/monitors/").json()}
    assert m["id"] in ids


def test_delete_monitor(client):
    n = _mk_node(client)
    m = _mk_monitor(client, n["id"])
    assert client.delete(f"/monitors/{m['id']}").status_code == 204
    ids = {x["id"] for x in client.get("/monitors/").json()}
    assert m["id"] not in ids


def test_agent_config_delivers_monitors(client):
    """agent 拉配置 → 返回负责的监控项 + 版本号"""
    n = _mk_node(client)
    _mk_monitor(client, n["id"])
    cfg = client.get(f"/agent/config?token={n['token']}").json()
    assert cfg["node_id"] == n["id"]
    assert len(cfg["monitors"]) >= 1
    assert "monitors_version" in cfg


def test_monitor_check_report(client):
    """agent 上报探测结果 → status 更新 + 落历史"""
    n = _mk_node(client)
    m = _mk_monitor(client, n["id"])
    now = datetime.now(timezone.utc)
    resp = client.post(f"/agent/monitor-check?token={n['token']}", json={
        "monitor_id": m["id"], "ts": now.isoformat(), "success": True, "latency_ms": 12.3,
    })
    assert resp.status_code == 200
    listed = {x["id"]: x for x in client.get("/monitors/").json()}
    assert listed[m["id"]]["status"] == "up"
    assert listed[m["id"]]["last_latency_ms"] == 12.3
    checks = client.get(f"/monitors/{m['id']}/checks").json()
    assert len(checks) >= 1
    assert checks[0]["success"] is True


def test_monitor_check_wrong_node(client):
    """agent 上报不属于自己的监控项 → 404"""
    n1 = _mk_node(client)
    n2 = _mk_node(client)
    m = _mk_monitor(client, n1["id"])
    now = datetime.now(timezone.utc)
    resp = client.post(f"/agent/monitor-check?token={n2['token']}", json={
        "monitor_id": m["id"], "ts": now.isoformat(), "success": True,
    })
    assert resp.status_code == 404


def test_monitor_version_bumps(client):
    """增删监控项 → monitors_version 递增"""
    n = _mk_node(client)
    v0 = client.get(f"/agent/config?token={n['token']}").json()["monitors_version"]
    _mk_monitor(client, n["id"])
    v1 = client.get(f"/agent/config?token={n['token']}").json()["monitors_version"]
    assert v1 > v0
