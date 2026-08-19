<script setup lang="ts">
// 总览页三区：服务器卡（状态+CPU/内存迷你条）+ 流量速览（选一台+实时开关）+ 服务监控（图表⇄简易双模式）。
// 定位：全局健康一眼看 + 跳转入口。5s 刷状态；图表区独立节奏（静态不自动刷，实时 3s 增量）。
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from "vue";
import { useRouter } from "vue-router";
import * as echarts from "echarts";
import {
  listNodes, getNodeDetail, getNodeMetrics, listMonitors, createMonitor, removeMonitor, getMonitorSeries,
  type Node, type NodeDetail, type Monitor, type MetricPoint,
} from "../../api/servers";
import { toast } from "../../composables/useToast";
import Icon from "../../shell/Icon.vue";
import Dropdown from "../../shell/Dropdown.vue";
import MonitorDetailModal from "./MonitorDetailModal.vue";

const router = useRouter();
const nodes = ref<Node[]>([]);
const nodeDetails = ref<Record<number, NodeDetail>>({});
const monitors = ref<Monitor[]>([]);

// ═══════════ 区1：服务器卡 ═══════════
const statusLabel: Record<string, string> = { online: "在线", offline: "离线", pending: "待报到", removed: "已移除" };
const statusColor: Record<string, string> = { online: "var(--pink)", offline: "var(--text-faint)", pending: "var(--accent-dim)", removed: "var(--text-faint)" };

function cpuPct(n: Node): number | null { return nodeDetails.value[n.id]?.latest_sys_metric?.cpu_pct ?? null; }
function memPct(n: Node): number | null { return nodeDetails.value[n.id]?.latest_sys_metric?.mem_pct ?? null; }

// ═══════════ 区2：流量速览 ═══════════
const trafficNodeId = ref<number | null>(null);
const trafficLive = ref(true);           // 默认实时（速览就是要看现在）
const trafficWindow = ref(300);          // 实时窗长（秒）
const winOpen = ref(false);
const LIVE_WINDOWS = [
  { s: 300, label: "5分钟" }, { s: 900, label: "15分钟" }, { s: 1800, label: "30分钟" }, { s: 3600, label: "1小时" },
];
const trafficPoints = ref<MetricPoint[]>([]);
const trafficIface = ref<string>("");
const chartEl = ref<HTMLElement | null>(null);
let chart: echarts.ECharts | null = null;
let liveTimer: ReturnType<typeof setInterval> | null = null;
let trafficSeq = 0;

const onlineNodes = computed(() => nodes.value.filter((n) => n.status === "online"));
const trafficNodeOptions = computed(() => onlineNodes.value.map((n) => ({ value: n.id, label: n.name })));

// 网卡下拉：物理且 up 的接口，默认路由网卡标注
const trafficIfaceOptions = computed(() => {
  const n = nodeDetails.value[trafficNodeId.value ?? -1];
  if (!n) return [];
  return Object.entries(n.interfaces || {})
    .filter(([, m]) => m.is_physical && m.up)
    .map(([name, m]) => ({ value: name, label: m.is_default ? `${name}（默认）` : name }));
});

function defaultIface(n: NodeDetail | undefined): string {
  if (!n) return "";
  const ifaces = n.interfaces || {};
  const phys = Object.entries(ifaces).filter(([, m]) => m.is_physical && m.up);
  const def = phys.find(([, m]) => m.is_default) || phys[0];
  return def ? def[0] : "";
}

