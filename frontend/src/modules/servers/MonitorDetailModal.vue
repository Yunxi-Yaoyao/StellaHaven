<script setup lang="ts">
// 监控项详情浮窗：总览页卡片点击 / 详情页服务监控列表共用。
// Tab1 图表：统计行 + 延迟&丢包双轴曲线（1h/6h/24h/7d）+ 24h 逐小时可用率色块
// Tab2 MTR：近 60 天历史（定时/失败/手动三触发），可展开逐跳表格，支持「立即 MTR」
// Tab3 编辑：名称/类型/主机/端口/间隔；探测节点灰色禁改（换了历史数据就串台了）
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from "vue";
import * as echarts from "echarts";
import {
  getMonitorSeries, updateMonitor, listMonitorMtr, runMonitorMtr,
  mtrHopRows, type Monitor, type MtrTask, type MonitorCheckPoint, type MtrHopRow,
} from "../../api/servers";
import { toast } from "../../composables/useToast";
import Icon from "../../shell/Icon.vue";
import Dropdown from "../../shell/Dropdown.vue";

const props = defineProps<{
  monitor: Monitor;
  nodeName: string;
  initialTab?: "chart" | "mtr" | "edit";
}>();
const emit = defineEmits<{ close: []; saved: [] }>();

const tab = ref<"chart" | "mtr" | "edit">(props.initialTab ?? "chart");

const TYPE_LABEL: Record<string, string> = { ping: "Ping", tcp: "TCP", udp: "UDP", http: "HTTP", https: "HTTPS" };

// ═══════════ Tab1 图表 ═══════════
const RANGES = [
  { s: 3600, label: "1h" }, { s: 21600, label: "6h" }, { s: 86400, label: "24h" }, { s: 604800, label: "7d" },
];
const range = ref(86400);
const points = ref<MonitorCheckPoint[]>([]);
const chartEl = ref<HTMLElement | null>(null);
let chart: echarts.ECharts | null = null;

// 24h 逐小时可用率色块（独立取数，不随范围切换）
const hourBuckets = ref<{ ts: string; success: boolean; latency_ms: number | null }[]>([]);

const stats = computed(() => {
  const pts = points.value;
  if (!pts.length) return null;
  const ok = pts.filter((p) => p.success);
  const lats = ok.filter((p) => p.latency_ms != null).map((p) => p.latency_ms!);
  // 丢包率：ping 有逐次 loss_pct 用真实值；其余类型用失败率（一次探测=一个包的语义）
  const withLoss = pts.filter((p) => p.loss_pct != null);
  const loss = withLoss.length
    ? withLoss.reduce((s, p) => s + (p.loss_pct ?? 0), 0) / withLoss.length
    : (pts.length - ok.length) / pts.length * 100;
  return {
    total: pts.length,
    avail: ok.length / pts.length * 100,
    avgLat: lats.length ? lats.reduce((a, b) => a + b, 0) / lats.length : null,
    loss,
  };
});

async function loadSeries() {
  const end = new Date();
  const start = new Date(end.getTime() - range.value * 1000);
  const opts: { start: string; end: string; step?: number; limit?: number } = {
    start: start.toISOString(), end: end.toISOString(), limit: 5000,
  };
  if (range.value >= 604800) opts.step = 600;   // 7d 原始点上万，10 分钟桶降采样
  else if (range.value >= 21600) opts.step = 120; // 6h/24h 两分钟桶足够细
  try {
    points.value = await getMonitorSeries(props.monitor.id, opts);
    await nextTick();
    paintChart();
  } catch { /* 静默 */ }
}

async function loadHourBuckets() {
  const end = new Date();
  const start = new Date(end.getTime() - 86400000);
  try {
    hourBuckets.value = await getMonitorSeries(props.monitor.id, {
      start: start.toISOString(), end: end.toISOString(), step: 3600,
    });
  } catch { /* 静默 */ }
}

