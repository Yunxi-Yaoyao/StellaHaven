"""节点域 services：节点纳管 + agent 上报处理。"""
import platform
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.repositories import node as repo
from app.models.node import Node
from app.schemas.monitor import NodeRead
from app.services.server_status import node_status
from app.schemas.monitor import AgentReport, MetricPoint, SysMetricPoint, NodeDetail, NodeUpdate
from app.services import host as host_svc


def list_nodes(db: Session, skip: int = 0, limit: int = 100) -> list[NodeRead]:
    return [NodeRead.model_validate(n).model_copy(update={"status": node_status(n)})
            for n in repo.list_all(db, skip, limit)]


def get_node(db: Session, node_id: int) -> Node | None:
    return repo.get_by_id(db, node_id)


def create_node(db: Session, name: str, platform: str, host: str) -> Node:
    from app.services.node_monitor_policy import reconcile
    try:
        node = repo.create(db, name, platform, host, commit=False)
        from app.services.alerts import create_node_interruption_rule
        create_node_interruption_rule(db, node)
        from app.services.entry_monitor_groups import reconcile as reconcile_parent
        reconcile_parent(db, node)
        reconcile(db)
        return node
    except Exception:
        db.rollback()
        raise


def remove_node(db: Session, node_id: int) -> None:
    # Removing an inventory record is not authorization to stop a local service.
    # A display name/loopback/NAT address cannot establish process ownership.
    from app.services.entry_monitor_groups import reconcile
    try:
        # Match host admission and role rebinding: policy before Node locks.
        from app.services.node_monitor_policy import _load
        _load(db, locked=True)
        node = db.query(Node).filter_by(id=node_id).with_for_update().populate_existing().first()
        if node is None:
            return
        node.status = 'removed'
        db.flush()
        reconcile(db, node)
        db.commit()
    except Exception:
        db.rollback()
        raise


def handle_report(db: Session, token: str, report: AgentReport) -> Node:
    """agent 上报：鉴权 → 心跳 → 写流量/系统指标（幂等）。"""
    node = repo.get_by_token(db, token)
    if node is None or node.status == "removed":
        raise ValueError("invalid token")
    # 心跳 + 状态转换（pending/offline → online）；带网卡清单则更新（首次上报时）
    # Node → Rule → State: catch a missed deadline before receipt advancement.
    # The existing heartbeat commit durably commits this transition as well.
    try:
        node = db.query(Node).filter_by(id=node.id).with_for_update().populate_existing().one()
        if node.status == "removed":
            raise ValueError("invalid token")
        from app.services import alerts
        alerts.evaluate_node_rules(db, node_id=node.id)
    except Exception:
        db.rollback()
        raise
    repo.heartbeat(db, node.id, agent_version=report.agent_version, interfaces=report.interfaces, storage=report.storage, components=report.components, os_info=report.os_info)
    # 公网 IP 探测结果（agent 首次上报时带一次）：写 public_ip + 地区
    if report.public_ip_info:
        apply_public_ip_info(db, node.id, report.public_ip_info)
    # 地图独立周期上报：省略字段不覆盖缓存，显式 null 才清除快照。
    if "map_snapshot" in report.model_fields_set:
        from app.services.server_map import save_snapshot
        save_snapshot(db, node.id, report.map_snapshot)
    # Heartbeat/inventory above retain their independent durability. From here,
    # samples, alert states/events and in-app notifications form ONE transaction:
    # failure must leave samples retryable, not consume them before evaluation.
    try:
        # Heartbeat committed and released the first Node lock. Reacquire before
        # metric rules too, matching editor/worker Node → Rule → State ordering.
        node = db.query(Node).filter_by(id=node.id).with_for_update().populate_existing().one()
        if report.control_channel is not None:
            from app.services.entry_monitoring import save_channel
            try:
                save_channel(db, node, report.control_channel)
            except ValueError:
                from fastapi import HTTPException
                raise HTTPException(422, "管理入口监控样本与当前配置不匹配") from None
        else:
            from app.services.entry_monitor_groups import reconcile as reconcile_parent
            reconcile_parent(db, node)
        inserted = 0
        if report.metrics:
            inserted += repo.insert_metrics(db, node.id, report.metrics, commit=False)
        if report.sys_metrics:
            inserted += repo.insert_sys_metrics(db, node.id, report.sys_metrics, commit=False)
        if inserted:
            from app.services.alert_metrics import evaluate_node
            evaluate_node(db, node.id)
        from app.services import alerts
        alerts.evaluate_node_rules(db, node_id=node.id, heartbeat_node_id=node.id)
        if "map_snapshot" in report.model_fields_set:
            alerts.evaluate_wg_rules(db)
        db.commit()  # dispatch hooks run only after this successful outer commit
    except Exception:
        db.rollback()
        raise
    result = repo.get_by_id(db, node.id)
    if result is None:
        raise ValueError("node not found")
    from app.services.node_monitor_policy import reconcile
    reconcile(db)  # online capability arrival activates deferred node monitors
    return result


