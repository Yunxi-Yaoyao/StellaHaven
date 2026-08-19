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


def _normalize_target(target: str) -> str:
    """目标输入容错：全角冒号→半角、去空白。用户从聊天/文档复制常带全角「：」。"""
    return target.replace("：", ":").replace(" ", "").strip()


def mtr_spec(mtype: str, target: str) -> tuple[str, str, int | None]:
    """监控项 → MTR 规格 (host, proto, port)。单一事实源：配置下发和手动触发都用它。

    ping → icmp；tcp/udp → 同协议同端口；http/https → 对主机+端口做 TCP MTR
    （HTTP 是应用层协议没有 MTR，TCP MTR 到 80/443 等价于到 web 服务的路径诊断）。
    """
    t = _normalize_target(target)
    if mtype == "ping":
        return t, "icmp", None
    if mtype in ("http", "https"):
        # 剥 scheme 和路径，只留 host[:port]
        if "://" in t:
            t = t.split("://", 1)[1]
        t = t.split("/", 1)[0]
        host, _, port = t.rpartition(":")
        if host and port.isdigit():
            return host, "tcp", int(port)
        return t, "tcp", 443 if mtype == "https" else 80
    # tcp / udp
    host, _, port = t.rpartition(":")
    if host and port.isdigit():
        return host, mtype, int(port)
    return t, mtype, None


def create_monitor(db: Session, name: str, mtype: str, target: str,
                   interval: int, timeout: int, node_id: int) -> Monitor:
    node = node_repo.get_by_id(db, node_id)
    if node is None or node.status == "removed":
        raise ValueError("探测节点不存在")
    m = repo.create(db, name, mtype, _normalize_target(target), interval, timeout, node_id)
    config_repo.bump_monitors_version(db)  # 版本号 +1，agent 心跳 diff
    return m


def update_monitor(db: Session, monitor_id: int, fields: dict) -> Monitor:
    """编辑监控项。fields 已剔 None；换探测节点要校验存在。版本号 +1 让 agent 拉新配置。"""
    if repo.get_by_id(db, monitor_id) is None:
        raise ValueError("监控项不存在")
    if "node_id" in fields:
        node = node_repo.get_by_id(db, fields["node_id"])
        if node is None or node.status == "removed":
            raise ValueError("探测节点不存在")
    if "target" in fields:
        fields["target"] = _normalize_target(fields["target"])
    m = repo.update(db, monitor_id, fields)
    assert m is not None  # 上面已校验存在
    config_repo.bump_monitors_version(db)
    return m


def remove_monitor(db: Session, monitor_id: int) -> None:
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
    rows = repo.list_checks_range(db, monitor_id, start, end, limit)
    if not step:
        return [{"ts": r.ts, "success": r.success, "latency_ms": r.latency_ms, "loss_pct": r.loss_pct} for r in rows]
    buckets: dict[int, list] = {}
    for r in rows:
        k = int(r.ts.timestamp()) // step
        buckets.setdefault(k, []).append(r)
    out = []
    for k in sorted(buckets):
        rs = buckets[k]
        # 桶成功 = 过半探测成功（全对才算好的规则太狠：一小时 60 次探测丢 1 次就整小时标红，
        # 和按探测次数算的可用率对不上）
        ok = sum(1 for r in rs if r.success) * 2 >= len(rs)
        lats = [r.latency_ms for r in rs if r.success and r.latency_ms is not None]
        losses = [r.loss_pct for r in rs if r.loss_pct is not None]
        out.append({
            "ts": datetime.fromtimestamp(k * step, tz=rows[0].ts.tzinfo),
            "success": ok,
            "latency_ms": round(sum(lats) / len(lats), 2) if lats else None,
            "loss_pct": round(sum(losses) / len(losses), 2) if losses else None,
        })
    return out


def record_check(db: Session, monitor_id: int, ts: datetime, success: bool,
                 latency_ms: float | None, loss_pct: float | None) -> None:
    """agent 上报一次探测结果：落 monitor_checks + 更新监控项 status。"""
    repo.insert_check(db, monitor_id, ts, success, latency_ms, loss_pct)
    repo.update_last_result(db, monitor_id, "up" if success else "down", ts, latency_ms)
