// 服务器监控模块 API 封装
import { api } from "./client";
import type {ControlChannel} from './nodeMonitoringPolicy';

// ── 类型 ──
export interface StorageItem {
  device: string;
  mount: string;
  fstype: string;
  total: number;
  used: number | null;
  percent: number | null;
  kind: "physical" | "network" | "virtual" | "volume";
  model?: string | null;
  bus?: string | null;
  volume_mounts?: string[];
  pool_mounts?: string[];
  usage_scope?: "measured" | "shared_pool" | "unmeasured";
  sampled_at?: string | null;
}

export interface StorageStatus {
  state: "collecting" | "available" | "query_failed";
  sampled_at: string | null;
  attempted_at?: string | null;
}

// 硬件快照复用 sys_info 随详情轮询返回；旧 Agent 可不提供 hardware。
export interface HardwareCpu {
  sampled_at?: string | null;
  model: string | null;
  physical_cores: number | null;
  logical_cores: number | null;
  frequency_mhz: number | null;
  max_frequency_mhz: number | null;
  base_frequency_mhz?: number | null;
  base_frequency_source?: string | null;
  temperature_c: number | null;
  temperature_source: string | null;
  frequency_source: string | null;
}
export interface HardwareGpu {
  id: string;
  name: string;
  vendor?: string | null;
  kind?: "integrated" | "discrete" | "unknown";
  telemetry_status?: "available" | "unsupported" | "driver_missing" | "query_failed";
  temperature_c: number | null;
  graphics_clock_mhz: number | null;
  memory_clock_mhz: number | null;
  utilization_pct: number | null;
  memory_used_mib: number | null;
  memory_total_mib: number | null;
  power_w: number | null;
  fan_pct: number | null;
  source: string;
}
export interface HardwareSensor {
  name: string;
  kind: "temperature" | "fan";
  value: number | null;
  unit: "°C" | "RPM";
  source: string;
  scope?: 'os_visible' | 'host_visible';
}
export interface HardwareMachine {
  kind: "physical" | "virtual" | "container" | "unknown";
  vendor: string | null;
  model: string | null;
  virtualization: string | null;
  evidence: string[];
  detected_at: string | null;
}
// Classification belongs to the Agent; names, OS and VBS flags are not evidence here.
export function machineTypeLabel(machine?: HardwareMachine | null): string {
  switch (machine?.kind) {
    case "physical": return "物理机";
    case "virtual": return "虚拟机";
    case "container": return "容器";
    default: return "未判定";
  }
}
export function machineTypeTitle(machine?: HardwareMachine | null): string {
  if (!machine) return "Agent 尚未上报机器类型";
  return [
    machine.kind === 'unknown' ? '机器类型证据不足' : null,
    `判断依据：${machine.evidence?.length ? machine.evidence.join("；") : "未提供"}`,
    machine.vendor, machine.model,
    machine.virtualization ? `虚拟化：${machine.virtualization}` : null,
    machine.detected_at ? `检测时间：${machine.detected_at}` : "检测时间未知",
  ].filter(Boolean).join(" · ");
}
export interface PhysicalInventory {
  board: { vendor: string | null; model: string | null } | null;
  bios: { vendor: string | null; version: string | null } | null;
  memory_modules: { slot: string | null; capacity_bytes: number | null; speed_mts: number | null;
    configured_speed_mts: number | null; vendor: string | null; part_number: string | null }[];
  disks: { name: string | null; model: string | null; size_bytes: number | null;
    bus: string | null; rotational: boolean | null }[];
}
export interface HardwareMemory {
  total_bytes: number | null;
  available_bytes: number | null;
  used_bytes: number | null;
  source: string | null;
  scope: 'os_visible' | 'host_visible' | 'cgroup' | 'unknown';
  state: 'available' | 'query_failed' | 'unlimited' | 'unknown';
  sampled_at: string | null;
  attempted_at?: string | null;
  cgroup?: HardwareMemory | null;
}
export interface PlatformInventory {
  board: PhysicalInventory['board'];
  bios: PhysicalInventory['bios'];
  source: string;
  scope: 'platform_reported' | 'host_visible';
  state: string;
  sampled_at: string | null;
}
export interface HardwareInfo {
  memory?: HardwareMemory | null;
  platform_inventory?: PlatformInventory | null;
  physical_inventory?: PhysicalInventory | null;
  machine?: HardwareMachine | null;
  sampled_at: string | null;
  sensors_sampled_at?: string | null;
  cpu: HardwareCpu;
  gpus: HardwareGpu[];
  sensors: HardwareSensor[];
  availability: { cpu_temperature: string; gpu: string; gpu_presence?: 'unknown' | 'none' | 'present'; gpu_query?: 'available' | 'query_failed' };
}

