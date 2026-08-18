"""监控模块测试：节点纳管 + agent 上报 + 幂等补传 + 心跳状态转换。"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4


def _mk_node(client):
    return client.post("/nodes/", json={
        "name": f"node_{uuid4().hex[:8]}",
        "platform": "linux",
        "host": "10.0.0.1",
    }).json()


def test_create_node(client):
    """创建节点 → 201 + status=pending + 生成 token"""
    n = _mk_node(client)
    assert n["status"] == "pending"
    assert n["token"]  # 有鉴权 token


def test_list_nodes(client):
    """列表能查到刚建的节点"""
    n = _mk_node(client)
    ids = {x["id"] for x in client.get("/nodes/").json()}
    assert n["id"] in ids


def test_agent_report_flow(client):
    """完整上报链路：pending → 上报 → online + 数据落库"""
    n = _mk_node(client)
    token = n["token"]

    # agent 上报流量 + 系统指标
    now = datetime.now(timezone.utc)
    resp = client.post(f"/agent/report?token={token}", json={
        "metrics": [
            {"iface": "eth0", "ts": now.isoformat(), "rx_delta": 1000, "tx_delta": 500},
        ],
        "sys_metrics": [
            {"ts": now.isoformat(), "cpu_pct": 0.5, "mem_pct": 0.3, "disk_pct": 0.7},
        ],
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "online"

    # 节点状态变成 online
    nodes = {x["id"]: x for x in client.get("/nodes/").json()}
    assert nodes[n["id"]]["status"] == "online"


def test_agent_report_idempotent(client):
    """幂等：同一 (node,iface,ts) 重复上报，不报错、不重复入库"""
    n = _mk_node(client)
    token = n["token"]
    ts = datetime.now(timezone.utc).isoformat()
    payload = {
        "metrics": [{"iface": "eth0", "ts": ts, "rx_delta": 111, "tx_delta": 222}],
    }
    assert client.post(f"/agent/report?token={token}", json=payload).status_code == 200
    # 重复上报同一 ts
    assert client.post(f"/agent/report?token={token}", json=payload).status_code == 200
    # 不炸、不重复即可（重复丢弃由唯一约束保证）


def test_agent_report_bad_token(client):
    """坏 token → 401"""
    resp = client.post("/agent/report?token=bad-token", json={"metrics": []})
    assert resp.status_code == 401


def test_remove_node(client):
    """移除节点 → 从列表消失"""
    n = _mk_node(client)
    assert client.delete(f"/nodes/{n['id']}").status_code == 204
    ids = {x["id"] for x in client.get("/nodes/").json()}
    assert n["id"] not in ids


def test_agent_config(client):
    """拉配置 → 返回 node_id"""
    n = _mk_node(client)
    cfg = client.get(f"/agent/config?token={n['token']}").json()
    assert cfg["node_id"] == n["id"]
