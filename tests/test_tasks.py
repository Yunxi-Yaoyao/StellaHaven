"""任务域测试：打流 / MTR / 命令 的发起 + agent 轮询领取 + 结果回传 + 打流并发限制。

注意：iperf 有「全局并发限制」（pending/running 只允许一个），而测试数据 commit 后
残留（rollback 挡不住 commit），所以每个创建 pending 打流的测试必须自己清理——
否则会卡住后续测试的并发检查。
"""
from uuid import uuid4


def _mk_node(client):
    return client.post("/nodes/", json={
        "name": f"node_{uuid4().hex[:8]}", "platform": "linux", "host": "10.0.0.1",
    }).json()


def _mk_iperf(client, node_id):
    return client.post("/iperf-tasks", json={
        "server_node_id": node_id, "client_node_id": node_id, "mode": "iperf3",
    }).json()


def _finish_iperf(client, task_id, token):
    """清理：把 pending 打流任务 finish 成 done，释放并发限制。"""
    client.post(f"/agent/iperf-tasks/{task_id}/result?token={token}&status=done", json={})


def test_create_iperf_task(client):
    """发起打流 → 201 + pending"""
    n = _mk_node(client)
    t = _mk_iperf(client, n["id"])
    assert t["status"] == "pending"
    assert t["mode"] == "iperf3"
    _finish_iperf(client, t["id"], n["token"])


def test_iperf_concurrency_limit(client):
    """并发限制：同一时间只允许一个打流任务"""
    n = _mk_node(client)
    t1 = _mk_iperf(client, n["id"])
    # 第二个 pending 打流 → 409
    assert client.post("/iperf-tasks", json={
        "server_node_id": n["id"], "client_node_id": n["id"],
    }).status_code == 409
    _finish_iperf(client, t1["id"], n["token"])


def test_agent_poll_and_finish_iperf(client):
    """agent 领取打流任务 → 回传结果 → 状态 pending→running→done"""
    n = _mk_node(client)
    t = _mk_iperf(client, n["id"])
    # agent 轮询领取（现在返回完整任务详情）
    polled = client.get(f"/agent/tasks?token={n['token']}").json()
    assert polled["node_id"] == n["id"]
    task = next(x for x in polled["iperf_tasks"] if x["id"] == t["id"])
    assert task["mode"] == "iperf3"
    assert "server_host" in task
    # 回传结果
    assert client.post(f"/agent/iperf-tasks/{t['id']}/result?token={n['token']}&status=done",
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
