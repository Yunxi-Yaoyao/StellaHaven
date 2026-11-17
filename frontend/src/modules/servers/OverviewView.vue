<script setup lang="ts">
import {notifyClientPreferenceChange} from '../settings/clientPreferenceEvents';
// 总览页三区：服务器卡（状态+CPU/内存迷你条）+ 流量速览（选一台+实时开关）+ 服务监控（图表⇄简易双模式）。
// 定位：全局健康一眼看 + 跳转入口。5s 刷状态；图表区独立节奏（静态不自动刷，实时 3s 增量）。
import { ref, computed, watch, nextTick, onMounted, onUnmounted, defineAsyncComponent } from "vue";
import { useRouter, useRoute } from "vue-router";
import * as echarts from "./chartRuntime";
import { metricColors } from '../../stores/appearance';
import { overviewInterfaces, overviewDefaultInterface } from "./interfaceSelection";
import { summarizeMonitorPoints } from "./monitorStats";
import { createRequestLane, createPoller, mapBounded } from "./polling";
import {
  listNodes, getNodeDetail, getNodeMetrics, listMonitors, getMonitorSeries, listMonitorGroups,
  type Node, type NodeDetail, type Monitor, type MetricPoint, type MonitorGroup,
} from "../../api/servers";
import {monitorStatusLabel,monitorStatusReason} from "./monitorStatusLabel";
import Icon from "../../shell/Icon.vue";
import Dropdown from "../../shell/Dropdown.vue";
import MonitorChildPicker from './MonitorChildPicker.vue';
import AlertIncidentList from "./AlertIncidentList.vue";
const MonitorDetailModal = defineAsyncComponent(() => import("./MonitorDetailModal.vue"));
const MonitorGroupEditor = defineAsyncComponent(() => import('./MonitorGroupEditor.vue'));
const MonitorManagement = defineAsyncComponent(() => import('./MonitorManagement.vue'));
const showMonitorManagement = ref(false);
const ServerWorldMap = defineAsyncComponent(() => import("./ServerWorldMap.vue"));

const router = useRouter();
const nodes = ref<Node[]>([]);
const nodeDetails = ref<Record<number, NodeDetail>>({});
const detailState = ref<Record<number, "loading" | "ready" | "error">>({});
const nodesState = ref<"loading" | "ready" | "error">("loading");
const monitors = ref<Monitor[]>([]);
const monitorGroups = ref<MonitorGroup[]>([]);

const showGroupEditor = ref(false);
const groupEditorId = ref<number|null>(null);
const groupEditorMonitorId=ref<number|null>(null);
function editGroup(id:number|null=null,monitorId:number|null=null){groupEditorId.value=id;groupEditorMonitorId.value=monitorId;showGroupEditor.value=true;}
const route=useRoute();
watch(()=>route.hash,async hash=>{if(hash==='#service-monitors'){await nextTick();document.getElementById('service-monitors')?.scrollIntoView();}},{immediate:true,flush:'post'});

const groupError = ref('');
const chosenChildren = ref<Record<number,number>>({});

type Managed = {visible?:boolean;enabled?:boolean;eligible_child_ids?:number[]};
function eligible(item:Managed){return (item.visible??true)&&(item.enabled??true);}
type MonitorCard = Monitor & {cardKey:string; parent?:MonitorGroup; children:Monitor[]};
const monitorCards = computed<MonitorCard[]>(() => {
  const grouped = new Set(monitorGroups.value.flatMap(g=>g.child_ids));
  const cards:MonitorCard[] = [];
  for(const group of monitorGroups.value){
    if(!eligible(group as MonitorGroup&Managed))continue;
    const ids=(group as MonitorGroup&Managed).eligible_child_ids??group.child_ids;
    const children=ids.map(id=>monitors.value.find(m=>m.id===id)).filter((m):m is Monitor=>!!m&&eligible(m as Monitor&Managed));
    const selected=children.find(m=>m.id===chosenChildren.value[group.id])||children[0];
    if(selected)cards.push({...selected,cardKey:`g${group.id}`,parent:group,children});
  }
  cards.push(...monitors.value.filter(m=>!grouped.has(m.id)&&eligible(m as Monitor&Managed)).map(m=>({...m,cardKey:`m${m.id}`,children:[]})));
  return cards;
});
function chooseChild(groupId:number, childId:number){chosenChildren.value[groupId]=childId;}

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
const trafficState = ref<"idle" | "loading" | "ready" | "error">("idle");
const trafficNow = ref(Date.now());
const trafficIface = ref<string>("");
const chartEl = ref<HTMLElement | null>(null);
let chart: echarts.ECharts | null = null;
const trafficLane = createRequestLane();
let fullTraffic = true;
let resumeTraffic = false;
const livePoll = createPoller(async () => { await trafficLane.run(signal => fetchTraffic(fullTraffic, signal)); }, 3000);
let trafficSeq = 0;