export interface Node {
  id: number;
  name: string;
  platform: string;
  host: string;
  arch: string | null;
  agent_version: string | null;
  last_seen_at: string | null;
  status: "pending" | "online" | "offline" | "removed";
  token: string | null;
  interfaces: Record<string, { is_default: boolean; up: boolean; is_physical?: boolean; docker?: boolean; ip?: string | null }> | null;
  monitored_ifaces: Record<string, unknown> | null;
  storage: StorageItem[] | null;
  components: { iperf3?: boolean | {installed: boolean; version?: string}; speedtest?: boolean | {installed: boolean; version?: string}; mtr?: boolean | {installed: boolean; version?: string}; docker?: boolean | {installed: boolean; version?: string}; monitoring?: {ready?:boolean|null;types?:('ping'|'tcp')[]|null;scope?:'host'|'container'|null;targets?:string[]|null;approved_ranges?:string[]|null}|null; firewall?: { ufw?: { installed: boolean; active?: boolean }; iptables?: { installed: boolean } } } | null;
  control_channel?: ControlChannel | null;
  net_type: string;
  public_ip: string | null;
  public_ip_source: string | null;
  ip_version: string | null;
  region: string | null;
  uninstall_status: string | null;
  uninstall_error: string | null;
  installed: boolean;
  os_name: string | null;
  sys_info: { kernel: string | null; cpu_model: string | null; cpu_cores: number | null; cpu_logical_cores?: number | null; storage_status?: StorageStatus | null; load1: number | null; load5: number | null; load15: number | null; boot_time: number | null; hardware?: HardwareInfo | null } | null;
  created_at: string;
}

export interface Monitor {
  visible?: boolean;
  enabled?: boolean;
  effective_enabled?: boolean;
  management?: 'entry_icmp' | null;
  status_reason?: 'healthy'|'failure'|'pending'|'source_pending'|'source_offline'|'dns_error'|'dns_timeout'|'outside_scope'|'too_many_ips'|'budget_exceeded'|'unavailable'|'restricted'|'stale'|'entry_removed'|'invalid_target'|'unsupported'|'scope_pending';
  id: number;
  name: string;
  node_id: number;
  type: "ping" | "tcp" | "udp" | "http" | "https";
  target: string;
  interval: number;
  timeout: number;
  status: "up" | "down";
  last_check_at: string | null;
  last_latency_ms: number | null;
}

export interface MonitorCheck {
  id: number;
  monitor_id: number;
  ts: string;
  success: boolean;
  latency_ms: number | null;
  loss_pct: number | null;
}

export interface IperfTask {
  id: number;
  server_node_id: number | null;
  client_node_id: number;
  mode: "iperf3" | "speedtest";
  direction: string;
  duration: number;
  bytes: string | null;
  parallel: number;
  udp: boolean;
  bitrate: string | null;
  port: number;
  window: string | null;
  length: string | null;
  omit: number;
  zerocopy: boolean;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  server_started: boolean;        // server 端已起 -s（阶段提示用）
  started_at: string | null;      // client 领取时刻
  // 结果摘要列（done 时后端落列；iperf=接收均值/峰值，speedtest=下载/上传）
  avg_mbps: number | null;
  peak_mbps: number | null;
  lost_pct: number | null;
  jitter_ms: number | null;
  speedtest_server: string | null;   // speedtest 测速服务器 ID
  result_json: Record<string, unknown> | null;
  progress_json: { ts: string; bitrate: number; lost_pct?: number; jitter_ms?: number; role?: string; retry?: boolean; attempt?: number; reason?: string; note?: string }[] | null;
  created_at: string;
}

