"""监控模块路由：节点管理 + 监控项（前端，需登录）+ agent 上报/拉配置/探测上报（token 鉴权）。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.auth import current_user
from app.schemas.monitor import (
    NodeCreate, NodeRead, NodeDetail, NodeUpdate, NetTypeUpdate, IpChangeCreate, NetTaskRead, DockerCtlCreate, MetricPoint, SysMetricPoint,
    AgentReport, AgentConfig, MonitorForAgent,
    MonitorCreate, MonitorUpdate, MonitorRead, MonitorCheckRead, MonitorCheckReport, MonitorCheckPoint,
    MtrReport, MtrTaskRead,
)
from app.services import node as node_svc
from app.services import monitor as monitor_svc
from app.services import host as host_svc
from app.services import task as task_svc
from app.repositories import config as config_repo

# 节点管理走登录鉴权
node_router = APIRouter(dependencies=[Depends(current_user)], prefix="/nodes", tags=["nodes"])


@node_router.get("/", response_model=list[NodeRead])
def list_nodes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return node_svc.list_nodes(db)


@node_router.post("/", response_model=NodeRead, status_code=201)
def create_node(data: NodeCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return node_svc.create_node(db, data.name, data.platform, data.host)


@node_router.get("/host")
def get_host(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """本机：OS 用节点存的 platform（探一次存），agent 运行状态动态查。"""
    node = node_svc.get_host_node(db)
    installed = host_svc.is_agent_installed()
    return {
        # OS 显示名：优先 agent 采集的发行版友好名，退化为 platform/本机探测
        "os": (node.os_name if node and node.os_name else (node.platform if node else host_svc.detect_os())),
        "installed": installed,
        "node_id": node.id if node else None,
        "node_status": node.status if node else None,
    }


@node_router.post("/host/install", response_model=NodeRead, status_code=201)
def install_host(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """本机一键安装 agent。"""
    return node_svc.install_host_node(db)


@node_router.post("/{node_id}/uninstall", response_model=NodeRead)
def uninstall_node(node_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """发起卸载：下发卸载指令给 agent（pending → agent 领取 → 执行 → 回传）。"""
    try:
        return node_svc.request_uninstall(db, node_id)
    except ValueError as e:
        raise HTTPException(409, str(e))


@node_router.delete("/{node_id}", status_code=204)
def delete_node(node_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    node_svc.remove_node(db, node_id)


@node_router.get("/{node_id}/metrics", response_model=list[MetricPoint])
def read_node_metrics(node_id: int, iface: str | None = None,
                      start: datetime | None = None, end: datetime | None = None,
                      limit: int = 720, step: int | None = None,
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    """流量历史（倒序）。iface 指定网卡；start/end 时间范围；step>5 时降采样聚合。"""
    return node_svc.get_node_metrics(db, node_id, iface, start, end, limit, step)


@node_router.get("/{node_id}/traffic-stats")
def read_traffic_stats(node_id: int, iface: list[str] | None = Query(None),
                       start: datetime | None = None, end: datetime | None = None,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    """流量统计：95 分位 + MAX/MIN（速率峰值/谷值）+ 总流量，多网卡聚合，in/out 分开。"""
    return node_svc.get_traffic_stats(db, node_id, iface, start, end)


@node_router.get("/{node_id}/sys-metrics", response_model=list[SysMetricPoint])
def read_node_sys_metrics(node_id: int, start: datetime | None = None, end: datetime | None = None,
                          limit: int = 720, step: int | None = None,
                          user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """系统指标历史（倒序）。step>60 时降采样聚合。"""
    return node_svc.get_node_sys_metrics(db, node_id, start, end, limit, step)


@node_router.patch("/{node_id}", response_model=NodeRead)
def update_node(node_id: int, data: NodeUpdate,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    """更新节点（监控网卡设置等）。"""
    try:
        return node_svc.update_monitored_ifaces(db, node_id, data.monitored_ifaces)
    except ValueError:
        raise HTTPException(404, "节点不存在")


@node_router.patch("/{node_id}/net-type", response_model=NodeRead)
def update_net_type(node_id: int, data: NetTypeUpdate,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    """更新内网/公网标记（公网 + 手动 IP 时后端查地区）。"""
    try:
        return node_svc.update_net_type(db, node_id, data.net_type, data.public_ip)
    except ValueError:
        raise HTTPException(404, "节点不存在")


@node_router.post("/{node_id}/ip-change", status_code=201)
def change_ip(node_id: int, data: IpChangeCreate,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    """下发改 IP 任务（高危：agent 本地执行临时改 → ping 测试 → 通写持久化 / 不通回退）。"""
    node = node_svc.get_node(db, node_id)
    if node is None or node.status == "removed":
        raise HTTPException(404, "节点不存在")
    return task_svc.create_ip_change(db, node_id, data.iface, data.new_ip,
                                     data.prefix, data.gateway, data.ping_target)


@node_router.post("/{node_id}/firewall-scan", response_model=NetTaskRead, status_code=201)
def firewall_scan(node_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """下发防火墙结构化采集任务（ufw numbered + iptables-save 五表，只读不改规则）。"""
    try:
        return task_svc.create_firewall_scan(db, node_id)
    except ValueError as e:
        raise HTTPException(409, str(e))


@node_router.get("/net-tasks/{task_id}", response_model=NetTaskRead)
def read_net_task(task_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """查网络操作任务结果（防火墙扫描/改 IP 进度轮询用）。"""
    t = task_svc.get_net_task(db, task_id)
    if t is None:
        raise HTTPException(404, "任务不存在")
    return t


@node_router.post("/{node_id}/docker-scan", response_model=NetTaskRead, status_code=201)
def docker_scan(node_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """下发 Docker 容器列表采集（只读）。"""
    try:
        return task_svc.create_docker_scan(db, node_id)
    except ValueError as e:
        raise HTTPException(409, str(e))


@node_router.post("/{node_id}/docker-ctl", response_model=NetTaskRead, status_code=201)
def docker_ctl(node_id: int, data: DockerCtlCreate,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    """容器启停重启。"""
    try:
        return task_svc.create_docker_ctl(db, node_id, data.action, data.container)
    except ValueError as e:
        raise HTTPException(409, str(e))


@node_router.get("/{node_id}", response_model=NodeDetail)
def read_node(node_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """单节点详情：基础信息 + 实时快照（各监控网卡最新流量 + 最新系统指标）。"""
    try:
        return node_svc.get_node_detail(db, node_id)
    except ValueError:
        raise HTTPException(404, "节点不存在")


# agent 上报/拉配置：token 鉴权（agent 不是登录用户，凭安装命令里的 token）
agent_router = APIRouter(prefix="/agent", tags=["agent"])


@agent_router.post("/report")
def agent_report(token: str, report: AgentReport, db: Session = Depends(get_db)):
    """agent 上报流量/系统指标。token 在 query 里。幂等：重复补传自动丢弃。"""
    try:
        node = node_svc.handle_report(db, token, report)
    except ValueError:
        raise HTTPException(401, "无效的 agent token")
    return {
        "ok": True,
        "node_id": node.id,
        "status": node.status,
        "monitors_version": config_repo.get_monitors_version(db),
    }


@agent_router.get("/config", response_model=AgentConfig)
def agent_config(token: str, db: Session = Depends(get_db)):
    """agent 拉配置：监控网卡 + 负责的监控项 + 配置版本号。"""
    try:
        node = node_svc.get_agent_config(db, token)
    except ValueError:
        raise HTTPException(401, "无效的 agent token")
    monitors = monitor_svc.list_monitors_for_node(db, node.id)
    return AgentConfig(
        node_id=node.id,
        monitored_ifaces=node.monitored_ifaces,
        monitors_version=config_repo.get_monitors_version(db),
        monitors=[_monitor_for_agent(m) for m in monitors],
    )


def _monitor_for_agent(m) -> MonitorForAgent:
    """ORM → 下发模型，附带预计算的 MTR 规格（agent 不做协议映射，只执行）。"""
    host, proto, port = monitor_svc.mtr_spec(m.type, m.target)
    return MonitorForAgent(id=m.id, type=m.type, target=m.target, interval=m.interval,
                           timeout=m.timeout, mtr_host=host, mtr_proto=proto, mtr_port=port)


@agent_router.post("/mtr-report")
def agent_mtr_report(token: str, report: MtrReport, db: Session = Depends(get_db)):
    """agent 主动上报监控项 MTR 结果（定时/失败触发）。手动触发的走 mtr-tasks result 通道。"""
    from app.services import task as task_svc
    try:
        task_svc.report_mtr(db, token, report.monitor_id, report.trigger,
                            report.ok, report.result_json, report.error)
    except ValueError as e:
        raise HTTPException(401 if "token" in str(e) else 404, str(e))
    return {"ok": True}


@agent_router.post("/monitor-check")
def agent_monitor_check(token: str, report: MonitorCheckReport, db: Session = Depends(get_db)):
    """agent 上报一次探测结果：落 monitor_checks + 更新监控项 status。"""
    try:
        node = node_svc.get_agent_config(db, token)
    except ValueError:
        raise HTTPException(401, "无效的 agent token")
    mon = monitor_svc.get_monitor(db, report.monitor_id)
    if mon is None or mon.node_id != node.id:
        raise HTTPException(404, "监控项不存在或不属于该节点")
    monitor_svc.record_check(db, report.monitor_id, report.ts, report.success,
                             report.latency_ms, report.loss_pct)
    return {"ok": True}


@agent_router.get("/script")
def agent_script():
    """下发 agent 主程序源码（安装脚本用）。无鉴权——脚本本身不含密钥。"""
    from fastapi.responses import PlainTextResponse
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "agent" / "stella_agent.py"
    return PlainTextResponse(script.read_text(encoding="utf-8"))


@agent_router.get("/version")
def agent_version():
    """返回中心当前 agent 最新版本号（agent 自更新时对比用）。无鉴权。"""
    import re
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "agent" / "stella_agent.py"
    text = script.read_text(encoding="utf-8")
    m = re.search(r'AGENT_VERSION\s*=\s*"([^"]+)"', text)
    return {"version": m.group(1) if m else "0.0.0"}


@agent_router.get("/install.sh")
def agent_install_sh():
    """下发 Linux 安装脚本。无鉴权——脚本本身不含密钥。"""
    from fastapi.responses import PlainTextResponse
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "agent" / "install.sh"
    return PlainTextResponse(script.read_text(encoding="utf-8"),
                             media_type="text/plain; charset=utf-8")


@agent_router.get("/install.ps1")
def agent_install_ps1():
    """下发 Windows 安装脚本（PowerShell）。无鉴权——脚本本身不含密钥。"""
    from fastapi.responses import PlainTextResponse
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "agent" / "install.ps1"
    return PlainTextResponse(script.read_text(encoding="utf-8"),
                             media_type="text/plain; charset=utf-8")


# 监控项：登录鉴权
monitor_router = APIRouter(dependencies=[Depends(current_user)], prefix="/monitors", tags=["monitors"])


@monitor_router.get("/", response_model=list[MonitorRead])
def list_monitors(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return monitor_svc.list_monitors(db)


@monitor_router.post("/", response_model=MonitorRead, status_code=201)
def create_monitor(data: MonitorCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return monitor_svc.create_monitor(db, data.name, data.type, data.target,
                                          data.interval, data.timeout, data.node_id)
    except ValueError:
        raise HTTPException(404, "探测节点不存在")


@monitor_router.patch("/{monitor_id}", response_model=MonitorRead)
def update_monitor(monitor_id: int, data: MonitorUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return monitor_svc.update_monitor(db, monitor_id, data.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(404, str(e))


@monitor_router.delete("/{monitor_id}", status_code=204)
def delete_monitor(monitor_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    monitor_svc.remove_monitor(db, monitor_id)


@monitor_router.get("/{monitor_id}/mtr", response_model=list[MtrTaskRead])
def monitor_mtr_history(monitor_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """监控项的 MTR 历史（近 60 天，惰性清扫超期数据）。"""
    from app.services import task as task_svc
    if monitor_svc.get_monitor(db, monitor_id) is None:
        raise HTTPException(404, "监控项不存在")
    return task_svc.list_mtr_for_monitor(db, monitor_id)


@monitor_router.post("/{monitor_id}/mtr", response_model=MtrTaskRead, status_code=201)
def monitor_mtr_run(monitor_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """浮窗「立即 MTR」：按监控类型自动映射协议（http→tcp:80/443），走 mtr_tasks 轮询管道。"""
    from app.services import task as task_svc
    m = monitor_svc.get_monitor(db, monitor_id)
    if m is None:
        raise HTTPException(404, "监控项不存在")
    return task_svc.create_mtr_for_monitor(db, m)


@monitor_router.get("/{monitor_id}/checks", response_model=list[MonitorCheckRead])
def monitor_checks(monitor_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return monitor_svc.list_checks(db, monitor_id)


@monitor_router.get("/{monitor_id}/series", response_model=list[MonitorCheckPoint])
def monitor_series(monitor_id: int, start: datetime | None = None, end: datetime | None = None,
                   step: int | None = None, limit: int = 5000,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    """延迟曲线数据：start/end 时间范围 + step 秒分桶降采样。"""
    return monitor_svc.list_checks_range(db, monitor_id, start, end, step, limit)
