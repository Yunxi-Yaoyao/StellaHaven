"""任务域 services：打流 / MTR / 命令 的发起 + agent 轮询领取 + 结果回传。"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.repositories import task as repo
from app.repositories import node as node_repo
from app.models.task import IperfTask, MtrTask, AgentCommand, ComponentTask, NetTask


# ── 打流看门狗（惰性清扫：列表/详情被读时顺手扫，不开后台任务）──
def _iperf_timeout_sec(t: IperfTask) -> int:
    """running 任务的合理最长耗时。speedtest 全程 ~90s 阻塞；数据量模式速率未知给宽限。"""
    if t.mode == "speedtest":
        return 150
    if t.bytes:
        return 300
    return t.duration + 60


def sweep_stale_iperf(db: Session) -> None:
    """把卡死的打流任务标 failed：
    - running 超过合理时长（agent 失联/进程挂死，结果永远回不来）
    - pending 超过 5 分钟没人领（节点离线）——卡住的 pending 会一直占着「已有任务进行中」的并发锁
    """
    now = datetime.now(timezone.utc)
    dirty = False
    for t in db.query(IperfTask).filter(IperfTask.status == "running").all():
        base = t.started_at or t.created_at
        if base is None:
            continue
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        if (now - base).total_seconds() > _iperf_timeout_sec(t):
            t.status = "failed"
            t.result_json = {"error": "agent 失联：任务超时未完成（看门狗清理）"}
            dirty = True
    for t in db.query(IperfTask).filter(IperfTask.status == "pending").all():
        base = t.created_at
        if base is None:
            continue
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        if (now - base).total_seconds() > 300:
            t.status = "failed"
            t.result_json = {"error": "agent 超过 5 分钟未领取（节点离线？）"}
            dirty = True
    if dirty:
        db.commit()


# ── 发起（前端工具页）──
def create_iperf(db: Session, server_node_id: int | None, client_node_id: int,
                 mode: str, direction: str, duration: int, parallel: int,
                 udp: bool = False, bitrate: str | None = None, port: int = 5201,
                 window: str | None = None, length: str | None = None,
                 omit: int = 0, zerocopy: bool = False, bytes: str | None = None,
                 speedtest_server: str | None = None) -> IperfTask:
    # 打流并发限制：同一时间只允许一个 running/pending 打流任务（防打满带宽拖垮代理）
    sweep_stale_iperf(db)  # 先清卡死任务，别让僵尸占着并发锁
    active = db.query(IperfTask).filter(IperfTask.status.in_(["pending", "running"])).count()
    if active > 0:
        raise ValueError("已有打流任务进行中")
    # 节点约束：两端都必须在线；iperf3 互打时服务端必须是公网节点（client 要能连到 5201），且两端不同机
    client = node_repo.get_by_id(db, client_node_id)
    if client is None or client.status != "online":
        raise ValueError("客户端节点不在线")
    if mode == "iperf3":
        if server_node_id is None:
            raise ValueError("iperf3 互打需要选择服务端节点")
        if server_node_id == client_node_id:
            raise ValueError("服务端和客户端不能是同一台")
        server = node_repo.get_by_id(db, server_node_id)
        if server is None or server.status != "online":
            raise ValueError("服务端节点不在线")
        if server.net_type != "public":
            raise ValueError(f"服务端 {server.name} 不是公网节点，客户端连不到它的 5201 端口")
    return repo.create_iperf(db, server_node_id, client_node_id, mode, direction,
                             duration, parallel, udp, bitrate, port, window, length,
                             omit, zerocopy, bytes, speedtest_server)


def list_iperf(db: Session) -> list[IperfTask]:
    sweep_stale_iperf(db)
    return repo.list_iperf(db)


def get_iperf(db: Session, task_id: int) -> IperfTask | None:
    sweep_stale_iperf(db)
    return repo.get_iperf(db, task_id)


def cancel_iperf(db: Session, task_id: int) -> IperfTask | None:
    """中止打流任务：pending/running → cancelled。agent 检测到 cancelled 后 terminate iperf3 进程。"""
    t = repo.get_iperf(db, task_id)
    if t is None:
        return None
    if t.status in ("pending", "running"):
        t.status = "cancelled"
        db.commit()
    return t


# MTR 参数合法范围（对应 mtr 的 -c/-i/-m/-s）
_MTR_PARAM_RULES = {
    "count": (int, 1, 100),      # -c 发包数
    "interval": (float, 1.0, 60.0),  # -i 秒（mtr 非 root 下限 1.0）
    "max_hops": (int, 1, 255),   # -m
    "psize": (int, 24, 9000),    # -s 字节
}


def _valid_mtr_params(params: dict | None) -> dict | None:
    """过滤非法参数键/值，越界直接拒绝（防止 agent 拿到奇葩参数跑飞）。"""
    if not params:
        return None
    out: dict = {}
    for k, v in params.items():
        rule = _MTR_PARAM_RULES.get(k)
        if rule is None:
            continue
        typ, lo, hi = rule
        try:
            v2 = typ(v)
        except (TypeError, ValueError):
            raise ValueError(f"参数 {k} 格式不对")
        if not (lo <= v2 <= hi):
            raise ValueError(f"参数 {k} 超出范围 {lo}~{hi}")
        out[k] = v2
    return out or None


def create_mtr(db: Session, node_id: int, target: str, protocol: str,
               params: dict | None = None) -> MtrTask:
    return repo.create_mtr(db, node_id, target, protocol, params=_valid_mtr_params(params))


def update_mtr_live(db: Session, task_id: int, live: dict) -> None:
    repo.update_mtr_live(db, task_id, live)


def create_mtr_for_monitor(db: Session, monitor) -> MtrTask:
    """监控项浮窗的「立即 MTR」：按类型映射协议（http→tcp:80/443），target 存 host[:port]。"""
    from app.services.monitor import mtr_spec
    host, proto, port = mtr_spec(monitor.type, monitor.target)
    target = f"{host}:{port}" if port else host
    return repo.create_mtr(db, monitor.node_id, target, proto,
                           monitor_id=monitor.id, trigger="manual")


def report_mtr(db: Session, token: str, monitor_id: int, trigger: str,
               ok: bool, result_json: dict | None, error: str | None) -> MtrTask:
    """agent 主动上报的监控项 MTR（定时/失败触发）。校验 token 与监控项归属。"""
    from app.services.monitor import mtr_spec
    from app.repositories import monitor as monitor_repo
    node = node_repo.get_by_token(db, token)
    if node is None:
        raise ValueError("无效的 agent token")
    m = monitor_repo.get_by_id(db, monitor_id)
    if m is None or m.node_id != node.id:
        raise ValueError("监控项不存在")
    host, proto, port = mtr_spec(m.type, m.target)
    target = f"{host}:{port}" if port else host
    return repo.insert_mtr_report(db, node.id, monitor_id, target, proto,
                                  trigger, ok, result_json, error)


def list_mtr_for_monitor(db: Session, monitor_id: int) -> list[MtrTask]:
    return repo.list_mtr_for_monitor(db, monitor_id)


def list_mtr(db: Session) -> list[MtrTask]:
    return repo.list_mtr(db)


def create_command(db: Session, node_id: int, command: str) -> AgentCommand:
    return repo.create_command(db, node_id, command)


def list_commands(db: Session) -> list[AgentCommand]:
    return repo.list_commands(db)


# ── 组件代装（前端点「安装」）──
def install_component(db: Session, node_id: int, component: str) -> ComponentTask:
    if component not in ("iperf3", "speedtest", "ufw", "docker", "mtr"):
        raise ValueError("未知组件")
    # 同一节点同一组件若已有 pending/running 任务，直接复用，不重复下发
    existing = db.query(ComponentTask).filter(
        ComponentTask.node_id == node_id,
        ComponentTask.component == component,
        ComponentTask.status.in_(["pending", "running"]),
    ).first()
    if existing:
        return existing
    return repo.create_component(db, node_id, component)


def list_components(db: Session) -> list[ComponentTask]:
    return repo.list_components(db)


# ── agent 轮询：领取该节点待办任务 ──
def poll_tasks(db: Session, token: str) -> dict:
    """agent 拉待办任务：返回该节点的 pending 打流/MTR/命令，并标记为 running（领取）。

    agent 每 5s 轮询一次，领取后执行，再回传结果。

    返回完整任务详情（agent 执行所需），不是只回 id：
    - iperf：server/client 的 host、mode、duration、parallel、direction
    - mtr：target、protocol
    - command：command 原文
    """
    node = node_repo.get_by_token(db, token)
    if node is None or node.status == "removed":
        raise ValueError("invalid token")

    server_iperf = repo.pending_iperf_server(db, node.id)
    client_iperf = repo.pending_iperf_client(db, node.id)
    mtr = repo.pending_mtr_for_node(db, node.id)
    cmds = repo.pending_commands_for_node(db, node.id)
    comps = repo.pending_components_for_node(db, node.id)
    net_tasks = repo.pending_net_tasks(db, node.id)

    # 卸载指令：pending → running（agent 领取后执行卸载）
    uninstall = node.uninstall_status == "pending"
    if uninstall:
        node.uninstall_status = "running"

    # 领取：server 标记已起 -s（不抢 status，client 还能领）；client 领取 status→running + 记领取时刻（看门狗基准）
    now = datetime.now(timezone.utc)
    for t in server_iperf:
        t.server_started = True
    for t in client_iperf:
        t.status = "running"
        t.started_at = now
    for t in mtr:
        t.status = "running"
    for c in cmds:
        c.status = "running"
    for c in comps:
        c.status = "running"
    for t in net_tasks:
        t.status = "running"
    db.commit()

    # iperf 任务详情：查 server/client 节点的 host
    def _host(nid: int | None) -> str | None:
        if nid is None:
            return None
        n = node_repo.get_by_id(db, nid)
        return n.host if n else None

    return {
        "node_id": node.id,
        "uninstall": uninstall,
        "iperf_tasks": [
            {
                "id": t.id,
                "mode": t.mode,
                "server_host": _host(t.server_node_id),
                "client_host": _host(t.client_node_id),
                "same_host": t.server_node_id == t.client_node_id,
                "role": "server",
                "direction": t.direction,
                "duration": t.duration,
                "bytes": t.bytes,
                "parallel": t.parallel,
                "udp": t.udp, "bitrate": t.bitrate, "port": t.port,
                "window": t.window, "length": t.length, "omit": t.omit, "zerocopy": t.zerocopy,
                "speedtest_server": t.speedtest_server,
            }
            for t in server_iperf
        ] + [
            {
                "id": t.id,
                "mode": t.mode,
                "server_host": _host(t.server_node_id),
                "client_host": _host(t.client_node_id),
                "same_host": t.server_node_id == t.client_node_id,
                "role": "client",
                "direction": t.direction,
                "duration": t.duration,
                "bytes": t.bytes,
                "parallel": t.parallel,
                "udp": t.udp, "bitrate": t.bitrate, "port": t.port,
                "window": t.window, "length": t.length, "omit": t.omit, "zerocopy": t.zerocopy,
                "speedtest_server": t.speedtest_server,
            }
            for t in client_iperf
        ],
        "mtr_tasks": [
            {"id": t.id, "target": t.target, "protocol": t.protocol, "params": t.params_json}
            for t in mtr
        ],
        "commands": [
            {"id": c.id, "command": c.command}
            for c in cmds
        ],
        "component_installs": [
            {"id": c.id, "component": c.component}
            for c in comps
        ],
        "net_tasks": [
            {"id": t.id, "kind": t.kind, "payload": t.payload}
            for t in net_tasks
        ],
    }


# ── 结果回传 ──
def finish_iperf(db: Session, task_id: int, status: str, result_json: dict) -> None:
    repo.finish_iperf(db, task_id, status, result_json)


def finish_mtr(db: Session, task_id: int, status: str, result_json: dict) -> None:
    repo.finish_mtr(db, task_id, status, result_json)


def finish_command(db: Session, cmd_id: int, status: str,
                   stdout: str, stderr: str, exit_code: int) -> None:
    repo.finish_command(db, cmd_id, status, stdout, stderr, exit_code)


def append_iperf_progress(db: Session, task_id: int, point: dict) -> None:
    repo.append_iperf_progress(db, task_id, point)


def finish_component(db: Session, task_id: int, status: str, error: str = "") -> None:
    repo.finish_component(db, task_id, status, error)


# ── 网络操作任务（改 IP 回退 / 防火墙修改）──
def create_ip_change(db: Session, node_id: int, iface: str, new_ip: str,
                     prefix: int, gateway: str | None, ping_target: str) -> NetTask:
    """下发改 IP 任务（高危：agent 本地执行临时改 → ping 测试 → 通写持久化 / 不通回退）。"""
    payload = {"iface": iface, "new_ip": new_ip, "prefix": prefix,
               "gateway": gateway, "ping_target": ping_target}
    return repo.create_net_task(db, node_id, "ip_change", payload)


def create_firewall_scan(db: Session, node_id: int) -> NetTask:
    """下发防火墙结构化采集任务（ufw numbered + iptables-save 五表，只读）。"""
    node = node_repo.get_by_id(db, node_id)
    if node is None or node.status != "online":
        raise ValueError("节点不在线")
    return repo.create_net_task(db, node_id, "firewall_scan", None)


def create_docker_scan(db: Session, node_id: int) -> NetTask:
    """下发 Docker 容器列表采集（只读）。"""
    node = node_repo.get_by_id(db, node_id)
    if node is None or node.status != "online":
        raise ValueError("节点不在线")
    return repo.create_net_task(db, node_id, "docker_scan", None)


def create_pbr_scan(db: Session, node_id: int) -> NetTask:
    """下发 PBR 结构化采集（ip rule / 各路由表 / mangle 打标链，只读）。"""
    node = node_repo.get_by_id(db, node_id)
    if node is None or node.status != "online":
        raise ValueError("节点不在线")
    return repo.create_net_task(db, node_id, "pbr_scan", None)


def create_docker_logs(db: Session, node_id: int, container: str, tail: int = 150) -> NetTask:
    """下发容器日志读取（docker logs --tail，只读）。"""
    node = node_repo.get_by_id(db, node_id)
    if node is None or node.status != "online":
        raise ValueError("节点不在线")
    tail = max(1, min(int(tail), 500))  # 上限 500 行防大包
    return repo.create_net_task(db, node_id, "docker_logs", {"container": container, "tail": tail})


def create_docker_inspect(db: Session, node_id: int, container: str) -> NetTask:
    """下发容器配置查看（docker inspect 摘要化，只读）。"""
    node = node_repo.get_by_id(db, node_id)
    if node is None or node.status != "online":
        raise ValueError("节点不在线")
    return repo.create_net_task(db, node_id, "docker_inspect", {"container": container})


def latest_net_task(db: Session, node_id: int, kind: str) -> NetTask | None:
    return repo.latest_net_task(db, node_id, kind)


def create_docker_ctl(db: Session, node_id: int, action: str, container: str) -> NetTask:
    """容器启停重启（agent 侧再校验 action 白名单 + 容器名合法性）。"""
    if action not in ("start", "stop", "restart"):
        raise ValueError("不支持的操作")
    node = node_repo.get_by_id(db, node_id)
    if node is None or node.status != "online":
        raise ValueError("节点不在线")
    return repo.create_net_task(db, node_id, "docker_ctl", {"action": action, "container": container})


def get_net_task(db: Session, task_id: int) -> NetTask | None:
    return db.get(NetTask, task_id)


def finish_net_task(db: Session, task_id: int, status: str, result_json: dict | None) -> None:
    repo.finish_net_task(db, task_id, status, result_json)
