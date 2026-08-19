"""任务域 repositories：打流 / MTR / 命令 的 CRUD + agent 轮询领取 + 结果回传。"""
import json
from datetime import datetime, timezone, timedelta

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.models.task import IperfTask, MtrTask, AgentCommand, ComponentTask, NetTask

# 每类任务记录保留上限（惰性清理：新增时顺带裁掉旧记录）
KEEP = 100


def trim_old(db: Session, model, keep: int = KEEP) -> None:
    """只保留最新 keep 条，多余的从老到新删除。惰性清理，随 create 调用。"""
    ids = [r[0] for r in db.query(model.id).order_by(model.id.desc()).offset(keep).all()]
    if ids:
        db.query(model).filter(model.id.in_(ids)).delete(synchronize_session=False)


# ── iperf 打流 ──
def create_iperf(db: Session, server_node_id: int | None, client_node_id: int,
                 mode: str, direction: str, duration: int, parallel: int,
                 udp: bool = False, bitrate: str | None = None, port: int = 5201,
                 window: str | None = None, length: str | None = None,
                 omit: int = 0, zerocopy: bool = False, bytes: str | None = None,
                 speedtest_server: str | None = None) -> IperfTask:
    t = IperfTask(server_node_id=server_node_id, client_node_id=client_node_id,
                  mode=mode, direction=direction, duration=duration, parallel=parallel,
                  udp=udp, bitrate=bitrate, port=port, window=window,
                  length=length, omit=omit, zerocopy=zerocopy, bytes=bytes,
                  speedtest_server=speedtest_server)
    db.add(t)
    db.commit()
    trim_old(db, IperfTask)
    db.commit()
    db.refresh(t)
    return t


def list_iperf(db: Session, limit: int = 100) -> list[IperfTask]:
    return db.query(IperfTask).order_by(IperfTask.id.desc()).limit(limit).all()


def get_iperf(db: Session, task_id: int) -> IperfTask | None:
    return db.get(IperfTask, task_id)


# ── MTR ──
def create_mtr(db: Session, node_id: int, target: str, protocol: str,
               monitor_id: int | None = None, trigger: str = "manual") -> MtrTask:
    t = MtrTask(node_id=node_id, target=target, protocol=protocol,
                monitor_id=monitor_id, trigger=trigger)
    db.add(t)
    db.commit()
    trim_old(db, MtrTask)
    db.commit()
    db.refresh(t)
    return t


