"""监控模块 schemas：节点 / 上报 / 监控项 / 任务。"""
from datetime import datetime
from pydantic import BaseModel


# ── 节点 ──
class NodeCreate(BaseModel):
    name: str
    platform: str = "linux"  # linux / windows / fnos
    host: str


class NodeRead(BaseModel):
    id: int
    name: str
    platform: str
    host: str
    arch: str | None = None
    agent_version: str | None = None
    last_seen_at: datetime | None = None
    status: str
    token: str | None = None
    interfaces: dict | None = None
    monitored_ifaces: dict | None = None
    storage: list | None = None
    components: dict | None = None
    net_type: str = "internal"        # internal / public
    public_ip: str | None = None      # 公网 IP
    public_ip_source: str | None = None  # auto / manual
    ip_version: str | None = None     # IPv4 / IPv6
    region: str | None = None         # 地区（中文）
    uninstall_status: str | None = None
    uninstall_error: str | None = None
    installed: bool = False
    os_name: str | None = None      # 发行版友好名
    sys_info: dict | None = None    # 基本信息面板：{kernel, cpu_model, cpu_cores, load1/5/15, boot_time}
    created_at: datetime

    model_config = {"from_attributes": True}


# ── agent 上报 ──
class MetricPoint(BaseModel):
    """流量采样点：5s 窗口的字节增量"""
    iface: str
    ts: datetime
    rx_delta: int
    tx_delta: int


class SysMetricPoint(BaseModel):
    """系统指标采样点：60s"""
    ts: datetime
    cpu_pct: float | None = None
    mem_pct: float | None = None
    disk_pct: float | None = None


class NodeDetail(NodeRead):
    """详情页：节点基础信息 + 实时快照"""
    latest_metrics: list[MetricPoint] = []
    latest_sys_metric: SysMetricPoint | None = None


class NodeUpdate(BaseModel):
    """更新节点（监控网卡设置等）"""
    monitored_ifaces: dict | None = None


class NetTypeUpdate(BaseModel):
    """更新内网/公网标记"""
    net_type: str  # internal / public
    public_ip: str | None = None  # 公网服务器手动输入公网 IP


class IpChangeCreate(BaseModel):
    """改 IP 任务（高危，agent 本地执行回退）"""
    iface: str
    new_ip: str
    prefix: int = 24
    gateway: str | None = None
    ping_target: str  # 预计可 ping 的 IP/域名，不通则回退


class NetTaskRead(BaseModel):
    """网络操作任务（改 IP / 防火墙扫描 / Docker）"""
    id: int
    node_id: int
    kind: str
    status: str
    result_json: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DockerCtlCreate(BaseModel):
    """容器启停重启"""
    action: str      # start / stop / restart
    container: str   # 容器名或 ID


class AgentReport(BaseModel):
    """agent 上报：一次带流量 + 系统指标（可批量，补传时多条）。"""
    metrics: list[MetricPoint] = []
    sys_metrics: list[SysMetricPoint] = []
    interfaces: dict | None = None  # 网卡清单（首次上报时带，含默认出口标记）
    agent_version: str | None = None  # agent 版本号（首次上报时带）
    storage: list | None = None  # 存储视图：挂载点列表（首次上报时带）
    components: dict | None = None  # 组件检测状态：{"iperf3": bool, "speedtest": bool, "firewall": {...}}
    os_info: dict | None = None  # OS 信息：{os_name, kernel, cpu_model, cpu_cores, load1/5/15, boot_time}（每次上报都带）
    public_ip_info: dict | None = None  # 公网 IP 探测结果：{public_ip, ip_version, region}


class MonitorForAgent(BaseModel):
    """下发给 agent 的监控项（精简字段 + 预计算的 MTR 规格）"""
    id: int
    type: str
    target: str
    interval: int
    timeout: int
    mtr_host: str = ""        # MTR 目标主机（已从 target 剥离端口/路径）
    mtr_proto: str = "icmp"   # icmp / tcp / udp
    mtr_port: int | None = None

    model_config = {"from_attributes": True}


class AgentConfig(BaseModel):
    """agent 拉取的配置"""
    node_id: int
    monitored_ifaces: dict | None = None
    monitors_version: int = 0
    monitors: list[MonitorForAgent] = []