async function fetchTraffic(full: boolean) {
  const id = trafficNodeId.value;
  const iface = trafficIface.value;
  if (!id || !iface) { trafficPoints.value = []; paintTraffic(); return; }
  const seq = ++trafficSeq;
  const now = new Date();
  // 5s 采样：点数随窗长走（1h=720 点），写死 300 会把 1h 窗截成 25 分钟
  let start: string, end = now.toISOString(), limit = Math.ceil(trafficWindow.value / 5) + 20;
  const existing = trafficPoints.value;
  if (!full && existing.length) {
    start = new Date(new Date(existing[existing.length - 1].ts).getTime() + 1000).toISOString();
    limit = 100;  // 增量补点不需要全窗上限
  } else {
    start = new Date(now.getTime() - trafficWindow.value * 1000).toISOString();
  }
  try {
    const data = await getNodeMetrics(id, { iface, start, end, limit });
    if (seq !== trafficSeq) return;
    const pts = [...data].reverse();
    if (full || !existing.length) trafficPoints.value = pts;
    else {
      const lastTs = new Date(existing[existing.length - 1].ts).getTime();
      let merged = [...existing, ...pts.filter((p) => new Date(p.ts).getTime() > lastTs)];
      merged = merged.filter((p) => new Date(p.ts).getTime() >= Date.now() - trafficWindow.value * 1000);
      trafficPoints.value = merged;
    }
    paintTraffic();
  } catch { /* 静默 */ }
}