function hourBlocks(): ({ ok: boolean; label: string } | null)[] {
  const byHour = new Map<number, { success: boolean; latency_ms: number | null }>();
  for (const b of hourBuckets.value) {
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

function paintChart() {
  if (!chartEl.value) return;
  chart = chart || echarts.init(chartEl.value);
  const pts = points.value;
  const fmtT = (ts: string) => {
    const d = new Date(ts);
    const p = (n: number) => String(n).padStart(2, "0");
    return range.value >= 86400
      ? `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
      : `${p(d.getHours())}:${p(d.getMinutes())}`;
  };
  chart.setOption({
    backgroundColor: "transparent",
    grid: { left: 44, right: 44, top: 26, bottom: 22 },
    legend: { show: true, top: 0, textStyle: { color: "#8b93a7", fontSize: 11 }, itemWidth: 14 },
    tooltip: { trigger: "axis", backgroundColor: "#1c2130", borderColor: "rgba(255,255,255,0.1)", textStyle: { color: "#c9d4e8", fontSize: 12 } },
    xAxis: {
      type: "category", data: pts.map((p) => p.ts), boundaryGap: false,
      axisLabel: { color: "#5b6373", fontSize: 10, formatter: (v: string) => fmtT(v) },
      axisLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } },
    },
    yAxis: [
      { type: "value", name: "ms", nameTextStyle: { color: "#5b6373", fontSize: 10 }, axisLabel: { color: "#5b6373", fontSize: 10 }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } } },
      { type: "value", name: "%", max: 100, nameTextStyle: { color: "#5b6373", fontSize: 10 }, axisLabel: { color: "#5b6373", fontSize: 10 }, splitLine: { show: false } },
    ],
    series: [
      {
        name: "延迟", type: "line", showSymbol: false, smooth: true,
        data: pts.map((p) => (p.success && p.latency_ms != null ? +p.latency_ms.toFixed(1) : null)),
        lineStyle: { width: 1.5, color: "#9eb7e5" }, itemStyle: { color: "#9eb7e5" },
        areaStyle: { color: "#9eb7e5", opacity: 0.08 }, connectNulls: false,
      },
      {
        name: "丢包率", type: "line", yAxisIndex: 1, showSymbol: false, step: "end",
        // 失败=100%；ping 有逐次真实丢包率
        data: pts.map((p) => (!p.success ? 100 : +(p.loss_pct ?? 0).toFixed(1))),
        lineStyle: { width: 1, color: "#e58aa5" }, itemStyle: { color: "#e58aa5" },
        areaStyle: { color: "#e58aa5", opacity: 0.06 },
      },
    ],
  }, { notMerge: true });
}

watch(range, loadSeries);

// ═══════════ Tab2 MTR ═══════════
const mtrList = ref<MtrTask[]>([]);
const mtrLoading = ref(false);
const mtrRunning = ref(false);
const mtrOpenId = ref<number | null>(null);
const TRIGGER_LABEL: Record<string, string> = { manual: "手动", periodic: "定时", failure: "失败触发" };

function mtrSummary(t: MtrTask): string {
  if (t.status === "pending") return "等待节点领取…";
  if (t.status === "running") {
    const live = t.live_json?.hops?.length ?? 0;
    return live ? `实时探测中 · 已到 ${live} 跳` : "执行中…";
  }
  if (t.status === "failed") return (t.result_json as any)?.error?.slice(0, 60) || "失败";
  const rows = mtrHopRows(t.result_json?.report?.hubs);
  if (!rows.length) return "无逐跳数据";
  const last = rows[rows.length - 1];
  return `${rows.length} 跳 · 末跳 ${last.host} · 丢包 ${last.loss.toFixed(0)}% · 平均 ${last.avg != null ? last.avg.toFixed(1) : "-"}ms`;
}

// 展开的逐跳表：done 用最终结果，running 用实时快照（--raw 流式，跟终端一样边跑边刷）
function hopRows(t: MtrTask): MtrHopRow[] {
  if (t.status === "done") return mtrHopRows(t.result_json?.report?.hubs);
  return mtrHopRows(t.live_json?.hops);
}

async function loadMtr() {
  mtrLoading.value = true;
  try { mtrList.value = await listMonitorMtr(props.monitor.id); }
  catch { /* 静默 */ } finally { mtrLoading.value = false; }
}

async function runMtrNow() {
  if (mtrRunning.value) return;
  mtrRunning.value = true;
  try {
    const t = await runMonitorMtr(props.monitor.id);
    await loadMtr();
    mtrOpenId.value = t.id;
    // 轮询等结果（mtr 10 包 ~15-30s）
    for (let i = 0; i < 25; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      await loadMtr();
      const row = mtrList.value.find((x) => x.id === t.id);
      if (row && (row.status === "done" || row.status === "failed")) break;
    }
  } catch { toast("MTR 发起失败"); } finally { mtrRunning.value = false; }
}

function fmtTime(ts: string): string {
  const d = new Date(ts);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// ═══════════ Tab3 编辑 ═══════════
const monName = ref(props.monitor.name);
const monType = ref(props.monitor.type);
const monHost = ref("");
const monPort = ref("");
const monInterval = ref(props.monitor.interval);
const MON_TYPES = [
  { value: "tcp", label: "TCP 端口" }, { value: "http", label: "HTTP" }, { value: "https", label: "HTTPS" },
  { value: "ping", label: "Ping" }, { value: "udp", label: "UDP" },
];
const monNeedPort = computed(() => monType.value !== "ping");
const monPortRequired = computed(() => monType.value === "tcp" || monType.value === "udp");
const monPortPlaceholder = computed(() =>
  monType.value === "https" ? "默认 443" : monType.value === "http" ? "默认 80" : "1-65535");

function splitTarget(target: string): { host: string; port: string } {
  const t = target.replace("://", "§");  // 保护 scheme 冒号
  const i = t.lastIndexOf(":");
  if (i > 0 && /^\d+$/.test(t.slice(i + 1))) {
    return { host: t.slice(0, i).replace("§", "://"), port: t.slice(i + 1) };
  }
  return { host: target, port: "" };
}
const initTarget = splitTarget(props.monitor.target);
monHost.value = initTarget.host;
monPort.value = initTarget.port;

const saving = ref(false);
async function saveEdit() {
  if (saving.value) return;
  const host = monHost.value.replace(/：/g, ":").replace(/\s+/g, "").trim();
  const port = monPort.value.replace(/\D/g, "");
  if (!monName.value.trim()) { toast("名称要填喵~"); return; }
  if (!host) { toast("主机要填喵~"); return; }
  let target = host;
  if (monType.value !== "ping") {
    if (!port && monPortRequired.value) { toast("TCP/UDP 必须填端口喵~"); return; }
    if (port) {
      const p = Number(port);
      if (p < 1 || p > 65535) { toast("端口范围是 1-65535 喵~"); return; }
      target = `${host}:${p}`;
    }
  }
  saving.value = true;
  try {
    await updateMonitor(props.monitor.id, {
      name: monName.value.trim(), type: monType.value, target, interval: monInterval.value,
    });
    toast("已保存喵~");
    emit("saved");
  } catch { toast("保存失败"); } finally { saving.value = false; }
}

// ═══════════ 生命周期 ═══════════
watch(tab, (t) => {
  if (t === "chart") nextTick(() => { chart?.resize(); paintChart(); });
  if (t === "mtr" && !mtrList.value.length) loadMtr();
});
function onKey(e: KeyboardEvent) { if (e.key === "Escape") emit("close"); }
onMounted(() => {
  loadSeries();
  loadHourBuckets();
  if (tab.value === "mtr") loadMtr();
  document.addEventListener("keydown", onKey);
});
onUnmounted(() => {
  document.removeEventListener("keydown", onKey);
  chart?.dispose();
});
</script>

<template>
  <div class="mask" @click.self="emit('close')">
    <div class="mdl">
      <div class="mdl-head">
        <span class="mdl-title">{{ monitor.name }}</span>
        <span class="mdl-sub">{{ TYPE_LABEL[monitor.type] }} · {{ monitor.target }} · {{ nodeName }}</span>
        <span class="flex-spacer" />
        <button class="x" title="关闭" @click="emit('close')"><Icon name="x" :size="14" /></button>
      </div>
      <div class="mdl-tabs">
        <button class="mdl-tab" :class="{ active: tab === 'chart' }" @click="tab = 'chart'">图表</button>
        <button class="mdl-tab" :class="{ active: tab === 'mtr' }" @click="tab = 'mtr'">MTR 记录</button>
        <button class="mdl-tab" :class="{ active: tab === 'edit' }" @click="tab = 'edit'">编辑</button>
      </div>

      <!-- Tab1 图表 -->
      <div v-show="tab === 'chart'" class="mdl-body">
        <div v-if="stats" class="stat-row">
          <div class="stat"><span class="s-label">可用率</span><span class="s-value">{{ stats.avail.toFixed(1) }}%</span></div>
          <div class="stat"><span class="s-label">平均延迟</span><span class="s-value">{{ stats.avgLat != null ? stats.avgLat.toFixed(1) + "ms" : "—" }}</span></div>
          <div class="stat"><span class="s-label">丢包率</span><span class="s-value">{{ stats.loss.toFixed(1) }}%</span></div>
          <div class="stat"><span class="s-label">探测次数</span><span class="s-value">{{ stats.total }}</span></div>
          <span class="flex-spacer" />
          <div class="range-switch">
            <button v-for="r in RANGES" :key="r.s" class="rg-btn" :class="{ active: range === r.s }" @click="range = r.s">{{ r.label }}</button>
          </div>
        </div>
        <div ref="chartEl" class="mdl-chart" />
        <div class="avail-row">
          <span class="a-label">24h 可用率</span>
          <div class="blocks">
            <span v-for="(b, i) in hourBlocks()" :key="i" class="blk" :class="{ up: b?.ok, down: b && !b.ok }" :title="b?.label || '无数据'" />
          </div>
        </div>
      </div>

      <!-- Tab2 MTR -->
      <div v-show="tab === 'mtr'" class="mdl-body">
        <div class="mtr-bar">
          <span class="mtr-hint">近 60 天 · 每 30 分钟定时 + 失败自动触发</span>
          <span class="flex-spacer" />
          <button class="mini-btn" :disabled="mtrRunning" @click="runMtrNow">
            <Icon name="activity" :size="12" /> {{ mtrRunning ? "执行中…" : "立即 MTR" }}
          </button>
        </div>
        <div v-if="!mtrList.length && !mtrLoading" class="empty">还没有 MTR 记录，点右上角跑一次喵~</div>
        <div class="mtr-list">
          <template v-for="t in mtrList" :key="t.id">
            <div class="mtr-row clickable" @click="mtrOpenId = mtrOpenId === t.id ? null : t.id">
              <span class="mtr-time">{{ fmtTime(t.created_at) }}</span>
              <span class="mtr-trigger" :class="t.trigger">{{ TRIGGER_LABEL[t.trigger ?? "manual"] }}</span>
              <span class="mtr-status" :class="t.status">{{ t.status === "done" ? "完成" : t.status === "failed" ? "失败" : "执行中" }}</span>
              <span class="mtr-sum">{{ mtrSummary(t) }}</span>
            </div>
            <div v-if="mtrOpenId === t.id && hopRows(t).length" class="hops">
              <div class="hop hop-head">
                <span>跳</span><span>主机</span><span>Loss%</span><span>Snt</span><span>Last</span><span>Avg</span><span>Best</span><span>Wrst</span><span>StDev</span>
              </div>
              <div v-for="h in hopRows(t)" :key="h.hop" class="hop">
                <span>{{ h.hop }}</span>
                <span class="hop-host">{{ h.host }}</span>
                <span :class="{ bad: h.loss > 0 }">{{ h.loss.toFixed(1) }}</span>
                <span>{{ h.snt ?? "-" }}</span>
                <span>{{ h.last != null ? h.last.toFixed(1) : "-" }}</span>
                <span>{{ h.avg != null ? h.avg.toFixed(1) : "-" }}</span>
                <span>{{ h.best != null ? h.best.toFixed(1) : "-" }}</span>
                <span>{{ h.wrst != null ? h.wrst.toFixed(1) : "-" }}</span>
                <span>{{ h.stdev != null ? h.stdev.toFixed(1) : "-" }}</span>
              </div>
            </div>
            <div v-else-if="mtrOpenId === t.id" class="hops empty">{{ t.result_json?.error || "无逐跳数据" }}</div>
          </template>
        </div>
      </div>

      <!-- Tab3 编辑 -->
      <div v-show="tab === 'edit'" class="mdl-body edit-body">
        <label>名称</label>
        <input v-model="monName" />
        <label>类型</label>
        <Dropdown v-model="monType" :options="MON_TYPES" />
        <label>{{ monType.startsWith("http") ? "主机 / 域名（可带路径）" : "主机 / IP / 域名" }}</label>
        <input v-model="monHost" :placeholder="monType.startsWith('http') ? '如 example.com/health' : '如 example.com 或 1.2.3.4'" />
        <template v-if="monNeedPort">
          <label>端口<span v-if="!monPortRequired" class="lbl-hint">（可空）</span></label>
          <input v-model="monPort" inputmode="numeric" :placeholder="monPortPlaceholder" />
        </template>
        <label>探测节点</label>
        <div class="node-fixed">{{ nodeName }}<span class="lbl-hint">不可换节点（历史数据挂在原节点上）</span></div>
        <label>探测间隔（秒）</label>
        <input v-model.number="monInterval" type="number" min="10" />
        <div class="edit-foot">
          <button class="confirm" :disabled="saving" @click="saveEdit">{{ saving ? "保存中…" : "保存" }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask { position: fixed; inset: 0; background: rgba(10, 12, 18, 0.6); backdrop-filter: blur(3px); display: flex; align-items: center; justify-content: center; z-index: 100; }
.mdl { width: 720px; max-width: 92vw; max-height: 86vh; overflow-y: auto; background: var(--bg-raised, #1a1e2a); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 18px 22px; }
.mdl-head { display: flex; align-items: baseline; gap: 10px; }
.mdl-title { font-size: 16px; font-weight: 600; color: var(--text-hi, #e8edf7); }
.mdl-sub { font-size: 12px; color: var(--text-faint, #5b6373); font-family: var(--font-mono, monospace); }
.flex-spacer { flex: 1; }
.x { background: none; border: none; color: var(--text-faint, #5b6373); cursor: pointer; padding: 4px; }
.x:hover { color: var(--text-hi, #e8edf7); }

.mdl-tabs { display: flex; gap: 4px; margin: 14px 0 16px; border-bottom: 1px solid rgba(255,255,255,0.07); }
.mdl-tab { background: none; border: none; color: var(--text-lo, #8b93a7); font-size: 13px; padding: 7px 14px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.mdl-tab.active { color: var(--pink, #e58aa5); border-bottom-color: var(--pink, #e58aa5); }

.stat-row { display: flex; align-items: center; gap: 18px; margin-bottom: 10px; }
.stat { display: flex; flex-direction: column; gap: 2px; }
.s-label { font-size: 11px; color: var(--text-faint, #5b6373); }
.s-value { font-size: 15px; font-weight: 600; color: var(--text-hi, #e8edf7); font-variant-numeric: tabular-nums; }
.range-switch { display: flex; gap: 2px; background: rgba(255,255,255,0.04); border-radius: 7px; padding: 2px; }
.rg-btn { background: none; border: none; color: var(--text-lo, #8b93a7); font-size: 11px; padding: 4px 10px; border-radius: 5px; cursor: pointer; }
.rg-btn.active { background: rgba(255,255,255,0.09); color: var(--text-hi, #e8edf7); }
.mdl-chart { height: 240px; }
.avail-row { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.a-label { font-size: 11px; color: var(--text-faint, #5b6373); white-space: nowrap; }
.blocks { display: flex; gap: 3px; flex: 1; }
.blk { flex: 1; height: 14px; border-radius: 3px; background: rgba(255,255,255,0.05); }
.blk.up { background: var(--pink, #e58aa5); }
.blk.down { background: #e5534b; }

.mtr-bar { display: flex; align-items: center; margin-bottom: 10px; }
.mtr-hint { font-size: 11px; color: var(--text-faint, #5b6373); }
.mini-btn { display: inline-flex; align-items: center; gap: 5px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); color: var(--text-lo, #8b93a7); font-size: 12px; padding: 5px 12px; border-radius: 7px; cursor: pointer; }
.mini-btn:hover:not(:disabled) { color: var(--text-hi, #e8edf7); border-color: rgba(255,255,255,0.2); }
.mini-btn:disabled { opacity: 0.5; cursor: default; }
.empty { font-size: 12px; color: var(--text-faint, #5b6373); padding: 14px 0; text-align: center; }
.mtr-list { display: flex; flex-direction: column; }
.mtr-row { display: flex; align-items: center; gap: 10px; padding: 8px 6px; border-radius: 7px; font-size: 12px; }
.mtr-row:hover { background: rgba(255,255,255,0.04); }
.clickable { cursor: pointer; }
.mtr-time { color: var(--text-faint, #5b6373); font-family: var(--font-mono, monospace); white-space: nowrap; }
.mtr-trigger { font-size: 11px; padding: 1px 8px; border-radius: 8px; background: rgba(255,255,255,0.06); color: var(--text-lo, #8b93a7); white-space: nowrap; }
.mtr-trigger.failure { background: rgba(229,83,75,0.15); color: #e58a80; }
.mtr-trigger.periodic { background: rgba(158,183,229,0.12); color: #9eb7e5; }
.mtr-status { white-space: nowrap; }
.mtr-status.done { color: #7be39a; }
.mtr-status.failed { color: #e5534b; }
.mtr-status.pending, .mtr-status.running { color: var(--text-faint, #5b6373); }
.mtr-sum { color: var(--text-lo, #8b93a7); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hops { margin: 2px 0 8px 18px; border-left: 2px solid rgba(255,255,255,0.07); padding-left: 12px; }
/* 移动端：九列约 470px 超屏宽，横滑 */
@media (max-width: 768px) {
  .hops { overflow-x: auto; margin-left: 0; border-left: none; padding-left: 0; }
  .hops .hop { min-width: 470px; }
}
.hop { display: grid; grid-template-columns: 26px minmax(120px, 1fr) repeat(7, 46px); gap: 5px; font-size: 11px; font-family: var(--font-mono, monospace); color: var(--text-lo, #8b93a7); padding: 2px 0; }
.hop span:not(.hop-host) { text-align: right; }
.hop span:first-child { text-align: left; }
.hop-head { color: var(--text-faint, #5b6373); }
.hop-host { color: var(--text-hi, #e8edf7); overflow: hidden; text-overflow: ellipsis; }
.hop .bad { color: #e5534b; }

.edit-body label { display: block; font-size: 12px; color: var(--text-lo, #8b93a7); margin: 12px 0 5px; }
.edit-body input { width: 100%; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.09); border-radius: 8px; color: var(--text-hi, #e8edf7); font-size: 13px; padding: 8px 10px; outline: none; box-sizing: border-box; }
.edit-body input:focus { border-color: var(--pink, #e58aa5); }
.lbl-hint { color: var(--text-faint, #5b6373); font-size: 11px; font-weight: 400; margin-left: 6px; }
.node-fixed { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; color: var(--text-faint, #5b6373); font-size: 13px; padding: 8px 10px; cursor: not-allowed; }
.edit-foot { margin-top: 18px; display: flex; justify-content: flex-end; }
.confirm { background: var(--pink, #e58aa5); border: none; color: #14171f; font-size: 13px; font-weight: 600; padding: 8px 22px; border-radius: 8px; cursor: pointer; }
.confirm:disabled { opacity: 0.5; cursor: default; }
</style>