def get_agent_config(db: Session, token: str) -> Node:
    node = repo.get_by_token(db, token)
    if node is None or node.status == "removed":
        raise ValueError("invalid token")
    # Configuration reads never create system members or advance versions.
    return node


def get_host_node(db: Session) -> Node | None:
    """Explicit role binding, never a display name or request/NAT source IP."""
    from app.services.node_monitor_policy import host_node
    return host_node(db)


def ensure_host_node(db: Session) -> Node:
    """Only called by the explicit local installation action, not discovery."""
    from app.services.node_monitor_policy import ensure_local_host
    return ensure_local_host(db, platform.system().lower())


def installation_url(db: Session) -> str:
    """Only applied settings or an explicitly deployed, trusted main origin.

    Never derive a capability-bearing command from Host/Forwarded or the legacy
    public_host key. A malformed saved setting must not fall back to deployment.
    """
    import os
    from fastapi import HTTPException
    from app.models.config import AppConfig
    from app.services import access_entries
    from app.services.entry_registry import records
    from app.services.request_security import canonical_origin, trusted_origins
    if db.get(AppConfig, access_entries.KEY) is not None:
        url = access_entries.read(db)['public_origin']
    elif os.environ.get('STELLA_ENTRY_REGISTRY') or os.environ.get('STELLA_MAIN_ORIGIN'):
        url = records()['stella']['public']
    else:
        raise HTTPException(409, '请先在设置中应用本站安装地址；不会使用浏览器地址或旧默认端口')
    if not url or canonical_origin(url) != url or url not in trusted_origins():
        raise HTTPException(409, '已应用安装地址不在本站可信来源中，请检查内外网设置与部署许可')
    return url


HOST_INSTALL_KEY = 'host_install.v1'


def host_installation(db: Session) -> dict:
    import json
    from app.models.config import AppConfig
    row = db.get(AppConfig, HOST_INSTALL_KEY, populate_existing=True)
    value = json.loads(row.value) if row else {'status': 'not_started', 'message': '尚未安装本站宿主实例'}
    # A killed web worker cannot leave an eternal "installing" success illusion.
    if value['status'] in ('queued', 'installing') and datetime.now(timezone.utc).timestamp() - value.get('updated_at', 0) > 240:
        return {**value, 'status': 'interrupted', 'message': '安装任务已中断或超时，不能确认完成；请检查本站实例后重试'}
    return value


def _lock_host_install(db):
    # Both admission and completion hold this transaction-scoped lock. No helper
    # below may commit between the ownership check and its receipt/node writes.
    # Role writers already use the policy lock; acquire it before the receipt.
    from app.services.node_monitor_policy import _load
    _load(db, locked=True)
    from app.models.config import AppConfig
    if db.get_bind().dialect.name == 'postgresql':
        from sqlalchemy import text
        db.execute(text('SELECT pg_advisory_xact_lock(1937006960)'))
    db.query(AppConfig).filter_by(key=HOST_INSTALL_KEY).with_for_update().populate_existing().first()


def _write_host_install_state(db, status, message, node_id, attempt_id):
    import json
    from app.models.config import AppConfig
    row = db.get(AppConfig, HOST_INSTALL_KEY)
    if row is None:
        row = AppConfig(key=HOST_INSTALL_KEY, value=''); db.add(row)
    row.value = json.dumps({'status': status, 'message': message, 'node_id': node_id,
                           'attempt_id': attempt_id,
                           'updated_at': datetime.now(timezone.utc).timestamp()}, ensure_ascii=False)
    db.flush()


def _host_install_state(db, status, message, node_id=None):
    """Create a fresh receipt (preparation only, never async completion)."""
    from uuid import uuid4
    _lock_host_install(db)
    attempt_id = str(uuid4())
    _write_host_install_state(db, status, message, node_id, attempt_id)
    db.commit()
    return attempt_id