function fmtAxisTime(ms: number): string {
  const d = new Date(ms + 480 * 60000);  // 速览固定 UTC+8（详情页才有时区选择）
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`.slice(0, 5);
}
function rateBps(delta: number): number { return Math.max(0, delta * 8 / 5); }  // 5s 采样间隔 → bps
function fmtBps(v: number): string {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + " Gbps";
  if (v >= 1e6) return (v / 1e6).toFixed(1) + " Mbps";
  if (v >= 1e3) return (v / 1e3).toFixed(0) + " Kbps";
  return v.toFixed(0) + " bps";
}

function paintTraffic() {
  if (!chartEl.value) return;
  chart = echarts.getInstanceByDom(chartEl.value) || echarts.init(chartEl.value);
  const pts = trafficPoints.value;
  chart.setOption({
    backgroundColor: "transparent",
    grid: { left: 56, right: 16, top: 26, bottom: 22 },
    tooltip: {
      trigger: "axis",
      formatter: (params: any) => {
        if (!params?.length) return "";
        let html = `${params[0].axisValue}<br/>`;
        for (const prm of params) html += `${prm.marker}${prm.seriesName}：<b>${fmtBps(prm.value)}</b><br/>`;
        return html;
      },
    },
    legend: { textStyle: { color: "#9aa0aa" }, top: 0, right: 0 },
    xAxis: {
      type: "category", boundaryGap: false,
      data: pts.map((p) => fmtAxisTime(new Date(p.ts).getTime())),
      axisLine: { lineStyle: { color: "#2a2d35" } }, axisLabel: { color: "#9aa0aa" },
    },
    yAxis: {
      type: "value", axisLabel: { color: "#9aa0aa", formatter: (v: number) => fmtBps(v) },
      splitLine: { lineStyle: { color: "#1f2229" } },
    },
    series: [
      { name: "↓ 下载", type: "line", smooth: true, showSymbol: false, animation: false,
        data: pts.map((p) => Math.round(rateBps(p.rx_delta))), lineStyle: { width: 1.5 }, itemStyle: { color: "#9eb7e5" }, areaStyle: { opacity: 0.08 } },
      { name: "↑ 上传", type: "line", smooth: true, showSymbol: false, animation: false,
        data: pts.map((p) => Math.round(rateBps(p.tx_delta))), lineStyle: { width: 1.5, type: "dashed" }, itemStyle: { color: "#ff9ec7" } },
    ],
  }, { notMerge: true });
}

function startLive() { stopLive(); liveTimer = setInterval(() => fetchTraffic(false), 3000); }
function stopLive() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null; } }
watch(trafficLive, (on) => { if (on) { fetchTraffic(true); startLive(); } else stopLive(); });
watch(trafficWindow, () => { if (trafficLive.value) fetchTraffic(true); });
watch(trafficNodeId, async () => {
  trafficIface.value = defaultIface(nodeDetails.value[trafficNodeId.value ?? -1]);
  trafficPoints.value = [];
  await fetchTraffic(true);
});
// 换网卡：清空重来
watch(trafficIface, () => { trafficPoints.value = []; fetchTraffic(true); });

// ═══════════ 区3：服务监控（双模式）═══════════
const monMode = ref<"chart" | "simple">((localStorage.getItem("stella_mon_mode") as "chart" | "simple") || "chart");
function setMonMode(m: "chart" | "simple") {
  monMode.value = m;
  localStorage.setItem("stella_mon_mode", m);
  loadMonAll();
}
const monStatusColor: Record<string, string> = { up: "var(--pink)", down: "var(--text-faint)", unknown: "var(--accent-dim)" };
const sparks = ref<Record<number, { ts: string; latency_ms: number | null; success: boolean }[]>>({});
const sparkEls = new Map<number, HTMLElement>();
// 24h 逐小时桶：图表模式算可用率、简易模式画色块，一次查询喂两个模式
const monDaily = ref<Record<number, { avail: number | null; loss: number | null; buckets: { ts: string; success: boolean; latency_ms: number | null }[] }>>({});

async function loadMonDaily() {
  const end = new Date();
  const start = new Date(end.getTime() - 86400000);
  for (const m of monitors.value) {
    try {
      // 两次取数：小时桶画色块；原始点按探测次数算可用率（和详情页口径一致，桶粒度会虚低）
      const [buckets, raw] = await Promise.all([
        getMonitorSeries(m.id, { start: start.toISOString(), end: end.toISOString(), step: 3600 }),
        getMonitorSeries(m.id, { start: start.toISOString(), end: end.toISOString(), limit: 3000 }),
      ]);
      const ok = raw.filter((c) => c.success).length;
      // 丢包率：ping 有逐次 loss_pct 用真实值；其余类型用失败率
      const withLoss = raw.filter((c) => c.loss_pct != null);
      const loss = !raw.length ? null
        : withLoss.length ? withLoss.reduce((s, c) => s + (c.loss_pct ?? 0), 0) / withLoss.length
        : (raw.length - ok) / raw.length * 100;
      monDaily.value[m.id] = { avail: raw.length ? ok / raw.length * 100 : null, loss, buckets };
    } catch { /* 单个失败不影响其他 */ }
  }
}

// 简易模式的 24 格色块：对齐到小时，无数据的小时=null（空心）
function hourBlocks(id: number): ({ ok: boolean; label: string } | null)[] {
  const buckets = monDaily.value[id]?.buckets || [];
  const byHour = new Map<number, { success: boolean; latency_ms: number | null }>();
  for (const b of buckets) {
    const d = new Date(b.ts);
    d.setMinutes(0, 0, 0);
    byHour.set(d.getTime(), b);
  }
  const out: ({ ok: boolean; label: string } | null)[] = [];
  const cur = new Date();
  cur.setMinutes(0, 0, 0);
  for (let i = 23; i >= 0; i--) {
    const h = new Date(cur.getTime() - i * 3600000);
    const b = byHour.get(h.getTime());
    if (!b) { out.push(null); continue; }
    out.push({ ok: b.success, label: `${h.getHours()}时 · ${b.success ? "正常" : "故障"}${b.latency_ms != null ? " · " + b.latency_ms.toFixed(0) + "ms" : ""}` });
  }
  return out;
}

// 监控图表数据统一入口：24h 小时桶（两种模式都用）+ 图表模式的 1h sparkline
function loadMonAll() {
  loadMonDaily();
  if (monMode.value === "chart") loadSparklines();
}

async function loadSparklines() {
  const end = new Date();
  const start = new Date(end.getTime() - 3600000);  // 近 1 小时
  for (const m of monitors.value) {
    try {
      sparks.value[m.id] = await getMonitorSeries(m.id, { start: start.toISOString(), end: end.toISOString() });
    } catch { /* 单个失败不影响其他 */ }
  }
  await nextTick();
  paintSparklines();
}
function setSparkEl(id: number, el: any) {
  if (el instanceof HTMLElement) sparkEls.set(id, el);
}
function paintSparklines() {
  for (const m of monitors.value) {
    const el = sparkEls.get(m.id);
    const pts = sparks.value[m.id];
    if (!el || !pts?.length) continue;
    const c = echarts.getInstanceByDom(el) || echarts.init(el);
    const lats = pts.filter((p) => p.success && p.latency_ms != null).map((p) => p.latency_ms!);
    const max = lats.length ? Math.max(...lats) : 1;
    c.setOption({
      backgroundColor: "transparent",
      grid: { left: 0, right: 0, top: 2, bottom: 0 },
      xAxis: { type: "category", show: false, data: pts.map((p) => p.ts), boundaryGap: false },
      yAxis: { type: "value", show: false, min: 0, max: max * 1.15 },
      series: [{
        type: "line", showSymbol: false, animation: false, smooth: true,
        data: pts.map((p) => (p.success && p.latency_ms != null ? p.latency_ms : null)),
        lineStyle: { width: 1 }, itemStyle: { color: "#9eb7e5" }, areaStyle: { opacity: 0.15 },
        connectNulls: false,
      }],
    }, { notMerge: true });
  }
}
let sparkTimer: ReturnType<typeof setInterval> | null = null;

// ── 添加监控弹窗（编辑在 MonitorDetailModal 的 tab3）──
const showMonDialog = ref(false);
const monName = ref("");
const monType = ref<"ping" | "tcp" | "udp" | "http" | "https">("tcp");
const monHost = ref("");   // 主机/IP/域名（http(s) 可带路径）
const monPort = ref("");   // 端口单独输入，ping 无端口
const monInterval = ref(60);
const monNodeId = ref<number | null>(null);
const MON_TYPES = [
  { value: "tcp", label: "TCP 端口" }, { value: "http", label: "HTTP" }, { value: "https", label: "HTTPS" },
  { value: "ping", label: "Ping" }, { value: "udp", label: "UDP" },
];
const addNodeOptions = computed(() => nodes.value.map((n) => ({ value: n.id, label: n.name })));
const monNeedPort = computed(() => monType.value !== "ping");
const monPortRequired = computed(() => monType.value === "tcp" || monType.value === "udp");
const monPortPlaceholder = computed(() =>
  monType.value === "https" ? "默认 443" : monType.value === "http" ? "默认 80" : "1-65535");

// 提交拼接：全角冒号→半角、去空白，端口合法性校验
function composeTarget(): string | null {
  const host = monHost.value.replace(/：/g, ":").replace(/\s+/g, "").trim();
  const port = monPort.value.replace(/\D/g, "");
  if (!host) { toast("主机要填喵~"); return null; }
  if (monType.value !== "ping") {
    if (!port && monPortRequired.value) { toast("TCP/UDP 必须填端口喵~"); return null; }
    if (port) {
      const p = Number(port);
      if (p < 1 || p > 65535) { toast("端口范围是 1-65535 喵~"); return null; }
      return `${host}:${p}`;
    }
  }
  return host;
}

function openAddMon() {
  if (!nodes.value.length) { toast("还没有纳管节点，先去「服务器」页添加一台喵~"); return; }
  monName.value = ""; monHost.value = ""; monPort.value = "";
  monType.value = "tcp"; monInterval.value = 60;
  monNodeId.value = nodes.value[0].id;
  showMonDialog.value = true;
}
async function saveMonitor() {
  if (!monName.value.trim()) { toast("名称要填喵~"); return; }
  if (monNodeId.value == null) { toast("要先选探测节点喵~"); return; }
  const target = composeTarget();
  if (target == null) return;
  try {
    await createMonitor({ name: monName.value.trim(), type: monType.value, target, interval: monInterval.value, node_id: monNodeId.value });
    toast("监控项已添加");
    showMonDialog.value = false;
    await refresh();
    if (monMode.value === "chart") loadSparklines();
  } catch { toast("添加失败"); }
}

// ── 监控项详情浮窗（点卡片=图表 tab，点编辑=编辑 tab）──
const detailMon = ref<Monitor | null>(null);
const detailTab = ref<"chart" | "mtr" | "edit">("chart");
function openDetail(m: Monitor, t: "chart" | "mtr" | "edit" = "chart") {
  detailTab.value = t;
  detailMon.value = m;
}
function nodeName(id: number): string {
  return nodes.value.find((n) => n.id === id)?.name ?? `#${id}`;
}

