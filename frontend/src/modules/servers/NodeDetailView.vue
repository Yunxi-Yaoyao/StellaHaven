<script setup lang="ts">
// 节点详情页：基本信息 + 流量图（时间范围/时区/网卡多选/单位/统计卡）+ 系统指标 + 监控项
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import * as echarts from "echarts";
import Icon from "../../shell/Icon.vue";
import {
  getNodeDetail, getNodeMetrics, getNodeSysMetrics, getTrafficStats, updateNodeIfaces, updateNetType, changeIp,
  listMonitors, createMonitor, removeMonitor, createCommand, listCommands,
  type NodeDetail, type Monitor, type TrafficStats,
} from "../../api/servers";
import { toast } from "../../composables/useToast";
import Dropdown from "../../shell/Dropdown.vue";

// 由父组件（ServersPage）传入当前查看的节点 id；返回时 emit back（URL 不变，刷新回列表）
const props = defineProps<{ nodeId: number }>();
const emit = defineEmits<{ back: [] }>();
const nodeId = computed(() => props.nodeId);

const detail = ref<NodeDetail | null>(null);
const monitors = ref<Monitor[]>([]);

// ── 详情页标签页：概览 / 网络（标记+IP+防火墙）/ 服务监控 ──
const activeTab = ref<"overview" | "network" | "services">("overview");

// ── 网络标记（内网/公网）──
const netType = ref<"internal" | "public">("internal");
const publicIpInput = ref("");
const netTypeOptions = [
  { value: "internal", label: "内网" },
  { value: "public", label: "公网" },
];

// ── 网卡列表（默认隐藏 docker/容器网卡）──
const showDocker = ref(false);
type IfaceItem = { name: string; is_default: boolean; up: boolean; is_physical?: boolean; docker?: boolean; ip?: string | null };
const filteredIfaces = computed<IfaceItem[]>(() => {
  const ifs = detail.value?.interfaces || {};
  return Object.entries(ifs)
    .filter(([, meta]) => showDocker.value || !(meta as IfaceItem).docker)
    .map(([name, meta]) => {
      const m = meta as IfaceItem;
      return { name, is_default: m.is_default, up: m.up, is_physical: m.is_physical, docker: m.docker, ip: m.ip };
    });
});

// ── 防火墙检测状态 ──
const fw = computed(() => detail.value?.components?.firewall || {});

// ── 防火墙 / PBR 只读查看（复用 command 任务：下发 → 轮询拿 stdout）──
const fwOutput = ref("");
const fwLoading = ref(false);
const pbrOutput = ref("");
const pbrLoading = ref(false);

async function runNodeCommand(cmd: string): Promise<string> {
  const created = await createCommand({ node_id: nodeId.value, command: cmd });
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    try {
      const cmds = await listCommands();
      const c = cmds.find((x) => x.id === created.id);
      if (c && c.status !== "pending" && c.status !== "running") {
        return c.stdout || c.stderr || "(无输出)";
      }
    } catch { /* 继续轮询 */ }
  }
  return "(查询超时)";
}

async function viewFirewall() {
  fwLoading.value = true;
  fwOutput.value = "";
  try {
    fwOutput.value = await runNodeCommand(
      "sudo ufw status verbose 2>&1; echo '=== iptables ==='; sudo iptables-save 2>&1 | head -120"
    );
  } catch { fwOutput.value = "查看失败"; }
  fwLoading.value = false;
}

async function viewPbr() {
  pbrLoading.value = true;
  pbrOutput.value = "";
  try {
    pbrOutput.value = await runNodeCommand(
      "ip rule show; echo '=== rt_tables ==='; cat /etc/iproute2/rt_tables 2>/dev/null; echo '=== route table all ==='; ip route show table all 2>&1 | head -120"
    );
  } catch { pbrOutput.value = "查看失败"; }
  pbrLoading.value = false;
}

// ── 改 IP（高危：红色警告条 + 二次确认 + ping 回退）──
const ipFormOpen = ref(false);
const ipIface = ref("");
const ipNewIp = ref("");
const ipPrefix = ref(24);
const ipGateway = ref("");
const ipPingTarget = ref("");
const ipConfirmOpen = ref(false);

function openIpForm(iface: string) {
  ipIface.value = iface;
  ipNewIp.value = "";
  ipGateway.value = "";
  ipPingTarget.value = "";
  ipConfirmOpen.value = false;
  ipFormOpen.value = true;
}

async function submitIpChange() {
  try {
    await changeIp(nodeId.value, {
      iface: ipIface.value,
      new_ip: ipNewIp.value.trim(),
      prefix: ipPrefix.value,
      gateway: ipGateway.value.trim() || null,
      ping_target: ipPingTarget.value.trim(),
    });
    toast("改 IP 任务已下发喵~");
    ipFormOpen.value = false;
    ipConfirmOpen.value = false;
  } catch { toast("下发失败"); }
}

// ── 防火墙修改（高危：双入口表单/原文 + 红色警告条 + 二次确认 + 持久化）──
const fwModOpen = ref(false);
const fwMode = ref<"form" | "raw">("form");
const fwTool = ref<"ufw" | "iptables">("ufw");
const fwAction = ref<"allow" | "deny">("allow");
const fwPort = ref("");
const fwProto = ref<"tcp" | "udp" | "all">("tcp");
const fwRawCmd = ref("");
const fwConfirmOpen = ref(false);

function buildFwCmd(): string {
  if (fwMode.value === "raw") return fwRawCmd.value.trim();
  if (fwTool.value === "ufw") {
    const proto = fwProto.value === "all" ? "" : `/${fwProto.value}`;
    const portPart = fwPort.value.trim() ? `${fwPort.value.trim()}${proto}` : "";
    if (!portPart) return "";
    const action = fwAction.value === "allow" ? "allow" : "deny";
    return `sudo ufw ${action} ${portPart}`;
  }
  // iptables（改后持久化）
  const j = fwAction.value === "allow" ? "ACCEPT" : "DROP";
  const protoArg = fwProto.value === "all" ? "" : `-p ${fwProto.value}`;
  const dportArg = fwPort.value.trim() ? `--dport ${fwPort.value.trim()}` : "";
  return `sudo iptables -A INPUT ${protoArg} ${dportArg} -j ${j} && sudo iptables-save > /etc/iptables/rules.v4`
    .replace(/\s+/g, " ").trim();
}

async function submitFwChange() {
  const cmd = buildFwCmd();
  if (!cmd) { toast("请填写完整喵~"); return; }
  try {
    await createCommand({ node_id: nodeId.value, command: cmd });
    toast("防火墙规则已下发喵~");
    fwModOpen.value = false;
    fwConfirmOpen.value = false;
  } catch { toast("下发失败"); }
}

async function saveNetType() {
  try {
    const pubIp = netType.value === "public" ? (publicIpInput.value.trim() || null) : null;
    const updated = await updateNetType(nodeId.value, netType.value, pubIp);
    // 只更新标记相关字段，不动 latest_metrics/latest_sys_metric
    if (detail.value) {
      detail.value.net_type = updated.net_type;
      detail.value.public_ip = updated.public_ip;
      detail.value.public_ip_source = updated.public_ip_source;
      detail.value.ip_version = updated.ip_version;
      detail.value.region = updated.region;
    }
    toast(netType.value === "public" ? "已标记为公网服务器喵~" : "已标记为内网服务器喵~");
  } catch { toast("保存失败"); }
}

const statusLabel: Record<string, string> = { online: "在线", offline: "离线", pending: "待报到", removed: "已移除" };
const typeLabel: Record<string, string> = { ping: "PING", tcp: "TCP", udp: "UDP", http: "HTTP", https: "HTTPS" };