// 两种键格式并存：旧数据是 mtr --json 原生大写键，agent 0.6.0 起是 --raw 聚合的小写键（多 snt/last/stdev）
export interface MtrHop {
  count: number; host: string;
  "Loss%"?: number; Snt?: number; Last?: number; Avg?: number; Best?: number; Wrst?: number; StDev?: number;
  "loss%"?: number; snt?: number; last?: number | null; avg?: number | null;
  best?: number | null; wrst?: number | null; stdev?: number | null;
}
// 终端式表格用的归一化跳结构
export interface MtrHopRow { hop: number; host: string; loss: number; snt: number | null;
  last: number | null; avg: number | null; best: number | null; wrst: number | null; stdev: number | null; }
export function mtrHopRows(hubs: MtrHop[] | undefined | null): MtrHopRow[] {
  return (hubs || []).map((h) => ({
    hop: h.count,
    host: h.host,
    loss: h["loss%"] ?? h["Loss%"] ?? 0,
    snt: h.snt ?? h.Snt ?? null,
    last: h.last ?? h.Last ?? null,
    avg: h.avg ?? h.Avg ?? null,
    best: h.best ?? h.Best ?? null,
    wrst: h.wrst ?? h.Wrst ?? null,
    stdev: h.stdev ?? h.StDev ?? null,
  }));
}
export interface MtrParams { count?: number; interval?: number; max_hops?: number; psize?: number }
export interface MtrTask {
  id: number;
  job_id?: string | null;
  node_id: number;
  monitor_id?: number | null;      // 非空=挂在监控项上的 MTR 历史
  target: string;
  protocol: string;
  trigger?: "manual" | "periodic" | "failure";
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  result_json: ({ report?: { hubs?: MtrHop[] }; error?: string; raw?: string } & Record<string, unknown>) | null;
  params_json?: MtrParams | null;
  live_json?: { hops?: MtrHop[] } | null;  // 跑的过程中 agent 每 ~2s 覆写的实时逐跳快照
  created_at: string;
}

export interface Command {
  id: number;
  node_id: number;
  command: string;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  stdout: string | null;
  stderr: string | null;
  exit_code: number | null;
  created_at: string;
}

// ── 节点 ──
export const listNodes = (signal?: AbortSignal) => api<Node[]>("/nodes/", { signal });
export const createNode = (data: { name: string; platform: string; host: string }) =>
  api<Node>("/nodes/", { method: "POST", body: JSON.stringify(data) });
export const removeNode = (id: number) => api<void>(`/nodes/${id}`, { method: "DELETE" });

// ── 节点详情 ──
export interface MetricPoint {
  iface: string;
  ts: string;
  rx_delta: number;
  tx_delta: number;
}
export interface SysMetricPoint {
  ts: string;
  cpu_pct: number | null;
  mem_pct: number | null;
  disk_pct: number | null;
}
export interface NodeDetail extends Node {
  latest_metrics: MetricPoint[];
  latest_sys_metric: SysMetricPoint | null;
}