async function delMonitor(m: Monitor, ev: Event) {
  ev.stopPropagation();  // 卡片本体是详情浮窗，删除不触发
  try { await removeMonitor(m.id); toast("已删除"); await refresh(); } catch { toast("删除失败"); }
}

// ═══════════ 轮询 ═══════════
let timer: ReturnType<typeof setInterval> | null = null;
async function refresh() {
  try {
    [nodes.value, monitors.value] = await Promise.all([listNodes(), listMonitors()]);
    // 逐台拿详情（latest_sys_metric 喂迷你条）——节点数少，量级可控
    const details = await Promise.all(nodes.value.filter((n) => n.status === "online").map((n) => getNodeDetail(n.id).catch(() => null)));
    const map: Record<number, NodeDetail> = {};
    for (const d of details) if (d) map[d.id] = d;
    nodeDetails.value = map;
    // 流量速览默认选第一台在线节点
    if (trafficNodeId.value === null && onlineNodes.value.length) {
      trafficNodeId.value = onlineNodes.value[0].id;
    }
  } catch { /* 后端未就绪静默 */ }
}
onMounted(() => {
  refresh();
  timer = setInterval(refresh, 5000);   // 5s 只刷状态（卡片/监控状态），图表区不管
  loadMonAll();
  sparkTimer = setInterval(loadMonAll, 60000);  // 图表数据 60s 一轮（两种模式都要）
  window.addEventListener("resize", onResize);
  document.addEventListener("click", onDocClick);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
  if (sparkTimer) clearInterval(sparkTimer);
  stopLive();
  window.removeEventListener("resize", onResize);
  document.removeEventListener("click", onDocClick);
  chart?.dispose();
});
function onResize() { chart?.resize(); paintSparklines(); }
function onDocClick() { winOpen.value = false; }
// 监控项列表晚于 onMounted 回来，id 集合变化时（首次加载/增删）补图表数据
watch(() => monitors.value.map((m) => m.id).join(","), (v, old) => {
  if (v !== old) loadMonAll();
});
</script>

