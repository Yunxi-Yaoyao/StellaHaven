"""任务域 services：打流 / MTR / 命令 的发起 + agent 轮询领取 + 结果回传。"""
from sqlalchemy.orm import Session

from app.repositories import task as repo
from app.repositories import node as node_repo
from app.models.task import IperfTask, MtrTask, AgentCommand, ComponentTask, NetTask


# ── 发起（前端工具页）──
def create_iperf(db: Session, server_node_id: int | None, client_node_id: int,
                 mode: str, direction: str, duration: int, parallel: int,
                 udp: bool = False, bitrate: str | None = None, port: int = 5201,
                 window: str | None = None, length: str | None = None,
                 omit: int = 0, zerocopy: bool = False, bytes: str | None = None) -> IperfTask:
    # 打流并发限制：同一时间只允许一个 running/pending 打流任务（防打满带宽拖垮代理）
    active = db.query(IperfTask).filter(IperfTask.status.in_(["pending", "running"])).count()
    if active > 0:
        raise ValueError("已有打流任务进行中")
    return repo.create_iperf(db, server_node_id, client_node_id, mode, direction,
                             duration, parallel, udp, bitrate, port, window, length,
                             omit, zerocopy, bytes)


def list_iperf(db: Session) -> list[IperfTask]:
    return repo.list_iperf(db)


def get_iperf(db: Session, task_id: int) -> IperfTask | None:
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


def create_mtr(db: Session, node_id: int, target: str, protocol: str) -> MtrTask:
    return repo.create_mtr(db, node_id, target, protocol)


def list_mtr(db: Session) -> list[MtrTask]:
    return repo.list_mtr(db)


def create_command(db: Session, node_id: int, command: str) -> AgentCommand:
    return repo.create_command(db, node_id, command)


def list_commands(db: Session) -> list[AgentCommand]:
    return repo.list_commands(db)


# ── 组件代装（前端点「安装」）──
def install_component(db: Session, node_id: int, component: str) -> ComponentTask:
    if component not in ("iperf3", "speedtest"):
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

    # 领取：server 标记已起 -s（不抢 status，client 还能领）；client 领取 status→running
    for t in server_iperf:
        t.server_started = True
    for t in client_iperf:
        t.status = "running"
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
            }
            for t in client_iperf
        ],
        "mtr_tasks": [
            {"id": t.id, "target": t.target, "protocol": t.protocol}
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


def finish_net_task(db: Session, task_id: int, status: str, result_json: dict | None) -> None:
    repo.finish_net_task(db, task_id, status, result_json)
