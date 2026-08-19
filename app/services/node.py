"""节点域 services：节点纳管 + agent 上报处理。"""
import platform
from sqlalchemy.orm import Session

from app.repositories import node as repo
from app.models.node import Node
from app.schemas.monitor import AgentReport, MetricPoint, SysMetricPoint, NodeDetail, NodeUpdate
from app.services import host as host_svc


def list_nodes(db: Session, skip: int = 0, limit: int = 100) -> list[Node]:
    # 顺手惰性标记超时离线（不搞后台任务）
    repo.mark_offline_stale(db)
    return repo.list_all(db, skip, limit)


def get_node(db: Session, node_id: int) -> Node | None:
    return repo.get_by_id(db, node_id)


def create_node(db: Session, name: str, platform: str, host: str) -> Node:
    return repo.create(db, name, platform, host)


def remove_node(db: Session, node_id: int) -> None:
    node = repo.get_by_id(db, node_id)
    if node is not None and (node.name == "Stella" or node.host in ("127.0.0.1", "localhost")):
        # 宿主机：移除时同时卸载本地 agent，让预设回到「未安装」状态
        host_svc.uninstall_host()
    repo.remove(db, node_id)


def handle_report(db: Session, token: str, report: AgentReport) -> Node:
    """agent 上报：鉴权 → 心跳 → 写流量/系统指标（幂等）。"""
    node = repo.get_by_token(db, token)
    if node is None or node.status == "removed":
        raise ValueError("invalid token")
    # 心跳 + 状态转换（pending/offline → online）；带网卡清单则更新（首次上报时）
    repo.heartbeat(db, node.id, agent_version=report.agent_version, interfaces=report.interfaces, storage=report.storage, components=report.components, os_info=report.os_info)
    # 公网 IP 探测结果（agent 首次上报时带一次）：写 public_ip + 地区
    if report.public_ip_info:
        apply_public_ip_info(db, node.id, report.public_ip_info)
    # 写时序数据（幂等，补传重复自动丢弃）
    if report.metrics:
        repo.insert_metrics(db, node.id, report.metrics)
    if report.sys_metrics:
        repo.insert_sys_metrics(db, node.id, report.sys_metrics)
    result = repo.get_by_id(db, node.id)
    if result is None:
        raise ValueError("node not found")
    return result


def get_agent_config(db: Session, token: str) -> Node:
    node = repo.get_by_token(db, token)
    if node is None or node.status == "removed":
        raise ValueError("invalid token")
    return node


def get_host_node(db: Session) -> Node | None:
    """查宿主机「Stella」节点（不创建）。"""
    return repo.get_by_name(db, "Stella")


def ensure_host_node(db: Session) -> Node:
    """找到或创建宿主机「Stella」节点。platform 存系统类别（linux/windows），发行版名走 os_name。"""
    node = repo.get_by_name(db, "Stella")
    if node is None:
        node = repo.create(db, "Stella", platform.system().lower(), "127.0.0.1")
    return node


def install_host_node(db: Session) -> Node:
    """本机一键安装：确保节点存在 + 本地 exec 装 agent + 返回节点。"""
    node = ensure_host_node(db)
    if node.token is None:
        raise ValueError("节点 token 缺失")
    host_svc.install_host(node.token)
    # 安装/重装成功后清掉残留的卸载状态（否则 UI 一直显示「agent 已删除」）
    repo.set_uninstall_status(db, node.id, None)
    repo.set_installed(db, node.id, True)  # 装上了 → 托管
    result = repo.get_by_id(db, node.id)
    if result is None:
        raise ValueError("节点不存在")
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
def _monitored_ifaces(node: Node) -> list[str]:
    """监控网卡列表：优先 monitored_ifaces 设置，否则默认出口网卡，再否则第一个网卡。"""
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
    detail = NodeDetail.model_validate(node)
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
    return [
        MetricPoint(iface=r.iface, ts=r.ts, rx_delta=r.rx_delta, tx_delta=r.tx_delta)
        for r in repo.get_metrics(db, node_id, iface, start, end, limit, step)
    ]


def get_node_sys_metrics(db: Session, node_id: int, start=None, end=None,
                         limit: int = 720, step: int | None = None) -> list[SysMetricPoint]:
    """系统指标历史（倒序）。step>60 时降采样聚合。"""
    return [
        SysMetricPoint(ts=r.ts, cpu_pct=r.cpu_pct, mem_pct=r.mem_pct, disk_pct=r.disk_pct)
        for r in repo.get_sys_metrics(db, node_id, start, end, limit, step)
    ]


def get_traffic_stats(db: Session, node_id: int, ifaces: list[str] | None = None,
                      start=None, end=None) -> dict:
    """流量统计（多网卡聚合）。"""
    return repo.get_traffic_stats(db, node_id, ifaces, start, end)


def update_monitored_ifaces(db: Session, node_id: int, ifaces: dict | None) -> Node:
    """更新监控网卡设置。"""
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
    if node is None:
        return
    node.public_ip = public_ip
    node.public_ip_source = "auto"
    node.ip_version = info.get("ip_version") or _guess_ip_version(public_ip)
    node.region = info.get("region")
    db.commit()
