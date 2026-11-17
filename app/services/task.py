"""任务域 services：打流 / MTR / 命令 的发起 + agent 轮询领取 + 结果回传。"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.repositories import task as repo
from app.repositories import node as node_repo
from app.models.task import IperfTask, MtrTask, AgentCommand, ComponentTask, NetTask
from app.services.server_status import node_status


# ── 打流看门狗（惰性清扫：列表/详情被读时顺手扫，不开后台任务）──
def _iperf_timeout_sec(t: IperfTask) -> int:
    """running 任务的合理最长耗时。speedtest 全程 ~90s 阻塞；数据量模式速率未知给宽限。"""
    if t.mode == "speedtest":
        return 150
    if t.bytes:
        return 3660  # bounded one-hour data test + report grace, not an 180s server timer
    return t.duration + (t.omit or 0) + 60


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
    # Atomic admission is enforced inside repo.create_iperf's transaction.
    # 节点约束：两端都必须在线；iperf3 互打时服务端必须是公网节点（client 要能连到 5201），且两端不同机
    client = node_repo.get_by_id(db, client_node_id)
    if node_status(client) != "online":
        raise ValueError("客户端节点不在线")
    if mode == "iperf3":
        if server_node_id is None:
            raise ValueError("iperf3 互打需要选择服务端节点")
        if server_node_id == client_node_id:
            raise ValueError("服务端和客户端不能是同一台")
        server = node_repo.get_by_id(db, server_node_id)
        if server is None or node_status(server) != "online":
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
    # Serialize with agent result authorization; a stale running read must not
    # overwrite a result which committed while cancellation was waiting.
    t = db.query(IperfTask).filter(IperfTask.id == task_id).with_for_update().first()
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
    return create_mtr_job(db, [node_id], target, protocol, params)[0]


def _require_mtr_node(db: Session, node_id: int) -> None:
    node = node_repo.get_by_id(db, node_id)
    if node is None or node_status(node) != 'online':
        raise ValueError(f'节点 {node_id} 不在线')
    capability = (node.components or {}).get('mtr')
    installed = capability if isinstance(capability, bool) else (
        capability.get('installed') if isinstance(capability, dict) else None)
    if installed is False:
        raise ValueError(f'节点 {node_id} 未安装 MTR，请先下发组件安装')


def create_mtr_job(db: Session, node_ids: list[int], target: str, protocol: str,
                   params: dict | None = None) -> list[MtrTask]:
    if not target.strip() or len(target) > 256 or protocol not in ('icmp', 'tcp', 'udp'):
        raise ValueError('目标或协议不正确')
    if not 1 <= len(node_ids) <= 8 or len(set(node_ids)) != len(node_ids):
        raise ValueError('请选择 1–8 个不同节点')
    for nid in node_ids:
        _require_mtr_node(db, nid)
    return repo.create_mtr_job(db, node_ids, target, protocol, _valid_mtr_params(params))


def update_mtr_live(db: Session, task_id: int, live: dict) -> None:
    repo.update_mtr_live(db, task_id, live)


def create_mtr_for_monitor(db: Session, monitor) -> MtrTask:
    """监控项浮窗的「立即 MTR」：按类型映射协议（http→tcp:80/443），target 存 host[:port]。"""
    from app.services.monitor import mtr_spec
    _require_mtr_node(db, monitor.node_id)
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


def list_mtr(db: Session, trigger: str | None = None) -> list[MtrTask]:
    return repo.list_mtr(db, trigger=trigger)


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


def authorize_agent_task(db: Session, token: str, kind: str, task_id: int,
                         *, status: str | None = None, role: str | None = None,
                         write: bool = True):
    """Authenticate before lookup; lock through write to protect terminal states.

    iperf server reports are auxiliary only; missing role means client (legacy).
    Heartbeat staleness does not invalidate credentials: late replies still authenticate.
    """
    from fastapi import HTTPException
    node = node_repo.get_by_token(db, token)
    if node is None or node.status == "removed":
        raise HTTPException(401, "无效的 agent token")
    model = {"iperf": IperfTask, "mtr": MtrTask, "command": AgentCommand,
             "component": ComponentTask, "net": NetTask}[kind]
    task = db.query(model).filter(model.id == task_id).with_for_update().first() if write else db.get(model, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    if kind == "iperf":
        owners = {task.client_node_id}
        if task.mode == "iperf3":
            owners.add(task.server_node_id)
        if node.id not in owners:
            raise HTTPException(403, "任务不属于此节点")
        if write:
            if role not in ("client", "server"):
                raise HTTPException(422, "无效的 iperf role")
            expected = task.client_node_id if role == "client" else task.server_node_id
            if node.id != expected or (role == "server" and task.mode != "iperf3"):
                raise HTTPException(403, "节点与任务角色不匹配")
    elif task.node_id != node.id:
        raise HTTPException(403, "任务不属于此节点")
    if status is not None and status not in ("done", "failed"):
        raise HTTPException(422, "结果状态只能是 done / failed")
    if write:
        # Server may report startup failure before client has claimed the task.
        server_pending = kind == "iperf" and role == "server" and task.status == "pending" and task.server_started
        if task.status != "running" and not server_pending:
            raise HTTPException(409, "任务未运行或已经结束")
    return task


# ── 结果回传 ──
def _validate_iperf_result(mode: str, payload: dict, selected_server=None) -> dict:
    """Validate new writes, not the permissive historical read projection.

    Accept only complete measured shapes: Stella summary/native iperf, Go,
    Ookla bandwidth objects, or legacy speedtest-cli bit/s scalars. Never infer
    success from a vendor key alone. Return a copy; callers keep failed evidence.
    """
    import math

    def number(value, label, *, positive=False, maximum=None):
        try:
            valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                     and math.isfinite(value) and (value > 0 if positive else value >= 0)
                     and (maximum is None or value <= maximum))
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError(f'无效测速结果字段 {label}')

    def optional(obj, fields):
        for key in fields:
            if obj.get(key) is not None:
                number(obj[key], key, maximum=100 if key in ('lost_pct', 'lost_percent') else None)

    def optional_duration(obj):
        duration = obj.get('test_duration')
        if isinstance(duration, dict):
            # Pinned Go struct: four non-omitempty *time.Duration
            # fields, numeric nanoseconds or null. Never flatten it.
            if set(duration) != {'ping', 'download', 'upload', 'total'}:
                raise ValueError('无效测速结果字段 test_duration')
            for key, value in duration.items():
                if value is not None:
                    number(value, 'test_duration.' + key)
        elif duration is not None:
            # Preserve the pre-existing optional/scalar contract.
            number(duration, 'test_duration')

    def clean(obj):
        if not isinstance(obj, dict) or 'error' in obj:
            raise ValueError('测速结果包含错误或缺少有效对象')

    clean(payload)
    r = dict(payload)
    if mode == 'iperf3':
        if any(key in r for key in ('servers', 'download', 'upload')):
            raise ValueError('iperf3 任务不能接收 speedtest 结果')
        optional(r, ('avg_bitrate', 'peak_bitrate', 'send_avg_bitrate', 'total_bytes',
                     'jitter_ms', 'lost_pct', 'duration', 'retransmits'))
        end = r.get('end')
        if end is not None:
            clean(end)
        summaries = [obj[key] for obj in (r, end or {})
                     for key in ('sum_received', 'sum', 'sum_sent') if key in obj]
        for summary in summaries:
            clean(summary)
            for key in ('bits_per_second', 'bytes', 'seconds'):
                number(summary.get(key), key, positive=key == 'seconds')
            optional(summary, ('jitter_ms', 'lost_percent', 'lost_packets', 'packets', 'retransmits'))
        if 'avg_bitrate' in r:
            for key in ('avg_bitrate', 'total_bytes', 'duration'):
                number(r.get(key), key, positive=key == 'duration')
        elif not summaries:
            raise ValueError('iperf3 缺少完整接收/发送汇总')
        return r
    if mode != 'speedtest':
        raise ValueError('未知测速任务模式')
    if any(key in r for key in ('avg_bitrate', 'peak_bitrate', 'total_bytes', 'end', 'sum_sent')):
        raise ValueError('speedtest 任务不能接收 iperf3 结果')
    optional_duration(r)
    if 'servers' in r:
        servers = r['servers']
        if not isinstance(servers, list) or not servers:
            raise ValueError('speedtest-go 缺少服务器测速结果')
        for server in servers:
            clean(server)
            for key in ('dl_speed', 'ul_speed'):
                number(server.get(key), key)
            optional(server, ('latency', 'jitter'))
            optional_duration(server)
            if selected_server is not None and str(server.get('id')) != str(selected_server):
                raise ValueError('测速服务器与任务指定 ID 不一致')
    elif not all(key in r for key in ('download', 'upload')):
        raise ValueError('speedtest 缺少完整下载/上传结果')
    # Validate *every present known slot*, including mixed vendor payloads.
    scalar = all(isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool)
                 for k in ('download', 'upload'))
    for key in ('download', 'upload'):
        if key in r:
            if scalar:
                number(r[key], key)
            else:
                clean(r[key])
                number(r[key].get('bandwidth'), key + '.bandwidth')
                optional(r[key], ('bytes', 'elapsed'))
    if r.get('ping') is not None:
        if scalar:
            number(r['ping'], 'ping')
        else:
            clean(r['ping'])
            optional(r['ping'], ('latency', 'jitter', 'low', 'high'))
    if selected_server is not None and 'servers' not in r:
        server = r.get('server')
        if not isinstance(server, dict) or str(server.get('id')) != str(selected_server):
            raise ValueError('测速服务器与任务指定 ID 不一致')
    if scalar:
        # Old CLI scalars are bit/s; repository/UI bandwidth objects are byte/s.
        # Preserve original fields explicitly rather than changing their units silently.
        r['legacy_speedtest_cli'] = {k: r[k] for k in ('download', 'upload', 'ping') if k in r}
        for key in ('download', 'upload'):
            r[key] = {'bandwidth': r[key] / 8}
        if r.get('ping') is not None:
            r['ping'] = {'latency': r['ping']}
    return r


def finish_iperf(db: Session, task_id: int, status: str, result_json: dict) -> None:
    t = db.get(IperfTask, task_id)  # router already holds the row lock
    if t is None or t.status not in ('pending', 'running'):
        return
    if result_json.get('role') == 'server':
        if status == 'failed' and result_json.get('error'):
            t.status, t.result_json = 'failed', result_json
            db.commit()
        return
    reported_done = status == 'done'
    if reported_done:
        try:
            result_json = _validate_iperf_result(t.mode, result_json, getattr(t, 'speedtest_server', None))
        except ValueError as exc:
            status = 'failed'
            result_json = dict(result_json, error=result_json.get('error') or str(exc))
    if reported_done and t.mode == 'iperf3' and t.direction == 'forward':
        import math
        rates = [p.get('bitrate') for p in (t.progress_json or [])
                 if isinstance(p, dict) and p.get('role') == 'server' and not p.get('note') and not p.get('retry')]
        rates = [r for r in rates if isinstance(r, (int, float)) and not isinstance(r, bool) and math.isfinite(r) and r >= 0]
        result_json = dict(result_json, peak_bitrate=max(rates) if rates else None)
    repo.finish_iperf(db, task_id, status, result_json)


def finish_mtr(db: Session, task_id: int, status: str, result_json: dict) -> None:
    """Commit the real result and one all-terminal manual-job intent atomically.

    The router authenticates/locks the reporting node first. A job advisory lock
    serializes sibling finishes; do not lock sibling rows here (the router may
    already hold one, so that would reverse lock order and deadlock fan-out).
    """
    from sqlalchemy import text
    from app.services.result_notifications import stage_result, deliver_pending
    if status not in ('done', 'failed'):
        raise ValueError('结果状态只能是 done / failed')
    row = db.query(MtrTask).filter_by(id=task_id).with_for_update().populate_existing().first()
    if row is None or row.status != 'running':
        return  # unclaimed/unknown/replayed tasks are not new real terminals
    operation = 'mtr:' + (row.job_id or str(row.id))
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),
               {'key': 'mtr-finish:' + operation})
    row.status, row.result_json = status, result_json
    db.flush()  # production Session has autoflush=False
    if row.trigger == 'manual':
        members = (db.query(MtrTask).filter_by(job_id=row.job_id).populate_existing().limit(9).all()
                   if row.job_id else [row])
        if 1 <= len(members) <= 8 and all(m.trigger == 'manual' and m.status in ('done', 'failed') for m in members):
            failed = sum(m.status == 'failed' for m in members)
            stage_result(db.connection(), source='manual_test', operation_id=operation,
                         outcome='failure' if failed else 'success',
                         title='手动 MTR 执行失败' if failed else '手动 MTR 执行完成',
                         body=f'{len(members)} 个节点已全部结束：{len(members)-failed} 个完成，{failed} 个执行失败。执行完成不代表链路健康；请查看测试结果。',
                         node_ids=sorted(m.node_id for m in members))
    engine = db.get_bind().engine
    db.commit()
    deliver_pending(engine)


def finish_command(db: Session, cmd_id: int, status: str,
                   stdout: str, stderr: str, exit_code: int) -> None:
    repo.finish_command(db, cmd_id, status, stdout, stderr, exit_code)


def append_iperf_progress(db: Session, task_id: int, point: dict) -> None:
    import math
    for key, limit in (('bitrate', 1e15), ('lost_pct', 100), ('jitter_ms', 1e9)):
        value = point.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value) or not 0 <= value <= limit):
            raise ValueError(f'无效的 {key}')
    for key, limit in (('ts', 64), ('note', 256), ('reason', 256)):
        value = point.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise ValueError(f'无效的 {key}')
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
    if node_status(node) != "online":
        raise ValueError("节点不在线")
    return repo.create_net_task(db, node_id, "firewall_scan", None)


def create_docker_scan(db: Session, node_id: int) -> NetTask:
    """下发 Docker 容器列表采集（只读）。"""
    node = node_repo.get_by_id(db, node_id)
    if node_status(node) != "online":
        raise ValueError("节点不在线")
    return repo.create_net_task(db, node_id, "docker_scan", None)


def create_pbr_scan(db: Session, node_id: int) -> NetTask:
    """下发 PBR 结构化采集（ip rule / 各路由表 / mangle 打标链，只读）。"""
    node = node_repo.get_by_id(db, node_id)
    if node_status(node) != "online":
        raise ValueError("节点不在线")
    return repo.create_net_task(db, node_id, "pbr_scan", None)


def create_docker_logs(db: Session, node_id: int, container: str, tail: int = 150) -> NetTask:
    """下发容器日志读取（docker logs --tail，只读）。"""
    node = node_repo.get_by_id(db, node_id)
    if node_status(node) != "online":
        raise ValueError("节点不在线")
    tail = max(1, min(int(tail), 500))  # 上限 500 行防大包
    return repo.create_net_task(db, node_id, "docker_logs", {"container": container, "tail": tail})


def create_docker_inspect(db: Session, node_id: int, container: str) -> NetTask:
    """下发容器配置查看（docker inspect 摘要化，只读）。"""
    node = node_repo.get_by_id(db, node_id)
    if node_status(node) != "online":
        raise ValueError("节点不在线")
    return repo.create_net_task(db, node_id, "docker_inspect", {"container": container})


def latest_net_task(db: Session, node_id: int, kind: str) -> NetTask | None:
    return repo.latest_net_task(db, node_id, kind)


def create_docker_ctl(db: Session, node_id: int, action: str, container: str) -> NetTask:
    """容器启停重启（agent 侧再校验 action 白名单 + 容器名合法性）。"""
    if action not in ("start", "stop", "restart"):
        raise ValueError("不支持的操作")
    node = node_repo.get_by_id(db, node_id)
    if node_status(node) != "online":
        raise ValueError("节点不在线")
    return repo.create_net_task(db, node_id, "docker_ctl", {"action": action, "container": container})


def get_net_task(db: Session, task_id: int) -> NetTask | None:
    return db.get(NetTask, task_id)


def finish_net_task(db: Session, task_id: int, status: str, result_json: dict | None) -> None:
    repo.finish_net_task(db, task_id, status, result_json)
