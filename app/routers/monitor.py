"""监控模块路由：节点管理 + 监控项（前端，需登录）+ agent 上报/拉配置/探测上报（token 鉴权）。"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from datetime import datetime
from sqlalchemy.orm import Session
from typing import Annotated
from app.security import agent_token

from app.database import get_db
from app.models.user import User
from app.routers.auth import current_user, admin_user
from app.services import server_map, entry_monitoring
from app.schemas.control_channel import EntryDefinition
from app.schemas.channel import ChannelRead, ChannelWrite, ChannelProbe, ChannelReportAck
from app.services import agent_channels
from app.services.server_map import MapLocationUpdate
from app.schemas.monitor import (
    NodeCreate, NodeRead, NodeDetail, NodeUpdate, NetTypeUpdate, IpChangeCreate, NetTaskRead, DockerCtlCreate, DockerContainerAction, MetricPoint, SysMetricPoint,
    AgentReport, AgentConfig, MonitorForAgent,
    MonitorCreate, MonitorUpdate, MonitorRead, MonitorCheckRead, MonitorCheckReport, MonitorCheckPoint,
    MtrReport, MtrTaskRead, MonitorGroupWrite, MonitorGroupRead,
)
from app.services import node as node_svc
from app.services import monitor as monitor_svc
from app.services import host as host_svc
from app.services import task as task_svc
from app.repositories import config as config_repo
from app.services import node_monitor_policy as policy_svc
from app.schemas.node_monitor_policy import NodeMonitoringPolicyWrite, NodeMonitoringPolicyRead, NodeMonitoringPause

# 节点管理走登录鉴权
node_router = APIRouter(dependencies=[Depends(current_user)], prefix="/nodes", tags=["nodes"])


@node_router.get("/", response_model=list[NodeRead], response_model_exclude={"__all__": {"token"}})
def list_nodes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return node_svc.list_nodes(db)


@node_router.post("/", response_model=NodeRead, status_code=201, response_model_exclude={"token"})
def create_node(data: NodeCreate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return node_svc.create_node(db, data.name, data.platform, data.host)


@node_router.get('/entry-monitoring', response_model=list[EntryDefinition])
def entry_monitoring_summary(user: User = Depends(current_user)):
    return entry_monitoring.manifest()['entries']


@node_router.get('/monitoring-policy', response_model=NodeMonitoringPolicyRead)
def read_node_monitoring_policy(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return policy_svc.read(db)


@node_router.get('/report-channels', response_model=ChannelRead)
def read_report_channels(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return agent_channels.read(db)


@node_router.put('/report-channels', response_model=ChannelRead)
def write_report_channels(data: ChannelWrite, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return agent_channels.update(db, data.model_dump())


@node_router.put('/monitoring-policy', response_model=NodeMonitoringPolicyRead)
def write_node_monitoring_policy(data: NodeMonitoringPolicyWrite, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return policy_svc.update(db, data.model_dump())


@node_router.patch('/monitoring-policy/targets/{target_node_id}', response_model=NodeMonitoringPolicyRead)
def pause_node_monitoring(target_node_id: int, data: NodeMonitoringPause,
                          user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return policy_svc.suppress(db, target_node_id, data.suppressed)


@node_router.post('/{node_id}/install-command')
def install_command(node_id: int, request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Explicit, no-store credential retrieval; never piggyback on node lists."""
    import shlex
    from fastapi.responses import JSONResponse
    from app.repositories import node as node_repo
    node = node_repo.get_by_id(db, node_id)
    if node is None or node.status == 'removed' or not node.token:
        raise HTTPException(404, '节点不存在或凭证已移除')
    url = node_svc.installation_url(db)
    if node.platform == 'windows':
        quote = lambda s: "'" + s.replace("'", "''") + "'"
        command = ('& ([scriptblock]::Create((Invoke-WebRequest -UseBasicParsing -Uri ' +
                   quote(url + '/agent/install.ps1') + ').Content)) -Url ' + quote(url) + ' -Token ' + quote(node.token))
    else:
        command = ('curl -fsSL ' + shlex.quote(url + '/agent/install.sh') +
                   ' | sudo bash -s -- --url ' + shlex.quote(url) + ' --token ' + shlex.quote(node.token))
    role = node_svc.get_host_node(db)
    if role is not None and role.id == node.id:
        # Same explicit center-scoped slot as automatic host installation. Other
        # inventory nodes retain their original default/explicit-slot contract.
        command += (' -Instance ' + quote(host_svc.HOST_INSTANCE) if node.platform == 'windows'
                    else ' --instance ' + shlex.quote(host_svc.HOST_INSTANCE))
    return JSONResponse({'url': url, 'token': node.token, 'command': command},
                        headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})