// ── 时间范围 ──
type RangeKey = "1h" | "6h" | "24h" | "7d" | "30d" | "thismonth" | "lastmonth" | "custom";
const PRESETS: { key: RangeKey; label: string; seconds?: number }[] = [
  { key: "1h", label: "1小时", seconds: 3600 },
  { key: "6h", label: "6小时", seconds: 21600 },
  { key: "24h", label: "24小时", seconds: 86400 },
  { key: "7d", label: "7天", seconds: 604800 },
  { key: "30d", label: "近30天", seconds: 2592000 },
  { key: "thismonth", label: "本月" },
  { key: "lastmonth", label: "上月" },
];
const timeRange = ref<RangeKey>("1h");
const presetOpen = ref(false);
const customEditOpen = ref(false);
const customStart = ref("");
const customEnd = ref("");
// 系统指标独立时间范围（60s 颗粒，默认 1h）
const sysTimeRange = ref<RangeKey>("1h");
const sysPresetOpen = ref(false);
const sysCustomEditOpen = ref(false);
const sysCustomStart = ref("");
const sysCustomEnd = ref("");
const sysTzOpen = ref(false);

// ── 时区（分钟偏移，默认 UTC+8）──
const TZ_OPTIONS = [
  { label: "UTC+8", offset: 480 },
  { label: "UTC+0", offset: 0 },
  { label: "UTC+1", offset: 60 },
  { label: "UTC+9", offset: 540 },
  { label: "UTC-5", offset: -300 },
  { label: "UTC-8", offset: -480 },
];
const tzOffset = ref(480);        // 流量图时区
const sysTzOffset = ref(480);     // 系统指标时区（独立于流量图）
const tzOpen = ref(false);
function nowInTz(off: number = tzOffset.value) { return new Date(Date.now() + off * 60000); }
// 目标时区「本月第一天 00:00:00」对应的 UTC 时间戳
function monthStart(off: number = tzOffset.value): number {
  const t = nowInTz(off);
  return Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), 1) - off * 60000;
}
function prevMonthStart(off: number = tzOffset.value): number {
  const t = nowInTz(off);
  return Date.UTC(t.getUTCFullYear(), t.getUTCMonth() - 1, 1) - off * 60000;
}

// ── 单位 ──
const UNITS = [
  { key: "auto", label: "自动" },
  { key: "bps", label: "bps" },
  { key: "kbps", label: "Kbps" },
  { key: "mbps", label: "Mbps" },
  { key: "gbps", label: "Gbps" },
  { key: "bs", label: "B/s" },
  { key: "kbs", label: "KB/s" },
  { key: "mbs", label: "MB/s" },
  { key: "gbs", label: "GB/s" },
];
const unitMode = ref<"auto" | "bps" | "kbps" | "mbps" | "gbps" | "bs" | "kbs" | "mbs" | "gbs">("auto");
const unitOpen = ref(false);

// ── 网卡 ──
const selectedIfaces = ref<string[]>([]);
const ifaceDropdownOpen = ref(false);

const trafficStats = ref<TrafficStats | null>(null);

const trafficEl = ref<HTMLElement | null>(null);
const sysEl = ref<HTMLElement | null>(null);
let trafficChart: echarts.ECharts | null = null;
let sysChart: echarts.ECharts | null = null;

function monitoredIfaces(d: NodeDetail): string[] {
  if (d.monitored_ifaces && Object.keys(d.monitored_ifaces).length) return Object.keys(d.monitored_ifaces);
  if (d.interfaces) {
    for (const [name, meta] of Object.entries(d.interfaces)) if (meta.is_default) return [name];
    const first = Object.keys(d.interfaces);
    if (first.length) return [first[0]];
  }
  return [];
}

// 通用：算某个时间范围的起止（毫秒时间戳），off 为时区分钟偏移（影响自然月边界）
function computeSpan(tr: RangeKey, cStart: string, cEnd: string, off: number = tzOffset.value): { startMs: number; endMs: number } {
  const now = Date.now();
  if (tr === "custom") {
    return { startMs: new Date(cStart).getTime(), endMs: new Date(cEnd).getTime() };
  }
  if (tr === "thismonth") return { startMs: monthStart(off), endMs: now };
  if (tr === "lastmonth") return { startMs: prevMonthStart(off), endMs: monthStart(off) };
  const r = PRESETS.find((p) => p.key === tr) || PRESETS[0];
  return { startMs: now - (r.seconds || 3600) * 1000, endMs: now };
}
const span = computed(() => computeSpan(timeRange.value, customStart.value, customEnd.value, tzOffset.value));
const sysSpan = computed(() => computeSpan(sysTimeRange.value, sysCustomStart.value, sysCustomEnd.value, sysTzOffset.value));

// 查询参数：start/end（ISO）+ limit/step（按跨度自动降采样）
function getRange(): { start: string; end: string; limit: number; step?: number } {
  const s = span.value;
  const seconds = (s.endMs - s.startMs) / 1000;
  let limit = 720, step: number | undefined;
  if (seconds > 86400 * 7) { step = 900; limit = 3000; }
  else if (seconds > 86400) { step = 300; limit = 2016; }
  else if (seconds > 21600) { step = undefined; limit = 17280; }
  else if (seconds > 3600) { step = undefined; limit = 4320; }
  else { step = undefined; limit = 720; }
  return { start: new Date(s.startMs).toISOString(), end: new Date(s.endMs).toISOString(), limit, step };
}
// 系统指标查询参数（60s 颗粒，降采样阈值不同）
function getSysRange(): { start: string; end: string; limit: number; step?: number } {
  const s = sysSpan.value;
  const seconds = (s.endMs - s.startMs) / 1000;
  let limit = 1440, step: number | undefined;
  if (seconds > 86400 * 7) { step = 900; limit = 3000; }
  else if (seconds > 86400) { step = 300; limit = 2016; }
  else if (seconds > 21600) { step = undefined; limit = 1500; }  // 24h
  else if (seconds > 3600) { step = undefined; limit = 400; }   // 6h
  else { step = undefined; limit = 70; }                          // 1h
  return { start: new Date(s.startMs).toISOString(), end: new Date(s.endMs).toISOString(), limit, step };
}
function windowSeconds() { return getRange().step || 5; }

// 按钮文本：选预设显示预设名，手动改过就变「自定义」
const rangeLabel = computed(() => {
  if (timeRange.value === "custom") return "自定义";
  return PRESETS.find((p) => p.key === timeRange.value)?.label || "1小时";
});
const sysRangeLabel = computed(() => {
  if (sysTimeRange.value === "custom") return "自定义";
  return PRESETS.find((p) => p.key === sysTimeRange.value)?.label || "1小时";
});

