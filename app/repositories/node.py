"""节点域 repositories：节点 CRUD + 时序数据写入（幂等）。"""
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.node import Node, NodeMetric, NodeSysMetric, NodeStatusEvent


# ── 节点 ──
def list_all(db: Session, skip: int = 0, limit: int = 100) -> list[Node]:
    return (
        db.query(Node)
        .filter(Node.status != "removed")
        .order_by((Node.name != "Stella"), Node.id)  # 宿主机 Stella 固定第一，其余按 id（创建顺序）
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_by_id(db: Session, node_id: int) -> Node | None:
    return db.get(Node, node_id)


def get_by_token(db: Session, token: str) -> Node | None:
    return db.query(Node).filter(Node.token == token).first()


def get_by_name(db: Session, name: str) -> Node | None:
    return db.query(Node).filter(Node.name == name, Node.status != "removed").first()


def create(db: Session, name: str, platform: str, host: str) -> Node:
    node = Node(name=name, platform=platform, host=host, status="pending",
                token=secrets.token_urlsafe(32))
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def remove(db: Session, node_id: int) -> None:
    db.query(Node).filter(Node.id == node_id).update({"status": "removed"})
    db.commit()


def set_uninstall_status(db: Session, node_id: int, status: str | None, error: str | None = None) -> None:
    """更新节点卸载状态（pending/running/done/failed；None=重置回「未卸载」）。"""
    node = get_by_id(db, node_id)
    if node is None:
        return
    node.uninstall_status = status
    if status is None:
        node.uninstall_error = None
    elif error:
        node.uninstall_error = error
    elif status == "done":
        node.uninstall_error = None
    db.commit()


# ── 指标写入（幂等）──
def insert_metrics(db: Session, node_id: int, points: list) -> int:
    """批量写流量采样点。ON CONFLICT DO NOTHING 幂等——补传重复自动丢弃。

    返回实际写入条数（重复的被忽略）。
    """
    if not points:
        return 0
    stmt = pg_insert(NodeMetric).values([
        {"node_id": node_id, "iface": p.iface, "ts": p.ts,
         "rx_delta": p.rx_delta, "tx_delta": p.tx_delta}
        for p in points
    ]).on_conflict_do_nothing(
        constraint="uq_node_metric"
    )
    result = db.execute(stmt)  # type: ignore[assignment]  # CursorResult，有 rowcount
    db.commit()
    return result.rowcount


def insert_sys_metrics(db: Session, node_id: int, points: list) -> int:
    """批量写系统指标，幂等同理。"""
    if not points:
        return 0
    stmt = pg_insert(NodeSysMetric).values([
        {"node_id": node_id, "ts": p.ts,
         "cpu_pct": p.cpu_pct, "mem_pct": p.mem_pct, "disk_pct": p.disk_pct}
        for p in points
    ]).on_conflict_do_nothing(
        constraint="uq_node_sys_metric"
    )
    result = db.execute(stmt)  # type: ignore[assignment]  # CursorResult，有 rowcount
    db.commit()
    return result.rowcount


# ── 心跳 / 状态 ──
def heartbeat(db: Session, node_id: int, agent_version: str | None = None,
              interfaces: dict | None = None, storage: list | None = None,
              components: dict | None = None) -> Node:
    """上报即心跳：更新 last_seen_at，若之前是 pending/offline → online 并记状态事件。"""
    node = get_by_id(db, node_id)
    if node is None:
        raise ValueError("node not found")
    now = datetime.now(timezone.utc)
    old_status = node.status
    node.last_seen_at = now
    if not node.installed:
        node.installed = True  # 能上报心跳说明 agent 装上了
    if agent_version:
        node.agent_version = agent_version
    if interfaces is not None:
        node.interfaces = interfaces
        # 清理监控网卡里已不存在的网卡（网卡改名/消失后自动移除，避免幽灵网卡残留）
        if node.monitored_ifaces:
            valid = set(interfaces.keys())
            cleaned = {k: v for k, v in node.monitored_ifaces.items() if k in valid}
            if len(cleaned) != len(node.monitored_ifaces):
                # 清理后若为空则置 None，让前端回退到默认出口网卡（否则空 dict 会卡死流量图）
                node.monitored_ifaces = cleaned or None
    if storage is not None:
        node.storage = storage
    if components is not None:
        node.components = components
    # agent 重新上线 → 已结束的卸载状态（done/failed）复位：说明卸载没成功或已重装，别让「已删除」和「在线」打架
    if node.uninstall_status in ("done", "failed"):
        node.uninstall_status = None
        node.uninstall_error = None
    if old_status != "online":
        node.status = "online"
        db.add(NodeStatusEvent(node_id=node_id, status="online", ts=now, reason="上报"))
    db.commit()
    db.refresh(node)
    return node


def mark_offline_stale(db: Session, threshold_seconds: int = 120) -> int:
    """惰性判离线：把 last_seen_at 超过阈值还没下线的节点标 offline，记状态事件。

    返回标记了几个。由查询节点列表时顺手调用（不搞后台任务）。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=threshold_seconds)
    stale = db.query(Node).filter(
        Node.status == "online",
        Node.last_seen_at.isnot(None),
        Node.last_seen_at < cutoff,
    ).all()
    for node in stale:
        node.status = "offline"
        db.add(NodeStatusEvent(node_id=node.id, status="offline",
                               ts=datetime.now(timezone.utc), reason="心跳超时"))
    if stale:
        db.commit()
    return len(stale)


def mark_offline(db: Session, node_id: int, reason: str = "手动下线") -> Node | None:
    """显式标记节点离线（如卸载完成），记状态事件。"""
    node = get_by_id(db, node_id)
    if node is None:
        return None
    if node.status != "offline":
        node.status = "offline"
        db.add(NodeStatusEvent(node_id=node_id, status="offline",
                               ts=datetime.now(timezone.utc), reason=reason))
        db.commit()
    return node


def set_installed(db: Session, node_id: int, installed: bool) -> None:
    """设置节点是否托管（是否装过 agent）。"""
    node = get_by_id(db, node_id)
    if node is None:
        return
    node.installed = installed
    db.commit()


# ── 时序查询（详情页用）──
def get_metrics(db: Session, node_id: int, iface: str | None = None,
                start=None, end=None, limit: int = 720, step: int | None = None) -> list[NodeMetric]:
    """流量历史：倒序（最新在前），按网卡 + 时间范围过滤。默认 720 条 = 1 小时 5s 颗粒。

    step>5 时按 step 秒聚合（sum delta），用于长时间窗口降采样，避免 7 天 12 万点画图卡死。
    """
    if step and step > 5:
        ts_bucket = func.to_timestamp(
            func.floor(func.extract("epoch", NodeMetric.ts) / step) * step
        )
        q = (
            db.query(
                ts_bucket.label("ts"),
                func.sum(NodeMetric.rx_delta).label("rx_delta"),
                func.sum(NodeMetric.tx_delta).label("tx_delta"),
            )
            .filter(NodeMetric.node_id == node_id)
        )
        if iface:
            q = q.filter(NodeMetric.iface == iface)
        if start is not None:
            q = q.filter(NodeMetric.ts >= start)
        if end is not None:
            q = q.filter(NodeMetric.ts <= end)
        rows = q.group_by(ts_bucket).order_by(ts_bucket.desc()).limit(limit).all()
        return [
            NodeMetric(node_id=node_id, iface=iface or "", ts=r.ts,
                       rx_delta=int(r.rx_delta), tx_delta=int(r.tx_delta))
            for r in rows
        ]
    q = db.query(NodeMetric).filter(NodeMetric.node_id == node_id)
    if iface:
        q = q.filter(NodeMetric.iface == iface)
    if start is not None:
        q = q.filter(NodeMetric.ts >= start)
    if end is not None:
        q = q.filter(NodeMetric.ts <= end)
    return q.order_by(NodeMetric.ts.desc()).limit(limit).all()


def get_sys_metrics(db: Session, node_id: int, start=None, end=None,
                    limit: int = 720, step: int | None = None) -> list[NodeSysMetric]:
    """系统指标历史：倒序，按时间范围过滤。默认 720 条 = 12 小时 60s 颗粒。

    step>60 时按 step 秒聚合（avg 百分比），用于长时间窗口降采样。
    """
    if step and step > 60:
        ts_bucket = func.to_timestamp(
            func.floor(func.extract("epoch", NodeSysMetric.ts) / step) * step
        )
        q = (
            db.query(
                ts_bucket.label("ts"),
                func.avg(NodeSysMetric.cpu_pct).label("cpu_pct"),
                func.avg(NodeSysMetric.mem_pct).label("mem_pct"),
                func.avg(NodeSysMetric.disk_pct).label("disk_pct"),
            )
            .filter(NodeSysMetric.node_id == node_id)
        )
        if start is not None:
            q = q.filter(NodeSysMetric.ts >= start)
        if end is not None:
            q = q.filter(NodeSysMetric.ts <= end)
        rows = q.group_by(ts_bucket).order_by(ts_bucket.desc()).limit(limit).all()
        return [
            NodeSysMetric(node_id=node_id, ts=r.ts,
                          cpu_pct=r.cpu_pct, mem_pct=r.mem_pct, disk_pct=r.disk_pct)
            for r in rows
        ]
    q = db.query(NodeSysMetric).filter(NodeSysMetric.node_id == node_id)
    if start is not None:
        q = q.filter(NodeSysMetric.ts >= start)
    if end is not None:
        q = q.filter(NodeSysMetric.ts <= end)
    return q.order_by(NodeSysMetric.ts.desc()).limit(limit).all()


def get_latest_metrics(db: Session, node_id: int, ifaces: list[str]) -> list[NodeMetric]:
    """每个监控网卡最新一条流量点（详情页实时速率用）。"""
    out: list[NodeMetric] = []
    for iface in ifaces:
        m = (db.query(NodeMetric)
             .filter(NodeMetric.node_id == node_id, NodeMetric.iface == iface)
             .order_by(NodeMetric.ts.desc())
             .first())
        if m is not None:
            out.append(m)
    return out


def get_latest_sys_metric(db: Session, node_id: int) -> NodeSysMetric | None:
    """最新一条系统指标。"""
    return (db.query(NodeSysMetric)
            .filter(NodeSysMetric.node_id == node_id)
            .order_by(NodeSysMetric.ts.desc())
            .first())


def get_traffic_stats(db: Session, node_id: int, ifaces: list[str] | None = None,
                      start=None, end=None) -> dict:
    """流量统计（多网卡聚合）：先按 ts 把各网卡 delta 相加，再对聚合序列算 95 分位 / MAX / MIN / 总流量 / 采样数。

    ifaces 为空则聚合该节点全部网卡。这样多网卡时 MAX/MIN/95 值作用于「同一时刻各网卡之和」，
    语义正确（而不是把各网卡峰值再相加）。95 值对速率序列排序取 95% 位置，delta 与速率线性同序。
    """
    inner = db.query(
        NodeMetric.ts.label("ts"),
        func.sum(NodeMetric.rx_delta).label("rx"),
        func.sum(NodeMetric.tx_delta).label("tx"),
    ).filter(NodeMetric.node_id == node_id)
    if ifaces:
        inner = inner.filter(NodeMetric.iface.in_(ifaces))
    if start is not None:
        inner = inner.filter(NodeMetric.ts >= start)
    if end is not None:
        inner = inner.filter(NodeMetric.ts <= end)
    sub = inner.group_by(NodeMetric.ts).subquery()

    row = db.query(
        func.percentile_cont(0.95).within_group(sub.c.rx).label("rx_95"),
        func.percentile_cont(0.95).within_group(sub.c.tx).label("tx_95"),
        func.max(sub.c.rx).label("rx_max"),
        func.min(sub.c.rx).label("rx_min"),
        func.max(sub.c.tx).label("tx_max"),
        func.min(sub.c.tx).label("tx_min"),
        func.coalesce(func.sum(sub.c.rx), 0).label("rx_total"),
        func.coalesce(func.sum(sub.c.tx), 0).label("tx_total"),
        func.count().label("cnt"),
    ).one()
    return {
        "rx_95": float(row.rx_95) if row.rx_95 is not None else 0.0,
        "tx_95": float(row.tx_95) if row.tx_95 is not None else 0.0,
        "rx_max": float(row.rx_max) if row.rx_max is not None else 0.0,
        "rx_min": float(row.rx_min) if row.rx_min is not None else 0.0,
        "tx_max": float(row.tx_max) if row.tx_max is not None else 0.0,
        "tx_min": float(row.tx_min) if row.tx_min is not None else 0.0,
        "rx_total": int(row.rx_total),
        "tx_total": int(row.tx_total),
        "sample_count": int(row.cnt),
    }