const onlineNodes = computed(() => nodes.value.filter((n) => n.status === "online"));
const trafficNodeOptions = computed(() => onlineNodes.value.map((n) => ({ value: n.id, label: n.name })));

const selectedTrafficDetail = computed(() => nodeDetails.value[trafficNodeId.value ?? -1]);
const trafficHint = computed(() => {
  if (nodesState.value === "loading") return "节点加载中";
  if (nodesState.value === "error" && !onlineNodes.value.length) return "节点加载失败";
  if (!onlineNodes.value.length) return "暂无在线节点";
  const detail = selectedTrafficDetail.value;
  if (!detail) return detailState.value[trafficNodeId.value ?? -1] === "error" ? "节点详情加载失败" : "节点详情加载中";
  if (detail.interfaces == null) return "等待网卡上报";
  if (!trafficIface.value) return "暂无可用网卡";
  if (trafficState.value === "error") return "流量加载失败";
  if (trafficState.value === "idle" && !trafficLive.value) return "流量已暂停";
  if (trafficState.value === "idle" || trafficState.value === "loading" && !trafficPoints.value.length) return "流量加载中";
  if (!trafficPoints.value.length) return "暂无流量数据";
  const last = new Date(trafficPoints.value[trafficPoints.value.length - 1]!.ts).getTime();
  return trafficNow.value - last > 60000 ? "流量采样已过期" : "";
});
const trafficIfaceOptions = computed(() => overviewInterfaces(selectedTrafficDetail.value)
  .map(name => ({ value: name, label: selectedTrafficDetail.value?.interfaces?.[name]?.is_default ? `${name}（默认）` : name })));
const manualIfaces = new Map<number, string>();
function selectTrafficIface(name: string | number | boolean) {
  if (typeof name !== "string" || !overviewInterfaces(selectedTrafficDetail.value).includes(name)) return;
  if (trafficNodeId.value != null) manualIfaces.set(trafficNodeId.value, name);
  trafficIface.value = name;
}
// Details may arrive after selection (or a failed detail refresh); only live inventory is eligible.
watch([trafficNodeId, selectedTrafficDetail], () => {
  const id = trafficNodeId.value;
  const available = overviewInterfaces(selectedTrafficDetail.value);
  const chosen = id == null ? undefined : manualIfaces.get(id);
  trafficIface.value = chosen && available.includes(chosen) ? chosen : overviewDefaultInterface(selectedTrafficDetail.value);
}, { flush: "pre" });

async function fetchTraffic(full: boolean, signal: AbortSignal) {
  const id = trafficNodeId.value;
  const iface = trafficIface.value;
  const windowSeconds = trafficWindow.value;
  const isCurrent = () => !disposed && !document.hidden && !signal.aborted && seq === trafficSeq
    && id === trafficNodeId.value && iface === trafficIface.value && windowSeconds === trafficWindow.value;
  if (!id || !iface) { trafficPoints.value = []; paintTraffic(); return; }
  const seq = ++trafficSeq;
  fullTraffic = false;
  trafficState.value = "loading";
  trafficNow.value = Date.now();
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
    const data = await getNodeMetrics(id, { iface, start, end, limit, signal });
    if (!isCurrent()) return;
    const pts = [...data].reverse();
    if (full || !existing.length) trafficPoints.value = pts;
    else {
      const lastTs = new Date(existing[existing.length - 1].ts).getTime();
      let merged = [...existing, ...pts.filter((p) => new Date(p.ts).getTime() > lastTs)];
      merged = merged.filter((p) => new Date(p.ts).getTime() >= Date.now() - trafficWindow.value * 1000);
      trafficPoints.value = merged;
    }
    trafficState.value = "ready";
    void paintTraffic();
  } catch {
    if (isCurrent()) trafficState.value = "error";
  }
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