export const getNodeDetail = (id: number, signal?: AbortSignal) => api<NodeDetail>(`/nodes/${id}`, { signal });
export const getNodeMetrics = (id: number, opts?: { iface?: string; start?: string; end?: string; limit?: number; step?: number; signal?: AbortSignal }) => {
  const q = new URLSearchParams();
  if (opts?.iface) q.set("iface", opts.iface);
  if (opts?.start) q.set("start", opts.start);
  if (opts?.end) q.set("end", opts.end);
  if (opts?.limit) q.set("limit", String(opts.limit));
  if (opts?.step) q.set("step", String(opts.step));
  return api<MetricPoint[]>(`/nodes/${id}/metrics?${q.toString()}`, { signal: opts?.signal });
};
export const getNodeSysMetrics = (id: number, opts?: { start?: string; end?: string; limit?: number; step?: number; signal?: AbortSignal }) => {
  const q = new URLSearchParams();
  if (opts?.start) q.set("start", opts.start);
  if (opts?.end) q.set("end", opts.end);
  if (opts?.limit) q.set("limit", String(opts.limit));
  if (opts?.step) q.set("step", String(opts.step));
  return api<SysMetricPoint[]>(`/nodes/${id}/sys-metrics?${q.toString()}`, { signal: opts?.signal });
};

export interface TrafficStats {
  rx_95: number;
  tx_95: number;
  rx_max: number;
  rx_min: number;
  tx_max: number;
  tx_min: number;
  rx_total: number;
  tx_total: number;
  sample_count: number;
}
export const getTrafficStats = (id: number, opts?: { ifaces?: string[]; start?: string; end?: string; signal?: AbortSignal }) => {
  const q = new URLSearchParams();
  if (opts?.ifaces?.length) opts.ifaces.forEach((i) => q.append("iface", i));
  if (opts?.start) q.set("start", opts.start);
  if (opts?.end) q.set("end", opts.end);
  return api<TrafficStats>(`/nodes/${id}/traffic-stats?${q.toString()}`, { signal: opts?.signal });
};

export const updateNodeIfaces = (id: number, monitored_ifaces: Record<string, unknown> | null) =>
  api<Node>(`/nodes/${id}`, { method: "PATCH", body: JSON.stringify({ monitored_ifaces }) });

export const updateNetType = (id: number, net_type: string, public_ip: string | null) =>
  api<Node>(`/nodes/${id}/net-type`, { method: "PATCH", body: JSON.stringify({ net_type, public_ip }) });

export const changeIp = (id: number, data: { iface: string; new_ip: string; prefix: number; gateway: string | null; ping_target: string }) =>
  api(`/nodes/${id}/ip-change`, { method: "POST", body: JSON.stringify(data) });

// ── 防火墙结构化扫描（一期：只读）──
export interface FwUfwRule { num: number; to: string; action: string; from: string; v6: boolean }
export interface FwIptChain { name: string; policy: string | null; packets: number; bytes: number }
export interface FwIptRule { raw: string; chain: string | null; target: string | null; proto: string | null; sport: string | null; dport: string | null; source: string | null; dest: string | null; in_iface: string | null; out_iface: string | null }
export interface FirewallData {
  ufw: { installed: boolean; active?: boolean; defaults?: string | null; logging?: string | null; rules?: FwUfwRule[]; raw?: string } | null;
  iptables: { installed: boolean; error?: string; tables?: Record<string, { chains: FwIptChain[]; rules: FwIptRule[] }>; raw?: string } | null;
}
export interface NetTask {
  id: number; node_id: number; kind: string;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  result_json: FirewallData | Record<string, unknown> | null;
  created_at: string;
}
export const scanFirewall = (id: number) => api<NetTask>(`/nodes/${id}/firewall-scan`, { method: "POST" });
export const getNetTask = (taskId: number, signal?: AbortSignal) => api<NetTask>(`/nodes/net-tasks/${taskId}`, { signal });

// ── Docker 面板 ──
export interface DockerContainer { id: string; name: string; image: string; status: string; state: string; ports: string; created: string }
export const scanDocker = (id: number) => api<NetTask>(`/nodes/${id}/docker-scan`, { method: "POST" });
export const ctlDocker = (id: number, action: "start" | "stop" | "restart", container: string) =>
  api<NetTask>(`/nodes/${id}/docker-ctl`, { method: "POST", body: JSON.stringify({ action, container }) });

