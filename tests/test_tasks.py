"""任务域测试：打流 / MTR / 命令 的发起 + agent 轮询领取 + 结果回传 + 打流并发限制。

注意：iperf 有「全局并发限制」（pending/running 只允许一个），而测试数据 commit 后
残留（rollback 挡不住 commit），所以每个创建 pending 打流的测试必须自己清理——
否则会卡住后续测试的并发检查。
"""
from uuid import uuid4


def _mk_node(client, net_type="internal"):
    """创建节点 + 模拟 agent 首次上报（pending → online）；net_type=public 时标记公网。"""
    node = client.post("/nodes/", json={
        "name": f"node_{uuid4().hex[:8]}", "platform": "linux", "host": "10.0.0.1",
    }).json()
    # 上报心跳：pending → online（业务要求创建打流任务时两端都必须在线）
    client.post(f"/agent/report?token={node['token']}", json={"agent_version": "test"})
    if net_type == "public":
        client.patch(f"/nodes/{node['id']}/net-type", json={"net_type": "public"})
    return node


def _mk_iperf(client, server_node_id, client_node_id):
    return client.post("/iperf-tasks", json={
        "server_node_id": server_node_id, "client_node_id": client_node_id, "mode": "iperf3",
    }).json()


def _finish_iperf(client, task_id, token):
    """清理：把 pending 打流任务 finish 成 done，释放并发限制。"""
    client.post(f"/agent/iperf-tasks/{task_id}/result?token={token}&status=done", json={})


def test_create_iperf_task(client):
    """发起打流 → 201 + pending（服务端公网在线 + 客户端在线，两端不同机）"""
    server = _mk_node(client, net_type="public")
    c = _mk_node(client)
    t = _mk_iperf(client, server["id"], c["id"])
    assert t["status"] == "pending"
    assert t["mode"] == "iperf3"
    _finish_iperf(client, t["id"], c["token"])


def test_iperf_concurrency_limit(client):
    """并发限制：同一时间只允许一个打流任务"""
    server = _mk_node(client, net_type="public")
    c = _mk_node(client)
    t1 = _mk_iperf(client, server["id"], c["id"])
    # 第二个 pending 打流 → 409
    assert client.post("/iperf-tasks", json={
        "server_node_id": server["id"], "client_node_id": c["id"],
    }).status_code == 409
    _finish_iperf(client, t1["id"], c["token"])


def test_agent_poll_and_finish_iperf(client):
    """agent 领取打流任务 → 回传结果 → 状态 pending→running→done"""
    server = _mk_node(client, net_type="public")
    c = _mk_node(client)
    t = _mk_iperf(client, server["id"], c["id"])
    # 领取顺序必须模拟真实时序：server 先 poll（标记 server_started=True），client 才能领
    # （业务规则：client 抢跑会连到上一个任务的遗留 server → Connection refused）
    server_polled = client.get(f"/agent/tasks?token={server['token']}").json()
    assert any(x["id"] == t["id"] for x in server_polled["iperf_tasks"])
    # agent 轮询领取（现在返回完整任务详情）
    polled = client.get(f"/agent/tasks?token={c['token']}").json()
    assert polled["node_id"] == c["id"]
    task = next(x for x in polled["iperf_tasks"] if x["id"] == t["id"])
    assert task["mode"] == "iperf3"
    assert "server_host" in task
    # 回传结果
    assert client.post(f"/agent/iperf-tasks/{t['id']}/result?token={c['token']}&status=done",
                       json={"sum_sent": {"bits_per_second": 900000000}}).status_code == 200
    # 列表里状态是 done
    tasks = {x["id"]: x for x in client.get("/iperf-tasks").json()}
    assert tasks[t["id"]]["status"] == "done"
    assert tasks[t["id"]]["result_json"] is not None


def test_agent_poll_mtr_and_command(client):
    """agent 领取 MTR + 命令任务（返回完整详情）"""
    n = _mk_node(client)
    m = client.post("/mtr-tasks", json={"node_id": n["id"], "target": "8.8.8.8"}).json()
    c = client.post("/commands", json={"node_id": n["id"], "command": "echo hi"}).json()
    polled = client.get(f"/agent/tasks?token={n['token']}").json()
    mtr = next(x for x in polled["mtr_tasks"] if x["id"] == m["id"])
    cmd = next(x for x in polled["commands"] if x["id"] == c["id"])
    assert mtr["target"] == "8.8.8.8"
    assert cmd["command"] == "echo hi"


def test_agent_finish_command(client):
    """agent 回传命令结果 → stdout/stderr/exit_code 落库"""
    n = _mk_node(client)
    c = client.post("/commands", json={"node_id": n["id"], "command": "uname -a"}).json()
    client.post(f"/agent/commands/{c['id']}/result?token={n['token']}&status=done&stdout=Linux&exit_code=0")
    cmds = {x["id"]: x for x in client.get("/commands").json()}
    assert cmds[c["id"]]["status"] == "done"
    assert cmds[c["id"]]["stdout"] == "Linux"
    assert cmds[c["id"]]["exit_code"] == 0


def test_agent_poll_bad_token(client):
    """坏 token 拉任务 → 401"""
    assert client.get("/agent/tasks?token=bad").status_code == 401