<template>
  <div class="overview">
    <div class="head">
      <h2>总览</h2>
      <span class="sub">监控看板 · 状态 5s 刷新</span>
    </div>

    <!-- 区1：服务器卡 -->
    <section class="block">
      <div class="block-head">服务器</div>
      <div class="card-grid">
        <div v-for="n in nodes" :key="n.id" class="srv-card clickable" title="查看详情" @click="router.push(`/status/${n.id}`)">
          <span class="dot" :style="{ background: statusColor[n.status] }" />
          <div class="srv-main">
            <div class="srv-line1">
              <span class="name">{{ n.name }}</span>
              <span class="plat">{{ n.platform }}</span>
              <span class="st">{{ statusLabel[n.status] }}</span>
            </div>
            <div v-if="n.status === 'online'" class="srv-bars">
              <span class="mini-bar" :title="`CPU ${cpuPct(n)?.toFixed(0) ?? '-'}%`">
                <span class="mb-label">CPU</span>
                <span class="mb-track"><span class="mb-fill" :style="{ width: (cpuPct(n) ?? 0) + '%' }" /></span>
                <span class="mb-val">{{ cpuPct(n) != null ? cpuPct(n)!.toFixed(0) + "%" : "—" }}</span>
              </span>
              <span class="mini-bar" :title="`内存 ${memPct(n)?.toFixed(0) ?? '-'}%`">
                <span class="mb-label">MEM</span>
                <span class="mb-track"><span class="mb-fill mem" :style="{ width: (memPct(n) ?? 0) + '%' }" /></span>
                <span class="mb-val">{{ memPct(n) != null ? memPct(n)!.toFixed(0) + "%" : "—" }}</span>
              </span>
            </div>
          </div>
        </div>
        <div v-if="!nodes.length" class="hint-empty">暂无节点，去「服务器」页添加</div>
      </div>
    </section>

    <!-- 区2：流量速览 -->
    <section class="block">
      <div class="block-head">
        流量速览
        <Dropdown v-model="trafficNodeId" :options="trafficNodeOptions" class="ov-drop" />
        <button class="live-btn" :class="{ on: trafficLive }" title="实时：3s 增量刷新，窗口滚动" @click="trafficLive = !trafficLive">
          <span class="live-dot" /> 实时
        </button>
        <div class="pop-wrap">
          <button class="win-btn" @click.stop="winOpen = !winOpen">{{ LIVE_WINDOWS.find((w) => w.s === trafficWindow)?.label }} ▾</button>
          <div v-if="winOpen" class="pop-menu" @click.stop>
            <button v-for="w in LIVE_WINDOWS" :key="w.s" class="pop-item" :class="{ active: trafficWindow === w.s }" @click="trafficWindow = w.s; winOpen = false">{{ w.label }}</button>
          </div>
        </div>
        <span class="flex-spacer" />
        <Dropdown v-model="trafficIface" :options="trafficIfaceOptions" class="ov-drop iface-drop" />
      </div>
      <div class="chart-box">
        <div v-if="!onlineNodes.length" class="hint-empty">暂无在线节点</div>
        <div v-show="onlineNodes.length" ref="chartEl" class="ov-chart"></div>
      </div>
    </section>

    <!-- 区3：服务监控（双模式） -->
    <section class="block">
      <div class="block-head">
        服务监控
        <button class="mini-btn" @click="openAddMon"><Icon name="plus" :size="12" /> 添加</button>
        <span class="flex-spacer" />
        <div class="mode-switch">
          <button class="ms-btn" :class="{ active: monMode === 'chart' }" title="图表模式：每项带 1h 延迟走势" @click="setMonMode('chart')"><Icon name="activity" :size="12" /> 图表</button>
          <button class="ms-btn" :class="{ active: monMode === 'simple' }" title="简易模式：24h 逐小时状态色块" @click="setMonMode('simple')">简易</button>
        </div>
      </div>
      <div class="mon-grid">
        <div v-for="m in monitors" :key="m.id" class="mon-card clickable" title="点击查看详情" @click="openDetail(m)">
          <span class="dot" :style="{ background: monStatusColor[m.status] }" />
          <div class="mon-info">
            <div class="mon-name">{{ m.name }}</div>
            <div class="mon-target">{{ m.type }} · {{ m.target }}</div>
            <div v-if="monDaily[m.id]?.avail != null" class="mon-avail">
              24h 可用率 {{ monDaily[m.id].avail!.toFixed(1) }}%<template v-if="monDaily[m.id]?.loss != null"> · 丢包 {{ monDaily[m.id].loss!.toFixed(1) }}%</template>
            </div>
            <div v-if="monMode === 'chart'" :ref="(el) => setSparkEl(m.id, el)" class="spark"></div>
            <!-- 简易模式：uptime-kuma 式 24h 逐小时色块（实心=正常，红=故障，空心=无数据） -->
            <div v-else class="mon-blocks">
              <span
                v-for="(b, i) in hourBlocks(m.id)" :key="i"
                class="blk" :class="{ up: b?.ok, down: b && !b.ok }"
                :title="b?.label || '无数据'"
              />
            </div>
          </div>
          <span class="mon-latency" v-if="m.last_latency_ms != null">{{ m.last_latency_ms.toFixed(1) }}ms</span>
          <button class="mon-op" title="编辑" @click.stop="openDetail(m, 'edit')"><Icon name="edit" :size="13" /></button>
          <button class="mon-op danger" title="删除" @click="delMonitor(m, $event)"><Icon name="trash" :size="13" /></button>
        </div>
        <div v-if="!monitors.length" class="hint-empty">暂无监控项，点「添加」创建一个 TCP/HTTP 探测</div>
      </div>
    </section>

    <!-- 添加监控项弹窗（编辑在详情浮窗 tab3） -->
    <div v-if="showMonDialog" class="mask" @click.self="showMonDialog = false">
      <div class="dialog">
        <div class="d-head">添加服务监控</div>
        <div class="d-body">
          <label>名称</label>
          <input v-model="monName" placeholder="如 官网首页" />
          <label>类型</label>
          <Dropdown v-model="monType" :options="MON_TYPES" />
          <label>{{ monType.startsWith("http") ? "主机 / 域名（可带路径）" : "主机 / IP / 域名" }}</label>
          <input v-model="monHost" :placeholder="monType.startsWith('http') ? '如 example.com/health' : '如 example.com 或 1.2.3.4'" />
          <template v-if="monNeedPort">
            <label>端口<span v-if="!monPortRequired" class="lbl-hint">（可空）</span></label>
            <input v-model="monPort" inputmode="numeric" :placeholder="monPortPlaceholder" />
          </template>
          <label>探测节点</label>
          <Dropdown v-model="monNodeId" :options="addNodeOptions" />
          <label>探测间隔（秒）</label>
          <input v-model.number="monInterval" type="number" min="10" />
        </div>
        <div class="d-foot">
          <button class="cancel" @click="showMonDialog = false">取消</button>
          <button class="confirm" @click="saveMonitor">添加</button>
        </div>
      </div>
    </div>

    <!-- 监控项详情浮窗（图表 / MTR 记录 / 编辑） -->
    <MonitorDetailModal
      v-if="detailMon"
      :monitor="detailMon"
      :node-name="nodeName(detailMon.node_id)"
      :initial-tab="detailTab"
      @close="detailMon = null"
      @saved="detailMon = null; refresh(); monMode === 'chart' && loadSparklines()"
    />
  </div>