let trafficObserver: ResizeObserver | undefined;
// All paints wait for Vue's v-show update; zero-sized ancestors defer to RO.
async function paintTraffic() {
  await nextTick();
  const el = chartEl.value;
  if (disposed || document.hidden || !el || !onlineNodes.value.length) return;
  const { width, height } = el.getBoundingClientRect();
  if (width <= 0 || height <= 0) return;
  chart = chart || echarts.getInstanceByDom(el) || echarts.init(el);
  // Bounds include CSS zoom/transforms; feeding them back as CSS sizes scales twice.
  // Let ECharts measure the unscaled content box, as it does during init.
  chart.resize();
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
        data: pts.map((p) => Math.round(rateBps(p.rx_delta))), lineStyle: { width: 1.5 }, itemStyle: { color: metricColors.value.cpu }, areaStyle: { opacity: 0.08 } },
      { name: "↑ 上传", type: "line", smooth: true, showSymbol: false, animation: false,
        data: pts.map((p) => Math.round(rateBps(p.tx_delta))), lineStyle: { width: 1.5, type: "dashed" }, itemStyle: { color: metricColors.value.disk } },
    ],
  }, { notMerge: true });
}

function loadTraffic() {
  stopLive();
  fullTraffic = true;
  if (disposed) return Promise.resolve();
  if (document.hidden) { resumeTraffic = true; return Promise.resolve(); }
  if (!trafficNodeId.value || !trafficIface.value) return Promise.resolve();
  resumeTraffic = false;
  // Poller starts with this full query, then waits 3s from completion: no duplicate tick.
  if (trafficLive.value) { startLive(); return Promise.resolve(); }
  return trafficLane.run(signal => fetchTraffic(true, signal));
}
let disposed = false;
function startLive() { if (!disposed && trafficLive.value && !document.hidden && trafficIface.value) livePoll.start(); }
function stopLive() { trafficSeq++; livePoll.stop(); trafficLane.reset(); }
// One post-flush watcher coalesces node + resolved iface + window changes into one lane.
watch([trafficNodeId, trafficIface, trafficWindow, trafficLive], ([id, iface, windowSeconds, live], old) => {
  if (old && !live && old[3] && id === old[0] && iface === old[1] && windowSeconds === old[2]) {
    resumeTraffic = false;
    stopLive();
    if (trafficState.value === "loading") trafficState.value = trafficPoints.value.length ? "ready" : "idle";
    return;
  }
  if (!old || id !== old[0] || iface !== old[1]) {
    trafficPoints.value = [];
    trafficState.value = "idle";
    void paintTraffic();
  }
  void loadTraffic();
}, { flush: "post" });

// ═══════════ 区3：服务监控（双模式）═══════════
const monMode = ref<"chart" | "simple">((localStorage.getItem("stella_mon_mode") as "chart" | "simple") || "chart");
function setMonMode(m: "chart" | "simple") {
  monMode.value = m;
  notifyClientPreferenceChange('stella_mon_mode',m);
  localStorage.setItem("stella_mon_mode", m);
  loadMonAll();
}
const monStatusColor: Record<string, string> = { up: '#a9dbc6', down: '#e9a2a2', unknown: 'var(--text-lo)' };
const sparks = ref<Record<number, { ts: string; latency_ms: number | null; success: boolean }[]>>({});
const sparkEls = new Map<number, HTMLElement>();
let sparkObserver: ResizeObserver | undefined;
// 24h 逐小时桶：图表模式算可用率、简易模式画色块，一次查询喂两个模式
const monDaily = ref<Record<number, { avail: number | null; loss: number | null; buckets: { ts: string; success: boolean; latency_ms: number | null }[] }>>({});

