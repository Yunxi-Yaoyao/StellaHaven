"""监控项域 services：CRUD + agent 探测结果入库（无中心探测）。"""
from datetime import datetime
from sqlalchemy.orm import Session

from app.repositories import monitor as repo
from app.repositories import node as node_repo
from app.repositories import config as config_repo
from app.models.monitor import Monitor, MonitorCheck
from app.schemas.monitor import MonitorRead, MonitorCreate, MonitorUpdate
from app.monitor_targets import parse_target, parse_stored_target
from app.services.server_status import monitor_status
from app.services.node import query_window, run_history_query


def list_monitors(db: Session) -> list[MonitorRead]:
    from app.services.node_monitor_policy import dispatched
    from app.services.entry_monitoring import superseded_ids, removed_ids
    historical = superseded_ids(db) | removed_ids(db)
    monitors = [m for m in repo.list_all(db) if m.id not in historical]
    from app.services.entry_monitoring import current_ids, managed_ids
    automatic = managed_ids(db)
    active_ids = {m.id for m in dispatched(db, monitors)} | current_ids(db)
    return [present_monitor(db, m, active_ids=active_ids, automatic=automatic) for m in monitors]


def present_monitor(db, monitor, *, active_ids=None, automatic=None):
    from app.services.entry_monitoring import entry_reason, managed_ids, current_ids
    from app.services.node_monitor_policy import dispatched
    if automatic is None:
        automatic = managed_ids(db)
    if active_ids is None:
        active_ids = {m.id for m in dispatched(db, [monitor])} | current_ids(db)
    reason = entry_reason(db, monitor)
    if reason in ('healthy', 'failure') and monitor.id not in active_ids:
        reason = 'restricted'
    values = {field: getattr(monitor, field) for field in MonitorRead.model_fields if hasattr(monitor, field)}
    from app.services.monitor_management import effective_enabled
    return MonitorRead.model_validate(values | {
        # Business availability, not a synthetic target result. Keep the cause
        # separate and never write this projection back to status/check history.
        'status': 'up' if reason == 'healthy' else 'down',
        'last_latency_ms': monitor.last_latency_ms if reason == 'healthy' else None,
        'effective_enabled': effective_enabled(db, monitor),
        'status_reason': reason, 'management': 'entry_icmp' if monitor.id in automatic else None})


def list_monitors_for_node(db: Session, node_id: int) -> list[Monitor]:
    from app.services.node_monitor_policy import dispatched
    result = []
    for m in dispatched(db, repo.list_for_node(db, node_id)):
        try:
            parse_stored_target(m.type, m.target)
        except ValueError:
            continue  # old invalid definitions remain editable, never executable
        result.append(m)
    return result


def get_monitor(db: Session, monitor_id: int) -> Monitor | None:
    return repo.get_by_id(db, monitor_id)


def _normalize_target(target: str) -> str:
    """目标输入容错：全角冒号→半角、去空白。用户从聊天/文档复制常带全角「：」。"""
    return target.replace("：", ":").replace(" ", "").strip()


def mtr_spec(mtype: str, target: str) -> tuple[str, str, int | None]:
    """监控项 → MTR 规格 (host, proto, port)。单一事实源：配置下发和手动触发都用它。

    ping → icmp；tcp/udp → 同协议同端口；http/https → 对主机+端口做 TCP MTR
    （HTTP 是应用层协议没有 MTR，TCP MTR 到 80/443 等价于到 web 服务的路径诊断）。
    """
    parsed = parse_stored_target(mtype, target)
    return parsed.host, "icmp" if mtype == "ping" else mtype if mtype == "udp" else "tcp", parsed.port


def create_monitor(db: Session, name: str, mtype: str, target: str,
                   interval: int, timeout: int, node_id: int) -> Monitor:
    data = MonitorCreate(name=name, type=mtype, target=target, interval=interval, timeout=timeout, node_id=node_id)
    node = node_repo.get_by_id(db, node_id)
    if node is None or node.status == "removed":
        raise ValueError("探测节点不存在")
    m = repo.create(db, name, mtype, data.target, interval, timeout, node_id)
    config_repo.bump_monitors_version(db)  # 版本号 +1，agent 心跳 diff
    return m


