"""Public task results. These projections NEVER sanitize executable instructions.

Known normalized fields are typed; malformed values become null. Docker logs,
inspect env/cmd and firewall raw text remain literal tool output and may contain
operator-owned sensitive text. This module does not promise content redaction.
"""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, field_validator, model_validator
from app.schemas.public_node import (PublicRecord, Text, Integer, Number, Flag,
                                     project_optional, safe_legacy_json)


class ErrorResult(PublicRecord):
    error: Text | None = None


class IpChangePayload(PublicRecord):
    iface: Text | None = None
    new_ip: Text | None = None
    prefix: Integer | None = None
    gateway: Text | None = None
    ping_target: Text | None = None


class DockerPayload(PublicRecord):
    container: Text | None = None
    action: Text | None = None
    tail: Integer | None = None


class IpChangeResult(ErrorResult):
    ok: Flag | None = None
    rolled_back: Flag | None = None
    old_ip: Text | None = None
    new_ip: Text | None = None
    persisted: Flag | None = None
    backend: Text | None = None


class UfwRule(PublicRecord):
    num: Integer | None = None
    to: Text | None = None
    action: Text | None = None
    v6: Flag | None = None
    from_: Text | None = Field(default=None, alias='from')


class UfwResult(ErrorResult):
    installed: Flag | None = None
    active: Flag | None = None
    defaults: Text | None = None
    logging: Text | None = None
    raw: Text | None = None
    rules: list[UfwRule] | None = None


class IptablesChain(PublicRecord):
    name: Text | None = None
    policy: Text | None = None
    packets: Integer | None = None
    bytes: Integer | None = None


class IptablesRule(PublicRecord):
    raw: Text | None = None
    chain: Text | None = None
    target: Text | None = None
    proto: Text | None = None
    sport: Text | None = None
    dport: Text | None = None
    source: Text | None = None
    dest: Text | None = None
    in_iface: Text | None = None
    out_iface: Text | None = None


class IptablesTable(PublicRecord):
    chains: list[IptablesChain] | None = None
    rules: list[IptablesRule] | None = None


class IptablesResult(ErrorResult):
    installed: Flag | None = None
    raw: Text | None = None
    tables: dict[str, IptablesTable] | None = None


class FirewallResult(ErrorResult):
    ufw: UfwResult | None = None
    iptables: IptablesResult | None = None


class DockerContainer(PublicRecord):
    id: Text | None = None
    name: Text | None = None
    image: Text | None = None
    status: Text | None = None
    state: Text | None = None
    ports: Text | None = None
    created: Text | None = None


class DockerScanResult(ErrorResult):
    installed: Flag | None = None
    containers: list[DockerContainer] | None = None


class DockerCtlResult(ErrorResult):
    ok: Flag | None = None
    action: Text | None = None
    container: Text | None = None


class DockerLogsResult(ErrorResult):
    container: Text | None = None
    lines: Text | None = None
    tail: Integer | None = None


class DockerMount(PublicRecord):
    source: Text | None = None
    target: Text | None = None
    mode: Text | None = None
    rw: Flag | None = None


class DockerPort(PublicRecord):
    container: Text | None = None
    host: Text | None = None


class DockerInspectResult(ErrorResult):
    container: Text | None = None
    image: Text | None = None
    created: Text | None = None
    cmd: Text | None = None
    entrypoint: Text | None = None
    env: list[Text] | None = None
    mounts: list[DockerMount] | None = None
    ports: list[DockerPort] | None = None
    restart_policy: Text | None = None
    networks: list[Text] | None = None
    state: Text | None = None


class PbrRule(ErrorResult):
    pref: Integer | None = None
    mark: Text | None = None
    table: Text | None = None
    raw: Text | None = None
    from_: Text | None = Field(default=None, alias='from')


class PbrRoute(PublicRecord):
    dst: Text | None = None
    via: Text | None = None
    dev: Text | None = None
    scope: Text | None = None
    raw: Text | None = None


class PbrMark(PublicRecord):
    chain: Text | None = None
    uid: Text | None = None
    mark: Text | None = None
    raw: Text | None = None


class PbrResult(ErrorResult):
    rules: list[PbrRule] | None = None
    tables: dict[str, list[PbrRoute]] | None = None
    marks: list[PbrMark] | None = None


