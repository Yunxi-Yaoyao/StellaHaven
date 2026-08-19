<script setup lang="ts">
// 节点详情页：基本信息 + 流量图（时间范围/时区/网卡多选/单位/统计卡）+ 系统指标 + 监控项
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from "vue";
import { useRouter, useRoute } from "vue-router";
import * as echarts from "echarts";
import Icon from "../../shell/Icon.vue";
import {
  getNodeDetail, getNodeMetrics, getNodeSysMetrics, getTrafficStats, updateNodeIfaces, updateNetType, changeIp,
  listMonitors, getMonitorSeries, createCommand, listCommands, scanFirewall, getNetTask,
  latestNetTask, scanPbr,
  type NodeDetail, type Monitor, type MonitorCheckPoint, type TrafficStats, type FirewallData,
} from "../../api/servers";
import { toast } from "../../composables/useToast";
import Dropdown from "../../shell/Dropdown.vue";
import MonitorDetailModal from "./MonitorDetailModal.vue";

// 节点 id 由路由 /status/:id 经 props 传入（router/index.ts props 映射）；返回 = router 回列表
const props = defineProps<{ nodeId: number }>();
const nodeId = computed(() => props.nodeId);
const router = useRouter();

const detail = ref<NodeDetail | null>(null);
const monitors = ref<Monitor[]>([]);

// ── 监控项详情浮窗（与总览页共用组件：图表 / MTR / 编辑）──
const monModal = ref<Monitor | null>(null);
function openMonModal(m: Monitor) { monModal.value = m; }

// ── 详情页标签页：概览 / 网络（标记+IP+防火墙）/ 服务监控 ──
// 支持 ?tab= 直达（如总览页监控卡点击 → ?tab=services）
type TabKey = "overview" | "network" | "services";
const route = useRoute();
const activeTab = ref<TabKey>((route.query.tab as TabKey) || "overview");
watch(() => route.query.tab, (t) => { if (t && t !== activeTab.value) activeTab.value = t as TabKey; });

// ── 网络标记（内网/公网）──
const netType = ref<"internal" | "public">("internal");
const publicIpInput = ref("");
const netTypeOptions = [
  { value: "internal", label: "内网" },
  { value: "public", label: "公网" },
];

// ── 网卡列表（默认只显示物理/主网卡，隐藏 docker/容器/lo 回环）──
const showAllIfaces = ref(false);
type IfaceItem = { name: string; is_default: boolean; up: boolean; is_physical?: boolean; docker?: boolean; ip?: string | null };
const allIfaces = computed<IfaceItem[]>(() => {
  const ifs = detail.value?.interfaces || {};
  return Object.entries(ifs).map(([name, meta]) => {
    const m = meta as IfaceItem;
    return { name, is_default: m.is_default, up: m.up, is_physical: m.is_physical, docker: m.docker, ip: m.ip };
  });
});
// lo 回环判定：名字是 lo 或 ip 是 127.x / ::1
function isLoopback(m: IfaceItem): boolean {
  if (m.name === "lo" || m.name.startsWith("lo")) return true;
  const ip = m.ip || "";
  return ip.startsWith("127.") || ip === "::1";
}
const filteredIfaces = computed<IfaceItem[]>(() => {
  if (showAllIfaces.value) return allIfaces.value;
  return allIfaces.value.filter((m) => !m.docker && !isLoopback(m));
});

// ── 防火墙检测状态 ──
const fw = computed(() => detail.value?.components?.firewall || {});

// ── 防火墙 / PBR 只读查看（复用 command 任务：下发 → 轮询拿 stdout）──
const fwOutput = ref("");
const fwLoading = ref(false);
const pbrLoading = ref(false);

const fwAt = ref("");  // 防火墙快照时间

async function viewFirewall(force = true) {
  // 结构化扫描（一期）：agent 采集 ufw numbered + iptables-save 五表，前端表格展示
  // 惰性缓存：非强制且有 10 分钟内快照 → 直接用
  fwLoading.value = true;
  fwOutput.value = "";
  try {
    if (!force) {
      const latest = await latestNetTask(nodeId.value, "firewall_scan");
      const rj = latest?.result_json as any;
      if (latest && rj?.ufw) {
        fwData.value = rj;
        fwAt.value = latest.created_at;
        const tbls = rj?.iptables?.tables || {};
        fwIptTab.value = IPT_TABLE_ORDER.find((k) => tbls[k]) || Object.keys(tbls)[0] || "";
        if (Date.now() - new Date(latest.created_at).getTime() < SCAN_TTL) { fwLoading.value = false; return; }
        // 过期：先显示旧数据，继续往下后台重扫
      }
    }
    const t = await scanFirewall(nodeId.value);
    for (let i = 0; i < 15; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const cur = await getNetTask(t.id);
      if (cur.status === "done") {
        fwData.value = cur.result_json as FirewallData;
        fwAt.value = new Date().toISOString();
        // 默认选中第一个有数据的表
        const tbls = fwData.value?.iptables?.tables || {};
        fwIptTab.value = IPT_TABLE_ORDER.find((k) => tbls[k]) || Object.keys(tbls)[0] || "";
        fwLoading.value = false;
        return;
      }
      if (cur.status === "failed") {
        toast("防火墙扫描失败喵~");
        fwLoading.value = false;
        return;
      }
    }
    toast("扫描超时了喵~");
  } catch { toast("下发扫描失败"); }
  fwLoading.value = false;
}

// ── 防火墙结构化数据视图 ──
const fwData = ref<FirewallData | null>(null);
const fwView = ref<"ufw" | "iptables">("ufw");      // 顶层视图：UFW / iptables
const fwIptTab = ref("");                            // iptables 五表 tab
const fwShowRaw = ref(false);                        // 原文折叠
const IPT_TABLE_ORDER = ["filter", "nat", "mangle", "raw", "security"];
const iptTables = computed(() => {
  const tbls = fwData.value?.iptables?.tables || {};
  return IPT_TABLE_ORDER.filter((k) => tbls[k]).concat(Object.keys(tbls).filter((k) => !IPT_TABLE_ORDER.includes(k)));
});
// 大表（k3s 宿主 nat/filter 上千条）默认折叠，点开才渲染行
const fwChainsOpen = ref<Record<string, boolean>>({});
function toggleChain(key: string) { fwChainsOpen.value = { ...fwChainsOpen.value, [key]: !fwChainsOpen.value[key] }; }

// ── Docker 状态（面板已独立成 tab，详情页只留状态行）──
const dkComp = computed(() => (detail.value?.components as any)?.docker || null);  // 心跳里的检测状态

// ── 惰性扫描缓存：打开面板先读最近一次完成快照，超过 10 分钟自动后台重扫 ──
const SCAN_TTL = 10 * 60 * 1000;

interface PbrRule { pref: number; mark: string | null; table: string | null; from: string | null; raw: string }
interface PbrRoute { dst: string; via: string | null; dev: string | null; scope: string | null; raw: string }
interface PbrMark { chain: string | null; uid: string | null; mark: string | null; raw: string }
interface PbrData { rules: PbrRule[]; tables: Record<string, PbrRoute[]>; marks: PbrMark[] }

function goDockerTab() { router.push({ path: "/status", query: { view: "docker", node: String(nodeId.value) } }); }
function fmtScanTime(iso: string) {
  return iso ? `数据来自 ${new Date(iso).toLocaleTimeString("zh-CN", { hour12: false })}` : "";
}