def update_monitor(db: Session, monitor_id: int, fields: dict) -> Monitor:
    """编辑监控项。fields 已剔 None；换探测节点要校验存在。版本号 +1 让 agent 拉新配置。"""
    from app.services.entry_monitor_groups import lock
    from app.services.entry_monitoring import managed_ids
    lock(db)
    monitor = db.query(Monitor).filter_by(id=monitor_id).with_for_update().populate_existing().first()
    if monitor is None:
        raise ValueError("监控项不存在")
    from app.services.entry_monitoring import superseded_ids
    if monitor_id in superseded_ids(db):
        raise ValueError('归档入口监控历史只读')
    if monitor_id in managed_ids(db):
        if any(k not in ('name', 'visible', 'enabled') and getattr(monitor, k) != v for k, v in fields.items()):
            raise ValueError('自动入口监控项的目标、协议、节点和采样周期由入口配置决定；可改名称，其他目标请新建普通监控项')
    if "node_id" in fields:
        node = node_repo.get_by_id(db, fields["node_id"])
        if node is None or node.status == "removed":
            raise ValueError("探测节点不存在")
    fields = MonitorUpdate.model_validate(fields).model_dump(exclude_none=True)
    if "target" in fields or "type" in fields:
        fields["target"] = parse_target(fields.get("type", monitor.type), fields.get("target", monitor.target)).value
    if any(k in fields and fields[k] != getattr(monitor, k) for k in ("target", "type", "node_id")):
        fields.update(status="unknown", last_check_at=None, last_latency_ms=None)
    try:
        for key, value in fields.items():
            setattr(monitor, key, value)
        config_repo.bump_monitors_version(db)  # one commit: definition + version
        return monitor
    except Exception:
        db.rollback()
        raise


def remove_monitor(db: Session, monitor_id: int) -> None:
    from app.services.entry_monitor_groups import lock
    lock(db)
    from app.services.entry_monitoring import managed_ids
    if monitor_id in managed_ids(db):
        raise ValueError('自动入口系统监控项不可手动删除；请管理节点或站点入口设置')
    if repo.get_by_id(db, monitor_id) is None:
        return
    repo.remove(db, monitor_id)
    config_repo.bump_monitors_version(db)


def list_checks(db: Session, monitor_id: int, limit: int = 200) -> list[MonitorCheck]:
    return repo.list_checks(db, monitor_id, limit)


def list_checks_range(db: Session, monitor_id: int, start: datetime | None = None,
                      end: datetime | None = None, step: int | None = None,
                      limit: int = 5000) -> list[dict]:
    """延迟曲线数据：范围查询，可选 step 秒分桶降采样。

    返回 dict 列表：{ts, success, latency_ms, loss_pct}。分桶时 latency 取桶内
    成功样本均值，success=桶内全部成功才算 True（有一个失败就算桶失败，偏保守）。
    """
    start, end = query_window(start, end, limit, step)
    if step:
        return run_history_query(db, repo.list_checks_bucketed, monitor_id, start, end, step, limit)
    rows = run_history_query(db, repo.list_checks_range, monitor_id, start, end, limit)
    return [{"ts": r.ts, "success": r.success, "latency_ms": r.latency_ms,
             "loss_pct": r.loss_pct, "sample_count": 1,
             "success_count": int(r.success),
             "latency_count": int(r.success and r.latency_ms is not None),
             "loss_count": int(r.loss_pct is not None)} for r in rows]


def record_check(db: Session, monitor_id: int, ts: datetime, success: bool,
                 latency_ms: float | None, loss_pct: float | None) -> None:
    """agent 上报一次探测结果：落 monitor_checks + 更新监控项 status；顺带惰性评估告警。"""
    try:
        repo.insert_check(db, monitor_id, ts, success, latency_ms, loss_pct, commit=False)
        repo.update_last_result(db, monitor_id, "up" if success else "down", ts, latency_ms, commit=False)
        from app.services import alerts
        alerts.evaluate_monitor(db, monitor_id)
        db.commit()  # check, current status, event and notification are atomic
    except Exception:
        db.rollback()
        raise
