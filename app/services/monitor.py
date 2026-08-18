"""监控项域 services：CRUD + agent 探测结果入库（无中心探测）。"""
from datetime import datetime
from sqlalchemy.orm import Session

from app.repositories import monitor as repo
from app.repositories import node as node_repo
from app.repositories import config as config_repo
from app.models.monitor import Monitor, MonitorCheck


def list_monitors(db: Session) -> list[Monitor]:
    return repo.list_all(db)


def list_monitors_for_node(db: Session, node_id: int) -> list[Monitor]:
    return repo.list_for_node(db, node_id)


def get_monitor(db: Session, monitor_id: int) -> Monitor | None:
    return repo.get_by_id(db, monitor_id)


def create_monitor(db: Session, name: str, mtype: str, target: str,
                   interval: int, timeout: int, node_id: int) -> Monitor:
    node = node_repo.get_by_id(db, node_id)
    if node is None or node.status == "removed":
        raise ValueError("探测节点不存在")
    m = repo.create(db, name, mtype, target, interval, timeout, node_id)
    config_repo.bump_monitors_version(db)  # 版本号 +1，agent 心跳 diff
    return m


def remove_monitor(db: Session, monitor_id: int) -> None:
    if repo.get_by_id(db, monitor_id) is None:
        return
    repo.remove(db, monitor_id)
    config_repo.bump_monitors_version(db)


def list_checks(db: Session, monitor_id: int, limit: int = 200) -> list[MonitorCheck]:
    return repo.list_checks(db, monitor_id, limit)


def record_check(db: Session, monitor_id: int, ts: datetime, success: bool,
                 latency_ms: float | None, loss_pct: float | None) -> None:
    """agent 上报一次探测结果：落 monitor_checks + 更新监控项 status。"""
    repo.insert_check(db, monitor_id, ts, success, latency_ms, loss_pct)
    repo.update_last_result(db, monitor_id, "up" if success else "down", ts, latency_ms)