def initialize_host_install(db: Session, background_tasks) -> None:
    """After atomic owner/session commit; bind a real host role, never discover it."""
    from fastapi import HTTPException
    try:
        node = ensure_host_node(db)
        node_id = node.id
        _lock_host_install(db)
        if host_installation(db)['status'] in ('queued', 'installing'):
            db.rollback()
            return
        status, message = 'queued', '本站宿主安装任务已排队，尚未完成安装或认证在线'
        if not host_svc.supports_local_install():
            status, message = 'manual_required', 'Stella 运行在容器内；请在真实宿主机执行本站安装命令'
        else:
            try:
                installation_url(db)
            except HTTPException as exc:
                status, message = 'address_required', str(exc.detail)
        attempt_id = _host_install_state(db, status, message, node_id)
        if status == 'queued':
            background_tasks.add_task(_run_initial_host_install, db.get_bind(), node_id, attempt_id)
    except Exception:
        # Preparation must not roll back the already durable account/session,
        # nor turn another worker's admitted task into a retryable failure.
        db.rollback()
        try:
            _lock_host_install(db)
            if host_installation(db)['status'] not in ('queued', 'installing'):
                _host_install_state(db, 'failed', '宿主安装准备失败；账户已创建，请在服务器页重试或使用宿主接入命令')
            else:
                db.rollback()
        except Exception:
            db.rollback()


def _run_initial_host_install(engine, node_id, attempt_id=None):
    # Missing identity (including old worker callbacks) is never admission.
    if not attempt_id:
        return
    with Session(bind=engine) as db:
        try:
            install_host_node(db, initial=True, attempt_id=attempt_id, expected_node_id=node_id)
        except Exception:
            # The service alone owns terminal writes after admission. Rejection
            # and stale catch/finally paths cannot overwrite someone else's work.
            db.rollback()


def _finish_host_install(db, node_id, attempt_id, status, message):
    _lock_host_install(db)
    state = host_installation(db)
    node = get_host_node(db)
    if (state['status'] != 'installing' or state.get('attempt_id') != attempt_id or
            state.get('node_id') != node_id or node is None or node.id != node_id):
        db.rollback()
        return False
    if status == 'installed':
        # Do not call repository setters: their commits release the ownership
        # lock before the terminal receipt. These fields and receipt are atomic.
        node.installed = True
        node.uninstall_status = None
        node.uninstall_error = None
    _write_host_install_state(db, status, message, node_id, attempt_id)
    db.commit()
    return True


def install_host_node(db: Session, *, initial: bool = False, attempt_id=None, expected_node_id=None) -> Node | None:
    """Consume one unexpired queued attempt, or admit an explicit owner retry."""
    from fastapi import HTTPException
    from uuid import uuid4
    if initial and not attempt_id:
        return None
    if not initial:
        # Role creation may commit; it must precede the admission transaction.
        url = installation_url(db)
        node = ensure_host_node(db)
        expected_node_id = node.id
    _lock_host_install(db)
    state = host_installation(db)
    if initial:
        if (state['status'] != 'queued' or state.get('attempt_id') != attempt_id or
                state.get('node_id') != expected_node_id):
            db.rollback()
            return None
    elif state['status'] in ('queued', 'installing'):
        db.rollback()
        raise HTTPException(409, '本站宿主安装任务已在进行中，请等待状态更新')
    else:
        attempt_id = str(uuid4())
    # Preparation committed and released the policy lock. Its returned ORM
    # object is not current authorization, even in this Session's identity map.
    node = get_host_node(db)
    if node is not None:
        db.refresh(node)
    if node is None or node.status == 'removed' or node.id != expected_node_id:
        db.rollback()
        if initial:
            return None
        raise HTTPException(409, '本站宿主角色已变化，请读取最新状态后重试')
    node_id, token = node.id, node.token
    try:
        if initial:
            url = installation_url(db)
        if not token:
            raise ValueError('节点 token 缺失')
    except Exception as exc:
        message = str(exc.detail) if isinstance(exc, HTTPException) else '本站宿主安装准备失败，请检查安装地址与节点凭证'
        _write_host_install_state(db, 'failed', message, node_id, attempt_id)
        db.commit()
        raise
    _write_host_install_state(db, 'installing', '本站实例安装器运行中，尚未确认安装完成', node_id, attempt_id)
    db.commit()  # No transaction while the installer self-calls center identity.
    try:
        host_svc.install_host(token, url)
    except Exception as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, ValueError) else '本站宿主安装失败，请检查权限、依赖与安装地址后重试'
        _finish_host_install(db, node_id, attempt_id, 'failed', message)
        raise ValueError(message) from None
    if not _finish_host_install(db, node_id, attempt_id, 'installed', '本站实例服务安装完成，等待 Agent 认证上报在线'):
        if initial:
            return None
        raise HTTPException(409, '本站宿主安装任务已失去所有权，请读取最新状态')
    result = repo.get_by_id(db, node_id)
    if result is None:
        raise ValueError('节点不存在')
    return result