</template>

<style scoped>
.overview { height: 100%; overflow-y: auto; padding: 22px 26px; }
.head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 18px; }
h2 { font-size: 19px; font-weight: 600; letter-spacing: 1px; }
.sub { color: var(--text-faint); font-size: 12px; }
.block { margin-bottom: 24px; }
.block-head {
  display: flex; align-items: center; gap: 10px;
  font-size: 13px; font-weight: 600; color: var(--text-lo);
  letter-spacing: 1px; margin-bottom: 10px; flex-wrap: wrap;
}
.flex-spacer { flex: 1; }
.mini-btn {
  display: inline-flex; align-items: center; gap: 4px;
  border: 1px solid var(--accent-dim); background: transparent; color: var(--accent);
  font-size: 12px; padding: 4px 12px; border-radius: 999px; cursor: pointer;
}
.mini-btn:hover { background: var(--bg-raised); }
.hint-empty { color: var(--text-faint); font-size: 12px; padding: 8px 0; }

/* 区1 服务器卡 */
.card-grid { display: flex; flex-wrap: wrap; gap: 10px; }
.srv-card {
  display: flex; align-items: center; gap: 10px;
  background: var(--bg-raised); border: 1px solid rgba(255,255,255,0.06);
  border-radius: var(--radius-sm); padding: 10px 14px; font-size: 13px; min-width: 240px;
}
.clickable { cursor: pointer; transition: all var(--transition); }
.clickable:hover { border-color: var(--accent-dim); transform: translateY(-1px); }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.srv-main { flex: 1; min-width: 0; }
.srv-line1 { display: flex; align-items: center; gap: 8px; }
.name { font-weight: 600; }
.plat { font-size: 10.5px; color: var(--text-faint); background: rgba(255,255,255,0.05); border-radius: 4px; padding: 1px 6px; }
.st { color: var(--text-faint); font-size: 11px; margin-left: auto; }
.srv-bars { display: flex; gap: 14px; margin-top: 7px; }
.mini-bar { display: inline-flex; align-items: center; gap: 6px; }
.mb-label { font-size: 10px; color: var(--text-faint); width: 26px; }
.mb-track { width: 72px; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.07); overflow: hidden; display: inline-block; }
.mb-fill { display: block; height: 100%; border-radius: 2px; background: var(--accent); transition: width 0.6s ease; }
.mb-fill.mem { background: var(--pink); }
.mb-val { font-size: 10.5px; color: var(--text-lo); width: 30px; }

