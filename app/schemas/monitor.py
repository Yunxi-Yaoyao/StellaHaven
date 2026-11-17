"""监控模块 schemas：节点 / 上报 / 监控项 / 任务。"""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, Field, JsonValue, field_validator, model_validator
from app.schemas.control_channel import ControlChannel, EntryManifest
from app.schemas.channel import ChannelConfig, ChannelReceipt
from app.schemas.public_node import Interface, Components, Storage, SystemInfo, Number, project_optional
from app.schemas.public_task import (NetTaskRead, MtrResult, MtrLive, IperfPublicResult,
                                     IperfProgress, project_iperf_result)


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
    token: str | None = Field(default=None, exclude=True)
    interfaces: dict[str, Interface] | None = None
    monitored_ifaces: dict[str, JsonValue] | None = Field(default=None,
        description='User-owned interface display configuration; not raw agent telemetry.')
    storage: list[Storage] | None = None
    components: Components | None = None
    control_channel: ControlChannel | None = None
    net_type: str = "internal"        # internal / public
    public_ip: str | None = None      # 公网 IP
    public_ip_source: str | None = None  # auto / manual
    ip_version: str | None = None     # IPv4 / IPv6
    region: str | None = None         # 地区（中文）
    uninstall_status: str | None = None
    uninstall_error: str | None = None
    installed: bool = False
    os_name: str | None = None      # 发行版友好名
    sys_info: SystemInfo | None = None
    created_at: datetime

    @field_validator('interfaces', 'components', 'storage', 'sys_info', 'control_channel', mode='before')
    @classmethod
    def project_agent_slots(cls, value, info):
        if info.field_name == 'control_channel':
            import json
            from pydantic import ValidationError
            if isinstance(value, ControlChannel) or value is None:
                return value
            try:
                return ControlChannel.model_validate_json(json.dumps(value), strict=True)
            except (ValidationError, ValueError, TypeError):
                return None
        return project_optional(cls.model_fields[info.field_name].annotation, value)

    model_config = {"from_attributes": True}


# ── agent 上报 ──
class MetricPoint(BaseModel):
    """流量采样点：5s 窗口的字节增量"""
    iface: str
    ts: datetime
    rx_delta: int
    tx_delta: int
    interval_start: datetime | None = None
    elapsed_seconds: float | None = None
    quality: str | None = None


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


class DockerCtlCreate(BaseModel):
    """容器启停重启"""
    action: str      # start / stop / restart
    container: str   # 容器名或 ID


class DockerContainerAction(BaseModel):
    """容器日志/配置查看（只读）"""
    container: str   # 容器名或 ID
    tail: int = 150  # 日志行数（仅 docker-logs 用）


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
    map_snapshot: dict | None = None
    control_channel: ControlChannel | None = None
    channel_receipt: ChannelReceipt | None = None

    @field_validator("map_snapshot")
    @classmethod
    def validate_map_snapshot(cls, value):
        from app.services.server_map import validate_snapshot
        return validate_snapshot(value) if value is not None else None


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
    entry_monitoring: EntryManifest | None = None
    report_channel: ChannelConfig | None = None


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
    name: str = Field(min_length=1, max_length=64)
    type: Literal['ping', 'tcp', 'udp', 'http', 'https'] = 'tcp'
    target: str = Field(min_length=1, max_length=256)
    interval: int = Field(default=60, ge=10, le=86400)
    timeout: int = Field(default=5, ge=1, le=120)
    node_id: int = Field(gt=0)

    @model_validator(mode='after')
    def valid_target(self):
        from app.monitor_targets import parse_target
        if not self.name.strip():
            raise ValueError('名称不能为空')
        self.target = parse_target(self.type, self.target).value
        return self


class MonitorUpdate(BaseModel):
    """监控项编辑：全部可选，只改给了的字段。"""
    visible: bool | None = Field(default=None, strict=True)
    enabled: bool | None = Field(default=None, strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=64)
    type: Literal['ping', 'tcp', 'udp', 'http', 'https'] | None = None
    target: str | None = Field(default=None, min_length=1, max_length=256)
    interval: int | None = Field(default=None, ge=10, le=86400)
    timeout: int | None = Field(default=None, ge=1, le=120)
    node_id: int | None = Field(default=None, gt=0)

    @model_validator(mode='after')
    def valid_supplied_target(self):
        if self.name is not None and not self.name.strip():
            raise ValueError('名称不能为空')
        if self.type is not None and self.target is not None:
            from app.monitor_targets import parse_target
            self.target = parse_target(self.type, self.target).value
        return self