// 目标时区下的墙上时间：YYYY/MM/DD-HH:MM:SS
function fmtTime(ms: number, off: number = tzOffset.value): string {
  const d = new Date(ms + off * 60000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}/${p(d.getUTCMonth() + 1)}/${p(d.getUTCDate())}-${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}
// 图表 x 轴短格式（目标时区）：MM/DD HH:MM
function fmtAxisTime(ms: number, off: number = tzOffset.value): string {
  const d = new Date(ms + off * 60000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getUTCMonth() + 1)}/${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}
// datetime-local 值（浏览器本地时区）
function toLocalInput(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

// 网卡排序：默认出口 > 物理 > 虚拟
function sortedIfaces(): Array<[string, { is_default: boolean; is_physical?: boolean; ip?: string | null; up: boolean }]> {
  if (!detail.value?.interfaces) return [];
  const entries = Object.entries(detail.value.interfaces) as any[];
  entries.sort((a, b) => {
    const score = (m: any) => (m.is_default ? 0 : m.is_physical ? 1 : 2);
    const sa = score(a[1]); const sb = score(b[1]);
    if (sa !== sb) return sa - sb;
    return String(a[0]).localeCompare(String(b[0]));
  });
  return entries;
}

// ── 单位格式化 ──
function rateValue(delta: number): { value: number; suffix: string } {
  const bytesPerSec = delta / windowSeconds();
  const bitsPerSec = bytesPerSec * 8;
  if (unitMode.value === "auto") {
    if (bitsPerSec >= 1e9) return { value: bitsPerSec / 1e9, suffix: "Gbps" };
    if (bitsPerSec >= 1e6) return { value: bitsPerSec / 1e6, suffix: "Mbps" };
    if (bitsPerSec >= 1e3) return { value: bitsPerSec / 1e3, suffix: "Kbps" };
    return { value: bitsPerSec, suffix: "bps" };
  }
  const map: Record<string, { value: number; suffix: string }> = {
    bps: { value: bitsPerSec, suffix: "bps" },
    kbps: { value: bitsPerSec / 1e3, suffix: "Kbps" },
    mbps: { value: bitsPerSec / 1e6, suffix: "Mbps" },
    gbps: { value: bitsPerSec / 1e9, suffix: "Gbps" },
    bs: { value: bytesPerSec, suffix: "B/s" },
    kbs: { value: bytesPerSec / 1e3, suffix: "KB/s" },
    mbs: { value: bytesPerSec / 1e6, suffix: "MB/s" },
    gbs: { value: bytesPerSec / 1e9, suffix: "GB/s" },
  };
  return map[unitMode.value] || { value: bitsPerSec / 1e6, suffix: "Mbps" };
}
function fmtRate(delta: number): string {
  const r = rateValue(delta);
  const v = r.value;
  return (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2)) + " " + r.suffix;
}
function fmtBytes(bytes: number): string {
  if (unitMode.value === "auto") {
    if (bytes >= 1e12) return (bytes / 1e12).toFixed(2) + " TB";
    if (bytes >= 1e9) return (bytes / 1e9).toFixed(2) + " GB";
    if (bytes >= 1e6) return (bytes / 1e6).toFixed(2) + " MB";
    if (bytes >= 1e3) return (bytes / 1e3).toFixed(1) + " KB";
    return bytes.toFixed(0) + " B";
  }
  const byteMap: Record<string, [number, string]> = {
    bps: [1, "B"], kbps: [1e3, "KB"], mbps: [1e6, "MB"], gbps: [1e9, "GB"],
    bs: [1, "B"], kbs: [1e3, "KB"], mbs: [1e6, "MB"], gbs: [1e9, "GB"],
  };
  const [div, suffix] = byteMap[unitMode.value] || [1e6, "MB"];
  return (bytes / div).toFixed(2) + " " + suffix;
}
function chartUnit(): string {
  if (unitMode.value === "auto") return "Mbps";
  return UNITS.find((u) => u.key === unitMode.value)?.label || "Mbps";
}
// 图表数据专用：固定量级缩放（auto 固定 Mbps，手动跟随所选单位），
// 与 y 轴标签一致。统计卡文字用 rateValue（auto 自适应），图表不能自适应，否则数值和轴单位错位。
function chartRate(delta: number): number {
  const bytesPerSec = delta / windowSeconds();
  const bitsPerSec = bytesPerSec * 8;
  const map: Record<string, number> = {
    bps: bitsPerSec,
    kbps: bitsPerSec / 1e3,
    mbps: bitsPerSec / 1e6,
    gbps: bitsPerSec / 1e9,
    bs: bytesPerSec,
    kbs: bytesPerSec / 1e3,
    mbs: bytesPerSec / 1e6,
    gbs: bytesPerSec / 1e9,
  };
  if (unitMode.value === "auto") return bitsPerSec / 1e6;  // 固定 Mbps
  return map[unitMode.value] ?? bitsPerSec / 1e6;
}
// tooltip 数值精简格式化（按量级保留合理小数位）
function fmtVal(v: number): string {
  const a = Math.abs(v);
  if (a >= 100) return v.toFixed(1);
  if (a >= 1) return v.toFixed(2);
  if (a >= 0.01) return v.toFixed(3);
  return v.toFixed(5);
}

async function load() {
  try {
    detail.value = await getNodeDetail(nodeId.value);
    netType.value = detail.value.net_type === "public" ? "public" : "internal";
    publicIpInput.value = detail.value.public_ip || "";
    monitors.value = (await listMonitors()).filter((m) => m.node_id === nodeId.value);
    const ifaces = monitoredIfaces(detail.value);
    if (!selectedIfaces.value.length) selectedIfaces.value = ifaces;
    await Promise.all([renderTraffic(), renderSys(), loadStats()]);
  } catch { /* 静默 */ }
}

const COLORS = ["#ff9ec7", "#7be39a", "#7bd0e3", "#f0c060", "#bf7aff", "#ff8f8f"];

// ── 存储视图 ──
function fmtSize(bytes: number): string {
  if (bytes >= 1e12) return (bytes / 1e12).toFixed(2) + " TB";
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + " GB";
  if (bytes >= 1e6) return (bytes / 1e6).toFixed(0) + " MB";
  return (bytes / 1e3).toFixed(0) + " KB";
}
const physicalDisks = computed(() => (detail.value?.storage || []).filter((s) => s.kind === "physical"));
const virtualDisks = computed(() => (detail.value?.storage || []).filter((s) => s.kind !== "physical"));
const RING_R = 42;
const RING_CIRC = 2 * Math.PI * RING_R;

let trafficRenderSeq = 0;  // 请求序号：丢弃乱序返回的旧渲染
async function renderTraffic() {
  if (!trafficEl.value) return;
  if (!trafficChart) trafficChart = echarts.init(trafficEl.value);
  const seq = ++trafficRenderSeq;
  const range = getRange();
  const series: any[] = [];
  let times: string[] = [];
  const ifaces = selectedIfaces.value.length ? selectedIfaces.value : monitoredIfaces(detail.value!);
  for (let i = 0; i < ifaces.length; i++) {
    const iface = ifaces[i];
    const data = await getNodeMetrics(nodeId.value, { iface, start: range.start, end: range.end, limit: range.limit, step: range.step });
    if (seq !== trafficRenderSeq) return;  // 已有更新请求，丢弃
    const points = [...data].reverse();
    if (!times.length) times = points.map((p) => fmtAxisTime(new Date(p.ts).getTime()));
    const color = COLORS[i % COLORS.length];
    series.push({
      name: `${iface} ↓`, type: "line", smooth: true, showSymbol: false,
      data: points.map((p) => chartRate(p.rx_delta)),
      lineStyle: { width: 1.5 }, itemStyle: { color }, areaStyle: { opacity: 0.08 },
    });
    series.push({
      name: `${iface} ↑`, type: "line", smooth: true, showSymbol: false,
      data: points.map((p) => chartRate(p.tx_delta)),
      lineStyle: { width: 1.5, type: "dashed" }, itemStyle: { color },
    });
  }
  if (seq !== trafficRenderSeq) return;  // 已有更新请求，丢弃本次渲染
  trafficChart.setOption({
    backgroundColor: "transparent",
    grid: { left: 52, right: 16, top: 34, bottom: 26 },
    tooltip: {
      trigger: "axis",
      formatter: (params: any) => {
        if (!params || !params.length) return "";
        const unit = chartUnit();
        let html = `${params[0].axisValue}<br/>`;
        for (const p of params) html += `${p.marker}${p.seriesName}：<b>${fmtVal(p.value)} ${unit}</b><br/>`;
        return html;
      },
    },
    legend: { type: "scroll", textStyle: { color: "#9aa0aa" }, top: 0 },
    xAxis: { type: "category", data: times, boundaryGap: false, axisLine: { lineStyle: { color: "#2a2d35" } }, axisLabel: { color: "#9aa0aa" } },
    yAxis: { type: "value", name: chartUnit(), axisLabel: { color: "#9aa0aa" }, splitLine: { lineStyle: { color: "#1f2229" } } },
    series,
  }, { notMerge: true });  // notMerge：取消勾选网卡时彻底清掉旧 series，否则残留
}

let statsSeq = 0;  // 请求序号：丢弃乱序返回的旧统计
async function loadStats() {
  const seq = ++statsSeq;
  const range = getRange();
  const ifaces = selectedIfaces.value.length ? selectedIfaces.value : monitoredIfaces(detail.value!);
  if (!ifaces.length) { trafficStats.value = null; return; }
  try {
    const s = await getTrafficStats(nodeId.value, { ifaces, start: range.start, end: range.end });
    if (seq !== statsSeq) return;  // 已有更新请求，丢弃本次旧结果
    trafficStats.value = s;
  } catch { if (seq === statsSeq) trafficStats.value = null; }
}

function applyCustom() {
  if (!customStart.value || !customEnd.value) { toast("请选择起止时间喵~"); return; }
  if (new Date(customEnd.value) <= new Date(customStart.value)) { toast("结束时间要晚于开始时间喵~"); return; }
  customEditOpen.value = false;
  renderTraffic();
  loadStats();
}
function openCustomEdit() {
  customStart.value = toLocalInput(span.value.startMs);
  customEnd.value = toLocalInput(span.value.endMs);
  customEditOpen.value = !customEditOpen.value;
}
function onCustomEdit() {
  timeRange.value = "custom";  // 手动改起止时间 → 按钮变「自定义」
}
function selectPreset(key: RangeKey) {
  timeRange.value = key;
  presetOpen.value = false;
  renderTraffic();
  loadStats();
}
// 系统指标时间范围操作
function sysApplyCustom() {
  if (!sysCustomStart.value || !sysCustomEnd.value) { toast("请选择起止时间喵~"); return; }
  if (new Date(sysCustomEnd.value) <= new Date(sysCustomStart.value)) { toast("结束时间要晚于开始时间喵~"); return; }
  sysCustomEditOpen.value = false;
  renderSys();
}
function sysOpenCustomEdit() {
  sysCustomStart.value = toLocalInput(sysSpan.value.startMs);
  sysCustomEnd.value = toLocalInput(sysSpan.value.endMs);
  sysCustomEditOpen.value = !sysCustomEditOpen.value;
}
function sysOnCustomEdit() {
  sysTimeRange.value = "custom";
}
function sysSelectPreset(key: RangeKey) {
  sysTimeRange.value = key;
  sysPresetOpen.value = false;
  renderSys();
}

let sysRenderSeq = 0;  // 请求序号：只让最新一次渲染 setOption，丢弃乱序返回的旧请求
async function renderSys() {
  if (!sysEl.value) return;
  if (!sysChart) sysChart = echarts.init(sysEl.value);
  const seq = ++sysRenderSeq;
  const range = getSysRange();
  const data = await getNodeSysMetrics(nodeId.value, { start: range.start, end: range.end, limit: range.limit, step: range.step });
  if (seq !== sysRenderSeq) return;  // 已有更新的请求，丢弃本次旧结果
  const points = [...data].reverse();
  const times = points.map((p) => fmtAxisTime(new Date(p.ts).getTime(), sysTzOffset.value));
  sysChart.setOption({
    backgroundColor: "transparent",
    grid: { left: 52, right: 16, top: 30, bottom: 26 },
    tooltip: {
      trigger: "axis",
      formatter: (params: any) => {
        if (!params || !params.length) return "";
        let html = `${params[0].axisValue}<br/>`;
        for (const p of params) html += `${p.marker}${p.seriesName}：<b>${fmtVal(p.value)} %</b><br/>`;
        return html;
      },
    },
    legend: { data: ["CPU", "内存", "磁盘"], textStyle: { color: "#9aa0aa" }, top: 0 },
    xAxis: { type: "category", data: times, boundaryGap: false, axisLine: { lineStyle: { color: "#2a2d35" } }, axisLabel: { color: "#9aa0aa" } },
    yAxis: { type: "value", name: "%", max: 100, axisLabel: { color: "#9aa0aa" }, splitLine: { lineStyle: { color: "#1f2229" } } },
    series: [
      { name: "CPU", type: "line", smooth: true, showSymbol: false, data: points.map((p) => p.cpu_pct), lineStyle: { width: 1.5 }, itemStyle: { color: "#ff9ec7" } },
      { name: "内存", type: "line", smooth: true, showSymbol: false, data: points.map((p) => p.mem_pct), lineStyle: { width: 1.5 }, itemStyle: { color: "#f0c060" } },
      { name: "磁盘", type: "line", smooth: true, showSymbol: false, data: points.map((p) => p.disk_pct), lineStyle: { width: 1.5 }, itemStyle: { color: "#7bd0e3" } },
    ],
  }, { notMerge: true });  // notMerge：切时间范围彻底替换 xAxis/series，否则 merge 模式数据不刷新
}

// ── 网卡选择（下拉多选，自动保存为监控网卡）──
function toggleIface(name: string) {
  const i = selectedIfaces.value.indexOf(name);
  if (i >= 0) selectedIfaces.value.splice(i, 1);
  else selectedIfaces.value.push(name);
  saveIfaces();
  renderTraffic();
  loadStats();
}
async function saveIfaces() {
  if (!detail.value) return;
  try {
    const sel = selectedIfaces.value;
    const selected = Object.fromEntries(sel.map((n) => [n, detail.value!.interfaces?.[n] || { is_default: false, up: true }]));
    await updateNodeIfaces(nodeId.value, Object.keys(selected).length ? selected : null);
  } catch { /* 静默 */ }
}
// 切换时间/单位/时区/网卡时刷新
watch(timeRange, () => { renderTraffic(); loadStats(); });
watch(unitMode, () => { renderTraffic(); loadStats(); });
watch(tzOffset, () => { renderTraffic(); loadStats(); });  // 流量图时区
watch(sysTimeRange, () => { renderSys(); });
watch(sysTzOffset, () => { renderSys(); });  // 系统指标时区（独立）

// ── 监控项 ──
const showAdd = ref(false);
const newMon = ref({ name: "", type: "tcp", target: "" });
async function addMonitor() {
  if (!newMon.value.name.trim() || !newMon.value.target.trim()) { toast("名称和目标都要填喵~"); return; }
  try {
    await createMonitor({ name: newMon.value.name.trim(), type: newMon.value.type, target: newMon.value.target.trim(), node_id: nodeId.value });
    showAdd.value = false;
    newMon.value = { name: "", type: "tcp", target: "" };
    monitors.value = (await listMonitors()).filter((m) => m.node_id === nodeId.value);
  } catch { toast("添加失败喵~"); }
}
async function delMonitor(id: number) {
  try {
    await removeMonitor(id);
    monitors.value = (await listMonitors()).filter((m) => m.node_id === nodeId.value);
  } catch { toast("删除失败喵~"); }
}

let timer: ReturnType<typeof setInterval> | null = null;
function onResize() { trafficChart?.resize(); sysChart?.resize(); }
function onDocClick() { ifaceDropdownOpen.value = false; presetOpen.value = false; unitOpen.value = false; tzOpen.value = false; sysPresetOpen.value = false; sysTzOpen.value = false; }

// 切换节点（props.nodeId 变化，组件复用 setup 不重跑）：重置状态并重新加载
watch(() => props.nodeId, (newId, oldId) => {
  if (!newId || newId === oldId) return;
  selectedIfaces.value = [];
  trafficStats.value = null;
  detail.value = null;
  load();
});

onMounted(() => {
  load();
  timer = setInterval(load, 5000);
  window.addEventListener("resize", onResize);
  document.addEventListener("click", onDocClick);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
  window.removeEventListener("resize", onResize);
  document.removeEventListener("click", onDocClick);
  trafficChart?.dispose();
  sysChart?.dispose();
});

function goBack() { emit("back"); }
</script>

<template>
  <div class="detail-body">
      <!-- 头部 -->
      <header class="d-head">
      <button class="back" @click="goBack"><Icon name="chevron-left" :size="16" /> 返回</button>
      <span class="name">{{ detail?.name || "…" }}</span>
      <span v-if="detail" class="badge" :class="detail.status">{{ statusLabel[detail.status] }}</span>
      <span class="meta">
        <span v-if="detail?.platform">{{ detail.platform }}</span>
        <span v-if="detail?.arch">{{ detail.arch }}</span>
        <span v-if="detail?.agent_version">agent v{{ detail.agent_version }}</span>
        <span v-if="detail?.last_seen_at">心跳 {{ new Date(detail.last_seen_at).toLocaleString("zh-CN") }}</span>
      </span>
    </header>

    <!-- 标签页导航 -->
    <nav class="d-tabs">
      <button class="d-tab" :class="{ active: activeTab === 'overview' }" @click="activeTab = 'overview'">概览</button>
      <button class="d-tab" :class="{ active: activeTab === 'network' }" @click="activeTab = 'network'">网络</button>
      <button class="d-tab" :class="{ active: activeTab === 'services' }" @click="activeTab = 'services'">服务监控</button>
    </nav>

    <!-- Tab 1 概览：基本信息 + 存储 + 流量 + 系统指标 -->
    <div v-show="activeTab === 'overview'" class="tab-body">

    <!-- 存储面板 -->
    <section class="panel">
      <div class="panel-head"><span class="ph-title">存储</span></div>
      <div v-if="!detail?.storage?.length" class="empty">该节点暂无存储数据</div>
      <template v-else>
        <div v-if="physicalDisks.length" class="disk-group">
          <div class="disk-group-title">物理磁盘</div>
          <div class="disk-row">
            <div v-for="s in physicalDisks" :key="s.mount" class="disk-item">
              <div class="disk-ring">
                <svg viewBox="0 0 100 100" class="ring-svg">
                  <circle cx="50" cy="50" :r="RING_R" class="ring-bg" />
                  <circle cx="50" cy="50" :r="RING_R" class="ring-fg" :class="[s.kind, { warn: s.percent > 80 }]"
                          :stroke-dasharray="`${RING_CIRC * s.percent / 100} ${RING_CIRC}`"
                          transform="rotate(-90 50 50)" />
                </svg>
                <div class="ring-pct">{{ Math.round(s.percent) }}%</div>
              </div>
              <div class="disk-meta">
                <div class="disk-mount">{{ s.mount }}</div>
                <div class="disk-size">{{ fmtSize(s.used) }} / {{ fmtSize(s.total) }}</div>
                <div v-if="s.fstype" class="disk-fs">{{ s.fstype }}</div>
              </div>
            </div>
          </div>
        </div>
        <div v-if="virtualDisks.length" class="disk-group">
          <div class="disk-group-title">网络 / 虚拟磁盘</div>
          <div class="disk-row">
            <div v-for="s in virtualDisks" :key="s.mount" class="disk-item">
              <div class="disk-ring">
                <svg viewBox="0 0 100 100" class="ring-svg">
                  <circle cx="50" cy="50" :r="RING_R" class="ring-bg" />
                  <circle cx="50" cy="50" :r="RING_R" class="ring-fg" :class="[s.kind, { warn: s.percent > 80 }]"
                          :stroke-dasharray="`${RING_CIRC * s.percent / 100} ${RING_CIRC}`"
                          transform="rotate(-90 50 50)" />
                </svg>
                <div class="ring-pct">{{ Math.round(s.percent) }}%</div>
              </div>
              <div class="disk-meta">
                <div class="disk-mount">{{ s.mount }}</div>
                <div class="disk-size">{{ fmtSize(s.used) }} / {{ fmtSize(s.total) }}</div>
                <div v-if="s.fstype" class="disk-fs">{{ s.fstype }}</div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </section>

    <!-- 流量面板 -->
    <section class="panel">
      <div class="panel-head">
        <span class="ph-title">流量</span>

        <!-- 时间范围：起止显示 + 预设按钮 -->
        <span class="tl-label">时间</span>
        <button class="range-btn" title="点击编辑起止时间" @click="openCustomEdit">
          {{ fmtTime(span.startMs) }} <span class="range-sep">~</span> {{ fmtTime(span.endMs) }}
        </button>
        <div class="pop-wrap">
          <button class="preset-btn" :class="{ active: timeRange !== '1h' }" @click.stop="presetOpen = !presetOpen">{{ rangeLabel }} ▾</button>
          <div v-if="presetOpen" class="pop-menu" @click.stop>
            <button v-for="p in PRESETS" :key="p.key" class="pop-item" :class="{ active: timeRange === p.key }" @click="selectPreset(p.key)">{{ p.label }}</button>
          </div>
        </div>

        <!-- 网卡下拉多选 -->
        <div class="pop-wrap">
          <button class="ctrl-btn" @click.stop="ifaceDropdownOpen = !ifaceDropdownOpen">
            网卡（{{ selectedIfaces.length }}）▾
          </button>
          <div v-if="ifaceDropdownOpen" class="pop-menu iface-menu" @click.stop>
            <label v-for="[name, m] in sortedIfaces()" :key="name" class="dropdown-item">
              <input type="checkbox" :checked="selectedIfaces.includes(name)" @change="toggleIface(name)" />
              <span class="di-name">{{ name }}</span>
              <span class="di-tag" :class="{ phys: m.is_physical }">{{ m.is_physical ? "物理" : "虚拟" }}</span>
              <span class="di-ip">{{ m.ip || "无IP" }}</span>
              <span v-if="m.is_default" class="di-tag def">默认出口</span>
            </label>
          </div>
        </div>

        <!-- 单位下拉 -->
        <div class="pop-wrap">
          <button class="ctrl-btn" @click.stop="unitOpen = !unitOpen">{{ UNITS.find((u) => u.key === unitMode)?.label || "自动" }} ▾</button>
          <div v-if="unitOpen" class="pop-menu unit-menu" @click.stop>
            <button v-for="u in UNITS" :key="u.key" class="pop-item" :class="{ active: unitMode === u.key }" @click="unitMode = u.key as any; unitOpen = false">{{ u.label }}</button>
          </div>
        </div>

        <!-- 时区下拉 -->
        <div class="pop-wrap">
          <button class="ctrl-btn" @click.stop="tzOpen = !tzOpen">{{ TZ_OPTIONS.find((t) => t.offset === tzOffset)?.label || "UTC+8" }} ▾</button>
          <div v-if="tzOpen" class="pop-menu tz-menu" @click.stop>
            <button v-for="t in TZ_OPTIONS" :key="t.offset" class="pop-item" :class="{ active: tzOffset === t.offset }" @click="tzOffset = t.offset; tzOpen = false">{{ t.label }}</button>
          </div>
        </div>
      </div>

      <!-- 自定义时间编辑 -->
      <div v-if="customEditOpen" class="custom-range">
        <input type="datetime-local" v-model="customStart" @change="onCustomEdit" />
        <span class="cr-sep">~</span>
        <input type="datetime-local" v-model="customEnd" @change="onCustomEdit" />
        <button class="ghost-btn" @click="applyCustom">确定</button>
      </div>

      <div ref="trafficEl" class="chart"></div>

      <!-- 统计卡：下行/上行/合计，放流量图下方 -->
      <div v-if="trafficStats" class="stats-bar">
        <div class="stat-row">
          <span class="stat-dir down">下行</span>
          <span class="stat-item">95值 <b>{{ fmtRate(trafficStats.rx_95) }}</b></span>
          <span class="stat-item">MAX <b>{{ fmtRate(trafficStats.rx_max) }}</b></span>
          <span class="stat-item">MIN <b>{{ fmtRate(trafficStats.rx_min) }}</b></span>
          <span class="stat-item">总流量 <b>{{ fmtBytes(trafficStats.rx_total) }}</b></span>
        </div>
        <div class="stat-row">
          <span class="stat-dir up">上行</span>
          <span class="stat-item">95值 <b>{{ fmtRate(trafficStats.tx_95) }}</b></span>
          <span class="stat-item">MAX <b>{{ fmtRate(trafficStats.tx_max) }}</b></span>
          <span class="stat-item">MIN <b>{{ fmtRate(trafficStats.tx_min) }}</b></span>
          <span class="stat-item">总流量 <b>{{ fmtBytes(trafficStats.tx_total) }}</b></span>
        </div>
        <div class="stat-row total">
          <span class="stat-dir">合计</span>
          <span class="stat-item">总流量 <b>{{ fmtBytes(trafficStats.rx_total + trafficStats.tx_total) }}</b></span>
        </div>
      </div>
    </section>

    <!-- 系统指标面板 -->
    <section class="panel">
      <div class="panel-head">
        <span class="ph-title">系统指标</span>

        <!-- 时间范围：起止显示 + 预设按钮（独立于流量图） -->
        <span class="tl-label">时间</span>
        <button class="range-btn" title="点击编辑起止时间" @click="sysOpenCustomEdit">
          {{ fmtTime(sysSpan.startMs, sysTzOffset) }} <span class="range-sep">~</span> {{ fmtTime(sysSpan.endMs, sysTzOffset) }}
        </button>
        <div class="pop-wrap">
          <button class="preset-btn" :class="{ active: sysTimeRange !== '1h' }" @click.stop="sysPresetOpen = !sysPresetOpen">{{ sysRangeLabel }} ▾</button>
          <div v-if="sysPresetOpen" class="pop-menu" @click.stop>
            <button v-for="p in PRESETS" :key="p.key" class="pop-item" :class="{ active: sysTimeRange === p.key }" @click="sysSelectPreset(p.key)">{{ p.label }}</button>
          </div>
        </div>

        <!-- 时区（独立于流量图） -->
        <div class="pop-wrap">
          <button class="ctrl-btn" @click.stop="sysTzOpen = !sysTzOpen">{{ TZ_OPTIONS.find((t) => t.offset === sysTzOffset)?.label || "UTC+8" }} ▾</button>
          <div v-if="sysTzOpen" class="pop-menu tz-menu" @click.stop>
            <button v-for="t in TZ_OPTIONS" :key="t.offset" class="pop-item" :class="{ active: sysTzOffset === t.offset }" @click="sysTzOffset = t.offset; sysTzOpen = false">{{ t.label }}</button>
          </div>
        </div>
      </div>

      <div v-if="sysCustomEditOpen" class="custom-range">
        <input type="datetime-local" v-model="sysCustomStart" @change="sysOnCustomEdit" />
        <span class="cr-sep">~</span>
        <input type="datetime-local" v-model="sysCustomEnd" @change="sysOnCustomEdit" />
        <button class="ghost-btn" @click="sysApplyCustom">确定</button>
      </div>

      <div ref="sysEl" class="chart"></div>
    </section>
    </div>

    <!-- Tab 2 网络：标记 + IP 网卡 + 防火墙 -->
    <div v-show="activeTab === 'network'" class="tab-body">
      <!-- 标记面板：内网/公网 -->
      <section class="panel">
        <div class="panel-head"><span class="ph-title">网络标记</span></div>
        <div class="net-type-row">
          <span class="nt-label">网络类型</span>
          <Dropdown v-model="netType" :options="netTypeOptions" />
          <template v-if="netType === 'public'">
            <input v-model="publicIpInput" class="nt-input" placeholder="手动输入公网 IP（留空用自动探测）" />
            <button class="ghost-btn" @click="saveNetType">保存</button>
          </template>
          <template v-else>
            <button class="ghost-btn" @click="saveNetType">保存</button>
          </template>
        </div>
        <div v-if="detail?.net_type === 'public' && detail?.public_ip" class="net-display">
          {{ detail.public_ip }} -- [{{ detail.ip_version || 'IPv4' }}] -- {{ detail.region || '未知地区' }}
          <span class="nt-src">{{ detail.public_ip_source === 'auto' ? '（自动探测）' : '（手动）' }}</span>
        </div>
      </section>

      <!-- IP 网卡面板 -->
      <section class="panel">
        <div class="panel-head">
          <span class="ph-title">网卡</span>
          <label class="nt-check"><input type="checkbox" v-model="showDocker" /> 显示容器/虚拟网卡</label>
        </div>
        <div v-if="!filteredIfaces.length" class="empty">该节点暂无网卡数据</div>
        <div v-for="iface in filteredIfaces" :key="iface.name" class="iface-row">
          <span class="if-name">{{ iface.name }}</span>
          <span class="if-tag" :class="iface.is_physical ? 'phy' : 'virt'">{{ iface.is_physical ? '物理' : '虚拟' }}</span>
          <span v-if="iface.is_default" class="if-tag def">默认出口</span>
          <span class="if-ip">{{ iface.ip || '—' }}</span>
          <span class="if-up" :class="iface.up ? 'up' : 'down'">{{ iface.up ? 'UP' : 'DOWN' }}</span>
          <button v-if="iface.is_physical && iface.ip" class="ghost-btn" @click="openIpForm(iface.name)">改 IP</button>
        </div>
      </section>

      <!-- 改 IP 表单（高危：红色警告条 + 二次确认 + ping 回退） -->
      <section v-if="ipFormOpen" class="panel">
        <div class="panel-head"><span class="ph-title">修改 IP — {{ ipIface }}</span></div>
        <div class="danger-banner">⚠️ 高危操作：修改 IP 可能导致服务器断网失联。系统会在修改后 ping 测试，不通会自动回退旧 IP。</div>
        <div class="ip-form">
          <div class="ip-row">
            <label>新 IP</label>
            <input v-model="ipNewIp" placeholder="如 192.168.1.100" />
          </div>
          <div class="ip-row">
            <label>前缀长度</label>
            <input v-model.number="ipPrefix" type="number" min="1" max="32" />
          </div>
          <div class="ip-row">
            <label>网关（可选）</label>
            <input v-model="ipGateway" placeholder="留空不改网关" />
          </div>
          <div class="ip-row">
            <label>预计可 ping 的 IP/域名</label>
            <input v-model="ipPingTarget" placeholder="如 192.168.1.1 或 223.5.5.5" />
          </div>
        </div>
        <div class="ip-actions">
          <template v-if="!ipConfirmOpen">
            <button class="danger-btn" @click="ipConfirmOpen = true">确认修改</button>
            <button class="ghost-btn" @click="ipFormOpen = false">取消</button>
          </template>
          <template v-else>
            <span class="confirm-text">再次确认：真的要修改 {{ ipIface }} 的 IP 为 {{ ipNewIp }} 吗？</span>
            <button class="danger-btn" @click="submitIpChange">确认，开始修改</button>
            <button class="ghost-btn" @click="ipConfirmOpen = false">返回</button>
          </template>
        </div>
      </section>

      <!-- 防火墙面板 -->
      <section class="panel">
        <div class="panel-head">
          <span class="ph-title">防火墙</span>
          <button class="ghost-btn" @click="viewFirewall">{{ fwLoading ? '查询中…' : '查看规则' }}</button>
          <button class="danger-btn" @click="fwModOpen = !fwModOpen">{{ fwModOpen ? '收起' : '修改规则' }}</button>
        </div>
        <div class="fw-row">
          <span class="fw-name">UFW</span>
          <span v-if="fw.ufw?.installed" class="fw-st" :class="fw.ufw.active ? 'on' : 'off'">{{ fw.ufw.active ? '已启用' : '已安装（未启用）' }}</span>
          <span v-else class="fw-st off">未检测到</span>
        </div>
        <div class="fw-row">
          <span class="fw-name">iptables</span>
          <span v-if="fw.iptables?.installed" class="fw-st on">已安装</span>
          <span v-else class="fw-st off">未检测到</span>
        </div>
        <!-- 修改区域（高危） -->
        <div v-if="fwModOpen" class="fw-mod">
          <div class="danger-banner">⚠️ 高危操作：修改防火墙规则可能锁死服务器（尤其 iptables）。请确认规则正确后再执行。</div>
          <div class="fw-mod-tabs">
            <button class="ghost-btn" :class="{ active: fwMode === 'form' }" @click="fwMode = 'form'">表单</button>
            <button class="ghost-btn" :class="{ active: fwMode === 'raw' }" @click="fwMode = 'raw'">原文命令</button>
          </div>
          <template v-if="fwMode === 'form'">
            <div class="ip-row">
              <label>工具</label>
              <Dropdown v-model="fwTool" :options="[{ value: 'ufw', label: 'UFW' }, { value: 'iptables', label: 'iptables' }]" />
            </div>
            <div class="ip-row">
              <label>动作</label>
              <Dropdown v-model="fwAction" :options="[{ value: 'allow', label: '放行' }, { value: 'deny', label: '拒绝' }]" />
            </div>
            <div class="ip-row">
              <label>端口</label>
              <input v-model="fwPort" placeholder="如 80" />
            </div>
            <div class="ip-row">
              <label>协议</label>
              <Dropdown v-model="fwProto" :options="[{ value: 'tcp', label: 'TCP' }, { value: 'udp', label: 'UDP' }, { value: 'all', label: '全部' }]" />
            </div>
          </template>
          <template v-else>
            <div class="ip-row">
              <label>完整命令</label>
              <input v-model="fwRawCmd" placeholder="如 sudo ufw allow 80/tcp" />
            </div>
          </template>
          <div class="ip-actions">
            <template v-if="!fwConfirmOpen">
              <button class="danger-btn" @click="fwConfirmOpen = true">确认修改</button>
              <button class="ghost-btn" @click="fwModOpen = false">取消</button>
            </template>
            <template v-else>
              <span class="confirm-text">再次确认执行：{{ buildFwCmd() }}</span>
              <button class="danger-btn" @click="submitFwChange">确认执行</button>
              <button class="ghost-btn" @click="fwConfirmOpen = false">返回</button>
            </template>
          </div>
        </div>
        <pre v-if="fwOutput" class="cmd-output">{{ fwOutput }}</pre>
      </section>

      <!-- PBR 策略路由面板（只读） -->
      <section class="panel">
        <div class="panel-head">
          <span class="ph-title">策略路由（PBR）</span>
          <button class="ghost-btn" @click="viewPbr">{{ pbrLoading ? '查询中…' : '查看' }}</button>
        </div>
        <pre v-if="pbrOutput" class="cmd-output">{{ pbrOutput }}</pre>
      </section>
    </div>

    <!-- Tab 3 服务监控 -->
    <div v-show="activeTab === 'services'" class="tab-body">
    <!-- 监控项面板 -->
    <section class="panel">
      <div class="panel-head">
        <span class="ph-title">服务监控</span>
        <button class="ghost-btn" @click="showAdd = !showAdd">添加</button>
      </div>
      <div v-if="showAdd" class="mon-add">
        <input v-model="newMon.name" placeholder="名称" />
        <select v-model="newMon.type">
          <option value="ping">PING</option>
          <option value="tcp">TCP</option>
          <option value="udp">UDP</option>
          <option value="http">HTTP</option>
          <option value="https">HTTPS</option>
        </select>
        <input v-model="newMon.target" placeholder="目标（IP/域名/端口）" />
        <button class="ghost-btn" @click="addMonitor">确定</button>
      </div>
      <div class="mon-list">
        <div v-if="!monitors.length" class="empty">该节点还没有监控项</div>
        <div v-for="m in monitors" :key="m.id" class="mon-row">
          <span class="mon-type">{{ typeLabel[m.type] }}</span>
          <span class="mon-name">{{ m.name }}</span>
          <span class="mon-target">{{ m.target }}</span>
          <span class="mon-status" :class="m.status">{{ m.status === "up" ? "UP" : m.status === "down" ? "DOWN" : "—" }}</span>
          <button class="del" title="删除" @click="delMonitor(m.id)"><Icon name="trash" :size="13" /></button>
        </div>
      </div>
    </section>
    </div>
  </div>
</template>

<style scoped>
/* 详情内容区（作为根元素，在 ServersPage 的 view-body 里撑满） */
.detail-body {
  height: 100%;
  min-width: 0;
  overflow-y: auto;
  padding: 18px 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.d-head { display: flex; align-items: center; gap: 12px; }
.back {
  display: flex; align-items: center; gap: 4px;
  background: transparent; border: 1px solid var(--accent-dim); color: var(--accent);
  border-radius: var(--radius-sm); padding: 6px 12px; cursor: pointer; font-size: 13px;
}
.name { font-size: 20px; font-weight: 600; color: var(--text-hi); }
.badge { font-size: 11px; padding: 2px 9px; border-radius: 20px; letter-spacing: 1px; }
.badge.online { color: var(--pink); background: rgba(255, 158, 199, 0.12); }
.badge.offline { color: var(--text-faint); background: var(--bg-raised); }
.badge.pending { color: var(--accent-dim); background: var(--bg-raised); }
.meta { margin-left: auto; display: flex; gap: 12px; font-size: 12.5px; color: var(--text-lo); }

.panel {
  background: var(--bg-panel);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: var(--radius-sm);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
}
.panel-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; flex-wrap: wrap; }
.ph-title { font-size: 13px; font-weight: 600; color: var(--text-hi); }
.chart { height: 250px; }

/* ── 存储面板 ── */
.disk-group { margin-top: 6px; }
.disk-group-title { font-size: 12px; color: var(--text-faint); margin-bottom: 8px; }
.disk-row { display: flex; gap: 32px; flex-wrap: wrap; }
.disk-item { display: flex; align-items: center; gap: 14px; }
.disk-ring { position: relative; width: 96px; height: 96px; flex-shrink: 0; }
.ring-svg { width: 100%; height: 100%; }
.ring-bg { fill: none; stroke: rgba(255, 255, 255, 0.08); stroke-width: 8; }
.ring-fg { fill: none; stroke-width: 8; stroke-linecap: round; transition: stroke-dasharray 0.6s ease; }
.ring-fg.physical { stroke: #ff9ec7; }
.ring-fg.network { stroke: #7bd0e3; }
.ring-fg.virtual { stroke: #bf7aff; }
.ring-fg.warn { stroke: #f0a060; }
.ring-pct {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-size: 20px; font-weight: 600; color: var(--text-hi); font-variant-numeric: tabular-nums;
}
.disk-meta { display: flex; flex-direction: column; gap: 3px; }
.disk-mount { font-size: 13px; color: var(--text-hi); font-family: var(--font-mono); }
.disk-size { font-size: 12px; color: var(--text-lo); font-variant-numeric: tabular-nums; }
.disk-fs { font-size: 11px; color: var(--text-faint); }

/* ── 时间 / 网卡 / 单位 / 时区 控件 ── */
.tl-label { font-size: 12px; color: var(--text-faint); }
.range-btn {
  background: transparent; border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-sm); color: var(--text-hi); padding: 4px 10px;
  font-size: 12px; cursor: pointer; font-family: var(--font-mono); font-variant-numeric: tabular-nums;
}
.range-btn:hover { border-color: var(--accent-dim); }
.range-sep { color: var(--text-faint); margin: 0 2px; }

.pop-wrap { position: relative; }
.ctrl-btn, .preset-btn {
  background: transparent; border: 1px solid var(--accent-dim); color: var(--text-lo);
  border-radius: 14px; padding: 3px 12px; font-size: 12px; cursor: pointer;
}
.preset-btn.active, .ctrl-btn:hover { color: var(--accent); border-color: var(--accent); }
.pop-menu {
  position: absolute; top: 30px; left: 0; z-index: 20;
  background: var(--bg-raised); border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-sm); padding: 4px; min-width: 130px; max-height: 320px; overflow-y: auto;
  display: flex; flex-direction: column; gap: 2px;
}
.pop-item {
  background: transparent; border: none; color: var(--text-lo); text-align: left;
  padding: 6px 10px; font-size: 12px; border-radius: 4px; cursor: pointer;
}
.pop-item:hover { background: var(--bg-base); color: var(--text-hi); }
.pop-item.active { color: var(--accent); }
.iface-menu { min-width: 280px; }
.unit-menu { min-width: 120px; }

.custom-range { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.custom-range input[type="datetime-local"] {
  background: var(--bg-base); border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-sm); color: var(--text-hi); padding: 5px 8px; font-size: 12px;
}
.cr-sep { color: var(--text-faint); }

.dropdown-item { display: flex; align-items: center; gap: 8px; padding: 5px 8px; border-radius: 4px; cursor: pointer; }
.dropdown-item:hover { background: var(--bg-base); }
.di-name { font-size: 13px; color: var(--text-hi); font-family: var(--font-mono); }
.di-tag { font-size: 10px; color: var(--text-faint); background: var(--bg-base); padding: 1px 6px; border-radius: 8px; }
.di-tag.phys { color: var(--accent); }
.di-tag.def { color: var(--pink); }
.di-ip { font-size: 11px; color: var(--text-lo); font-family: var(--font-mono); }

/* ── 统计卡（图下方，三行）── */
.stats-bar {
  display: flex; flex-direction: column; gap: 6px;
  margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255, 255, 255, 0.05);
}
.stat-row { display: flex; align-items: baseline; gap: 20px; flex-wrap: wrap; }
.stat-dir { font-size: 12px; font-weight: 600; width: 34px; }
.stat-dir.down { color: #7bd0e3; }
.stat-dir.up { color: var(--pink); }
.stat-dir.total { color: var(--text-lo); }
.stat-item { font-size: 12px; color: var(--text-faint); }
.stat-item b { color: var(--text-hi); font-weight: 600; font-variant-numeric: tabular-nums; margin-left: 4px; }
.stat-row.total .stat-item b { color: var(--accent); }

.ghost-btn {
  background: transparent; border: 1px solid var(--accent-dim); color: var(--accent);
  border-radius: var(--radius-sm); padding: 4px 12px; cursor: pointer; font-size: 12px;
}
.mon-add { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; }
.mon-add input, .mon-add select {
  background: var(--bg-base); border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-sm); color: var(--text-hi); padding: 6px 10px; font-size: 13px;
}
.mon-list { display: flex; flex-direction: column; gap: 4px; }
.empty { font-size: 13px; color: var(--text-faint); padding: 12px 0; }
.mon-row { display: flex; align-items: center; gap: 10px; padding: 7px 8px; border-radius: 4px; }
.mon-row:hover { background: var(--bg-raised); }
.mon-type { font-size: 11px; color: var(--accent); font-family: var(--font-mono); width: 40px; }
.mon-name { font-size: 13px; color: var(--text-hi); }
.mon-target { font-size: 12px; color: var(--text-lo); font-family: var(--font-mono); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mon-status { font-size: 11px; padding: 1px 8px; border-radius: 10px; }
.mon-status.up { color: #7be39a; background: rgba(123, 227, 154, 0.12); }
.mon-status.down { color: var(--pink); background: rgba(255, 158, 199, 0.12); }
.mon-status.unknown { color: var(--text-faint); background: var(--bg-raised); }
.del { background: transparent; border: none; color: var(--text-faint); cursor: pointer; }
.del:hover { color: var(--pink); }

/* ── 详情页标签页导航 ── */
.d-tabs {
  display: flex; gap: 4px; padding: 0 16px 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.d-tab {
  background: transparent; border: none; color: var(--text-lo);
  font-size: 13px; padding: 7px 14px; cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -9px;
}
.d-tab:hover { color: var(--text-hi); }
.d-tab.active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 500; }
.tab-body { padding-top: 12px; }

/* ── 网络标记 ── */
.net-type-row { display: flex; align-items: center; gap: 10px; padding: 4px 0 10px; flex-wrap: wrap; }
.nt-label { font-size: 13px; color: var(--text-lo); }
.nt-input {
  background: var(--bg-base); border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-sm); color: var(--text-hi); padding: 6px 10px; font-size: 13px;
  min-width: 240px; font-family: var(--font-mono);
}
.net-display { font-size: 13px; color: var(--text-hi); font-family: var(--font-mono); padding-bottom: 4px; }
.nt-src { font-size: 11px; color: var(--text-faint); font-family: inherit; margin-left: 6px; }

/* ── 网卡列表 ── */
.nt-check { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--text-lo); cursor: pointer; margin-left: auto; }
.iface-row { display: flex; align-items: center; gap: 10px; padding: 7px 8px; border-radius: 4px; }
.iface-row:hover { background: var(--bg-raised); }
.if-name { font-size: 13px; color: var(--text-hi); font-family: var(--font-mono); min-width: 100px; }
.if-tag { font-size: 10px; padding: 1px 7px; border-radius: 8px; background: var(--bg-base); color: var(--text-faint); }
.if-tag.phy { color: var(--accent); }
.if-tag.virt { color: var(--text-faint); }
.if-tag.def { color: var(--pink); }
.if-ip { font-size: 12px; color: var(--text-lo); font-family: var(--font-mono); flex: 1; }
.if-up { font-size: 11px; padding: 1px 8px; border-radius: 10px; }
.if-up.up { color: #7be39a; background: rgba(123, 227, 154, 0.12); }
.if-up.down { color: var(--text-faint); background: var(--bg-raised); }

/* ── 防火墙 ── */
.fw-row { display: flex; align-items: center; gap: 12px; padding: 7px 8px; }
.fw-name { font-size: 13px; color: var(--text-hi); font-family: var(--font-mono); min-width: 90px; }
.fw-st { font-size: 12px; color: var(--text-lo); }
.fw-st.on { color: #7be39a; }
.fw-st.off { color: var(--text-faint); }

/* ── 命令输出（防火墙规则 / PBR 路由表）── */
.cmd-output {
  background: var(--bg-base); border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: var(--radius-sm); padding: 10px 12px; margin: 6px 0;
  font-family: var(--font-mono); font-size: 12px; line-height: 1.5;
  color: var(--text-lo); white-space: pre-wrap; word-break: break-all;
  max-height: 320px; overflow-y: auto;
}

/* ── 改 IP 表单（高危）── */
.danger-banner {
  background: rgba(255, 93, 108, 0.12); border: 1px solid rgba(255, 93, 108, 0.4);
  border-radius: var(--radius-sm); color: #ff5d6c; padding: 8px 12px; margin: 6px 0;
  font-size: 12px; line-height: 1.5;
}
.ip-form { display: flex; flex-direction: column; gap: 8px; padding: 4px 0; }
.ip-row { display: flex; align-items: center; gap: 10px; }
.ip-row label { font-size: 12px; color: var(--text-lo); min-width: 140px; }
.ip-row input {
  background: var(--bg-base); border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-sm); color: var(--text-hi); padding: 6px 10px; font-size: 13px;
  flex: 1; font-family: var(--font-mono);
}
.ip-actions { display: flex; align-items: center; gap: 10px; padding: 10px 0 4px; flex-wrap: wrap; }
.danger-btn {
  background: rgba(255, 93, 108, 0.15); border: 1px solid rgba(255, 93, 108, 0.5);
  color: #ff5d6c; border-radius: var(--radius-sm); padding: 5px 14px; cursor: pointer; font-size: 12px;
}
.danger-btn:hover { background: rgba(255, 93, 108, 0.25); }
.confirm-text { font-size: 12px; color: #ffb454; }

/* ── 防火墙修改区域 ── */
.fw-mod { padding: 8px 0 4px; }
.fw-mod-tabs { display: flex; gap: 8px; margin-bottom: 8px; }
.fw-mod-tabs .ghost-btn.active { color: var(--accent); border-color: var(--accent); }
</style>