/* 区2 流量速览 */
.ov-drop { min-width: 110px; }
.iface-drop { min-width: 130px; }
.d-body .lbl-hint { color: var(--text-faint); font-size: 11px; font-weight: 400; }
.live-btn {
  display: inline-flex; align-items: center; gap: 6px;
  background: transparent; border: 1px solid rgba(255,255,255,0.12); color: var(--text-lo);
  border-radius: 999px; padding: 4px 12px; cursor: pointer; font-size: 12px;
  transition: all var(--transition);
}
.live-btn:hover { border-color: var(--accent-dim); color: var(--text-hi); }
.live-btn.on { border-color: var(--pink); color: var(--pink); background: rgba(255,158,199,0.08); }
.live-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: 0.5; }
.live-btn.on .live-dot { opacity: 1; animation: livePulse 1.6s ease-in-out infinite; }
@keyframes livePulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
.pop-wrap { position: relative; }
.win-btn {
  background: transparent; border: 1px solid rgba(255,255,255,0.12); color: var(--text-lo);
  border-radius: var(--radius-sm); padding: 4px 10px; font-size: 12px; cursor: pointer;
}
.win-btn:hover { border-color: var(--accent-dim); color: var(--text-hi); }
.pop-menu {
  position: absolute; top: calc(100% + 4px); left: 0; z-index: 50; min-width: 90px;
  background: var(--bg-panel); border: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-sm); padding: 4px; box-shadow: 0 8px 24px rgba(0,0,0,0.4);
}
.pop-item {
  display: block; width: 100%; text-align: left; background: none; border: none;
  color: var(--text-lo); font-size: 12px; padding: 6px 10px; border-radius: 4px; cursor: pointer;
}
.pop-item:hover { background: var(--bg-raised); color: var(--text-hi); }
.pop-item.active { color: var(--accent); }
.chart-box { background: var(--bg-raised); border: 1px solid rgba(255,255,255,0.05); border-radius: var(--radius-sm); padding: 8px; }
.ov-chart { height: 200px; }

