// 服务器监控模块 API 封装
import { api } from "./client";

// ── 类型 ──
export interface StorageItem {
  device: string;
  mount: string;
  fstype: string;
  total: number;
  used: number;
  percent: number;
  kind: "physical" | "network" | "virtual";
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
  components: { iperf3: boolean; speedtest: boolean; firewall?: { ufw?: { installed: boolean; active?: boolean }; iptables?: { installed: boolean } } } | null;
  net_type: string;
  public_ip: string | null;
  public_ip_source: string | null;
  ip_version: string | null;
  region: string | null;
  uninstall_status: string | null;
  uninstall_error: string | null;
  installed: boolean;
  os_name: string | null;
  sys_info: { kernel: string | null; cpu_model: string | null; cpu_cores: number | null; load1: number | null; load5: number | null; load15: number | null; boot_time: number | null } | null;
  created_at: string;
}

export interface Monitor {
  id: number;
  name: string;
  node_id: number;
  type: "ping" | "tcp" | "udp" | "http" | "https";
  target: string;
  interval: number;
  timeout: number;
  status: "up" | "down" | "unknown";
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
  status: "pending" | "running" | "done" | "failed";
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
  node_id: number;
  monitor_id?: number | null;      // 非空=挂在监控项上的 MTR 历史
  target: string;
  protocol: string;
  trigger?: "manual" | "periodic" | "failure";
  status: "pending" | "running" | "done" | "failed";
  result_json: ({ report?: { hubs?: MtrHop[] }; error?: string; raw?: string } & Record<string, unknown>) | null;
  params_json?: MtrParams | null;
  live_json?: { hops?: MtrHop[] } | null;  // 跑的过程中 agent 每 ~2s 覆写的实时逐跳快照
  created_at: string;
}

export interface Command {
  id: number;
  node_id: number;
  command: string;
  status: "pending" | "running" | "done" | "failed";
  stdout: string | null;
  stderr: string | null;
  exit_code: number | null;
  created_at: string;
}

// ── 节点 ──
export const listNodes = () => api<Node[]>("/nodes/");
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