// ── 监控项 ──
export const listMonitors = (signal?: AbortSignal) => api<Monitor[]>("/monitors/", { signal });
export const createMonitor = (data: { name: string; type: string; target: string; node_id: number; interval?: number; timeout?: number }) =>
  api<Monitor>("/monitors/", { method: "POST", body: JSON.stringify(data) });
export const updateMonitor = (id: number, data: Partial<{ name: string; type: string; target: string; node_id: number; interval: number; timeout: number; visible: boolean; enabled: boolean }>) =>
  api<Monitor>(`/monitors/${id}`, { method: "PATCH", body: JSON.stringify(data) });
export const removeMonitor = (id: number,admit:()=>boolean=()=>true) => {
  let sent=false;
  return api<void>(`/monitors/${id}`, { method: "DELETE" },()=>{if(sent||!admit())return false;sent=true;return true;});
};
// Explicit parent metadata is separate from child probe/history identity.
export interface MonitorGroup {
  visible?: boolean; enabled?: boolean; eligible_child_ids?: number[];
  id: number; name: string; child_ids: number[]; failure_policy: 'any' | 'all'; rotation_seconds: 0 | 8 | 15 | 30;
  status: 'up' | 'down' | null; down_count: number; unknown_count: number; up_count?: number;
  automatic?: boolean; source_node_id?: number | null;
  entry_id?: 'public' | 'private' | null; target_origin?: string | null; availability_reason?: 'entry_not_configured' | 'no_connected_nodes' | null;
}
export type MonitorGroupWrite = Pick<MonitorGroup, 'name' | 'failure_policy' | 'rotation_seconds'> & {child_ids?:number[];visible?:boolean;enabled?:boolean};
export const listMonitorGroups = (signal?: AbortSignal, includeEmpty=false) => api<MonitorGroup[]>(`/monitors/groups${includeEmpty?'?include_empty=true':''}`, {signal});
export const saveMonitorGroup = (id: number | null, data: MonitorGroupWrite) => api<MonitorGroup>(id===null ? '/monitors/groups' : `/monitors/groups/${id}`, {method:id===null?'POST':'PUT',body:JSON.stringify(data)});
export type NewMonitorDraft = Parameters<typeof createMonitor>[0];
export interface MonitorBatchReceipt {group_id:number|null;monitor_ids:number[]}
export const createMonitorBatch = (data:{items:NewMonitorDraft[];request_key:string;group_id:number|null;expected_group_uuid:string|null},admit:()=>boolean=()=>true) => {
  let sent=false;
  return api<MonitorBatchReceipt>('/monitors/batches',{method:'POST',body:JSON.stringify(data)},()=>{if(sent||!admit())return false;sent=true;return true;});
};
export const getMonitorBatchReceipt = (key:string) => api<MonitorBatchReceipt>(`/monitors/batches/receipts/${encodeURIComponent(key)}`);
export const createMonitorGroup = (data:{name:string;items:NewMonitorDraft[];request_key:string;failure_policy:'any'|'all';rotation_seconds:0|8|15|30},admit:()=>boolean=()=>true) => {
  let sent=false;
  return api<MonitorGroup>('/monitors/groups',{method:'POST',body:JSON.stringify(data)},()=>{if(sent||!admit())return false;sent=true;return true;});
};
export const getMonitorGroupReceipt = (key:string) => api<{group_id:number;monitor_ids:number[]}>(`/monitors/groups/receipts/${encodeURIComponent(key)}`);
export const dissolveMonitorGroup = (id: number) => api<void>(`/monitors/groups/${id}`, {method:'DELETE'});
export interface MonitorGroupDeletionState {stable_uuid:string|null;identity_matches:boolean|null;group_exists:boolean;name:string|null;children:Pick<Monitor,'id'|'name'|'type'|'target'>[];protected:boolean;remaining_child_ids:number[]}
export const getMonitorGroupDeletionState = (id:number, expectedChildIds:number[]=[], signal?:AbortSignal, expectedStableUuid?:string) => {
  const query=new URLSearchParams();for(const mid of expectedChildIds)query.append('expected_child_ids',String(mid));
  if(expectedStableUuid!==undefined)query.set('expected_stable_uuid',expectedStableUuid);
  return api<MonitorGroupDeletionState>(`/monitors/groups/${id}/deletion-state${query.size?'?'+query:''}`,{signal});
};
export const deleteMonitorGroup = (id:number, expectedChildIds:number[], expectedStableUuid:string) => {
  // api() may refresh authentication on 401; this destructive action must never
  // be fetched twice. Unknown outcomes are resolved by scoped GET, not replay.
  let sent=false;
  return api<void>(`/monitors/groups/${id}/delete`,{method:'POST',body:JSON.stringify({expected_child_ids:expectedChildIds,expected_stable_uuid:expectedStableUuid})},()=>{if(sent)return false;sent=true;return true;});
};
export const createMonitorGroupChild = (id: number, data: Parameters<typeof createMonitor>[0]) =>
  api<Monitor>(`/monitors/groups/${id}/children`, {method:'POST',body:JSON.stringify(data)});