async function loadMonDaily(signal: AbortSignal) {
  const end = new Date();
  const start = new Date(end.getTime() - 86400000);
  await mapBounded(monitors.value, 3, async m => {
    try {
      // 两次取数：小时桶画色块；原始点按探测次数算可用率（和详情页口径一致，桶粒度会虚低）
      const [buckets, raw] = await Promise.all([
        getMonitorSeries(m.id, { start: start.toISOString(), end: end.toISOString(), step: 3600, signal }),
        getMonitorSeries(m.id, { start: start.toISOString(), end: end.toISOString(), step: 60, limit: 5000, signal }),
      ]);
      if (signal.aborted) return;
      const stat = summarizeMonitorPoints(raw);
      monDaily.value[m.id] = { avail: stat.total ? stat.avail : null, loss: stat.total ? stat.loss : null, buckets };
    } catch { /* 单个失败不影响其他 */ }
  }, signal);
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
const monitorLane = createRequestLane();
function loadMonAll() {
  if (document.hidden) return Promise.resolve();
  return monitorLane.run(async signal => {
    await Promise.all([loadMonDaily(signal), monMode.value === "chart" ? loadSparklines(signal) : Promise.resolve()]);
  });
}

async function loadSparklines(signal: AbortSignal) {
  const end = new Date();
  const start = new Date(end.getTime() - 3600000);  // 近 1 小时
  await mapBounded(monitors.value, 3, async m => {
    try {
      const rows = await getMonitorSeries(m.id, { start: start.toISOString(), end: end.toISOString(), step: 5, signal });
      if (signal.aborted) return;
      sparks.value[m.id] = rows;
    } catch { /* 单个失败不影响其他 */ }
  }, signal);
  if (signal.aborted) return;
  await nextTick();
  paintSparklines();
}
function setSparkEl(id: number, el: any) {
  if (el instanceof HTMLElement) {
    const old=sparkEls.get(id);
    if(old&&old!==el){sparkObserver?.unobserve(old);echarts.getInstanceByDom(old)?.dispose();}
    if(typeof ResizeObserver!=='undefined'){
      sparkObserver ||= new ResizeObserver(()=>{if(!disposed)paintSparklines();});
      sparkObserver.observe(el);
    }
    sparkEls.set(id, el);
    void nextTick().then(()=>{if(!disposed)paintSparklines();});
  }
}
function paintSparklines() {
  for (const m of monitors.value) {
    const el = sparkEls.get(m.id);
    const pts = sparks.value[m.id];
    if (!el || !el.isConnected || !pts?.length) continue;
    const c = echarts.getInstanceByDom(el) || echarts.init(el);
    c.resize();
    const lats = pts.filter((p) => p.success && p.latency_ms != null).map((p) => p.latency_ms!);
    const max = lats.length ? Math.max(...lats) : 1;
    c.setOption({
      backgroundColor: "transparent",
      grid: { left: 0, right: 0, top: 20, bottom: 0 },
      xAxis: { type: "category", show: false, data: pts.map((p) => p.ts), boundaryGap: false },
      yAxis: { type: "value", show: false, min: 0, max: max * 1.15 },
      series: [{
        type: "line", showSymbol: false, animation: false, smooth: true,
        data: pts.map((p) => (p.success && p.latency_ms != null ? p.latency_ms : null)),
        lineStyle: { width: 1 }, itemStyle: { color: metricColors.value.cpu }, areaStyle: { opacity: 0.15 },
        connectNulls: false,
      }],
    }, { notMerge: true });
  }
}
const sparkPoll = createPoller(async () => { await loadMonAll(); }, 60000);

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

// ═══════════ 轮询 ═══════════
const statusPoll = createPoller(refreshStatus, 5000);
function refresh() { return statusPoll.run(); }
async function refreshStatus(signal: AbortSignal) {
  try {
    const [newNodes, newMonitors] = await Promise.all([listNodes(signal), listMonitors(signal)]);
    try { const groups=await listMonitorGroups(signal); if(!signal.aborted){monitorGroups.value=groups;groupError.value='';} }
    catch { if(!signal.aborted)groupError.value='监控组刷新失败，保留上次结果；可重试。'; }
    if (signal.aborted) return;
    nodes.value = newNodes;
    nodesState.value = "ready";
    monitors.value = [...newMonitors].sort((a, b) => a.id - b.id);
    if (!onlineNodes.value.some(n => n.id === trafficNodeId.value)) {
      trafficNodeId.value = onlineNodes.value[0]?.id ?? null;
    }
    // Keep bounded detail polling; publish each successful inventory as it arrives.
    await mapBounded(onlineNodes.value, 3, async n => {
      detailState.value[n.id] = "loading";
      try {
        const detail = await getNodeDetail(n.id, signal);
        if (signal.aborted) return;
        nodeDetails.value[n.id] = detail;
        detailState.value[n.id] = "ready";
      } catch {
        if (!signal.aborted) detailState.value[n.id] = "error";
      }
    }, signal);
  } catch { if (!signal.aborted) nodesState.value = "error"; }
}
onMounted(() => {

  if (chartEl.value && typeof ResizeObserver !== "undefined") {
    trafficObserver = new ResizeObserver(() => { void paintTraffic(); });
    trafficObserver.observe(chartEl.value);
  }
  if (!document.hidden) { statusPoll.start(); sparkPoll.start(); if (trafficLive.value) startLive(); }
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("resize", onResize);
  document.addEventListener("click", onDocClick);
});
onUnmounted(() => {

  disposed = true;
  trafficObserver?.disconnect();
  statusPoll.stop(); sparkPoll.stop(); monitorLane.reset();
  document.removeEventListener("visibilitychange", onVisibility);
  for (const el of sparkEls.values()) echarts.getInstanceByDom(el)?.dispose();
  sparkEls.clear();
  sparkObserver?.disconnect();
  stopLive();
  window.removeEventListener("resize", onResize);
  document.removeEventListener("click", onDocClick);
  chart?.dispose();
});
function onVisibility() {
  if (disposed) return;
  if (document.hidden) {
    resumeTraffic ||= trafficState.value === "loading";
    statusPoll.stop(); sparkPoll.stop(); monitorLane.reset(); stopLive();
  } else {
    statusPoll.start(); sparkPoll.start(); void paintTraffic();
    if (trafficLive.value || resumeTraffic) void loadTraffic();
  }
}
function onResize() { void paintTraffic(); paintSparklines(); }
watch(metricColors, () => { if (chart) void paintTraffic(); paintSparklines(); });
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

    <ServerWorldMap />

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
        <Dropdown :model-value="trafficIface" @update:model-value="selectTrafficIface" :options="trafficIfaceOptions" class="ov-drop iface-drop" />
      </div>
      <div class="chart-box">
        <div v-if="trafficHint" class="hint-empty traffic-hint" role="status">
          {{ trafficHint }}
          <button v-if="trafficState === 'error' || trafficHint === '流量已暂停'" class="mini-btn traffic-retry" @click="loadTraffic">重试</button>
        </div>
        <div v-show="onlineNodes.length" ref="chartEl" class="ov-chart"></div>
      </div>
    </section>

    <!-- 区3：服务监控（双模式） -->
    <section id="service-monitors" class="block">
      <div class="block-head">
        服务监控
        <button class="mini-btn" @click="showMonitorManagement=true"><Icon name="settings" :size="12" /> 监控管理</button>
        <button class="mini-btn" @click="editGroup()"><Icon name="plus" :size="12" /> 添加监控</button>
        <span class="flex-spacer" />
        <div class="mode-switch">
          <button class="ms-btn" :class="{ active: monMode === 'chart' }" title="图表模式：每项带 1h 延迟走势" @click="setMonMode('chart')"><Icon name="activity" :size="12" /> 图表</button>
          <button class="ms-btn" :class="{ active: monMode === 'simple' }" title="简易模式：24h 逐小时状态色块" @click="setMonMode('simple')">简易</button>
        </div>
      </div>
      <p v-if="groupError" class="mon-group-error" role="status">{{groupError}} <button class="mini-btn" @click="refresh">重试</button></p>
      <div class="mon-grid">
        <div v-for="g in monitorGroups.filter(g=>g.automatic&&!g.child_ids.length&&eligible(g))" :key="`empty-${g.id}`" class="mon-card">
          <div class="mon-heading"><span class="mon-name">{{g.name}}</span><span/><button class="mon-op" :aria-label="`设置 ${g.name}`" @click="editGroup(g.id)"><Icon name="settings" :size="16" /></button></div>
          <p class="hint-empty">{{g.availability_reason==='entry_not_configured'?'未配置其他入口':'暂无接入节点'}}</p>
        </div>
        <div v-for="m in monitorCards" :key="m.cardKey" class="mon-card clickable" @click="openDetail(m)">
          <div class="mon-heading">
            <span class="mon-name" :title="m.parent?.name || m.name">{{m.parent?.name || m.name}}</span>
            <span class="mon-counts"><span class="mon-count-down" :class="{active:(m.parent?m.children.filter(c=>c.status!=='up').length:Number(m.status!=='up'))>0}">异常 {{m.parent?m.children.filter(c=>c.status!=='up').length:Number(m.status!=='up')}}</span><span class="mon-count-up">正常 {{m.parent?m.children.filter(c=>c.status==='up').length:Number(m.status==='up')}}</span></span>
            <button class="mon-op" :aria-label="`设置 ${m.parent?.name||m.name}`" @click.stop="editGroup(m.parent?.id??null,m.parent?null:m.id)"><Icon name="settings" :size="16" /></button>
          </div>
          <div class="mon-current">
            <MonitorChildPicker v-if="m.parent" compact :model-value="m.id" :children="m.children" :seconds="m.parent.rotation_seconds || 0" :parent-name="m.parent.name" @update:model-value="chooseChild(m.parent!.id,$event)">
              <span class="mon-target" :title="`${m.type} · ${m.target}`">{{m.type}} · {{m.target}}</span>
            </MonitorChildPicker>
            <span v-else class="mon-current-item"><span class="mon-current-name" :title="m.name">{{m.name}}</span><span class="mon-target" :title="`${m.type} · ${m.target}`">{{m.type}} · {{m.target}}</span></span>
          </div>
          <div class="mon-child-stack">
          <Transition name="mon-child" @after-enter="paintSparklines">
          <div :key="m.id" class="mon-child-content">
          <div class="mon-plot">
            <div class="mon-plot-metrics">
            <span class="mon-latency" :style="{color:monStatusColor[m.status]}" :title="[monitorStatusLabel(m),monitorStatusReason(m)].filter(Boolean).join(' · ')" :aria-label="`${monitorStatusLabel(m)}，${monitorStatusReason(m)}`"><span v-if="m.status!=='up'" class="mon-status-dot" aria-hidden="true" />{{ m.status==='up' && m.last_latency_ms != null ? m.last_latency_ms.toFixed(1) : '—' }} <small>ms</small></span>
            <div class="mon-metrics mon-avail"><span class="mon-availability">{{ monDaily[m.id]?.avail != null ? monDaily[m.id].avail!.toFixed(0) + '%' : '—' }}/24h</span><span aria-hidden="true"> · </span><span class="mon-loss">丢包 {{monDaily[m.id]?.loss != null ? monDaily[m.id].loss!.toFixed(1) + '%' : '暂无数据'}}</span></div>
            </div>
          <div v-if="monMode === 'chart'" :ref="(el) => setSparkEl(m.id, el)" class="spark"></div>
          <div v-else class="mon-blocks">
            <span v-for="(b, i) in hourBlocks(m.id)" :key="i" class="blk" :class="{ up: b?.ok, down: b && !b.ok }" :title="b?.label || '无数据'" />
          </div>
          </div>
          </div>
          </Transition>
          </div>
        </div>
        <div v-if="!monitors.length&&!monitorGroups.length" class="hint-empty">暂无监控项，点「添加监控」创建独立监控项或监控组</div>
      </div>
    </section>

    <MonitorManagement v-if="showMonitorManagement" :open="showMonitorManagement&&!showGroupEditor" :monitors="monitors" :groups="monitorGroups" :nodes="nodes" @close="showMonitorManagement=false" @changed="refresh();loadMonAll()" @edit-monitor="id=>editGroup(null,id)" @edit-group="id=>editGroup(id)" @add="editGroup(null)" />
    <MonitorGroupEditor v-if="showGroupEditor" :monitors="monitors" :groups="monitorGroups" :nodes="nodes" :initial-group-id="groupEditorId" :initial-monitor-id="groupEditorMonitorId" :node-name="nodeName" @close="showGroupEditor=false" @changed="refresh()" @saved="showGroupEditor=false;showMonitorManagement=true;refresh()" />
    <!-- 监控项详情浮窗（图表 / MTR 记录 / 编辑） -->
    <MonitorDetailModal
      v-if="detailMon"
      :key="detailMon.id"
      :monitor="detailMon"
      :node-name="nodeName(detailMon.node_id)"
      :node="nodes.find(n => n.id === detailMon?.node_id)"
      @refresh="refresh()"
      :initial-tab="detailTab" :allow-edit="detailTab==='edit'"
      @close="detailMon = null"
      @saved="detailMon = null; refresh(); loadMonAll()"
    />
    <AlertIncidentList mode="current" />
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
.mb-fill { display: block; height: 100%; border-radius: 2px; background: linear-gradient(90deg,var(--metric-cpu-start),var(--metric-cpu)); transition: width 0.6s ease; }
.mb-fill.mem { background: linear-gradient(90deg,var(--metric-memory-start),var(--metric-memory)); }
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
.mon-grid { display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr));gap:10px; }
.mon-card { container-type:inline-size; background:var(--bg-raised);border:1px solid rgba(255,255,255,.06);border-radius:12px;padding:13px 15px 9px;min-width:0; }
.mon-card.clickable { transition:border-color 140ms ease; }
.mon-card.clickable:hover { transform:none; }
.mon-heading { display:grid;grid-template-columns:minmax(0,1fr) auto 24px;align-items:center;gap:10px;height:26px;min-width:0; }
.mon-name { min-width:0;font-size:14px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }
.mon-counts { display:flex;gap:10px;white-space:nowrap;font-size:12px;font-variant-numeric:tabular-nums; }
.mon-count-down { color:var(--text-lo); }.mon-count-down.active { color:#e9a2a2; }.mon-count-up { color:#a9dbc6; }
.mon-op { display:flex;align-items:center;justify-content:center;width:24px;height:26px;padding:0;border:0;background:transparent;color:var(--text-lo);cursor:pointer; }
.mon-op:hover { color:var(--accent); }
.mon-op:focus-visible { outline:2px solid var(--accent);outline-offset:2px; }
.mon-current { display:flex;align-items:center;gap:12px;height:27px;margin-top:8px;min-width:0;white-space:nowrap; }
.mon-current-item { display:flex;gap:6px;min-width:0;align-items:center; }
.mon-current-name { flex:0 1 auto;max-width:55%;min-width:56px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;color:var(--text-hi); }
.mon-current :deep(.mon-child-picker) { min-width:0;width:100%;align-self:center; }
.mon-target { display:block;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:var(--text-lo); }
.mon-latency { display:flex;align-items:baseline;gap:2px;font-size:13px;white-space:nowrap;font-variant-numeric:tabular-nums; }
.mon-latency small { font-size:12px;color:var(--text-lo); }
.mon-status-dot { width:5px;height:5px;background:currentColor;border-radius:50%;align-self:center;flex:none; }
.mon-metrics { display:flex;gap:4px;font-size:11.5px;color:var(--text-lo);white-space:nowrap;font-variant-numeric:tabular-nums; }
.mon-availability,.mon-loss { color:var(--text-lo); }
.mon-plot{position:relative;min-width:0;width:100%}.mon-plot-metrics{position:absolute;left:0;top:0;right:0;z-index:1;display:flex;align-items:baseline;gap:10px;white-space:nowrap;pointer-events:none;line-height:19px;background:linear-gradient(90deg,var(--bg-panel) 0%,transparent 100%)}
.mon-group-error { color:#e9a2a2;font-size:13px; }
.mon-child-stack { display:grid;min-width:0;margin-top:8px; }
.mon-child-content { grid-area:1/1;width:100%;min-width:0; }
.mon-child-leave-active { pointer-events:none; }
.mon-child-enter-active,.mon-child-leave-active { transition:opacity 180ms ease,transform 180ms ease; }
.mon-child-enter-from { opacity:0;transform:translateX(6px); }
.mon-child-leave-to { opacity:0;transform:translateX(-6px); }
@media(prefers-reduced-motion:reduce) { .mon-child-enter-active,.mon-child-leave-active { transition:none; } }
.spark { height:53px;width:100%; }
.mon-blocks { padding-top:18px;display:flex;gap:2px;width:100%;height:53px;align-items:center; }
.blk { flex:1;height:14px;border-radius:2px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.04); }
.blk.up { background:var(--pink);border-color:transparent;opacity:.85; }
.blk.down { background:#ff5d6c;border-color:transparent; }
@media (max-width: 480px) { .overview { padding: 16px 12px; } .srv-card { min-width: 0; width: 100%; box-sizing: border-box; } .srv-bars { flex-wrap: wrap; gap: 6px; } }

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