def request_uninstall(db: Session, node_id: int) -> Node:
    """发起卸载：置 pending，等 agent 轮询领取。"""
    node = repo.get_by_id(db, node_id)
    if node is None or node.status == "removed":
        raise ValueError("节点不存在")
    if node.uninstall_status in ("pending", "running"):
        raise ValueError("卸载已在进行中")
    repo.set_uninstall_status(db, node_id, "pending")
    result = repo.get_by_id(db, node_id)
    if result is None:
        raise ValueError("节点不存在")
    return result


def finish_uninstall(db: Session, token: str, status: str, error: str) -> None:
    """agent 回传卸载结果：done / failed。"""
    node = repo.get_by_token(db, token)
    if node is None:
        return
    repo.set_uninstall_status(db, node.id, status, error or None)
    if status == "done":
        # agent 已删除自己，不会再上报心跳 → 立即标 offline，不等 120s 惰性超时
        repo.mark_offline(db, node.id, reason="卸载完成")
        repo.set_installed(db, node.id, False)  # 卸载成功 → 回到未托管


# ── 详情页 ──
MAX_QUERY_POINTS = 5000
MAX_QUERY_WINDOW = timedelta(days=31)
MAX_QUERY_IFACES = 16


def query_window(start=None, end=None, limit: int = 720, step: int | None = None):
    """HTTP-safe service budget, including internal callers bypassing Query()."""
    from fastapi import HTTPException
    def reject(message):
        raise HTTPException(422, detail={"code": "monitor_query_budget", "message": message})
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_QUERY_POINTS:
        reject(f"limit must be between 1 and {MAX_QUERY_POINTS}")
    if step is not None and (not isinstance(step, int) or isinstance(step, bool) or not 1 <= step <= 86400):
        reject("step must be between 1 and 86400 seconds")
    if end is None:
        end = start + timedelta(hours=1) if start is not None else datetime.now(timezone.utc)
    if start is None:
        start = end - timedelta(hours=1)
    if start.tzinfo is None or end.tzinfo is None:
        reject("start/end must include a timezone")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if end <= start or end - start > MAX_QUERY_WINDOW:
        reject("window must be positive and at most 31 days")
    return start, end


def run_history_query(db, query, *args):
    """A hard per-statement budget; output LIMIT alone does not bound aggregation."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    from fastapi import HTTPException
    try:
        if db is not None:
            db.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        return query(db, *args)
    except OperationalError as exc:
        if getattr(exc.orig, "pgcode", None) != "57014":
            raise
        db.rollback()
        raise HTTPException(503, detail={"code": "monitor_query_timeout",
                            "message": "Query exceeded 5 seconds; select a shorter window"}) from None


def _monitored_ifaces(node: Node) -> list[str]:
    """详情页显示网卡：优先显示偏好，否则默认出口/首张网卡；不限制历史采集。"""
    if node.monitored_ifaces:
        ifaces = list(node.monitored_ifaces.keys())
        if ifaces:
            return ifaces
    if node.interfaces:
        for name, meta in node.interfaces.items():
            if isinstance(meta, dict) and meta.get("is_default"):
                return [name]
        first = list(node.interfaces.keys())
        if first:
            return [first[0]]
    return []


def get_node_detail(db: Session, node_id: int) -> NodeDetail:
    """详情页：节点基础信息 + 实时快照（各监控网卡最新流量 + 最新系统指标）。"""
    node = repo.get_by_id(db, node_id)
    if node is None or node.status == "removed":
        raise ValueError("节点不存在")
    if node_status(node) != 'online':
        from fastapi import HTTPException
        raise HTTPException(409, detail={'code': 'node_not_online', 'message': '节点尚未正常在线，不能进入详情'})
    detail = NodeDetail.model_validate(node)
    detail.status = node_status(node)
    ifaces = _monitored_ifaces(node)
    detail.latest_metrics = [
        MetricPoint(iface=m.iface, ts=m.ts, rx_delta=m.rx_delta, tx_delta=m.tx_delta)
        for m in repo.get_latest_metrics(db, node_id, ifaces)
    ]
    s = repo.get_latest_sys_metric(db, node_id)
    if s is not None:
        detail.latest_sys_metric = SysMetricPoint(ts=s.ts, cpu_pct=s.cpu_pct,
                                                  mem_pct=s.mem_pct, disk_pct=s.disk_pct)
    return detail


def get_node_metrics(db: Session, node_id: int, iface: str | None = None,
                     start=None, end=None, limit: int = 720, step: int | None = None) -> list[MetricPoint]:
    """流量历史（倒序）。step>5 时降采样聚合。"""
    start, end = query_window(start, end, limit, step)
    return [
        MetricPoint(iface=r.iface, ts=r.ts, rx_delta=r.rx_delta, tx_delta=r.tx_delta)
        for r in run_history_query(db, repo.get_metrics, node_id, iface, start, end, limit, step)
    ]


def get_node_sys_metrics(db: Session, node_id: int, start=None, end=None,
                         limit: int = 720, step: int | None = None) -> list[SysMetricPoint]:
    """系统指标历史（倒序）。step>60 时降采样聚合。"""
    start, end = query_window(start, end, limit, step)
    return [
        SysMetricPoint(ts=r.ts, cpu_pct=r.cpu_pct, mem_pct=r.mem_pct, disk_pct=r.disk_pct)
        for r in run_history_query(db, repo.get_sys_metrics, node_id, start, end, limit, step)
    ]


def get_traffic_stats(db: Session, node_id: int, ifaces: list[str] | None = None,
                      start=None, end=None) -> dict:
    """流量统计（多网卡聚合）。"""
    start, end = query_window(start, end)
    if ifaces is not None and len(ifaces) > MAX_QUERY_IFACES:
        from fastapi import HTTPException
        raise HTTPException(422, detail={"code": "monitor_query_budget", "message": "at most 16 interfaces"})
    return run_history_query(db, repo.get_traffic_stats, node_id, ifaces, start, end)


def update_monitored_ifaces(db: Session, node_id: int, ifaces: dict | None) -> Node:
    """更新图表默认显示网卡；agent始终上报所有网卡。"""
    node = repo.get_by_id(db, node_id)
    if node is None or node.status == "removed":
        raise ValueError("节点不存在")
    node.monitored_ifaces = ifaces
    db.commit()
    db.refresh(node)
    return node


# ── 标记：内网/公网 + 公网 IP 地区查询 ──
import urllib.request
import json as _json


def _http_json(url: str, timeout: float = 5.0) -> dict | None:
    """带 UA 的 HTTP GET。ip-api 等对默认 python UA 反爬，偶发拒绝（Remote end closed），带浏览器 UA 才稳定。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Stella)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read())
    except Exception:
        return None