export const listMonitorChecks = (id: number) => api<MonitorCheck[]>(`/monitors/${id}/checks`);

// 监控项的 MTR 历史（近 60 天）+ 手动触发
export const listMonitorMtr = (id: number, signal?: AbortSignal) => api<MtrTask[]>(`/monitors/${id}/mtr`, { signal });
export const runMonitorMtr = (id: number) => api<MtrTask>(`/monitors/${id}/mtr`, { method: "POST" });

// 延迟曲线点（范围/降采样）
export interface MonitorCheckPoint {
  sample_count?: number;
  success_count?: number;
  latency_count?: number;
  loss_count?: number;
  ts: string;
  success: boolean;
  latency_ms: number | null;
  loss_pct: number | null;
}
export const getMonitorSeries = (id: number, opts?: { start?: string; end?: string; step?: number; limit?: number; signal?: AbortSignal }) => {
  const q = new URLSearchParams();
  if (opts?.start) q.set("start", opts.start);
  if (opts?.end) q.set("end", opts.end);
  if (opts?.step) q.set("step", String(opts.step));
  if (opts?.limit) q.set("limit", String(opts.limit));
  const qs = q.toString();
  return api<MonitorCheckPoint[]>(`/monitors/${id}/series${qs ? "?" + qs : ""}`, { signal: opts?.signal });
};

// ── 任务 ──
export const listIperfTasks = (signal?: AbortSignal) => api<IperfTask[]>("/iperf-tasks", {signal});
// progressAfter=N：progress_json 只返回第 N 点之后的增量（append-only，下标稳定），实时轮询省流量
export const getIperfTask = (id: number, opts?: { progressAfter?: number; signal?: AbortSignal }) =>
  api<IperfTask>(`/iperf-tasks/${id}${opts?.progressAfter != null ? `?progress_after=${opts.progressAfter}` : ""}`, {signal: opts?.signal});
export const cancelIperfTask = (id: number) => api<{ ok: boolean }>(`/iperf-tasks/${id}/cancel`, { method: "POST" });
export const createIperfTask = (data: {
  server_node_id: number | null;
  client_node_id: number;
  mode?: string;
  direction?: string;
  duration?: number;
  bytes?: string | null;
  parallel?: number;
  udp?: boolean;
  bitrate?: string | null;
  port?: number;
  window?: string | null;
  length?: string | null;
  omit?: number;
  zerocopy?: boolean;
  speedtest_server?: string | null;
}) => api<IperfTask>("/iperf-tasks", { method: "POST", body: JSON.stringify(data) });