def insert_mtr_report(db: Session, node_id: int, monitor_id: int, target: str,
                      protocol: str, trigger: str, ok: bool,
                      result_json: dict | None, error: str | None) -> MtrTask:
    """agent 主动上报的 MTR 结果（监控项定时/失败触发）——直接落成 done/failed 行。"""
    payload = result_json or {}
    if error:
        payload = {**payload, "error": error}
    t = MtrTask(node_id=node_id, monitor_id=monitor_id, target=target, protocol=protocol,
                trigger=trigger, status="done" if ok else "failed", result_json=payload or None)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def list_mtr_for_monitor(db: Session, monitor_id: int, limit: int = 200) -> list[MtrTask]:
    """监控项的 MTR 历史（近 60 天）。惰性清扫：读的时候顺手删 60 天前的（全表）。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=60)
    db.query(MtrTask).filter(MtrTask.created_at < cutoff).delete()
    db.commit()
    return db.query(MtrTask).filter(MtrTask.monitor_id == monitor_id)\
        .order_by(MtrTask.id.desc()).limit(limit).all()


def list_mtr(db: Session, limit: int = 100) -> list[MtrTask]:
    return db.query(MtrTask).order_by(MtrTask.id.desc()).limit(limit).all()


def get_mtr(db: Session, task_id: int) -> MtrTask | None:
    return db.get(MtrTask, task_id)


# ── 命令 ──
def create_command(db: Session, node_id: int, command: str) -> AgentCommand:
    c = AgentCommand(node_id=node_id, command=command)
    db.add(c)
    db.commit()
    trim_old(db, AgentCommand)
    db.commit()
    db.refresh(c)
    return c


def list_commands(db: Session, limit: int = 100) -> list[AgentCommand]:
    return db.query(AgentCommand).order_by(AgentCommand.id.desc()).limit(limit).all()


def get_command(db: Session, cmd_id: int) -> AgentCommand | None:
    return db.get(AgentCommand, cmd_id)


# ── agent 轮询：领取该节点待办任务 ──
def pending_iperf_server(db: Session, node_id: int) -> list[IperfTask]:
    """本节点作为 server 且还没起 -s 的任务（status pending/running 都可领，用 server_started 去重）。"""
    return db.query(IperfTask).filter(
        IperfTask.server_node_id == node_id,
        IperfTask.status.in_(["pending", "running"]),
        IperfTask.server_started.is_(False),
    ).all()


def pending_iperf_client(db: Session, node_id: int) -> list[IperfTask]:
    """本节点作为 client 且 pending 的任务（client 领取后 status→running，避免重复领）。

    iperf3 要求 server 端已就绪（server_started=True）才让 client 领取——否则 client
    抢跑会探测/连到上一个任务的遗留 server（正在退出），报 Connection refused /
    server has terminated，任务秒标 failed，server 端再也领不到。speedtest 无 server，不检查。"""
    return db.query(IperfTask).filter(
        IperfTask.client_node_id == node_id,
        IperfTask.status == "pending",
        or_(
            IperfTask.mode == "speedtest",
            IperfTask.server_started.is_(True),
        ),
    ).all()


def pending_iperf_for_node(db: Session, node_id: int) -> list[IperfTask]:
    """该节点参与的 pending 打流任务（作为 server 或 client）。"""
    return db.query(IperfTask).filter(
        IperfTask.status == "pending",
        (IperfTask.server_node_id == node_id) | (IperfTask.client_node_id == node_id),
    ).all()


def pending_mtr_for_node(db: Session, node_id: int) -> list[MtrTask]:
    return db.query(MtrTask).filter(
        MtrTask.status == "pending", MtrTask.node_id == node_id,
    ).all()


def pending_commands_for_node(db: Session, node_id: int) -> list[AgentCommand]:
    return db.query(AgentCommand).filter(
        AgentCommand.status == "pending", AgentCommand.node_id == node_id,
    ).all()


# ── 结果回传 ──
def _iperf_summary(task: IperfTask, r: dict) -> dict:
    """从 result_json 提取摘要列（带宽/丢包/抖动），双格式兼容（iperf3 自建 / speedtest-go / ookla）。

    列语义：avg_mbps=主速率（iperf=接收均值，speedtest=下载），peak_mbps=次速率（iperf=峰值，speedtest=上传）。
    数据异常（suspicious）的任务不落列——避免脏数据混进历史摘要。
    """
    out: dict = {"avg_mbps": None, "peak_mbps": None, "lost_pct": None, "jitter_ms": None}
    if not isinstance(r, dict) or r.get("suspicious"):
        return out
    if task.mode == "speedtest":
        srv = (r.get("servers") or [{}])[0] or {}
        dl = srv.get("dl_speed")
        ul = srv.get("ul_speed")
        jit = srv.get("jitter")
        if jit is not None and dl is not None:
            jit = jit / 1e6  # speedtest-go：jitter 是纳秒（Go time.Duration 序列化），有 dl_speed 即为该格式
        if dl is None and r.get("download", {}).get("bandwidth") is not None:
            dl = r["download"]["bandwidth"]
        if ul is None and r.get("upload", {}).get("bandwidth") is not None:
            ul = r["upload"]["bandwidth"]
        ping = r.get("ping") or {}
        if jit is None and ping.get("jitter") is not None:
            jit = ping["jitter"]  # ookla/librespeed：ms，直接用
        out["avg_mbps"] = round(dl * 8 / 1e6, 2) if dl is not None else None
        out["peak_mbps"] = round(ul * 8 / 1e6, 2) if ul is not None else None
        out["jitter_ms"] = round(jit, 3) if jit is not None else None
        return out
    if r.get("avg_bitrate") is not None:
        out["avg_mbps"] = round(r["avg_bitrate"] / 1e6, 2)
    if r.get("peak_bitrate") is not None:
        out["peak_mbps"] = round(r["peak_bitrate"] / 1e6, 2)
    if r.get("lost_pct") is not None:
        out["lost_pct"] = r["lost_pct"]
    if r.get("jitter_ms") is not None:
        out["jitter_ms"] = r["jitter_ms"]
    return out


def finish_iperf(db: Session, task_id: int, status: str, result_json: dict) -> None:
    """回传打流结果。server 只是辅助（起 -s 等服务），结果以 client 为准，server 回传不覆盖。
    done 时顺带把摘要落到独立列（列表/历史查询不用扛整包 result_json）。"""
    task = db.get(IperfTask, task_id)
    if task is None:
        return
    if task.status == "cancelled":
        return  # 已被前端中止，agent 的 failed 回传不覆盖 cancelled 状态
    role = (result_json or {}).get("role")
    if role == "server":
        return  # server 端结果（含 timeout）不覆盖 client 的实时曲线/汇总
    task.status = status
    task.result_json = result_json
    if status == "done":
        for k, v in _iperf_summary(task, result_json).items():
            setattr(task, k, v)
    db.commit()


def append_iperf_progress(db: Session, task_id: int, point: dict) -> None:
    """原子追加一个实时打流进度点（client + server agent 每秒并发回传）。

    用单条 SQL 的 jsonb 拼接（`||`），靠 PostgreSQL 行锁保证并发安全。
    之前是读-改-写（读 progress_json → append → 写回），client/server 两端并发回传时
    后写的覆盖先写的，导致 progress 点大量丢失（20 秒任务只存下 6 个点）。"""
    db.execute(
        text(
            "UPDATE iperf_tasks SET progress_json = "
            "COALESCE(progress_json, '[]'::jsonb) || (:p)::jsonb WHERE id = :id"
        ),
        {"p": json.dumps(point), "id": task_id},
    )
    db.commit()


def finish_mtr(db: Session, task_id: int, status: str, result_json: dict) -> None:
    db.query(MtrTask).filter(MtrTask.id == task_id).update({
        "status": status, "result_json": result_json,
    })
    db.commit()


def finish_command(db: Session, cmd_id: int, status: str,
                   stdout: str, stderr: str, exit_code: int) -> None:
    db.query(AgentCommand).filter(AgentCommand.id == cmd_id).update({
        "status": status, "stdout": stdout, "stderr": stderr, "exit_code": exit_code,
    })
    db.commit()


# ── 组件代装 ──
def create_component(db: Session, node_id: int, component: str) -> ComponentTask:
    t = ComponentTask(node_id=node_id, component=component)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def list_components(db: Session, limit: int = 100) -> list[ComponentTask]:
    return db.query(ComponentTask).order_by(ComponentTask.id.desc()).limit(limit).all()


def pending_components_for_node(db: Session, node_id: int) -> list[ComponentTask]:
    return db.query(ComponentTask).filter(
        ComponentTask.status == "pending", ComponentTask.node_id == node_id,
    ).all()


def finish_component(db: Session, task_id: int, status: str, error: str = "") -> None:
    db.query(ComponentTask).filter(ComponentTask.id == task_id).update({
        "status": status, "error": error or None,
    })
    db.commit()


# ── 网络操作任务（改 IP 回退 / 防火墙修改）──
def create_net_task(db: Session, node_id: int, kind: str, payload: dict | None) -> NetTask:
    t = NetTask(node_id=node_id, kind=kind, payload=payload)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def pending_net_tasks(db: Session, node_id: int) -> list[NetTask]:
    return db.query(NetTask).filter(
        NetTask.status == "pending", NetTask.node_id == node_id,
    ).all()


def finish_net_task(db: Session, task_id: int, status: str, result_json: dict | None) -> None:
    db.query(NetTask).filter(NetTask.id == task_id).update({
        "status": status, "result_json": result_json,
    })
    db.commit()