class MonitorCheckReport(BaseModel):
    """agent 上报一次探测结果"""
    monitor_id: int
    ts: datetime
    success: bool
    latency_ms: float | None = None
    loss_pct: float | None = None


class MtrReport(BaseModel):
    """agent 主动上报的 MTR 结果（监控项定时/失败触发）"""
    monitor_id: int
    trigger: str = "periodic"  # periodic / failure
    ok: bool
    error: str | None = None
    result_json: dict | None = None


# ── 监控项 ──
class MonitorCreate(BaseModel):
    name: str
    type: str = "tcp"  # ping / tcp / udp / http / https
    target: str
    interval: int = 60
    timeout: int = 5
    node_id: int  # 探测源节点（必填，统一 agent 探测）


class MonitorUpdate(BaseModel):
    """监控项编辑：全部可选，只改给了的字段。"""
    name: str | None = None
    type: str | None = None
    target: str | None = None
    interval: int | None = None
    timeout: int | None = None
    node_id: int | None = None


class MonitorRead(BaseModel):
    id: int
    name: str
    node_id: int
    type: str
    target: str
    interval: int
    timeout: int
    status: str
    last_check_at: datetime | None = None
    last_latency_ms: float | None = None

    model_config = {"from_attributes": True}


class MonitorCheckRead(BaseModel):
    id: int
    monitor_id: int
    ts: datetime
    success: bool
    latency_ms: float | None = None
    loss_pct: float | None = None

    model_config = {"from_attributes": True}


class MonitorCheckPoint(BaseModel):
    """延迟曲线点（范围/降采样查询用，无行 id）。"""
    ts: datetime
    success: bool
    latency_ms: float | None = None
    loss_pct: float | None = None


# ── 任务（打流 / MTR / 命令）──
class IperfTaskCreate(BaseModel):
    server_node_id: int | None = None  # NULL = 公共 speedtest
    client_node_id: int
    mode: str = "iperf3"  # iperf3 / speedtest
    direction: str = "forward"  # forward / reverse
    duration: int = 10
    bytes: str | None = None
    parallel: int = 1
    udp: bool = False
    bitrate: str | None = None
    port: int = 5201
    window: str | None = None
    length: str | None = None
    omit: int = 0
    zerocopy: bool = False
    speedtest_server: str | None = None  # speedtest 指定测速服务器 ID（None=自动选延迟最低）


class IperfTaskRead(BaseModel):
    id: int
    server_node_id: int | None = None
    client_node_id: int
    mode: str
    direction: str
    duration: int
    bytes: str | None = None
    parallel: int
    udp: bool = False
    bitrate: str | None = None
    port: int = 5201
    window: str | None = None
    length: str | None = None
    omit: int = 0
    zerocopy: bool = False
    status: str
    server_started: bool = False        # 阶段提示用：server 端是否已起 -s
    started_at: datetime | None = None  # client 领取时刻
    # 结果摘要列（done 时从 result_json 提取；iperf=接收均值/峰值，speedtest=下载/上传）
    avg_mbps: float | None = None
    peak_mbps: float | None = None
    lost_pct: float | None = None
    jitter_ms: float | None = None
    speedtest_server: str | None = None  # speedtest 测速服务器 ID
    result_json: dict | None = None
    progress_json: list | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MtrTaskCreate(BaseModel):
    node_id: int
    target: str
    protocol: str = "icmp"
    # 探测参数：count(-c 包数) / interval(-i 秒) / max_hops(-m) / psize(-s 字节)，空=默认
    params: dict | None = None


class MtrTaskRead(BaseModel):
    id: int
    node_id: int
    monitor_id: int | None = None
    target: str
    protocol: str
    trigger: str = "manual"
    status: str
    result_json: dict | None = None
    params_json: dict | None = None
    live_json: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CommandCreate(BaseModel):
    node_id: int
    command: str


class CommandRead(BaseModel):
    id: int
    node_id: int
    command: str
    status: str
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ComponentInstallCreate(BaseModel):
    node_id: int
    component: str  # iperf3 / speedtest


class ComponentTaskRead(BaseModel):
    id: int
    node_id: int
    component: str
    status: str
    error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