const pbrData = ref<PbrData | null>(null);
const pbrAt = ref("");           // 快照时间
const pbrOpen = ref<Record<string, boolean>>({});  // 路由表展开

async function pollNetTask(tid: number, tries = 15): Promise<any> {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const cur = await getNetTask(tid);
    if (cur.status === "done") return cur.result_json;
    if (cur.status === "failed") return { error: (cur.result_json as any)?.error || "扫描失败" };
  }
  return { error: "扫描超时" };
}

async function loadPbr(force = false) {
  pbrLoading.value = true;
  try {
    if (!force) {
      const latest = await latestNetTask(nodeId.value, "pbr_scan");
      const rj = latest?.result_json as any;
      if (latest && rj?.rules) {
        pbrData.value = rj;
        pbrAt.value = latest.created_at;
        if (Date.now() - new Date(latest.created_at).getTime() < SCAN_TTL) { pbrLoading.value = false; return; }
        // 过期：先显示旧数据，后台继续重扫
      }
    }
    const t = await scanPbr(nodeId.value);
    const rj = await pollNetTask(t.id);
    if (rj?.rules) { pbrData.value = rj; pbrAt.value = new Date().toISOString(); }
    else if (rj?.error) toast(`PBR 扫描失败：${rj.error}`);
  } catch { toast("PBR 加载失败"); }
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

// ── 时间范围（流量图 + 系统指标共享一组控件）──
type RangeKey = "1h" | "6h" | "24h" | "7d" | "30d" | "90d" | "180d" | "thismonth" | "lastmonth" | "custom";
const PRESETS: { key: RangeKey; label: string; seconds?: number }[] = [
  { key: "1h", label: "1小时", seconds: 3600 },
  { key: "6h", label: "6小时", seconds: 21600 },
  { key: "24h", label: "24小时", seconds: 86400 },
  { key: "7d", label: "7天", seconds: 604800 },
  { key: "30d", label: "近30天", seconds: 2592000 },
  { key: "90d", label: "近90天", seconds: 7776000 },
  { key: "180d", label: "近180天", seconds: 15552000 },
  { key: "thismonth", label: "本月" },
  { key: "lastmonth", label: "上月" },
  { key: "custom", label: "自定义" },
];
const timeRange = ref<RangeKey>("1h");
const presetOpen = ref(false);
const customEditOpen = ref(false);
const customStart = ref("");
const customEnd = ref("");

// ── 实时模式：窗口跟随当前时间滚动，每 3s 增量拉取新点追加 ──
const LIVE_WINDOWS = [
  { s: 300, label: "5分钟" }, { s: 900, label: "15分钟" }, { s: 1800, label: "30分钟" },
  { s: 3600, label: "1小时" }, { s: 7200, label: "2小时" },
];
const liveMode = ref(false);
const liveWindow = ref(300);
const liveOpen = ref(false);   // 窗长下拉
let liveTimer: ReturnType<typeof setInterval> | null = null;

// ── 时区（分钟偏移，默认 UTC+8，两图共享）──
const TZ_OPTIONS = [
  { label: "UTC+8", offset: 480 },
  { label: "UTC+0", offset: 0 },
  { label: "UTC+1", offset: 60 },
  { label: "UTC+9", offset: 540 },
  { label: "UTC-5", offset: -300 },
  { label: "UTC-8", offset: -480 },
];
const tzOffset = ref(480);
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
// 实时模式下 span = [now - 窗长, now]，跟随当前时间滚动
const span = computed(() => {
  if (liveMode.value) {
    const now = Date.now();
    return { startMs: now - liveWindow.value * 1000, endMs: now };
  }
  return computeSpan(timeRange.value, customStart.value, customEnd.value, tzOffset.value);
});

// 查询参数：start/end（ISO）+ limit/step（按跨度自动降采样）
function getRange(): { start: string; end: string; limit: number; step?: number } {
  const s = span.value;
  const seconds = (s.endMs - s.startMs) / 1000;
  let limit = 720, step: number | undefined;
  if (seconds > 86400 * 60) { step = 7200; limit = 2200; }       // >60d
  else if (seconds > 86400 * 30) { step = 3600; limit = 2200; }  // >30d
  else if (seconds > 86400 * 7) { step = 900; limit = 3000; }
  else if (seconds > 86400) { step = 300; limit = 2016; }
  else if (seconds > 21600) { step = undefined; limit = 17280; }
  else if (seconds > 3600) { step = undefined; limit = 4320; }
  else { step = undefined; limit = 720; }
  return { start: new Date(s.startMs).toISOString(), end: new Date(s.endMs).toISOString(), limit, step };
}
// 系统指标查询参数（60s 颗粒，与流量图共享时间范围，降采样阈值不同）
function getSysRange(): { start: string; end: string; limit: number; step?: number } {
  const s = span.value;
  const seconds = (s.endMs - s.startMs) / 1000;
  let limit = 1440, step: number | undefined;
  if (seconds > 86400 * 60) { step = 7200; limit = 2200; }
  else if (seconds > 86400 * 30) { step = 3600; limit = 2200; }
  else if (seconds > 86400 * 7) { step = 900; limit = 3000; }
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
// 目标时区下的墙上时间：YYYY/MM/DD-HH:MM:SS
function fmtTime(ms: number, off: number = tzOffset.value): string {
  const d = new Date(ms + off * 60000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}/${p(d.getUTCMonth() + 1)}/${p(d.getUTCDate())}-${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}
// 起止按钮短格式：今天内 HH:mm，跨天 MM-DD HH:mm（目标时区）
function fmtTimeShort(ms: number, off: number = tzOffset.value): string {
  const d = new Date(ms + off * 60000);
  const n = new Date(Date.now() + off * 60000);
  const p = (x: number) => String(x).padStart(2, "0");
  const hm = `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
  const sameDay = d.getUTCFullYear() === n.getUTCFullYear() && d.getUTCMonth() === n.getUTCMonth() && d.getUTCDate() === n.getUTCDate();
  return sameDay ? hm : `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${hm}`;
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

// 状态类加载（节点详情 + 监控项）：5s 轮询只走这里，不碰图表
async function load() {
  try {
    detail.value = await getNodeDetail(nodeId.value);
    netType.value = detail.value.net_type === "public" ? "public" : "internal";
    publicIpInput.value = detail.value.public_ip || "";
    monitors.value = (await listMonitors()).filter((m) => m.node_id === nodeId.value);
    const ifaces = monitoredIfaces(detail.value);
    if (!selectedIfaces.value.length) selectedIfaces.value = ifaces;
  } catch { /* 静默 */ }
}

// 图表全量加载：进入页面 / 切范围 / 开实时 时整段重取一次
async function loadCharts() {
  await Promise.all([fetchTraffic(true), fetchSys(true), loadStats()]);
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

// ── 基本信息面板（OS/内核/CPU/负载/运行时间，来自 agent os_info）──
const si = computed(() => detail.value?.sys_info || null);
// 30s 心跳 tick：让 uptime 文本自己走（detail 5s 刷新时 sys_info 不变的话 computed 不重算）
const uptimeTick = ref(0);
let uptimeTimer: ReturnType<typeof setInterval> | null = null;
const uptimeText = computed(() => {
  void uptimeTick.value;
  const bt = si.value?.boot_time;
  if (!bt) return null;
  let sec = Math.max(0, Math.floor(Date.now() / 1000 - bt));
  const d = Math.floor(sec / 86400); sec %= 86400;
  const h = Math.floor(sec / 3600); sec %= 3600;
  const m = Math.floor(sec / 60);
  if (d > 0) return `${d} 天 ${h} 小时`;
  if (h > 0) return `${h} 小时 ${m} 分钟`;
  return `${m} 分钟`;
});
const RING_R = 42;
const RING_CIRC = 2 * Math.PI * RING_R;

let trafficRenderSeq = 0;  // 请求序号：丢弃乱序返回的旧渲染

// ── 图表数据层：full=整段重取，delta=只取上次之后的新点（实时模式用）──
const trafficPoints = ref<Record<string, MetricPoint[]>>({});  // 每网卡时序（时间正序）
const sysPoints = ref<SysMetricPoint[]>([]);

async function fetchTraffic(full: boolean) {
  const seq = ++trafficRenderSeq;
  // 首屏 detail 还没回来时 monitoredIfaces 会炸，直接跳过等下一轮
  const ifaces = selectedIfaces.value.length ? selectedIfaces.value : (detail.value ? monitoredIfaces(detail.value) : []);
  if (!ifaces.length) return;
  const base = getRange();
  const next: Record<string, MetricPoint[]> = full ? {} : { ...trafficPoints.value };
  for (const iface of ifaces) {
    let start = base.start, end = base.end, limit = base.limit, step = base.step;
    const existing = next[iface] || [];
    if (!full && existing.length) {
      // 增量：只拉最后一点之后的新数据
      start = new Date(new Date(existing[existing.length - 1].ts).getTime() + 1000).toISOString();
      end = new Date().toISOString();
      limit = 300; step = undefined;
    }
    try {
      const data = await getNodeMetrics(nodeId.value, { iface, start, end, limit, step });
      if (seq !== trafficRenderSeq) return;  // 已有更新请求，丢弃
      const points = [...data].reverse();
      if (full) {
        next[iface] = points;
      } else {
        const lastTs = existing.length ? new Date(existing[existing.length - 1].ts).getTime() : 0;
        let merged = [...existing, ...points.filter((pt) => new Date(pt.ts).getTime() > lastTs)];
        if (liveMode.value) merged = merged.filter((pt) => new Date(pt.ts).getTime() >= Date.now() - liveWindow.value * 1000);
        next[iface] = merged;
      }
    } catch { /* 单网卡失败不影响其他 */ }
  }
  if (seq !== trafficRenderSeq) return;
  // 丢掉不再选中的网卡
  trafficPoints.value = Object.fromEntries(Object.entries(next).filter(([k]) => ifaces.includes(k)));
  paintTraffic();
}

function paintTraffic() {
  if (!trafficEl.value) return;
  if (!trafficChart) trafficChart = echarts.init(trafficEl.value);
  const ifaces = Object.keys(trafficPoints.value);
  const series: any[] = [];
  let times: string[] = [];
  ifaces.forEach((iface, i) => {
    const points = trafficPoints.value[iface];
    if (!times.length) times = points.map((pt) => fmtAxisTime(new Date(pt.ts).getTime()));
    const color = COLORS[i % COLORS.length];
    series.push({
      name: `${iface} ↓`, type: "line", smooth: true, showSymbol: false, animation: false,
      data: points.map((pt) => chartRate(pt.rx_delta)),
      lineStyle: { width: 1.5 }, itemStyle: { color }, areaStyle: { opacity: 0.08 },
    });
    series.push({
      name: `${iface} ↑`, type: "line", smooth: true, showSymbol: false, animation: false,
      data: points.map((pt) => chartRate(pt.tx_delta)),
      lineStyle: { width: 1.5, type: "dashed" }, itemStyle: { color },
    });
  });
  trafficChart.setOption({
    backgroundColor: "transparent",
    grid: { left: 52, right: 16, top: 34, bottom: 26 },
    tooltip: {
      trigger: "axis",
      formatter: (params: any) => {
        if (!params || !params.length) return "";
        const unit = chartUnit();
        let html = `${params[0].axisValue}<br/>`;
        for (const prm of params) html += `${prm.marker}${prm.seriesName}：<b>${fmtVal(prm.value)} ${unit}</b><br/>`;
        return html;
      },
    },
    legend: { type: "scroll", textStyle: { color: "#9aa0aa" }, top: 0 },
    xAxis: { type: "category", data: times, boundaryGap: false, axisLine: { lineStyle: { color: "#2a2d35" } }, axisLabel: { color: "#9aa0aa" } },
    yAxis: { type: "value", name: chartUnit(), axisLabel: { color: "#9aa0aa" }, splitLine: { lineStyle: { color: "#1f2229" } } },
    series,
  }, { notMerge: true });  // notMerge：取消勾选网卡时彻底清掉旧 series，否则残留；animation:false 保证增量刷新不闪
}

let statsSeq = 0;  // 请求序号：丢弃乱序返回的旧统计
async function loadStats() {
  const seq = ++statsSeq;
  const range = getRange();
  const ifaces = selectedIfaces.value.length ? selectedIfaces.value : (detail.value ? monitoredIfaces(detail.value) : []);
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
  loadCharts();
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
  presetOpen.value = false;
  if (key === "custom") { openCustomEdit(); return; }  // 先编辑起止时间，确定后再加载
  timeRange.value = key;
  loadCharts();
}

// ── 实时模式控制 ──
async function liveTick() {
  await Promise.all([fetchTraffic(false), fetchSys(false)]);
  loadStats();
}
function startLive() {
  stopLive();
  liveTimer = setInterval(liveTick, 3000);
}
function stopLive() {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
}
function toggleLive() {
  liveMode.value = !liveMode.value;
}
function pickLiveWindow(s: number) {
  liveWindow.value = s;
  liveOpen.value = false;
}
watch(liveMode, (on) => {
  if (on) { loadCharts(); startLive(); }
  else stopLive();
});
watch(liveWindow, () => { if (liveMode.value) loadCharts(); });


let sysRenderSeq = 0;  // 防乱序：只认最后一次请求的结果
async function fetchSys(full: boolean) {
  const seq = ++sysRenderSeq;
  const base = getSysRange();
  let start = base.start, end = base.end, limit = base.limit, step = base.step;
  const existing = sysPoints.value;
  if (!full && existing.length) {
    start = new Date(new Date(existing[existing.length - 1].ts).getTime() + 1000).toISOString();
    end = new Date().toISOString();
    limit = 100; step = undefined;
  }
  try {
    const data = await getNodeSysMetrics(nodeId.value, { start, end, limit, step });
    if (seq !== sysRenderSeq) return;  // 已有更新的请求，丢弃本次旧结果
    const points = [...data].reverse();
    if (full) {
      sysPoints.value = points;
    } else {
      const lastTs = existing.length ? new Date(existing[existing.length - 1].ts).getTime() : 0;
      let merged = [...existing, ...points.filter((pt) => new Date(pt.ts).getTime() > lastTs)];
      if (liveMode.value) merged = merged.filter((pt) => new Date(pt.ts).getTime() >= Date.now() - liveWindow.value * 1000);
      sysPoints.value = merged;
    }
    paintSys();
  } catch { /* 静默 */ }
}

function paintSys() {
  if (!sysEl.value) return;
  if (!sysChart) sysChart = echarts.init(sysEl.value);
  const points = sysPoints.value;
  const times = points.map((pt) => fmtAxisTime(new Date(pt.ts).getTime()));
  sysChart.setOption({
    backgroundColor: "transparent",
    grid: { left: 52, right: 16, top: 30, bottom: 26 },
    tooltip: {
      trigger: "axis",
      formatter: (params: any) => {
        if (!params || !params.length) return "";
        let html = `${params[0].axisValue}<br/>`;
        for (const prm of params) html += `${prm.marker}${prm.seriesName}：<b>${fmtVal(prm.value)} %</b><br/>`;
        return html;
      },
    },
    legend: { data: ["CPU", "内存", "磁盘"], textStyle: { color: "#9aa0aa" }, top: 0 },
    xAxis: { type: "category", data: times, boundaryGap: false, axisLine: { lineStyle: { color: "#2a2d35" } }, axisLabel: { color: "#9aa0aa" } },
    yAxis: { type: "value", name: "%", max: 100, axisLabel: { color: "#9aa0aa" }, splitLine: { lineStyle: { color: "#1f2229" } } },
    series: [
      { name: "CPU", type: "line", smooth: true, showSymbol: false, animation: false, data: points.map((pt) => pt.cpu_pct), lineStyle: { width: 1.5 }, itemStyle: { color: "#ff9ec7" } },
      { name: "内存", type: "line", smooth: true, showSymbol: false, animation: false, data: points.map((pt) => pt.mem_pct), lineStyle: { width: 1.5 }, itemStyle: { color: "#f0c060" } },
      { name: "磁盘", type: "line", smooth: true, showSymbol: false, animation: false, data: points.map((pt) => pt.disk_pct), lineStyle: { width: 1.5 }, itemStyle: { color: "#7bd0e3" } },
    ],
  }, { notMerge: true });  // notMerge：切时间范围彻底替换 xAxis/series；animation:false 增量不闪
}

// ── 网卡选择（下拉多选，自动保存为监控网卡）──
function toggleIface(name: string) {
  const i = selectedIfaces.value.indexOf(name);
  if (i >= 0) selectedIfaces.value.splice(i, 1);
  else selectedIfaces.value.push(name);
  saveIfaces();
  fetchTraffic(true);
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
watch(timeRange, () => { loadCharts(); });
watch(unitMode, () => { paintTraffic(); loadStats(); });  // 单位只影响格式化，不重拉数据
watch(tzOffset, () => { paintTraffic(); paintSys(); loadStats(); });  // 时区只影响轴标签，不重拉数据

// ── 监控项（只读：列表 + 状态 + 延迟曲线；增删在总览页）──
const expandedMonId = ref<number | null>(null);
const monRange = ref<"1h" | "6h" | "24h" | "7d" | "30d">("24h");
const monSeries = ref<MonitorCheckPoint[]>([]);
const monAvail = ref<{ pct: number; avg: number | null; total: number } | null>(null);
let monChart: echarts.ECharts | null = null;
// 范围 → 降采样 step（秒）：目标 300~400 个点
const MON_RANGES: { key: "1h" | "6h" | "24h" | "7d" | "30d"; label: string; sec: number; step?: number }[] = [
  { key: "1h", label: "1小时", sec: 3600 },
  { key: "6h", label: "6小时", sec: 21600, step: 60 },
  { key: "24h", label: "24小时", sec: 86400, step: 300 },
  { key: "7d", label: "7天", sec: 604800, step: 1800 },
  { key: "30d", label: "30天", sec: 2592000, step: 7200 },
];
async function toggleMon(id: number) {
  expandedMonId.value = expandedMonId.value === id ? null : id;
  if (expandedMonId.value !== null) await loadMonSeries();
}
async function pickMonRange(key: typeof monRange.value) {
  monRange.value = key;
  await loadMonSeries();
}
async function loadMonSeries() {
  const id = expandedMonId.value;
  if (id === null) return;
  const r = MON_RANGES.find((x) => x.key === monRange.value)!;
  const end = new Date();
  const start = new Date(end.getTime() - r.sec * 1000);
  try {
    // 曲线（范围内，按 step 降采样）
    monSeries.value = await getMonitorSeries(id, {
      start: start.toISOString(), end: end.toISOString(), step: r.step,
    });
    // 24h 可用率：独立取原始点（不降采样，成功率按探测次数算才准）
    const raw24 = await getMonitorSeries(id, { start: new Date(end.getTime() - 86400000).toISOString(), end: end.toISOString(), limit: 3000 });
    const okCount = raw24.filter((c) => c.success).length;
    const lats = raw24.filter((c) => c.success && c.latency_ms != null).map((c) => c.latency_ms!);
    monAvail.value = raw24.length
      ? { pct: okCount / raw24.length * 100, avg: lats.length ? lats.reduce((a, b) => a + b, 0) / lats.length : null, total: raw24.length }
      : null;
    await nextTick();
    paintMonChart(id);
  } catch { /* 静默 */ }
}
function paintMonChart(id: number) {
  const el = document.getElementById(`mon-chart-${id}`);
  if (!el) return;
  monChart = echarts.getInstanceByDom(el) || echarts.init(el);
  const pts = monSeries.value;
  monChart.setOption({
    backgroundColor: "transparent",
    grid: { left: 48, right: 16, top: 24, bottom: 24 },
    tooltip: {
      trigger: "axis",
      formatter: (params: any) => {
        if (!params || !params.length) return "";
        let html = `${params[0].axisValue}<br/>`;
        for (const prm of params) html += `${prm.marker}${prm.seriesName}：<b>${prm.value ?? "-"} ms</b><br/>`;
        return html;
      },
    },
    xAxis: {
      type: "category", boundaryGap: false,
      data: pts.map((c) => fmtAxisTime(new Date(c.ts).getTime())),
      axisLine: { lineStyle: { color: "#2a2d35" } }, axisLabel: { color: "#9aa0aa" },
    },
    yAxis: { type: "value", name: "ms", axisLabel: { color: "#9aa0aa" }, splitLine: { lineStyle: { color: "#1f2229" } } },
    series: [{
      name: "延迟", type: "line", smooth: true, showSymbol: false, animation: false,
      data: pts.map((c) => (c.success && c.latency_ms != null ? +c.latency_ms.toFixed(1) : null)),
      lineStyle: { width: 1.5 }, itemStyle: { color: "#9eb7e5" }, areaStyle: { opacity: 0.08 },
      connectNulls: false,  // 失败的点断开，曲线上的缺口 = 不可达
    }],
  }, { notMerge: true });
}

let timer: ReturnType<typeof setInterval> | null = null;
function onResize() { trafficChart?.resize(); sysChart?.resize(); }
function onDocClick() { ifaceDropdownOpen.value = false; presetOpen.value = false; unitOpen.value = false; tzOpen.value = false; liveOpen.value = false; opsOpen.value = false; }

// 切换节点（props.nodeId 变化，组件复用 setup 不重跑）：重置状态并重新加载
watch(() => props.nodeId, (newId, oldId) => {
  if (!newId || newId === oldId) return;
  selectedIfaces.value = [];
  trafficStats.value = null;
  detail.value = null;
  trafficPoints.value = {};
  sysPoints.value = [];
  expandedMonId.value = null;
  monAvail.value = null;
  load();
  loadCharts();
});

onMounted(async () => {
  await load();        // 先拿节点详情（网卡清单），再画图表
  loadCharts();
  // 惰性扫描缓存：面板打开即有数据（10 分钟内快照直接用，过期后台重扫）
  viewFirewall(false);
  loadPbr(false);
  timer = setInterval(load, 5000);  // 5s 只刷状态类，图表不动
  uptimeTimer = setInterval(() => { uptimeTick.value++; }, 30000);
  window.addEventListener("resize", onResize);
  document.addEventListener("click", onDocClick);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
  if (uptimeTimer) clearInterval(uptimeTimer);
  stopLive();
  window.removeEventListener("resize", onResize);
  document.removeEventListener("click", onDocClick);
  trafficChart?.dispose();
  sysChart?.dispose();
  monChart?.dispose();
});

function goBack() { router.push({ path: "/status", query: { view: "nodes" } }); }

// ── 头部「操作」下拉：对本节点打流/MTR/命令（跳转工具页并预填本节点）──
const opsOpen = ref(false);
function goTool(t: "iperf" | "mtr" | "command" | "records") {
  opsOpen.value = false;
  router.push({ path: "/status", query: { view: "tools", tool: t, node: String(nodeId.value) } });
}
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
      <!-- 操作下拉：对本节点发起工具（跳转预填，无刷新） -->
      <div class="ops" @click.stop>
        <button class="ops-btn" @click="opsOpen = !opsOpen">
          <Icon name="zap" :size="13" /> 操作 <Icon name="chevron" :size="11" :class="{ rot: opsOpen }" />
        </button>
        <div v-if="opsOpen" class="ops-menu">
          <button @click="goTool('iperf')">打流测速</button>
          <button @click="goTool('mtr')">MTR 路径测试</button>
          <button @click="goTool('command')">下发命令</button>
          <button @click="goTool('records')">此节点记录</button>
        </div>
      </div>
    </header>

    <!-- 标签页导航 -->
    <nav class="d-tabs">
      <button class="d-tab" :class="{ active: activeTab === 'overview' }" @click="activeTab = 'overview'">概览</button>
      <button class="d-tab" :class="{ active: activeTab === 'network' }" @click="activeTab = 'network'">网络</button>
      <button class="d-tab" :class="{ active: activeTab === 'services' }" @click="activeTab = 'services'">服务监控</button>
    </nav>

    <!-- Tab 1 概览：基本信息 + 存储 + 流量 + 系统指标 -->
    <div v-show="activeTab === 'overview'" class="tab-body">

    <!-- 基本信息 + 存储 并排双栏 -->
    <div class="duo-grid">
    <!-- 基本信息面板 -->
    <section class="panel">
      <div class="panel-head"><span class="ph-title">基本信息</span></div>
      <div v-if="!detail?.sys_info && !detail?.os_name" class="empty">等待 agent 上报系统信息…</div>
      <div v-else class="info-grid">
        <div class="info-row"><span class="ik">系统</span><span class="iv">{{ detail!.os_name || detail!.platform }}</span></div>
        <div class="info-row" v-if="si?.kernel"><span class="ik">内核</span><span class="iv mono">{{ si.kernel }}</span></div>
        <div class="info-row" v-if="si?.cpu_model"><span class="ik">CPU</span><span class="iv">{{ si.cpu_model }}<template v-if="si.cpu_cores"> · {{ si.cpu_cores }} 核</template></span></div>
        <div class="info-row" v-if="si?.load1 != null"><span class="ik">负载</span><span class="iv mono">{{ si.load1 }} / {{ si.load5 }} / {{ si.load15 }}</span></div>
        <div class="info-row" v-if="uptimeText"><span class="ik">运行</span><span class="iv">{{ uptimeText }}</span></div>
        <div class="info-row" v-if="detail!.arch"><span class="ik">架构</span><span class="iv">{{ detail!.arch }}</span></div>
        <div class="info-row" v-if="detail!.agent_version"><span class="ik">agent</span><span class="iv">v{{ detail!.agent_version }}</span></div>
      </div>
    </section>

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
    </div><!-- /duo-grid -->

    <!-- 共享时间工具条：流量 + 系统指标 共用一组时间控件 -->
    <div class="chart-toolbar">
      <span class="tl-label">时间</span>
      <button class="range-btn" title="点击编辑起止时间" @click="openCustomEdit">
        {{ fmtTimeShort(span.startMs) }} <span class="range-sep">~</span> {{ fmtTimeShort(span.endMs) }}
      </button>
      <div class="pop-wrap">
        <button class="preset-btn" :class="{ active: timeRange !== '1h' }" :disabled="liveMode" @click.stop="presetOpen = !presetOpen">{{ rangeLabel }} ▾</button>
        <div v-if="presetOpen && !liveMode" class="pop-menu" @click.stop>
          <button v-for="p in PRESETS" :key="p.key" class="pop-item" :class="{ active: timeRange === p.key }" @click="selectPreset(p.key)">{{ p.label }}</button>
        </div>
      </div>

      <!-- 实时模式：窗口跟随当前时间滚动，每 3s 增量拉取 -->
      <button class="live-btn" :class="{ on: liveMode }" title="实时模式：窗口滚动，3s 增量刷新" @click="toggleLive">
        <span class="live-dot" /> 实时
      </button>
      <div v-if="liveMode" class="pop-wrap">
        <button class="ctrl-btn" @click.stop="liveOpen = !liveOpen">{{ LIVE_WINDOWS.find((w) => w.s === liveWindow)?.label || "5分钟" }} ▾</button>
        <div v-if="liveOpen" class="pop-menu" @click.stop>
          <button v-for="w in LIVE_WINDOWS" :key="w.s" class="pop-item" :class="{ active: liveWindow === w.s }" @click="pickLiveWindow(w.s)">{{ w.label }}</button>
        </div>
      </div>

      <!-- 时区下拉（两图共享） -->
      <div class="pop-wrap">
        <button class="ctrl-btn" @click.stop="tzOpen = !tzOpen">{{ TZ_OPTIONS.find((t) => t.offset === tzOffset)?.label || "UTC+8" }} ▾</button>
        <div v-if="tzOpen" class="pop-menu tz-menu" @click.stop>
          <button v-for="t in TZ_OPTIONS" :key="t.offset" class="pop-item" :class="{ active: tzOffset === t.offset }" @click="tzOffset = t.offset; tzOpen = false">{{ t.label }}</button>
        </div>
      </div>
    </div>

    <!-- 自定义时间编辑（深色主题弹层） -->
    <div v-if="customEditOpen" class="custom-range">
      <input type="datetime-local" v-model="customStart" @change="onCustomEdit" />
      <span class="cr-sep">~</span>
      <input type="datetime-local" v-model="customEnd" @change="onCustomEdit" />
      <button class="ghost-btn" @click="applyCustom">确定</button>
    </div>

    <!-- 流量面板 -->
    <section class="panel">
      <div class="panel-head">
        <span class="ph-title">流量</span>

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
        <span v-if="liveMode" class="live-hint"><span class="live-dot" /> 实时</span>
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
          <button class="ghost-btn" @click="showAllIfaces = !showAllIfaces">{{ showAllIfaces ? '收起虚拟网卡' : `全部 ${allIfaces.length} 张` }}</button>
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
          <span v-if="fwAt" class="ph-hint">{{ fmtScanTime(fwAt) }}{{ fwLoading ? " · 更新中…" : "" }}</span>
          <button class="ghost-btn" :disabled="fwLoading" @click="viewFirewall(true)">{{ fwLoading && !fwData ? '扫描中…' : '重新扫描' }}</button>
          <button v-if="fwData" class="ghost-btn" @click="fwShowRaw = !fwShowRaw">{{ fwShowRaw ? '收起原文' : '原文' }}</button>
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

        <!-- 结构化扫描结果 -->
        <div v-if="fwData" class="fw-scan">
          <div class="fw-view-tabs">
            <button class="fw-vtab" :class="{ active: fwView === 'ufw' }" @click="fwView = 'ufw'">UFW</button>
            <button class="fw-vtab" :class="{ active: fwView === 'iptables' }" @click="fwView = 'iptables'">iptables</button>
          </div>

          <!-- UFW 视图 -->
          <div v-if="fwView === 'ufw'" class="fw-body">
            <template v-if="fwData.ufw?.installed">
              <div class="fw-meta">
                <span class="fw-st" :class="fwData.ufw.active ? 'on' : 'off'">{{ fwData.ufw.active ? '已启用' : '未启用' }}</span>
                <span v-if="fwData.ufw.defaults" class="fw-defaults">默认策略：{{ fwData.ufw.defaults }}</span>
                <span v-if="fwData.ufw.logging" class="fw-defaults">日志：{{ fwData.ufw.logging }}</span>
              </div>
              <table v-if="fwData.ufw.rules?.length" class="fw-table">
                <thead><tr><th>#</th><th>目标（To）</th><th>动作</th><th>来源（From）</th></tr></thead>
                <tbody>
                  <tr v-for="r in fwData.ufw.rules" :key="r.num + (r.v6 ? '-v6' : '')">
                    <td class="mono">{{ r.num }}</td>
                    <td class="mono">{{ r.to }}</td>
                    <td><span class="fw-act" :class="r.action.startsWith('ALLOW') ? 'allow' : 'deny'">{{ r.action }}</span></td>
                    <td class="mono">{{ r.from }}{{ r.v6 ? ' (v6)' : '' }}</td>
                  </tr>
                </tbody>
              </table>
              <div v-else class="empty">没有规则（{{ fwData.ufw.active ? '启用中但规则为空' : '未启用' }}）</div>
            </template>
            <div v-else class="empty">该节点未安装 UFW</div>
          </div>

          <!-- iptables 五表视图 -->
          <div v-else class="fw-body">
            <template v-if="fwData.iptables?.installed && !fwData.iptables.error">
              <div class="fw-view-tabs sub">
                <button v-for="t in iptTables" :key="t" class="fw-vtab" :class="{ active: fwIptTab === t }" @click="fwIptTab = t">
                  {{ t }}<span class="fw-count">{{ fwData.iptables!.tables![t].rules.length }}</span>
                </button>
              </div>
              <template v-if="fwIptTab && fwData.iptables!.tables![fwIptTab]">
                <!-- 链概览 -->
                <div class="fw-chains">
                  <span v-for="ch in fwData.iptables!.tables![fwIptTab].chains" :key="ch.name" class="fw-chain" :title="`${ch.packets} 包 / ${(ch.bytes / 1e6).toFixed(1)} MB`">
                    {{ ch.name }}<b v-if="ch.policy" class="fw-pol" :class="ch.policy.toLowerCase()">{{ ch.policy }}</b>
                  </span>
                </div>
                <!-- 规则表：默认折叠防大表卡页面 -->
                <div class="fw-toggle" @click="toggleChain(fwIptTab)">
                  {{ fwChainsOpen[fwIptTab] ? '收起规则' : `展开 ${fwData.iptables!.tables![fwIptTab].rules.length} 条规则` }}
                </div>
                <div v-if="fwChainsOpen[fwIptTab]" class="fw-rules-wrap">
                  <table class="fw-table">
                    <thead><tr><th>链</th><th>目标</th><th>协议</th><th>端口</th><th>源</th><th>目的</th><th>接口</th></tr></thead>
                    <tbody>
                      <tr v-for="(r, i) in fwData.iptables!.tables![fwIptTab].rules" :key="i" :title="r.raw">
                        <td class="mono">{{ r.chain }}</td>
                        <td><span v-if="r.target" class="fw-act" :class="['ACCEPT', 'RETURN'].includes(r.target) ? 'allow' : (['DROP', 'REJECT'].includes(r.target) ? 'deny' : '')">{{ r.target }}</span></td>
                        <td class="mono">{{ r.proto || '*' }}</td>
                        <td class="mono">{{ r.dport ? ':' + r.dport : (r.sport ? 's:' + r.sport : '*') }}</td>
                        <td class="mono">{{ r.source || '*' }}</td>
                        <td class="mono">{{ r.dest || '*' }}</td>
                        <td class="mono">{{ [r.in_iface && 'in:' + r.in_iface, r.out_iface && 'out:' + r.out_iface].filter(Boolean).join(' ') || '*' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>
            </template>
            <div v-else-if="fwData.iptables?.error" class="empty">{{ fwData.iptables.error }}</div>
            <div v-else class="empty">该节点未安装 iptables</div>
          </div>
        </div>
        <pre v-if="fwShowRaw && fwData" class="cmd-output">{{ (fwData.ufw?.raw || '') + '\n=== iptables ===\n' + (fwData.iptables?.raw || '') }}</pre>
        <pre v-if="fwOutput" class="cmd-output">{{ fwOutput }}</pre>
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

      <!-- PBR 策略路由面板（结构化竖向展示，打开自动加载缓存，过期后台重扫） -->
      <section class="panel">
        <div class="panel-head">
          <span class="ph-title">策略路由（PBR）</span>
          <span v-if="pbrAt" class="ph-hint">{{ fmtScanTime(pbrAt) }}{{ pbrLoading ? " · 更新中…" : "" }}</span>
          <button class="ghost-btn" :disabled="pbrLoading" @click="loadPbr(true)">{{ pbrLoading && !pbrData ? '扫描中…' : '重新扫描' }}</button>
        </div>
        <div v-if="!pbrData && !pbrLoading" class="empty">加载中…</div>
        <template v-if="pbrData">
          <!-- 打标链：谁被打了什么标记 -->
          <div class="pbr-block">
            <div class="pbr-bt">打标规则（mangle）</div>
            <div v-if="!pbrData.marks.length" class="empty">无 MARK 打标规则</div>
            <div v-for="(m, i) in pbrData.marks" :key="i" class="pbr-item" :title="m.raw">
              <span class="pbr-k">链</span><span class="pbr-v mono">{{ m.chain }}</span>
              <span class="pbr-k">UID</span><span class="pbr-v mono">{{ m.uid ?? "全部" }}</span>
              <span class="pbr-k">标记</span><span class="pbr-v mono pbr-mark">{{ m.mark }}</span>
            </div>
          </div>
          <!-- 规则：标记/来源 → 路由表 -->
          <div class="pbr-block">
            <div class="pbr-bt">路由规则（ip rule，按优先级）</div>
            <div v-for="r in pbrData.rules" :key="r.pref" class="pbr-item" :title="r.raw">
              <span class="pbr-k">优先级</span><span class="pbr-v mono">{{ r.pref }}</span>
              <span class="pbr-k">匹配</span><span class="pbr-v mono">{{ r.mark ? `fwmark ${r.mark}` : (r.from ? `from ${r.from}` : "全部流量") }}</span>
              <span class="pbr-k">查表</span><span class="pbr-v mono pbr-table">{{ r.table }}</span>
            </div>
          </div>
          <!-- 路由表：每张表一个可折叠块 -->
          <div class="pbr-block">
            <div class="pbr-bt">路由表</div>
            <div v-for="(routes, tname) in pbrData.tables" :key="tname" class="pbr-tbl">
              <div class="pbr-tbl-head" @click="pbrOpen[tname] = !pbrOpen[tname]">
                <span class="mono">table {{ tname }}</span>
                <span class="pbr-cnt">{{ routes.length }} 条</span>
                <span class="pbr-chev">{{ pbrOpen[tname] ? "▾" : "▸" }}</span>
              </div>
              <template v-if="pbrOpen[tname]">
                <div v-for="(r, i) in routes" :key="i" class="pbr-item route" :title="r.raw">
                  <span class="pbr-k">目的</span><span class="pbr-v mono">{{ r.dst }}</span>
                  <span v-if="r.via" class="pbr-k">网关</span><span v-if="r.via" class="pbr-v mono">{{ r.via }}</span>
                  <span v-if="r.dev" class="pbr-k">出口</span><span v-if="r.dev" class="pbr-v mono">{{ r.dev }}</span>
                </div>
              </template>
            </div>
          </div>
        </template>
      </section>

      <!-- Docker：独立 tab（侧栏 Docker），这里只留状态 + 入口 -->
      <section class="panel">
        <div class="panel-head">
          <span class="ph-title">Docker</span>
          <span v-if="dkComp?.installed" class="fw-st" :class="dkComp.running ? 'on' : 'off'">{{ dkComp.running ? '运行中' : '已安装（守护未运行）' }}</span>
          <span v-else-if="dkComp && !dkComp.installed" class="fw-st off">未安装</span>
          <button v-if="dkComp?.installed" class="ghost-btn" @click="goDockerTab">打开面板</button>
        </div>
        <div v-if="dkComp && !dkComp.installed" class="empty">该节点未安装 Docker（可在服务器页组件区代装）</div>
      </section>
    </div>

    <!-- Tab 3 服务监控 -->
    <div v-show="activeTab === 'services'" class="tab-body">
    <!-- 监控项面板 -->
    <section class="panel">
      <div class="panel-head">
        <span class="ph-title">服务监控</span>
        <span class="ph-hint">增删在总览页 · 点击展开延迟曲线</span>
      </div>
      <div class="mon-list">
        <div v-if="!monitors.length" class="empty">该节点还没有监控项</div>
        <template v-for="m in monitors" :key="m.id">
          <div class="mon-row clickable" :class="{ open: expandedMonId === m.id }" @click="toggleMon(m.id)">
            <span class="mon-type">{{ typeLabel[m.type] }}</span>
            <span class="mon-name">{{ m.name }}</span>
            <span class="mon-target">{{ m.target }}</span>
            <span v-if="m.last_latency_ms != null" class="mon-lat">{{ m.last_latency_ms.toFixed(1) }}ms</span>
            <span class="mon-status" :class="m.status">{{ m.status === "up" ? "UP" : m.status === "down" ? "DOWN" : "—" }}</span>
            <button class="mon-op" title="详情浮窗（图表 / MTR / 编辑）" @click.stop="openMonModal(m)"><Icon name="activity" :size="13" /></button>
            <Icon name="chevron" :size="12" class="mon-chev" :class="{ rot: expandedMonId === m.id }" />
          </div>
          <div v-if="expandedMonId === m.id" class="mon-detail">
            <div v-if="monAvail" class="mon-stats">
              24h 可用率 <b :class="{ bad: monAvail.pct < 99 }">{{ monAvail.pct.toFixed(1) }}%</b>
              <template v-if="monAvail.avg != null"> · 平均延迟 <b>{{ monAvail.avg.toFixed(1) }} ms</b></template>
              · 探测 {{ monAvail.total }} 次
            </div>
            <div class="mon-ranges">
              <button v-for="r in MON_RANGES" :key="r.key" class="range-chip" :class="{ active: monRange === r.key }" @click.stop="pickMonRange(r.key)">{{ r.label }}</button>
            </div>
            <div :id="`mon-chart-${m.id}`" class="mon-chart"></div>
            <div v-if="!monSeries.length" class="empty">该范围内暂无探测数据</div>
          </div>
        </template>
      </div>
    </section>
    </div>

    <!-- 监控项详情浮窗（图表 / MTR 记录 / 编辑） -->
    <MonitorDetailModal
      v-if="monModal"
      :monitor="monModal"
      :node-name="detail?.name ?? ''"
      @close="monModal = null"
      @saved="monModal = null; load()"
    />
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
/* 共享时间工具条 */
.chart-toolbar { display: flex; align-items: center; gap: 10px; margin: 0 0 12px 2px; flex-wrap: wrap; }
/* 实时开关 */
.live-btn {
  display: inline-flex; align-items: center; gap: 6px;
  background: transparent; border: 1px solid rgba(255,255,255,0.12); color: var(--text-lo);
  border-radius: 999px; padding: 5px 14px; cursor: pointer; font-size: 12.5px;
  transition: all var(--transition);
}
.live-btn:hover { border-color: var(--accent-dim); color: var(--text-hi); }
.live-btn.on { border-color: var(--pink); color: var(--pink); background: rgba(255,158,199,0.08); }
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; opacity: 0.5; }
.live-btn.on .live-dot { opacity: 1; animation: livePulse 1.6s ease-in-out infinite; }
@keyframes livePulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
.live-hint { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: var(--pink); font-weight: 400; }
.live-hint .live-dot { opacity: 1; animation: livePulse 1.6s ease-in-out infinite; }
/* 深色主题的原生日期时间控件（color-scheme 让 Chrome 用深色 picker） */
.custom-range input[type="datetime-local"] {
  color-scheme: dark;
  background: var(--bg-raised); border: 1px solid rgba(255,255,255,0.12);
  border-radius: var(--radius-sm); color: var(--text-hi);
  padding: 6px 10px; font-size: 12.5px; outline: none;
}
.custom-range input[type="datetime-local"]:focus { border-color: var(--accent-dim); }
/* 操作下拉 */
.ops { position: relative; }
.ops-btn {
  display: inline-flex; align-items: center; gap: 6px;
  background: transparent; border: 1px solid rgba(255,255,255,0.12); color: var(--text-lo);
  border-radius: var(--radius-sm); padding: 6px 12px; cursor: pointer; font-size: 13px;
  transition: all var(--transition);
}
.ops-btn:hover { color: var(--accent); border-color: var(--accent-dim); }
.ops-menu {
  position: absolute; top: calc(100% + 4px); right: 0; z-index: 30; min-width: 140px;
  background: var(--bg-raised); border: 1px solid rgba(255,255,255,0.1);
  border-radius: var(--radius-sm); padding: 4px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4); display: flex; flex-direction: column;
}
.ops-menu button {
  background: transparent; border: none; color: var(--text-lo); text-align: left;
  padding: 8px 12px; border-radius: 4px; cursor: pointer; font-size: 13px;
  transition: all var(--transition); white-space: nowrap;
}
.ops-menu button:hover { background: var(--bg-panel); color: var(--accent); }
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
/* 基本信息 + 存储 并排双栏（窄屏自动单列） */
.duo-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 1100px) { .duo-grid { grid-template-columns: 1fr; } }
.info-grid { display: flex; flex-direction: column; gap: 7px; margin-top: 6px; }
.info-row { display: flex; gap: 10px; align-items: baseline; font-size: 12.5px; }
.ik { color: var(--text-faint); flex-shrink: 0; width: 34px; }
.iv { color: var(--text-hi); word-break: break-all; }
.iv.mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
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

/* ghost-btn 基础样式已上移到全局 style.css */
.mon-add { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; }
.mon-add input, .mon-add select {
  background: var(--bg-base); border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-sm); color: var(--text-hi); padding: 6px 10px; font-size: 13px;
}
.mon-list { display: flex; flex-direction: column; gap: 4px; }
.empty { font-size: 13px; color: var(--text-faint); padding: 12px 0; }
.mon-row { display: flex; align-items: center; gap: 10px; padding: 7px 8px; border-radius: 4px; }
.mon-row:hover { background: var(--bg-raised); }
.mon-row.clickable { cursor: pointer; }
.mon-row.open { background: var(--bg-raised); }
.ph-hint { font-size: 11px; color: var(--text-faint); font-weight: 400; }
.mon-lat { font-size: 12px; color: var(--accent); }
.mon-chev { color: var(--text-faint); transition: transform var(--transition); }
.mon-chev.rot { transform: rotate(90deg); }
.mon-op { border: none; background: transparent; color: var(--text-faint); cursor: pointer; padding: 3px; }
.mon-op:hover { color: var(--accent); }
.mon-detail { padding: 8px 10px 12px; border-radius: 0 0 4px 4px; background: var(--bg-raised); margin-bottom: 6px; }
.mon-stats { font-size: 12px; color: var(--text-lo); margin-bottom: 8px; }
.mon-stats b { color: var(--text-hi); font-weight: 475; }
.mon-stats b.bad { color: #e58a8a; }
.mon-ranges { display: flex; gap: 4px; margin-bottom: 8px; }
.range-chip {
  background: transparent; border: 1px solid rgba(255,255,255,0.1); color: var(--text-lo);
  border-radius: 999px; padding: 3px 12px; font-size: 11.5px; cursor: pointer; transition: all var(--transition);
}
.range-chip:hover { border-color: var(--accent-dim); color: var(--text-hi); }
.range-chip.active { border-color: var(--accent-dim); color: var(--accent); background: rgba(158,183,229,0.08); }
.mon-chart { height: 180px; }
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

/* ── 防火墙结构化扫描 ── */
.fw-scan { margin-top: 10px; border-top: 1px solid rgba(255, 255, 255, 0.06); padding-top: 10px; }
.fw-view-tabs { display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
.fw-view-tabs.sub { margin-bottom: 8px; }
.fw-vtab {
  background: transparent; border: 1px solid rgba(255, 255, 255, 0.08); color: var(--text-lo);
  border-radius: var(--radius-sm); padding: 3px 12px; font-size: 12px; cursor: pointer;
  font-family: var(--font-mono); display: inline-flex; align-items: center; gap: 6px;
}
.fw-vtab:hover { border-color: var(--accent-dim); color: var(--text-hi); }
.fw-vtab.active { border-color: var(--pink); color: var(--pink); }
.fw-count {
  font-size: 10px; background: rgba(255, 255, 255, 0.08); border-radius: 8px;
  padding: 0 6px; color: var(--text-faint);
}
.fw-vtab.active .fw-count { background: rgba(255, 158, 199, 0.15); color: var(--pink); }
.fw-meta { display: flex; align-items: center; gap: 14px; margin-bottom: 10px; flex-wrap: wrap; }
.fw-defaults { font-size: 12px; color: var(--text-faint); }
.fw-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.fw-table th {
  text-align: left; color: var(--text-faint); font-weight: 500; padding: 5px 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08); font-size: 11px;
}
.fw-table td { padding: 5px 8px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); color: var(--text-lo); }
.fw-table td.mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.fw-table tbody tr:hover td { background: rgba(255, 255, 255, 0.02); }
.fw-act { font-size: 11px; font-family: var(--font-mono); color: var(--text-lo); }
.fw-act.allow { color: #7be39a; }
.fw-act.deny { color: #ff8f8f; }
.fw-chains { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.fw-chain {
  font-size: 11px; font-family: var(--font-mono); color: var(--text-lo);
  border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; padding: 2px 8px;
  display: inline-flex; align-items: center; gap: 5px;
}
.fw-pol { font-weight: 600; font-size: 10px; }
.fw-pol.accept { color: #7be39a; }
.fw-pol.drop { color: #ff8f8f; }
.fw-toggle {
  font-size: 12px; color: var(--accent-hi); cursor: pointer; padding: 4px 0; user-select: none;
}
.fw-toggle:hover { color: var(--pink); }
.fw-rules-wrap { max-height: 420px; overflow: auto; }

/* ── Docker 面板 ── */
.dk-list-wrap { max-height: 420px; overflow: auto; margin-top: 8px; }
.dk-table .dk-name { color: var(--text-hi); }
.dk-image { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dk-ports { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.dk-state { white-space: nowrap; font-size: 12px; }
.dk-state.up { color: #7be39a; }
.dk-state.down { color: var(--text-faint); }
.dk-ops { white-space: nowrap; text-align: right; }

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

/* ── PBR 结构化竖向展示 ── */
.pbr-block { margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 8px; }
.pbr-bt { font-size: 12px; color: var(--text-faint); margin-bottom: 6px; }
.pbr-item { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; padding: 5px 8px; border-radius: 6px; background: rgba(255,255,255,0.02); margin-bottom: 4px; font-size: 12px; }
.pbr-item.route { margin-left: 10px; }
.pbr-k { color: var(--text-faint); font-size: 11px; flex-shrink: 0; }
.pbr-v { color: var(--text-hi); word-break: break-all; min-width: 0; }
.pbr-v.mono { font-family: var(--font-mono, monospace); font-size: 11.5px; }
.pbr-mark, .pbr-table { color: var(--pink); }
.pbr-tbl { margin-bottom: 4px; }
.pbr-tbl-head { display: flex; align-items: center; gap: 8px; cursor: pointer; padding: 5px 8px; border-radius: 6px; color: var(--text-hi); font-size: 12.5px; }
.pbr-tbl-head:hover { background: rgba(255,255,255,0.04); }
.pbr-cnt { color: var(--text-faint); font-size: 11px; }
.pbr-chev { margin-left: auto; color: var(--text-faint); }

/* 移动端：防火墙七列宽表转竖向卡片（行=块，单元格带标签竖排） */
@media (max-width: 768px) {
  .fw-table, .fw-table thead, .fw-table tbody, .fw-table tr, .fw-table td { display: block; }
  .fw-table thead { display: none; }
  .fw-table tr { border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; margin-bottom: 8px; padding: 6px 10px; }
  .fw-table td { padding: 2px 0; border: none; word-break: break-all; }
}
</style>