export const getNodeDetail = (id: number) => api<NodeDetail>(`/nodes/${id}`);
export const getNodeMetrics = (id: number, opts?: { iface?: string; start?: string; end?: string; limit?: number; step?: number }) => {
  const q = new URLSearchParams();
  if (opts?.iface) q.set("iface", opts.iface);
  if (opts?.start) q.set("start", opts.start);
  if (opts?.end) q.set("end", opts.end);
  if (opts?.limit) q.set("limit", String(opts.limit));
  if (opts?.step) q.set("step", String(opts.step));
  return api<MetricPoint[]>(`/nodes/${id}/metrics?${q.toString()}`);
};
export const getNodeSysMetrics = (id: number, opts?: { start?: string; end?: string; limit?: number; step?: number }) => {
  const q = new URLSearchParams();
  if (opts?.start) q.set("start", opts.start);
  if (opts?.end) q.set("end", opts.end);
  if (opts?.limit) q.set("limit", String(opts.limit));
  if (opts?.step) q.set("step", String(opts.step));
  return api<SysMetricPoint[]>(`/nodes/${id}/sys-metrics?${q.toString()}`);
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
export const getTrafficStats = (id: number, opts?: { ifaces?: string[]; start?: string; end?: string }) => {
  const q = new URLSearchParams();
  if (opts?.ifaces?.length) opts.ifaces.forEach((i) => q.append("iface", i));
  if (opts?.start) q.set("start", opts.start);
  if (opts?.end) q.set("end", opts.end);
  return api<TrafficStats>(`/nodes/${id}/traffic-stats?${q.toString()}`);
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
  status: "pending" | "running" | "done" | "failed";
  result_json: FirewallData | Record<string, unknown> | null;
  created_at: string;
}
export const scanFirewall = (id: number) => api<NetTask>(`/nodes/${id}/firewall-scan`, { method: "POST" });
export const getNetTask = (taskId: number) => api<NetTask>(`/nodes/net-tasks/${taskId}`);

// ── Docker 面板 ──
export interface DockerContainer { id: string; name: string; image: string; status: string; state: string; ports: string; created: string }
export const scanDocker = (id: number) => api<NetTask>(`/nodes/${id}/docker-scan`, { method: "POST" });
export const ctlDocker = (id: number, action: "start" | "stop" | "restart", container: string) =>
  api<NetTask>(`/nodes/${id}/docker-ctl`, { method: "POST", body: JSON.stringify({ action, container }) });

// ── 监控项 ──
export const listMonitors = () => api<Monitor[]>("/monitors/");
export const createMonitor = (data: { name: string; type: string; target: string; node_id: number; interval?: number; timeout?: number }) =>
  api<Monitor>("/monitors/", { method: "POST", body: JSON.stringify(data) });
export const updateMonitor = (id: number, data: Partial<{ name: string; type: string; target: string; node_id: number; interval: number; timeout: number }>) =>
  api<Monitor>(`/monitors/${id}`, { method: "PATCH", body: JSON.stringify(data) });
export const removeMonitor = (id: number) => api<void>(`/monitors/${id}`, { method: "DELETE" });
export const listMonitorChecks = (id: number) => api<MonitorCheck[]>(`/monitors/${id}/checks`);

// 监控项的 MTR 历史（近 60 天）+ 手动触发
export const listMonitorMtr = (id: number) => api<MtrTask[]>(`/monitors/${id}/mtr`);
export const runMonitorMtr = (id: number) => api<MtrTask>(`/monitors/${id}/mtr`, { method: "POST" });

// 延迟曲线点（范围/降采样）
export interface MonitorCheckPoint {
  ts: string;
  success: boolean;
  latency_ms: number | null;
  loss_pct: number | null;
}
export const getMonitorSeries = (id: number, opts?: { start?: string; end?: string; step?: number; limit?: number }) => {
  const q = new URLSearchParams();
  if (opts?.start) q.set("start", opts.start);
  if (opts?.end) q.set("end", opts.end);
  if (opts?.step) q.set("step", String(opts.step));
  if (opts?.limit) q.set("limit", String(opts.limit));
  const qs = q.toString();
  return api<MonitorCheckPoint[]>(`/monitors/${id}/series${qs ? "?" + qs : ""}`);
};

// ── 任务 ──
export const listIperfTasks = () => api<IperfTask[]>("/iperf-tasks");
// progressAfter=N：progress_json 只返回第 N 点之后的增量（append-only，下标稳定），实时轮询省流量
export const getIperfTask = (id: number, opts?: { progressAfter?: number }) =>
  api<IperfTask>(`/iperf-tasks/${id}${opts?.progressAfter != null ? `?progress_after=${opts.progressAfter}` : ""}`);
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

export const listMtrTasks = () => api<MtrTask[]>("/mtr-tasks");
export const createMtrTask = (data: { node_id: number; target: string; protocol?: string; params?: MtrParams }) =>
  api<MtrTask>("/mtr-tasks", { method: "POST", body: JSON.stringify(data) });

export const listCommands = () => api<Command[]>("/commands");
export const createCommand = (data: { node_id: number; command: string }) =>
  api<Command>("/commands", { method: "POST", body: JSON.stringify(data) });

// ── 组件代装 ──
export interface ComponentTask {
  id: number;
  node_id: number;
  component: "iperf3" | "speedtest";
  status: "pending" | "running" | "done" | "failed";
  error: string | null;
  created_at: string;
}
export const listComponentInstalls = () => api<ComponentTask[]>("/component-installs");
export const installComponent = (node_id: number, component: "iperf3" | "speedtest") =>
  api<ComponentTask>("/component-installs", { method: "POST", body: JSON.stringify({ node_id, component }) });

// ── 宿主机 ──
export interface HostInfo {
  os: string;
  installed: boolean;
  node_id: number | null;
  node_status: string | null;
}
export const getHost = () => api<HostInfo>("/nodes/host");
export const installHost = () => api<Node>("/nodes/host/install", { method: "POST" });
export const requestUninstall = (id: number) => api<Node>(`/nodes/${id}/uninstall`, { method: "POST" });

// ── 全局配置 ──
export const getPublicHost = () => api<{ value: string }>("/config/public-host");
export const setPublicHost = (value: string) =>
  api<{ ok: boolean; value: string }>("/config/public-host", { method: "PUT", body: JSON.stringify({ value }) });