# Canonical persisted UUID text: no coercion, normalization or numeric-ID fallback.
GroupStableUUID = Annotated[str, Field(strict=True, pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')]


class MonitorGroupDelete(BaseModel):
    model_config = {"extra": "forbid"}
    expected_stable_uuid: GroupStableUUID
    expected_child_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(max_length=12)

    @model_validator(mode='after')
    def distinct_children(self):
        if len(set(self.expected_child_ids)) != len(self.expected_child_ids):
            raise ValueError('确认成员不能重复')
        return self


class MonitorGroupDeleteChild(BaseModel):
    id: int
    name: str
    type: str
    target: str


class MonitorGroupDeletionState(BaseModel):
    stable_uuid: str | None
    identity_matches: bool | None
    group_exists: bool
    name: str | None
    children: list[MonitorGroupDeleteChild]
    protected: bool
    remaining_child_ids: list[int]


class MonitorGroupReceipt(BaseModel):
    group_id: int
    monitor_ids: list[int]


class MonitorGroupItemCreate(MonitorCreate):
    model_config = {"extra": "forbid"}


class MonitorBatchCreate(BaseModel):
    model_config = {"extra": "forbid"}
    items: list[MonitorGroupItemCreate] = Field(min_length=1, max_length=12)
    request_key: str = Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    group_id: int | None = Field(default=None, gt=0, strict=True)
    expected_group_uuid: GroupStableUUID | None = None


class MonitorBatchReceipt(BaseModel):
    group_id: int | None
    monitor_ids: list[int]


class MonitorGroupCreate(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1, max_length=64)
    items: list[MonitorGroupItemCreate] = Field(min_length=1, max_length=12)
    request_key: str = Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    failure_policy: Literal['any', 'all'] = 'any'
    rotation_seconds: Literal[0, 8, 15, 30] = 0


class MonitorGroupWrite(BaseModel):
    visible: bool | None = Field(default=None, strict=True)
    enabled: bool | None = Field(default=None, strict=True)
    name: str = Field(min_length=1, max_length=64)
    # Existing automatic groups may include all nodes; service bounds manual groups.
    child_ids: list[int] | None = Field(default=None, min_length=0, max_length=10000)
    failure_policy: Literal['any', 'all'] = 'any'
    rotation_seconds: Literal[0, 8, 15, 30] = 0


class MonitorGroupRead(MonitorGroupWrite):
    visible: bool = True
    enabled: bool = True
    eligible_child_ids: list[int] = []
    id: int
    child_ids: list[int]
    automatic: bool = False
    source_node_id: int | None = None
    entry_id: Literal['public', 'private'] | None = None
    target_origin: str | None = None
    availability_reason: Literal['entry_not_configured', 'no_connected_nodes'] | None = None
    status: Literal['up', 'down'] | None
    down_count: int
    up_count: int = 0
    unknown_count: int


class MonitorRead(BaseModel):
    visible: bool = True
    enabled: bool = True
    effective_enabled: bool = True
    id: int
    name: str
    node_id: int
    type: str
    target: str
    interval: int
    timeout: int
    status: Literal['up', 'down']
    last_check_at: datetime | None = None
    last_latency_ms: float | None = None
    management: Literal['entry_icmp'] | None = None
    status_reason: Literal['healthy', 'failure', 'pending', 'source_pending', 'source_offline',
        'dns_error', 'dns_timeout', 'outside_scope', 'too_many_ips', 'budget_exceeded',
        'unavailable', 'restricted', 'stale', 'entry_removed', 'invalid_target', 'unsupported', 'scope_pending'] = 'pending'

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
    """Series point; counts preserve exact weighted statistics after bucketing."""
    ts: datetime
    success: bool
    latency_ms: float | None = None
    loss_pct: float | None = None
    sample_count: int = 1
    success_count: int = 0
    latency_count: int = 0
    loss_count: int = 0


# ── 任务（打流 / MTR / 命令）──
class IperfTaskCreate(BaseModel):
    server_node_id: int | None = Field(default=None, gt=0)
    client_node_id: int = Field(gt=0)
    mode: Literal['iperf3', 'speedtest'] = 'iperf3'
    direction: Literal['forward', 'reverse'] = 'forward'
    duration: int = Field(default=10, ge=1, le=3600)
    bytes: str | None = Field(default=None, max_length=24)
    parallel: int = Field(default=1, ge=1, le=16)
    udp: bool = False
    bitrate: str | None = Field(default=None, max_length=24)
    port: int = Field(default=5201, ge=1, le=65535)
    window: str | None = Field(default=None, max_length=24)
    length: str | None = Field(default=None, max_length=24)
    omit: int = Field(default=0, ge=0, le=60)
    zerocopy: bool = False
    speedtest_server: str | None = Field(default=None, max_length=12)

    @field_validator('bytes', 'bitrate', 'window', 'length')
    @classmethod
    def valid_quantity(cls, value):
        import re
        if value is None:
            return None
        # Keep caller suffix exactly: byte quantities and bit rates use different bases.
        if not re.fullmatch(r'(?:\d+(?:\.\d+)?)(?:[KMGkmg])?', value) or not 0 < float(value.rstrip('KMGkmg')) <= 1e12:
            raise ValueError('数量须为正数，可带 K/M/G 后缀')
        return value

    @field_validator('speedtest_server')
    @classmethod
    def valid_speedtest_server(cls, value):
        import re
        if value is not None and not re.fullmatch(r'[1-9][0-9]{0,11}', value):
            raise ValueError('speedtest_server 只能为单个正整数服务器 ID，自动选择请传 null')
        return value

    @model_validator(mode='after')
    def mapped_options(self):
        if self.mode == 'speedtest':
            if (self.server_node_id is not None or self.direction != 'forward' or self.duration != 10
                    or self.parallel != 1 or self.udp or self.bytes is not None or self.bitrate is not None
                    or self.window is not None or self.length is not None or self.omit or self.zerocopy
                    or self.port != 5201):
                raise ValueError('speedtest 不支持 iperf3 参数；请仅选择客户端和 speedtest_server')
        elif self.speedtest_server is not None:
            raise ValueError('speedtest_server 仅适用于 speedtest 模式')
        return self


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
    avg_mbps: Number | None = None
    peak_mbps: Number | None = None
    lost_pct: Number | None = None
    jitter_ms: Number | None = None
    speedtest_server: str | None = None  # speedtest 测速服务器 ID
    result_json: IperfPublicResult | None = None
    progress_json: list[IperfProgress] | None = None
    created_at: datetime

    @field_validator('result_json', mode='before')
    @classmethod
    def project_result(cls, value, info):
        return project_iperf_result(value, info.data.get('mode'))

    @field_validator('progress_json', 'avg_mbps', 'peak_mbps', 'lost_pct', 'jitter_ms', mode='before')
    @classmethod
    def project_measurements(cls, value, info):
        return project_optional(cls.model_fields[info.field_name].annotation, value)

    model_config = {"from_attributes": True}


class MtrTaskCreate(BaseModel):
    node_id: int
    target: str
    protocol: str = "icmp"
    # 探测参数：count(-c 包数) / interval(-i 秒) / max_hops(-m) / psize(-s 字节)，空=默认
    params: dict | None = None


class MtrJobCreate(BaseModel):
    node_ids: list[int] = Field(min_length=1, max_length=8)
    target: str = Field(min_length=1, max_length=256)
    protocol: Literal['icmp', 'tcp', 'udp'] = 'icmp'
    params: dict | None = None


class MtrTaskRead(BaseModel):
    id: int
    job_id: str | None = None
    node_id: int
    monitor_id: int | None = None
    target: str
    protocol: str
    trigger: str = "manual"
    status: str
    result_json: MtrResult | None = None
    params_json: dict[str, JsonValue] | None = Field(default=None,
        description='User MTR options, including historical/future JSON options; not telemetry.')
    live_json: MtrLive | None = None
    created_at: datetime

    @field_validator('result_json', 'live_json', mode='before')
    @classmethod
    def project_results(cls, value, info):
        return project_optional(cls.model_fields[info.field_name].annotation, value)

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