class NetTaskEnvelope(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    node_id: int
    status: str
    created_at: datetime

    @field_validator('result_json', 'payload', mode='before', check_fields=False)
    @classmethod
    def project_slots(cls, value, info):
        return project_optional(cls.model_fields[info.field_name].annotation, value)


class IpChangeTask(NetTaskEnvelope):
    kind: Literal['ip_change']
    payload: IpChangePayload | None = None
    result_json: IpChangeResult | None = None


class FirewallTask(NetTaskEnvelope):
    kind: Literal['firewall_scan']
    payload: PublicRecord | None = None
    result_json: FirewallResult | None = None


class DockerScanTask(NetTaskEnvelope):
    kind: Literal['docker_scan']
    payload: PublicRecord | None = None
    result_json: DockerScanResult | None = None


class DockerCtlTask(NetTaskEnvelope):
    kind: Literal['docker_ctl']
    payload: DockerPayload | None = None
    result_json: DockerCtlResult | None = None


class DockerLogsTask(NetTaskEnvelope):
    kind: Literal['docker_logs']
    payload: DockerPayload | None = None
    result_json: DockerLogsResult | None = None


class DockerInspectTask(NetTaskEnvelope):
    kind: Literal['docker_inspect']
    payload: DockerPayload | None = None
    result_json: DockerInspectResult | None = None


class PbrTask(NetTaskEnvelope):
    kind: Literal['pbr_scan']
    payload: PublicRecord | None = None
    result_json: PbrResult | None = None


class LegacyNetResult(PublicRecord):
    raw_origin: Literal['legacy_unknown_net_task'] | None = None
    raw_payload: JsonValue = None


class UnknownNetTask(NetTaskEnvelope):
    kind: Literal['unknown']
    reported_kind: Text | None = None
    payload: None = None
    result_json: LegacyNetResult | None = None


NetTaskVariant = Annotated[IpChangeTask | FirewallTask | DockerScanTask | DockerCtlTask |
    DockerLogsTask | DockerInspectTask | PbrTask | UnknownNetTask, Field(discriminator='kind')]


class NetTaskRead(RootModel[NetTaskVariant]):
    """Existing envelope layout, discriminated by kind; no global result wrap."""
    @model_validator(mode='before')
    @classmethod
    def unknown_kind(cls, value):
        if isinstance(value, cls):
            return value.root
        kind = value.get('kind') if isinstance(value, dict) else getattr(value, 'kind', None)
        if kind in ('ip_change', 'firewall_scan', 'docker_scan', 'docker_ctl', 'docker_logs', 'docker_inspect', 'pbr_scan') or isinstance(value, UnknownNetTask):
            return value
        get = value.get if isinstance(value, dict) else lambda key: getattr(value, key, None)
        result = get('result_json')
        return {**{key: get(key) for key in ('id', 'node_id', 'status', 'created_at')},
                'kind': 'unknown', 'reported_kind': kind if isinstance(kind, str) else None,
                'result_json': None if result is None else {
                    'raw_origin': 'legacy_unknown_net_task', 'raw_payload': safe_legacy_json(result)}}


class MtrHop(PublicRecord):
    count: Integer | None = None
    host: Text | None = None
    name: Text | None = None
    snt: Integer | None = None
    loss_pct: Number | None = Field(default=None, alias='loss%')
    last: Number | None = None
    avg: Number | None = None
    best: Number | None = None
    wrst: Number | None = None
    stdev: Number | None = None
    legacy_loss_pct: Number | None = Field(default=None, alias='Loss%')
    Snt: Integer | None = None
    Last: Number | None = None
    Avg: Number | None = None
    Best: Number | None = None
    Wrst: Number | None = None
    StDev: Number | None = None


class MtrSpec(PublicRecord):
    dst: Text | None = None
    tos: Integer | None = None
    psize: Integer | None = None
    bitpattern: Integer | None = None
    tests: Integer | None = None


class MtrReportResult(PublicRecord):
    mtr: MtrSpec | None = None
    hubs: list[MtrHop] | None = None


class MtrResult(ErrorResult):
    report: MtrReportResult | None = None
    raw: Text | None = None
    hubs: list[MtrHop] | None = None


class MtrLive(PublicRecord):
    hops: list[MtrHop] | None = None


class IperfProgress(PublicRecord):
    ts: Text | None = None
    bitrate: Number | None = None
    role: Text | None = None
    note: Text | None = None
    lost_pct: Number | None = None
    jitter_ms: Number | None = None
    retry: Flag | None = None
    attempt: Integer | None = None
    reason: Text | None = None

    @model_validator(mode='before')
    @classmethod
    def preserve_index(cls, value):
        if not isinstance(value, (dict, cls)):
            return {'ts': None, 'bitrate': None, 'role': None}
        return value


class ToolResult(ErrorResult):
    raw_payload: JsonValue = Field(default=None,
        description='Original agent/tool JSON, finite JSON with private keys removed. Not normalized measurements; units and vendor extensions are retained. May include opaque tool text.')


class IperfResult(ToolResult):
    raw_origin: Literal['stella_iperf_summary', 'iperf_tool_json']
    role: Text | None = None
    avg_bitrate: Number | None = None
    peak_bitrate: Number | None = None
    send_avg_bitrate: Number | None = None
    total_bytes: Number | None = None
    lost_pct: Number | None = None
    jitter_ms: Number | None = None
    retransmits: Integer | None = None
    duration: Number | None = None
    parallel: Integer | None = None
    direction: Text | None = None
    udp: Flag | None = None
    suspicious: Flag | None = None
    # Existing UI reads these vendor paths; explicitly RAW compatibility slots,
    # not fabricated fixed iperf schemas. Full vendor output is in raw_payload.
    end: JsonValue = Field(default=None, description='RAW iperf tool end object; compatibility alias of raw_payload.end.')
    sum_sent: JsonValue = Field(default=None, description='RAW legacy iperf sum_sent; compatibility alias of raw_payload.sum_sent.')
    raw: Text | None = None


class SpeedtestResult(ToolResult):
    raw_origin: Literal['speedtest_tool_json']
    via_proxy: Flag | None = None
    suspicious: Flag | None = None
    raw: Text | None = None
    servers: JsonValue = Field(default=None, description='RAW speedtest-go servers, including nanosecond latency/jitter; compatibility alias of raw_payload.servers.')
    download: JsonValue = Field(default=None, description='RAW vendor download: CLI bits/sec scalar or Ookla bandwidth object (bytes/sec). No unit conversion; alias of raw_payload.download.')
    upload: JsonValue = Field(default=None, description='RAW vendor upload: CLI bits/sec scalar or Ookla bandwidth object (bytes/sec); alias of raw_payload.upload.')
    ping: JsonValue = Field(default=None, description='RAW vendor ping scalar/object, not normalized milliseconds; alias of raw_payload.ping.')
    server: JsonValue = Field(default=None, description='RAW vendor server metadata; compatibility alias of raw_payload.server.')


class LegacyIperfResult(ToolResult):
    raw_origin: Literal['legacy_unknown_task_mode']


class TaskErrorResult(ToolResult):
    raw_origin: Literal['task_error']
    role: Text | None = None


IperfPublicResult = Annotated[IperfResult | SpeedtestResult | LegacyIperfResult | TaskErrorResult,
                              Field(discriminator='raw_origin')]


def project_iperf_result(value, mode):
    if value is None:
        return None
    if isinstance(value, (IperfResult, SpeedtestResult, LegacyIperfResult, TaskErrorResult)):
        return value
    raw = safe_legacy_json(value)
    fields = dict(raw) if isinstance(raw, dict) else {}
    if 'error' in fields:
        # Watchdog/server diagnostics and tool failures share this channel;
        # claiming that these came from a specific executable would be false.
        origin = 'task_error'
    elif mode == 'speedtest':
        origin = 'speedtest_tool_json'
    elif mode == 'iperf3':
        origin = 'stella_iperf_summary' if any(k in fields for k in ('avg_bitrate', 'peak_bitrate', 'send_avg_bitrate', 'role')) else 'iperf_tool_json'
    else:
        origin = 'legacy_unknown_task_mode'
    fields.update(raw_origin=origin, raw_payload=raw)
    return project_optional(IperfPublicResult, fields)


# Agent-only instruction channel: never apply public-result redaction here.
class AgentIperfInstruction(BaseModel):
    id: int
    mode: str
    server_host: str | None
    client_host: str | None
    same_host: bool
    role: Literal['server', 'client']
    direction: str
    duration: int
    bytes: str | None
    parallel: int
    udp: bool
    bitrate: str | None
    port: int
    window: str | None
    length: str | None
    omit: int
    zerocopy: bool
    speedtest_server: str | None


class AgentMtrInstruction(BaseModel):
    id: int
    target: str
    protocol: str
    params: dict[str, JsonValue] | None = Field(description='Executable MTR options, preserved verbatim, including extension options.')


class AgentCommandInstruction(BaseModel):
    id: int
    command: str


class AgentComponentInstruction(BaseModel):
    id: int
    component: str


class AgentNetInstruction(BaseModel):
    id: int
    kind: str
    payload: JsonValue = Field(description='Agent execution protocol JSON, NOT public telemetry. ip_change uses iface/new_ip/prefix/gateway/ping_target; docker actions use container/action/tail; scans may be null/empty. Future tool options and legacy JSON shapes pass unchanged.')


class AgentTasksRead(BaseModel):
    node_id: int
    uninstall: bool
    iperf_tasks: list[AgentIperfInstruction]
    mtr_tasks: list[AgentMtrInstruction]
    commands: list[AgentCommandInstruction]
    component_installs: list[AgentComponentInstruction]
    net_tasks: list[AgentNetInstruction]
