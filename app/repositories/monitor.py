"""监控项域 repositories：监控项 CRUD + 探测结果写入（幂等）+ 历史查询。"""
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.monitor import Monitor, MonitorCheck


# ── 监控项 CRUD ──
def list_all(db: Session, skip: int = 0, limit: int = 200) -> list[Monitor]:
    return db.query(Monitor).offset(skip).limit(limit).all()


def list_for_node(db: Session, node_id: int) -> list[Monitor]:
    """某节点负责的监控项（agent 拉配置用）。"""
    return db.query(Monitor).filter(Monitor.node_id == node_id).all()


def get_by_id(db: Session, monitor_id: int) -> Monitor | None:
    return db.get(Monitor, monitor_id)


def create(db: Session, name: str, mtype: str, target: str,
           interval: int, timeout: int, node_id: int | None) -> Monitor:
    m = Monitor(name=name, type=mtype, target=target, interval=interval,
                timeout=timeout, node_id=node_id, status="unknown")
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def remove(db: Session, monitor_id: int) -> None:
    # 先清探测历史，再删监控项——否则 monitor_checks 外键约束会拦下硬删
    db.query(MonitorCheck).filter(MonitorCheck.monitor_id == monitor_id).delete()
    db.query(Monitor).filter(Monitor.id == monitor_id).delete()
    db.commit()


def update(db: Session, monitor_id: int, fields: dict) -> Monitor | None:
    """编辑监控项。探测历史挂在 monitor_id 上，改配置不动历史。"""
    m = db.get(Monitor, monitor_id)
    if m is None:
        return None
    for k, v in fields.items():
        setattr(m, k, v)
    db.commit()
    db.refresh(m)
    return m


# ── 探测结果 ──
def insert_check(db: Session, monitor_id: int, ts: datetime, success: bool,
                 latency_ms: float | None, loss_pct: float | None) -> int:
    """写一次探测结果。幂等（同 monitor 同 ts 去重）。"""
    stmt = pg_insert(MonitorCheck).values(
        monitor_id=monitor_id, ts=ts, success=success,
        latency_ms=latency_ms, loss_pct=loss_pct,
    ).on_conflict_do_nothing(constraint="uq_monitor_check")
    result = db.execute(stmt)  # type: ignore[assignment]  # CursorResult，有 rowcount
    db.commit()
    return result.rowcount


def update_last_result(db: Session, monitor_id: int, status: str,
                       ts: datetime, latency_ms: float | None) -> None:
    db.query(Monitor).filter(Monitor.id == monitor_id).update({
        "status": status, "last_check_at": ts, "last_latency_ms": latency_ms,
    })
    db.commit()


def list_checks(db: Session, monitor_id: int, limit: int = 200) -> list[MonitorCheck]:
    """探测结果历史，最近的在前面（可用率计算用）。"""
    return db.query(MonitorCheck).filter(MonitorCheck.monitor_id == monitor_id)\
        .order_by(MonitorCheck.ts.desc()).limit(limit).all()


def list_checks_range(db: Session, monitor_id: int, start: datetime | None = None,
                      end: datetime | None = None, limit: int = 5000) -> list[MonitorCheck]:
    """时间范围内的探测结果，升序（画延迟曲线用）。limit 是安全上限。"""
    q = db.query(MonitorCheck).filter(MonitorCheck.monitor_id == monitor_id)
    if start is not None:
        q = q.filter(MonitorCheck.ts >= start)
    if end is not None:
        q = q.filter(MonitorCheck.ts <= end)
    return q.order_by(MonitorCheck.ts.asc()).limit(limit).all()


# ── 调度：找该探测的监控项 ──
def due_monitors(db: Session, now: datetime) -> list[Monitor]:
    """到了探测时间的监控项：last_check_at 为空，或 last_check_at + interval ≤ now。

    惰性判断：谁请求就顺手扫一遍。监控项数量少（几十个封顶），全查出来
    Python 侧过滤最简单且不容易出错（不跟 SQL 的 interval 算术较劲）。
    """
    from datetime import timedelta
    result = []
    for m in db.query(Monitor).all():
        if m.last_check_at is None:
            result.append(m)
        elif m.last_check_at + timedelta(seconds=m.interval) <= now:
            result.append(m)
    return result