@node_router.get("/map-topology")
def read_map_topology(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """本地快照组装，不发起外网定位；沿用节点列表的登录可见性。"""
    return server_map.get_topology(db)


@node_router.patch("/{node_id}/map-location")
def update_map_location(node_id: int, data: MapLocationUpdate,
                        user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """人工坐标优先；坐标全 null 清除人工设置（不清 agent 快照）。"""
    try:
        return server_map.set_manual_location(db, node_id, data)
    except ValueError:
        raise HTTPException(404, "节点不存在")


@node_router.get("/host")
def get_host(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """本机：OS 用节点存的 platform（探一次存），agent 运行状态动态查。"""
    node = node_svc.get_host_node(db)
    local_install = host_svc.supports_local_install()
    installed = bool(node.installed) if node else False
    try:
        install_url, address_error = node_svc.installation_url(db), None
    except HTTPException as exc:
        install_url, address_error = None, str(exc.detail)
    return {
        "installation_url": install_url,
        "installation_address_error": address_error,
        # OS 显示名：优先 agent 采集的发行版友好名，退化为 platform/本机探测
        "os": (node.os_name or node.platform) if node else (host_svc.detect_os() if local_install else ""),
        "installed": installed,
        "local_install_supported": local_install,
        "node_id": node.id if node else None,
        "node_status": node_svc.node_status(node) if node else None,
        "installation": node_svc.host_installation(db),
    }


@node_router.post('/host/prepare', response_model=NodeRead, status_code=201, response_model_exclude={'token'})
def prepare_host(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Explicit real-host role for container/manual access; no service discovery."""
    return node_svc.ensure_host_node(db)


@node_router.post("/host/install", response_model=NodeRead, status_code=201, response_model_exclude={"token"})
def install_host(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """仅裸机运行时提供本机安装，容器不能安装宿主 agent。"""
    if not host_svc.supports_local_install():
        raise HTTPException(409, "Stella 运行在容器内，请在目标服务器执行节点安装命令")
    # The instance installer authenticates center+node ownership before touching
    # scoped paths. A legacy/foreign process is not a reason to block this center.
    try:
        return node_svc.install_host_node(db)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@node_router.post("/{node_id}/uninstall", response_model=NodeRead, response_model_exclude={"token"})
def uninstall_node(node_id: int, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """发起卸载：下发卸载指令给 agent（pending → agent 领取 → 执行 → 回传）。"""
    try:
        return node_svc.request_uninstall(db, node_id)
    except ValueError as e:
        raise HTTPException(409, str(e))


@node_router.delete("/{node_id}", status_code=204)
def delete_node(node_id: int, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    node_svc.remove_node(db, node_id)


@node_router.get("/{node_id}/metrics", response_model=list[MetricPoint])
def read_node_metrics(node_id: int, iface: str | None = None,
                      start: datetime | None = None, end: datetime | None = None,
                      limit: int = Query(720, ge=1, le=5000), step: int | None = Query(None, ge=1, le=86400),
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
                          limit: int = Query(720, ge=1, le=5000), step: int | None = Query(None, ge=1, le=86400),
                          user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """系统指标历史（倒序）。step>60 时降采样聚合。"""
    return node_svc.get_node_sys_metrics(db, node_id, start, end, limit, step)


@node_router.patch("/{node_id}", response_model=NodeRead, response_model_exclude={"token"})
def update_node(node_id: int, data: NodeUpdate,
                user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """更新节点（监控网卡设置等）。"""
    try:
        return node_svc.update_monitored_ifaces(db, node_id, data.monitored_ifaces)
    except ValueError:
        raise HTTPException(404, "节点不存在")


@node_router.patch("/{node_id}/net-type", response_model=NodeRead, response_model_exclude={"token"})
def update_net_type(node_id: int, data: NetTypeUpdate,
                    user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """更新内网/公网标记（公网 + 手动 IP 时后端查地区）。"""
    try:
        return node_svc.update_net_type(db, node_id, data.net_type, data.public_ip)
    except ValueError:
        raise HTTPException(404, "节点不存在")


@node_router.post("/{node_id}/ip-change", response_model=NetTaskRead, status_code=201)
def change_ip(node_id: int, data: IpChangeCreate,
              user: User = Depends(admin_user), db: Session = Depends(get_db)):
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
               user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """容器启停重启。"""
    try:
        return task_svc.create_docker_ctl(db, node_id, data.action, data.container)
    except ValueError as e:
        raise HTTPException(409, str(e))


@node_router.post("/{node_id}/pbr-scan", response_model=NetTaskRead, status_code=201)
def pbr_scan(node_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """下发 PBR 结构化采集（ip rule/路由表/mangle 打标，只读）。"""
    try:
        return task_svc.create_pbr_scan(db, node_id)
    except ValueError as e:
        raise HTTPException(409, str(e))


@node_router.post("/{node_id}/docker-logs", response_model=NetTaskRead, status_code=201)
def docker_logs(node_id: int, data: DockerContainerAction,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    """读容器日志（tail 行，只读）。"""
    try:
        return task_svc.create_docker_logs(db, node_id, data.container, data.tail)
    except ValueError as e:
        raise HTTPException(409, str(e))


@node_router.post("/{node_id}/docker-inspect", response_model=NetTaskRead, status_code=201)
def docker_inspect(node_id: int, data: DockerContainerAction,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    """读容器配置摘要（inspect 只读）。"""
    try:
        return task_svc.create_docker_inspect(db, node_id, data.container)
    except ValueError as e:
        raise HTTPException(409, str(e))


@node_router.get("/{node_id}/net-tasks/latest", response_model=NetTaskRead | None)
def latest_net_task(node_id: int, kind: str, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """某节点某类型最近一次完成的扫描（前端惰性缓存：打开页面先读快照，过期再自动重扫）。"""
    return task_svc.latest_net_task(db, node_id, kind)


@node_router.get("/{node_id}", response_model=NodeDetail, response_model_exclude={"token"})
def read_node(node_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """单节点详情：基础信息 + 实时快照（各监控网卡最新流量 + 最新系统指标）。"""
    try:
        return node_svc.get_node_detail(db, node_id)
    except ValueError:
        raise HTTPException(404, "节点不存在")


# agent 上报/拉配置：token 鉴权（agent 不是登录用户，凭安装命令里的 token）
agent_router = APIRouter(prefix="/agent", tags=["agent"])


@agent_router.post("/report", response_model=ChannelReportAck)
def agent_report(request: Request, token: Annotated[str, Depends(agent_token)], report: AgentReport, db: Session = Depends(get_db)):
    """agent 上报流量/系统指标。token 在 query 里。幂等：重复补传自动丢弃。"""
    try:
        if report.channel_receipt is not None:
            from app.repositories import node as node_repo
            authenticated = node_repo.get_by_token(db, token)
            if authenticated is None or authenticated.status == 'removed':
                raise ValueError('invalid token')
            agent_channels.receipt(db, authenticated, report.channel_receipt, str(request.base_url).rstrip('/'))
        node = node_svc.handle_report(db, token, report)
    except ValueError:
        raise HTTPException(401, "无效的 agent token")
    return {
        "ok": True,
        "node_id": node.id,
        "status": node.status,
        "monitors_version": config_repo.get_monitors_version(db),
        "channel_revision": agent_channels.assignment(agent_channels._load(db), node.id)['revision'],
    }


@agent_router.get("/config", response_model=AgentConfig, response_model_exclude_none=True)
def agent_config(token: Annotated[str, Depends(agent_token)], db: Session = Depends(get_db)):
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
        entry_monitoring=entry_monitoring.manifest(node, db=db),
        report_channel=agent_channels.optional_config(db, node),
    )


@agent_router.get('/entry-probe', response_model=ChannelProbe)
def agent_entry_probe(request: Request, token: Annotated[str, Depends(agent_token)], db: Session = Depends(get_db)):
    # Normal node Bearer, read-only, no tasks/heartbeat/duplicate metric writes.
    from app.repositories import node as node_repo
    node = node_repo.get_by_token(db, token)
    if node is None or node.status == 'removed':
        raise HTTPException(401, '无效的 agent token')
    from fastapi.responses import JSONResponse
    return JSONResponse(agent_channels.probe(node, str(request.base_url).rstrip('/')),
                        headers={'Cache-Control':'no-store'})


def _monitor_for_agent(m) -> MonitorForAgent:
    """ORM → 下发模型，附带预计算的 MTR 规格（agent 不做协议映射，只执行）。"""
    from app.monitor_targets import parse_stored_target
    host, proto, port = monitor_svc.mtr_spec(m.type, m.target)
    return MonitorForAgent(id=m.id, type=m.type, target=parse_stored_target(m.type, m.target).value, interval=m.interval,
                           timeout=m.timeout, mtr_host=host, mtr_proto=proto, mtr_port=port)


@agent_router.post("/mtr-report")
def agent_mtr_report(token: Annotated[str, Depends(agent_token)], report: MtrReport, db: Session = Depends(get_db)):
    """agent 主动上报监控项 MTR 结果（定时/失败触发）。手动触发的走 mtr-tasks result 通道。"""
    from app.services import task as task_svc
    try:
        task_svc.report_mtr(db, token, report.monitor_id, report.trigger,
                            report.ok, report.result_json, report.error)
    except ValueError as e:
        raise HTTPException(401 if "token" in str(e) else 404, str(e))
    return {"ok": True}


@agent_router.post("/monitor-check")
def agent_monitor_check(token: Annotated[str, Depends(agent_token)], report: MonitorCheckReport, db: Session = Depends(get_db)):
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


@agent_router.get('/map-targets')
def agent_map_targets(token: Annotated[str, Depends(agent_token)], db: Session = Depends(get_db)):
    try:
        return {'targets': server_map.get_probe_targets(db, token)}
    except ValueError:
        raise HTTPException(401, '无效的 agent token')


@agent_router.get("/script")
def agent_script():
    """下发 agent 主程序源码（安装脚本用）。无鉴权——脚本本身不含密钥。"""
    from fastapi.responses import PlainTextResponse
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "agent" / "stella_agent.py"
    return PlainTextResponse(script.read_bytes())


@agent_router.get("/version")
def agent_version():
    """返回中心当前 agent 最新版本号（agent 自更新时对比用）。无鉴权。"""
    import re
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "agent" / "stella_agent.py"
    body = script.read_bytes()
    text = body.decode('utf-8')
    m = re.search(r'AGENT_VERSION\s*=\s*"([^"]+)"', text)
    available = m.group(1) if m else "0.0.0"
    import os
    rollout = os.getenv('STELLA_AGENT_ROLLOUT_VERSION', available)
    if (rollout not in {'0.6.9', '0.6.10', '0.6.11', '0.6.15', '0.6.16', '0.6.17', '0.6.18', '0.6.19', '0.6.20', available}
            or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', available)
            or tuple(map(int, rollout.split('.'))) > tuple(map(int, available.split('.')))):
        raise HTTPException(503, 'Agent 滚动版本配置无效')
    if rollout == available:
        import hashlib
        return {'version': rollout, 'sha256': hashlib.sha256(body).hexdigest(), 'size': len(body)}
    # The parked legacy announcement is not a manifest for the newer script.
    return {"version": rollout}


from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from app.repositories import node as identity_node_repo
from app.services import agent_install as identity_install_svc


class AgentIdentityRead(BaseModel):
    """Authenticated install binding and exact source, never writable paths."""
    model_config = ConfigDict(extra='forbid')
    center_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    node_id: int = Field(gt=0)
    source_version: str = Field(pattern=r'^\d+\.\d+\.\d+$')
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_size: int = Field(gt=0, le=8 * 1024 * 1024)


@agent_router.get('/identity', response_model=AgentIdentityRead)
def agent_identity(token: Annotated[str, Depends(agent_token)], db: Session = Depends(get_db)):
    from pathlib import Path
    import hashlib
    import re
    from fastapi.responses import JSONResponse
    node = identity_node_repo.get_by_token(db, token)
    if node is None or node.status == 'removed':
        raise HTTPException(401, '无效的 agent token')
    try:
        center = identity_install_svc.installation_center_id()
    except (RuntimeError, OSError, ValueError, KeyError, IndexError):
        raise HTTPException(503, '中心签名身份不可用；拒绝无归属安装') from None
    body = (Path(__file__).resolve().parents[2] / 'agent' / 'stella_agent.py').read_bytes()
    match = re.search(rb'AGENT_VERSION\s*=\s*"([^"]+)"', body)
    if not match:
        raise HTTPException(503, 'Agent 源码版本无法读取')
    result = AgentIdentityRead(center_id=center, node_id=node.id,
        source_version=match.group(1).decode('utf-8'), source_sha256=hashlib.sha256(body).hexdigest(), source_size=len(body))
    return JSONResponse(result.model_dump(), headers={'Cache-Control': 'no-store'})


class AgentReleaseRead(BaseModel):
    """Public artifact metadata, separate from the legacy updater decision."""
    model_config = ConfigDict(extra='forbid')
    source_version: str
    source_sha256: str
    source_size: int
    announcement_version: str
    rollout_policy: Literal['pinned', 'source']


@agent_router.get('/release', response_model=AgentReleaseRead)
def agent_release():
    """Read-only source fingerprint; never an instruction to update a node."""
    import hashlib
    import re
    from pathlib import Path
    from fastapi.responses import JSONResponse
    announcement = agent_version()
    body = (Path(__file__).resolve().parents[2] / 'agent' / 'stella_agent.py').read_bytes()
    match = re.search(rb'AGENT_VERSION\s*=\s*"([^"]+)"', body)
    if not match:
        raise HTTPException(503, 'Agent 源码版本无法读取')
    version = match.group(1).decode('utf-8')
    metadata = AgentReleaseRead(
        source_version=version, source_sha256=hashlib.sha256(body).hexdigest(),
        source_size=len(body), announcement_version=announcement['version'],
        rollout_policy='source' if announcement['version'] == version else 'pinned',
    )
    return JSONResponse(metadata.model_dump(), headers={'Cache-Control': 'no-store'})


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


@agent_router.get("/run-agent.ps1")
def agent_run_ps1():
    """Public credential-free Windows task entry point, matching /agent/script."""
    from fastapi.responses import PlainTextResponse
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "agent" / "run-agent.ps1"
    return PlainTextResponse(script.read_bytes(), media_type="text/plain; charset=utf-8")


@agent_router.get("/hardware-sensors.ps1")
def agent_hardware_sensors_ps1():
    """Public opt-in read-only hardware bridge; contains no credentials."""
    from fastapi.responses import PlainTextResponse
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "agent" / "hardware-sensors.ps1"
    return PlainTextResponse(script.read_bytes(), media_type="text/plain; charset=utf-8")


# 监控项：登录鉴权
monitor_router = APIRouter(dependencies=[Depends(current_user)], prefix="/monitors", tags=["monitors"])


from app.schemas.monitor import MonitorBatchCreate, MonitorBatchReceipt


@monitor_router.get('/batches/receipts/{request_key}', response_model=MonitorBatchReceipt)
def monitor_batch_receipt(request_key: str, request: Request, db: Session = Depends(get_db)):
    from app.services.monitor_batches import receipt
    result = receipt(db, request_key, request.state.auth_session.id)
    if result is None:
        raise HTTPException(404, '创建结果尚未确认；请勿重复创建')
    return result


@monitor_router.post('/batches', response_model=MonitorBatchReceipt, status_code=201)
def create_monitor_batch(data: MonitorBatchCreate, request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    from app.services.monitor_batches import create, BatchConflict
    try:
        return create(db, data, session_id=request.state.auth_session.id)
    except BatchConflict as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@monitor_router.get('/groups', response_model=list[MonitorGroupRead])
def list_monitor_groups(include_empty: bool = False, db: Session = Depends(get_db)):
    from app.services.monitor_groups import list_groups
    return list_groups(db, include_empty=include_empty)


from app.schemas.monitor import MonitorGroupCreate, MonitorGroupReceipt, MonitorGroupDelete, MonitorGroupDeletionState, GroupStableUUID


@monitor_router.get('/groups/{group_id}/deletion-state', response_model=MonitorGroupDeletionState)
def monitor_group_deletion_state(group_id: int, expected_child_ids: list[int] = Query(default=[], max_length=12), expected_stable_uuid: GroupStableUUID | None = Query(default=None), db: Session = Depends(get_db)):
    from app.services.monitor_groups import deletion_state
    return deletion_state(db, group_id, expected_child_ids, expected_stable_uuid)


@monitor_router.post('/groups/{group_id}/delete', status_code=204)
def delete_monitor_group(group_id: int, data: MonitorGroupDelete, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    from app.services.monitor_groups import delete_group, GroupScopeConflict
    try:
        delete_group(db, group_id, data.expected_child_ids, data.expected_stable_uuid)
    except GroupScopeConflict as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@monitor_router.get('/groups/receipts/{request_key}', response_model=MonitorGroupReceipt)
def monitor_group_receipt(request_key: str, request: Request, db: Session = Depends(get_db)):
    from app.services.monitor_groups import creation_receipt
    result = creation_receipt(db, request_key, request.state.auth_session.id)
    if result is None:
        raise HTTPException(404, '创建结果尚未确认；请勿重复创建')
    return result


@monitor_router.post('/groups', response_model=MonitorGroupRead, status_code=201)
def create_monitor_group(data: MonitorGroupCreate, request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    from app.services.monitor_groups import create_group
    try:
        return create_group(db, data, session_id=request.state.auth_session.id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@monitor_router.post('/groups/{group_id}/children', response_model=MonitorRead, status_code=201)
def create_monitor_group_child(group_id: int, data: MonitorCreate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    from app.services.monitor_groups import create_child
    try:
        return monitor_svc.present_monitor(db, create_child(db, group_id, data))
    except ValueError as e:
        raise HTTPException(400, str(e))


@monitor_router.put('/groups/{group_id}', response_model=MonitorGroupRead)
def update_monitor_group(group_id: int, data: MonitorGroupWrite, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    from app.services.monitor_groups import save_group
    try:
        return save_group(db, group_id, **data.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@monitor_router.delete('/groups/{group_id}', status_code=204)
def dissolve_monitor_group(group_id: int, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    from app.services.monitor_groups import remove_group
    try:
        remove_group(db, group_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@monitor_router.get("/", response_model=list[MonitorRead])
def list_monitors(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return monitor_svc.list_monitors(db)


@monitor_router.post("/", response_model=MonitorRead, status_code=201)
def create_monitor(data: MonitorCreate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    node = node_svc.get_node(db, data.node_id)
    if node is None or node.status == "removed":
        raise HTTPException(404, "探测节点不存在")
    try:
        monitor = monitor_svc.create_monitor(db, data.name, data.type, data.target,
                                             data.interval, data.timeout, data.node_id)
        return monitor_svc.present_monitor(db, monitor)
    except ValueError as e:
        raise HTTPException(400, str(e))


@monitor_router.patch("/{monitor_id}", response_model=MonitorRead)
def update_monitor(monitor_id: int, data: MonitorUpdate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    try:
        monitor = monitor_svc.update_monitor(db, monitor_id, data.model_dump(exclude_none=True))
        return monitor_svc.present_monitor(db, monitor)
    except ValueError as e:
        raise HTTPException(404 if monitor_svc.get_monitor(db, monitor_id) is None else 400, str(e))


@monitor_router.delete("/{monitor_id}", status_code=204)
def delete_monitor(monitor_id: int, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    try:
        monitor_svc.remove_monitor(db, monitor_id)
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))


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
    try:
        return task_svc.create_mtr_for_monitor(db, m)
    except ValueError as e:
        raise HTTPException(400, str(e))


@monitor_router.get("/{monitor_id}/checks", response_model=list[MonitorCheckRead])
def monitor_checks(monitor_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return monitor_svc.list_checks(db, monitor_id)


@monitor_router.get("/{monitor_id}/series", response_model=list[MonitorCheckPoint])
def monitor_series(monitor_id: int, start: datetime | None = None, end: datetime | None = None,
                   step: int | None = Query(None, ge=1, le=86400), limit: int = Query(5000, ge=1, le=5000),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    """延迟曲线数据：start/end 时间范围 + step 秒分桶降采样。"""
    return monitor_svc.list_checks_range(db, monitor_id, start, end, step, limit)