def _guess_ip_version(ip: str) -> str:
    return "IPv6" if ":" in ip else "IPv4"


def lookup_ip_region(ip: str) -> dict:
    """查 IP 地区（中文）。双服务 fallback：ip-api.com（中文）→ ipinfo.io（英文）。"""
    # 主：ip-api.com，lang=zh-CN 直接返回中文（country/city 有中文，regionName 常是英文）
    d = _http_json(f"http://ip-api.com/json/{ip}?lang=zh-CN&fields=status,country,regionName,city,query")
    if d and d.get("status") == "success":
        return {"ip": d.get("query"), "ip_version": _guess_ip_version(ip),
                "region": d.get("city") or d.get("country") or ""}
    # 备：ipinfo.io（返回英文 region/country）
    d = _http_json(f"https://ipinfo.io/{ip}/json")
    if d and d.get("ip"):
        return {"ip": d["ip"], "ip_version": _guess_ip_version(ip),
                "region": d.get("city") or d.get("country") or ""}
    return {}


def update_net_type(db: Session, node_id: int, net_type: str, public_ip: str | None = None) -> Node:
    """更新内网/公网标记。公网 + 手动 IP 时查地区。内网则清空公网信息。"""
    node = repo.get_by_id(db, node_id)
    if node is None or node.status == "removed":
        raise ValueError("节点不存在")
    node.net_type = net_type
    if net_type == "public":
        if public_ip:
            info = lookup_ip_region(public_ip)
            node.public_ip = public_ip
            node.public_ip_source = "manual"
            node.ip_version = info.get("ip_version") or _guess_ip_version(public_ip)
            node.region = info.get("region") or None
        # public_ip 为空：保留 agent 自动探测的值（若有），否则等 agent 上报
    else:
        node.public_ip = None
        node.public_ip_source = None
        node.ip_version = None
        node.region = None
    db.commit()
    db.refresh(node)
    return node


def apply_public_ip_info(db: Session, node_id: int, info: dict | None) -> None:
    """agent 上报的公网 IP 探测结果写入节点（自动来源）。"""
    if not info:
        return
    public_ip = info.get("public_ip")
    if not public_ip:
        return
    node = repo.get_by_id(db, node_id)
    if node is None or node.public_ip_source == "manual":
        return
    node.public_ip = public_ip
    node.public_ip_source = "auto"
    node.ip_version = info.get("ip_version") or _guess_ip_version(public_ip)
    node.region = info.get("region")
    db.commit()