/* 区3 服务监控 */
.mode-switch { display: flex; gap: 2px; background: var(--bg-panel); border-radius: 999px; padding: 2px; }
.ms-btn {
  display: inline-flex; align-items: center; gap: 4px;
  background: transparent; border: none; color: var(--text-lo);
  border-radius: 999px; padding: 4px 12px; font-size: 12px; cursor: pointer; transition: all var(--transition);
}
.ms-btn:hover { color: var(--text-hi); }
.ms-btn.active { background: var(--bg-raised); color: var(--accent); }
/* grid 等宽列：flex+min-width 会让卡片按内容自适应，同行宽度不一致 */
.mon-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
.mon-card {
  display: flex; align-items: flex-start; gap: 10px;
  background: var(--bg-raised); border: 1px solid rgba(255,255,255,0.06);
  border-radius: var(--radius-sm); padding: 10px 14px; min-width: 0;
}
.mon-card .dot { margin-top: 5px; }
.mon-info { flex: 1; min-width: 0; }
.mon-name { font-size: 13px; font-weight: 600; }
.mon-target { font-size: 11px; color: var(--text-faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mon-avail { font-size: 10.5px; color: var(--text-lo); margin-top: 2px; }
.spark { height: 34px; margin-top: 6px; }
.mon-blocks { display: flex; gap: 2px; margin-top: 7px; }
.blk { flex: 1; height: 14px; border-radius: 2px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.04); }
.blk.up { background: var(--pink); border-color: transparent; opacity: 0.85; }
.blk.down { background: #ff5d6c; border-color: transparent; }
.mon-latency { font-size: 12px; color: var(--accent); }
.mon-op { border: none; background: transparent; color: var(--text-faint); cursor: pointer; padding: 3px; }
.mon-op:hover { color: var(--accent); }
.mon-op.danger:hover { color: var(--pink); }

/* 弹窗 */
.mask { position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: grid; place-items: center; z-index: 100; }
.dialog { width: 420px; background: var(--bg-panel); border: 1px solid var(--bg-raised); border-radius: var(--radius); overflow: hidden; }
.d-head { padding: 14px 18px; font-size: 14px; font-weight: 600; border-bottom: 1px solid rgba(255,255,255,0.05); }
.d-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 6px; }
.d-body label { font-size: 11.5px; color: var(--text-faint); margin-top: 4px; }
.d-body input {
  padding: 8px 12px; background: var(--bg-raised); border: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-sm); color: var(--text-hi); font-size: 13px; outline: none;
}
.d-body input:focus { border-color: var(--accent-dim); }
.d-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px 16px; }
.d-foot button { padding: 8px 18px; border-radius: var(--radius-sm); font-size: 13px; cursor: pointer; }
.d-foot .cancel { background: transparent; border: 1px solid var(--text-faint); color: var(--text-faint); }
.d-foot .confirm { background: var(--accent); border: none; color: var(--bg-base); font-weight: 600; }
</style>