export const listMtrTasks = (signal?: AbortSignal) => api<MtrTask[]>("/mtr-tasks?trigger=manual", {signal});
export const getMtrTask = (id: number, signal?: AbortSignal) => api<MtrTask>(`/mtr-tasks/${id}`, {signal});
export const createMtrJob = (data: { node_ids: number[]; target: string; protocol: string; params?: MtrParams }) =>
  api<MtrTask[]>('/mtr-jobs', { method: 'POST', body: JSON.stringify(data) });
export const createMtrTask = (data: { node_id: number; target: string; protocol?: string; params?: MtrParams }) =>
  api<MtrTask>("/mtr-tasks", { method: "POST", body: JSON.stringify(data) });

export const listCommands = (signal?: AbortSignal) => api<Command[]>("/commands", { signal });
export const createCommand = (data: { node_id: number; command: string }) =>
  api<Command>("/commands", { method: "POST", body: JSON.stringify(data) });

// ── 组件代装 ──
export type CompName = "iperf3" | "speedtest" | "ufw" | "docker" | "mtr";
export interface ComponentTask {
  id: number;
  node_id: number;
  component: CompName;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  error: string | null;
  created_at: string;
}
export const listComponentInstalls = (signal?: AbortSignal) => api<ComponentTask[]>("/component-installs", { signal });
export const installComponent = (node_id: number, component: CompName) =>
  api<ComponentTask>("/component-installs", { method: "POST", body: JSON.stringify({ node_id, component }) });

// ── 扫描任务（防火墙/PBR/Docker）──
export const scanPbr = (nodeId: number) =>
  api<NetTask>(`/nodes/${nodeId}/pbr-scan`, { method: "POST" });
export const dockerLogs = (nodeId: number, container: string, tail = 150) =>
  api<NetTask>(`/nodes/${nodeId}/docker-logs`, { method: "POST", body: JSON.stringify({ container, tail }) });
export const dockerInspect = (nodeId: number, container: string) =>
  api<NetTask>(`/nodes/${nodeId}/docker-inspect`, { method: "POST", body: JSON.stringify({ container }) });
/** 某节点某类型最近一次完成的扫描（惰性缓存：页面打开先读快照，过期再自动重扫） */
export const latestNetTask = (nodeId: number, kind: string) =>
  api<NetTask | null>(`/nodes/${nodeId}/net-tasks/latest?kind=${encodeURIComponent(kind)}`);

// ── 宿主机 ──
export interface HostInfo {
  local_install_supported?: boolean;
  os: string;
  installed: boolean;
  node_id: number | null;
  installation_url?: string | null;
  installation_address_error?: string | null;
  installation?: { status: 'not_started' | 'queued' | 'installing' | 'installed' | 'failed' | 'interrupted' | 'manual_required' | 'address_required'; message: string; node_id?: number | null };
  node_status: string | null;
}
export interface InstallCommand { url: string; token: string; command: string }
export async function getInstallCommand(id: number, signal?: AbortSignal): Promise<InstallCommand> {
  const value = await api<InstallCommand>(`/nodes/${id}/install-command`, { method: 'POST', cache: 'no-store', signal });
  if (!value || typeof value.url !== 'string' || !/^https?:\/\//.test(value.url) ||
      typeof value.token !== 'string' || !value.token.trim() || ['undefined', 'null'].includes(value.token) ||
      typeof value.command !== 'string' || !value.command.trim()) {
    throw new Error('安装命令响应无效，请重新获取；不会拼接缺失凭证');
  }
  return value;
}
export const prepareHost = () => api<Node>('/nodes/host/prepare', { method: 'POST', cache: 'no-store' });
export const getHost = () => api<HostInfo>("/nodes/host");
export const installHost = () => api<Node>("/nodes/host/install", { method: "POST" });
export const requestUninstall = (id: number) => api<Node>(`/nodes/${id}/uninstall`, { method: "POST" });

// ── 全局配置 ──
export const getPublicHost = () => api<{ value: string }>("/config/public-host");
export const setPublicHost = (value: string) =>
  api<{ ok: boolean; value: string }>("/config/public-host", { method: "PUT", body: JSON.stringify({ value }) });
