<script setup lang="ts">
// 工具页：打流测速 / MTR / 下发命令（由 tool prop 决定渲染哪一个）
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from "vue";
import * as echarts from "echarts";
import {
  listNodes, listIperfTasks, getIperfTask, createIperfTask, cancelIperfTask, listMtrTasks, createMtrTask,
  listCommands, createCommand,
  mtrHopRows, type Node, type IperfTask, type MtrTask, type Command, type MtrHopRow,
} from "../../api/servers";
import { useRouter } from "vue-router";
import { toast } from "../../composables/useToast";
import Icon from "../../shell/Icon.vue";
import Dropdown from "../../shell/Dropdown.vue";
import NodeComponents from "./NodeComponents.vue";

const props = defineProps<{ tool: "iperf" | "mtr" | "command"; presetNode?: number | null }>();

const TITLES: Record<string, { title: string; hint: string }> = {
  iperf: { title: "打流测速", hint: "iperf3 服务器互打 / 公共 speedtest" },
  mtr: { title: "MTR 路径测试", hint: "ICMP / UDP / TCP 路径探测" },
  command: { title: "下发命令", hint: "在节点执行任意命令" },
};
const toolTitle = computed(() => TITLES[props.tool]?.title || "");
const toolHint = computed(() => TITLES[props.tool]?.hint || "");

const nodes = ref<Node[]>([]);
const iperfTasks = ref<IperfTask[]>([]);
const router = useRouter();
// 工具页只留进行中 + 最近 3 条，完整历史去记录页
function activePlusRecent<T extends { status: string }>(list: T[], n = 3): T[] {
  const active = list.filter((t) => t.status === "pending" || t.status === "running");
  const rest = list.filter((t) => !active.includes(t)).slice(0, n);
  return [...active, ...rest];
}
const iperfRecent = computed(() => activePlusRecent(iperfTasks.value));
const mtrRecent = computed(() => activePlusRecent(mtrTasks.value));
const cmdRecent = computed(() => activePlusRecent(commands.value));
function goRecords() { router.push({ path: "/status", query: { view: "tools", tool: "records" } }); }
const mtrTasks = ref<MtrTask[]>([]);
const commands = ref<Command[]>([]);

// 打流表单
const iperfServerId = ref<number | null>(null);
const iperfClientId = ref<number | null>(null);
const iperfMode = ref<"iperf3" | "speedtest">("iperf3");
const iperfDuration = ref(10);
const iperfBytes = ref<string>("");
const iperfLimit = ref<"time" | "bytes">("time");  // 测速模式：按时长 / 按数据量（-t 与 -n 互斥）
const iperfParallel = ref(1);
const iperfDirection = ref("forward");
const iperfUdp = ref(false);
const iperfBitrate = ref<string>("");
const iperfPort = ref(5201);
const iperfWindow = ref<string>("");
const iperfLength = ref<string>("");
const iperfOmit = ref(0);
const iperfZerocopy = ref(false);
const iperfPreset = ref("quick");
const advOpen = ref(false);

// 预制方案：一键填充参数
interface IperfPreset { id: string; name: string; desc: string; }
const PRESETS: IperfPreset[] = [
  { id: "quick", name: "快速测试", desc: "10s 单流" },
  { id: "max", name: "压满带宽", desc: "10s 4流" },
  { id: "reverse", name: "反向测试", desc: "10s 反向" },
  { id: "udp", name: "UDP 丢包测试", desc: "UDP 100M" },
  { id: "stable", name: "长稳测试", desc: "60s" },
  { id: "fast", name: "高速链路", desc: "8流 零拷贝" },
];
function applyPreset(id: string) {
  iperfPreset.value = id;
  iperfBytes.value = "";  // 预制方案默认按时长，清空数据量
  iperfLimit.value = "time";
  const p: Record<string, () => void> = {
    quick: () => { iperfUdp.value = false; iperfDuration.value = 10; iperfParallel.value = 1; iperfDirection.value = "forward"; iperfBitrate.value = ""; iperfZerocopy.value = false; iperfOmit.value = 0; },
    max: () => { iperfUdp.value = false; iperfDuration.value = 10; iperfParallel.value = 4; iperfDirection.value = "forward"; iperfBitrate.value = ""; iperfZerocopy.value = false; iperfOmit.value = 0; },
    reverse: () => { iperfUdp.value = false; iperfDuration.value = 10; iperfParallel.value = 1; iperfDirection.value = "reverse"; iperfBitrate.value = ""; iperfZerocopy.value = false; iperfOmit.value = 0; },
    udp: () => { iperfUdp.value = true; iperfDuration.value = 10; iperfParallel.value = 1; iperfDirection.value = "forward"; iperfBitrate.value = "100M"; iperfZerocopy.value = false; iperfOmit.value = 0; },
    stable: () => { iperfUdp.value = false; iperfDuration.value = 60; iperfParallel.value = 1; iperfDirection.value = "forward"; iperfBitrate.value = ""; iperfZerocopy.value = false; iperfOmit.value = 0; },
    fast: () => { iperfUdp.value = false; iperfDuration.value = 10; iperfParallel.value = 8; iperfDirection.value = "forward"; iperfBitrate.value = ""; iperfZerocopy.value = true; iperfOmit.value = 0; },
  };
  p[id]?.();
}

// 下拉栏选项（替代原生 select）
const presetOptions = PRESETS.map((p) => ({ value: p.id, label: p.name, desc: p.desc }));
const modeOptions = [
  { value: "iperf3", label: "服务器互打（iperf3）" },
  { value: "speedtest", label: "公共 speedtest" },
];
const nodeOptions = computed(() => onlineNodes().map((n) => ({ value: n.id, label: n.name + (n.net_type === "public" ? " · 公网" : "") })));
// 打流服务端：只列公网在线节点（client 要直连它的 5201）；只有一台时自动选中
const iperfServerOptions = computed(() =>
  onlineNodes().filter((n) => n.net_type === "public").map((n) => ({ value: n.id, label: n.name + " · 公网" })));
// 打流客户端：在线节点，排除已选服务端（两端不能同机）
const iperfClientOptions = computed(() =>
  onlineNodes().filter((n) => n.id !== iperfServerId.value).map((n) => ({ value: n.id, label: n.name + (n.net_type === "public" ? " · 公网" : "") })));
const limitOptions = [
  { value: "time", label: "按时长" },
  { value: "bytes", label: "按数据量" },
];
const directionOptions = [
  { value: "forward", label: "正向（client→server）" },
  { value: "reverse", label: "反向（server→client）" },
];
const protoOptions = [
  { value: false, label: "TCP" },
  { value: true, label: "UDP" },
];
const mtrProtoOptions = [
  { value: "icmp", label: "ICMP" },
  { value: "udp", label: "UDP" },
  { value: "tcp", label: "TCP" },
];

function onPresetChange(v: string | number | boolean) {
  applyPreset(String(v));
}

// 实时打流曲线
const chartRef = ref<HTMLDivElement | null>(null);
let chart: echarts.ECharts | null = null;
const activeTaskId = ref<number | null>(null);
const activeTask = ref<IperfTask | null>(null);
const chartPoints = ref<{ ts: string; bitrate: number; lost_pct?: number; jitter_ms?: number; role?: string; retry?: boolean; attempt?: number; reason?: string; note?: string }[]>([]);
const retryEvents = computed(() => chartPoints.value.filter((p) => p.retry));
// speedtest 阶段提示：agent 回传的 note 点（选择服务器/测速中…），取最新一条
const stageNote = computed(() => [...chartPoints.value].reverse().find((p) => p.note)?.note || "");
// 任务阶段提示：从 status + server_started + 进度点数推导（后端零改动）
const phaseHint = computed(() => {
  const t = activeTask.value;
  if (!t) return "";
  if (t.status === "pending") {
    if (t.mode === "speedtest") return "等待客户端领取任务…";
    return t.server_started ? "服务端已就绪，等待客户端领取…" : "等待服务端领取并起 iperf3 -s…";
  }
  if (t.status === "running") {
    if (t.mode === "speedtest") return stageNote.value || "测速中（选服务器 → ping → 下载 → 上传，约 1 分钟）…";
    if (!chartPoints.value.filter((p) => !p.retry && !p.note).length) return "已领取，连接服务端中…";
  }
  return "";
});


// 实时指标（running 时显示最新值，不用等完成）——吞吐/丢包都用接收端真实数据
const chartDir = computed(() => activeTask.value?.direction || "forward");
const liveThruput = computed(() => {
  const pts = recvPoints(chartPoints.value, chartDir.value);
  const last = pts[pts.length - 1];
  if (!last) return "-";
  if (last.bitrate > 1e9) return "数据异常";
  return (last.bitrate / 1e6).toFixed(1) + " Mbps";
});
const liveSend = computed(() => {
  const clientPts = chartPoints.value.filter((p) => (p.role || "client") !== "server");
  const serverPts = chartPoints.value.filter((p) => p.role === "server");
  const sendPts = chartDir.value === "reverse" ? serverPts : clientPts;
  const last = sendPts[sendPts.length - 1];
  if (!last) return null;
  if (last.bitrate > 1e9) return "数据异常";
  return (last.bitrate / 1e6).toFixed(1) + " Mbps";
});
const liveLoss = computed(() => {
  const last = [...recvPoints(chartPoints.value, chartDir.value)].reverse().find((p) => p.lost_pct != null);
  return last?.lost_pct != null ? last.lost_pct.toFixed(2) + "%" : null;
});
const liveJitter = computed(() => {
  const last = [...recvPoints(chartPoints.value, chartDir.value)].reverse().find((p) => p.jitter_ms != null);
  return last?.jitter_ms != null ? last.jitter_ms.toFixed(2) + " ms" : null;
});
// 实时累计指标（跑动中就能算，不用等完成）：平均/峰值/已传数据量
const liveAvg = computed(() => {
  const pts = recvPoints(chartPoints.value, chartDir.value);
  if (!pts.length) return null;
  if (pts.some((p) => p.bitrate > 1e9)) return "数据异常";
  const sum = pts.reduce((a, p) => a + p.bitrate, 0);
  return (sum / pts.length / 1e6).toFixed(1) + " Mbps";
});
const livePeak = computed(() => {
  const pts = recvPoints(chartPoints.value, chartDir.value);
  if (!pts.length) return null;
  if (pts.some((p) => p.bitrate > 1e9)) return "数据异常";
  return (Math.max(...pts.map((p) => p.bitrate)) / 1e6).toFixed(1) + " Mbps";
});
const liveBytes = computed(() => {
  const pts = recvPoints(chartPoints.value, chartDir.value);
  if (!pts.length) return null;
  if (pts.some((p) => p.bitrate > 1e9)) return "数据异常";
  // 每秒一个点，每点 bitrate 是 bits/s（代表该秒流量），累计数据量 = Σbitrate/8（bytes）
  const totalBits = pts.reduce((a, p) => a + p.bitrate, 0);
  return fmtBytes(totalBits / 8);
});

// MTR 表单（主机/端口分栏，tcp/udp 才显示端口；全角冒号容错）
const mtrNodeId = ref<number | null>(null);
const mtrHost = ref("");
const mtrPort = ref("");
const mtrProtocol = ref("icmp");
// 高级参数（对应 mtr -c/-i/-m/-s，后端有范围校验）
const mtrAdv = ref(false);
const mtrCount = ref(10);
const mtrInterval = ref(1);
const mtrMaxHops = ref(30);
const mtrPsize = ref(64);

// 命令表单
const cmdNodeId = ref<number | null>(null);
const cmdText = ref("");

let timer: ReturnType<typeof setInterval> | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;

async function refresh() {
  try {
    [nodes.value, iperfTasks.value, mtrTasks.value, commands.value] = await Promise.all([
      listNodes(), listIperfTasks(), listMtrTasks(), listCommands(),
    ]);
    // 默认选中：服务端选唯一公网在线节点（多台公网时选第一台），客户端选第一台在线（且≠服务端）
    if (iperfServerId.value === null || !iperfServerOptions.value.some((o) => o.value === iperfServerId.value)) {
      iperfServerId.value = iperfServerOptions.value[0]?.value ?? null;
    }
    if (iperfClientId.value === null || !iperfClientOptions.value.some((o) => o.value === iperfClientId.value)) {
      iperfClientId.value = iperfClientOptions.value[0]?.value ?? null;
    }
    if (mtrNodeId.value === null && nodes.value.length) mtrNodeId.value = nodes.value[0].id;
    if (cmdNodeId.value === null && nodes.value.length) cmdNodeId.value = nodes.value[0].id;
  } catch { /* 静默 */ }
}
let presetApplied = false;
function applyPresetNode() {
  // 详情页「操作」跳入：预填本节点（iperf：公网节点预填服务端、内网预填客户端；mtr/command=目标节点），只应用一次
  if (presetApplied || props.presetNode == null) return;
  const n = nodes.value.find((x) => x.id === props.presetNode && x.status === "online");
  if (!n) return;
  if (n.net_type === "public") iperfServerId.value = n.id;
  else iperfClientId.value = n.id;
  mtrNodeId.value = n.id;
  cmdNodeId.value = n.id;
  presetApplied = true;
}

onMounted(() => { refresh().then(applyPresetNode); timer = setInterval(refresh, 5000); });
onUnmounted(() => {
  if (timer) clearInterval(timer);
  stopPoll();
  if (mtrLiveTimer) clearInterval(mtrLiveTimer);
  chart?.dispose();
});

const onlineNodes = () => nodes.value.filter((n) => n.status === "online");

async function startIperf() {
  if (iperfMode.value === "iperf3" && (iperfServerId.value === null || iperfClientId.value === null)) {
    toast("互打需要选服务端和客户端喵~"); return;
  }
  if (iperfMode.value === "speedtest" && iperfClientId.value === null) {
    toast("选一个节点跑 speedtest 喵~"); return;
  }
  try {
    const t = await createIperfTask({
      server_node_id: iperfMode.value === "iperf3" ? iperfServerId.value : null,
      client_node_id: iperfClientId.value!,
      mode: iperfMode.value,
      direction: iperfDirection.value,
      duration: iperfLimit.value === "time" ? iperfDuration.value : 10,
      bytes: iperfLimit.value === "bytes" ? iperfBytes.value || null : null,
      parallel: iperfParallel.value,
      udp: iperfUdp.value,
      bitrate: iperfBitrate.value || null,
      port: iperfPort.value,
      window: iperfWindow.value || null,
      length: iperfLength.value || null,
      omit: iperfOmit.value,
      zerocopy: iperfZerocopy.value,
      speedtest_server: iperfMode.value === "speedtest" && stServerId.value ? stServerId.value : null,
    });
    toast("打流任务已下发");
    // 开始实时跟踪
    activeTaskId.value = t.id;
    activeTask.value = t;
    chartPoints.value = [];
    progressCursor = 0;
    startPoll();
    await refresh();
  } catch (e: any) {
    toast(e?.status === 409 ? "已有打流任务进行中，等它跑完" : "下发失败");
  }
}

// 实时进度游标：独立于 chartPoints.length——之前直接用数组长度当 cursor，
// 两次轮询并发时旧请求带回重复点把长度推高，后续点被永久跳过（发送端虚线最常丢）。
let progressCursor = 0;
let pollInFlight = false;

function startPoll() {
  stopPoll();
  pollTimer = setInterval(async () => {
    if (activeTaskId.value === null || pollInFlight) return;  // 串行化：上一次没回来就跳过这轮
    pollInFlight = true;
    try {
      // 增量拉取：只取游标之后的进度点（progress 是 append-only，下标稳定），
      // 不用每秒扛全量数组——10s 任务全量也就 20 点，60s 长任务省 95% 流量
      const t = await getIperfTask(activeTaskId.value, { progressAfter: progressCursor });
      activeTask.value = t;
      if (t.progress_json?.length) {
        chartPoints.value = chartPoints.value.concat(t.progress_json);
        progressCursor += t.progress_json.length;  // 游标只按真实新增推进，不吃重复
        renderChart();
      }
      if (t.status === "done" || t.status === "failed") {
        stopPoll();
        // 收尾全量补拉一次：server 端最后几秒的进度点可能晚于 client 的 done 回传，
        // 增量轮询已停，不全量补一次实时曲线会比历史记录少尾巴
        try {
          const full = await getIperfTask(activeTaskId.value);
          if (full.progress_json?.length) {
            chartPoints.value = full.progress_json;
            progressCursor = full.progress_json.length;
            renderChart();
          }
        } catch { /* 静默 */ }
        await refresh(); // 历史记录刷新
      }
    } catch { /* 静默 */ }
    finally { pollInFlight = false; }
  }, 1000);
}
function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

async function cancelTask() {
  if (activeTaskId.value === null) return;
  try {
    await cancelIperfTask(activeTaskId.value);
    toast("已中止打流喵~");
    await refresh();
  } catch {
    toast("中止失败");
  }
}

function buildChartOption(x: string[], y: number[], sendY?: number[], lost?: (number | null)[]) {
  const hasLost = !!(lost && lost.some((v) => v != null));
  const hasSend = !!(sendY && sendY.some((v) => v != null));
  const yAxis: any[] = [{
    type: "value", name: "Mbps", nameTextStyle: { color: "#9aa0aa" },
    axisLabel: { color: "#9aa0aa" },
    splitLine: { lineStyle: { color: "#1f2229" } },
  }];
  if (hasLost) {
    yAxis.push({
      type: "value", name: "丢包%", position: "right", min: 0,
      nameTextStyle: { color: "#9aa0aa" },
      axisLabel: { color: "#9aa0aa", formatter: "{value}%" },
      splitLine: { show: false },
    });
  }
  const series: any[] = [{
    name: "接收速率", type: "line", data: y, smooth: true, showSymbol: false,
    lineStyle: { color: "#ff9ec7", width: 1.5 },
    itemStyle: { color: "#ff9ec7" },
    areaStyle: { color: "#ff9ec7", opacity: 0.08 },
  }];
  if (hasSend) {
    series.push({
      name: "发送速率", type: "line", data: sendY, smooth: true, showSymbol: false,
      lineStyle: { color: "#5ac8fa", width: 1.2, type: "dashed" },
      itemStyle: { color: "#5ac8fa" },
    });
  }
  if (hasLost) {
    series.push({
      name: "丢包率", type: "line", data: lost, yAxisIndex: 1, smooth: true, showSymbol: false,
      lineStyle: { color: "#ffb454", width: 1.5 },
      itemStyle: { color: "#ffb454" },
      areaStyle: { color: "#ffb454", opacity: 0.10 },
    });
  }
  return {
    backgroundColor: "transparent",
    grid: { left: 52, right: hasLost ? 52 : 16, top: 34, bottom: 26 },
    tooltip: {
      trigger: "axis",
      formatter: (params: any) => {
        const arr = Array.isArray(params) ? params : [params];
        const t0 = arr[0]?.axisValue;
        let s = t0 ? `第 ${t0} 秒` : "";
        for (const p of arr) {
          if (p.value == null) continue;
          if (p.seriesName === "丢包率") s += `<br/>${p.marker} 丢包率：${Number(p.value).toFixed(2)}%`;
          else if (p.seriesName === "发送速率") s += `<br/>${p.marker} 发送：${Number(p.value).toFixed(1)} Mbps`;
          else s += `<br/>${p.marker} 接收：${Number(p.value).toFixed(1)} Mbps`;
        }
        return s;
      },
    },
    xAxis: {
      type: "category", data: x, boundaryGap: false,
      axisLabel: { color: "#9aa0aa", formatter: (v: string) => v + "s" },
      axisLine: { lineStyle: { color: "#2a2d35" } },
    },
    yAxis,
    series,
  };
}

// 从混合的 progress 点里提取接收/发送速率和丢包率。
// 接收端=真实速率（正向 server、反向 client），发送端=发送速率（虚线基准，UDP 时=目标带宽）。
function splitChartPoints(pts: { ts: string; bitrate: number; lost_pct?: number; jitter_ms?: number; role?: string; retry?: boolean; note?: string }[], direction: string) {
  const data = pts.filter((p) => !p.retry && !p.note);  // 重试事件/阶段提示点（bitrate=0 占位）不画进吞吐曲线
  const clientPts = data.filter((p) => (p.role || "client") !== "server");
  const serverPts = data.filter((p) => p.role === "server");
  const recvPts = direction === "reverse" ? clientPts : serverPts;
  const sendPts = direction === "reverse" ? serverPts : clientPts;
  const thruPts = recvPts.length ? recvPts : sendPts;  // 接收端还没数据时回退发送端
  const y = thruPts.map((p) => p.bitrate / 1e6);       // 接收速率（主体实线）
  const sendY = sendPts.map((p) => p.bitrate / 1e6);   // 发送速率（虚线基准）
  const lost = thruPts.map((p) => (p.lost_pct != null ? p.lost_pct : null));
  // x 轴用序号（client/server 每秒各一个点，序号对齐同一秒，避免时序错位）
  const maxLen = Math.max(clientPts.length, serverPts.length);
  const x = Array.from({ length: maxLen }, (_, i) => String(i + 1));
  return { x, y, sendY, lost };
}

// 取接收端进度点（吞吐用接收端真实数据，sender 统计可能虚高）
function recvPoints(pts: { ts: string; bitrate: number; lost_pct?: number; jitter_ms?: number; role?: string; retry?: boolean; note?: string }[], direction: string) {
  const data = pts.filter((p) => !p.retry && !p.note);
  const clientPts = data.filter((p) => (p.role || "client") !== "server");
  const serverPts = data.filter((p) => p.role === "server");
  const recv = direction === "reverse" ? clientPts : serverPts;
  const send = direction === "reverse" ? serverPts : clientPts;
  return recv.length ? recv : send;
}

function renderChart() {
  if (!chartRef.value) return;
  // 每次动态获取实例：切工具/路由时 .lc-canvas 会被 v-if 销毁重建，
  // 模块级缓存的 chart 会指向已销毁的旧元素，setOption 打在空气上 → 图表空白。
  // getInstanceByDom 按当前 DOM 取实例，元素重建了就重新 init。
  chart = echarts.getInstanceByDom(chartRef.value) || echarts.init(chartRef.value);
  const dir = activeTask.value?.direction || "forward";
  const { x, y, sendY, lost } = splitChartPoints(chartPoints.value, dir);
  chart.setOption(buildChartOption(x, y, sendY, lost), { notMerge: true });
}

const statusLabel: Record<string, string> = { pending: "排队中", running: "执行中", done: "完成", failed: "失败", cancelled: "已中止" };
const statusColor: Record<string, string> = { pending: "var(--accent-dim)", running: "var(--pink)", done: "var(--pink)", failed: "var(--text-faint)", cancelled: "var(--accent-dim)" };

function fmtBandwidth(t: IperfTask): string {
  const r = t.result_json as any;
  if (t.status !== "done" || !r) return "-";
  if (r.suspicious) return "数据异常";
  if (t.mode === "speedtest") {
    const srv = r?.servers?.[0] || {};
    const dl = srv.dl_speed != null ? srv.dl_speed : (r?.download?.bandwidth ?? null);
    return dl != null ? (dl * 8 / 1e6).toFixed(1) + " Mbps" : "-";
  }
  if (r?.avg_bitrate != null) {
    return (r.avg_bitrate / 1e6).toFixed(1) + " Mbps";
  }
  const bps = r?.end?.sum_received?.bits_per_second || r?.end?.sum_sent?.bits_per_second || r?.sum_sent?.bits_per_second;
  if (!bps) return "-";
  return (bps / 1e6).toFixed(1) + " Mbps";
}

// 历史记录展开（互斥：同一时间只展开一个）
const expandedTaskId = ref<number | null>(null);
const expandedCmdId = ref<number | null>(null);
function toggleCmd(id: number) { expandedCmdId.value = expandedCmdId.value === id ? null : id; }

// 记录时间：今天内显示 HH:mm，跨年/跨天显示 MM-DD HH:mm；悬浮 title 给完整时间
function fmtTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`;
  if (d.toDateString() === now.toDateString()) return hm;
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${hm}`;
}
function toggleExpand(id: number) {
  expandedTaskId.value = expandedTaskId.value === id ? null : id;
}
const expandedMtrId = ref<number | null>(null);
function toggleMtr(id: number) {
  expandedMtrId.value = expandedMtrId.value === id ? null : id;
}

// 解析 MTR 结果里的每一跳（mtr --json 大写键 / agent 0.6.0 raw 聚合小写键都兼容）
function mtrRows(t: MtrTask): MtrHopRow[] {
  const r = t.result_json as any;
  return mtrHopRows(r?.report?.hubs || r?.hubs || []);
}
// 运行中的 MTR 实时逐跳表（agent --raw 每 ~2s 覆写 live_json，2s 轮询跟终端一样边跑边刷）
const runningMtr = computed(() =>
  mtrTasks.value.find((t) => t.status === "running" || t.status === "pending") || null);
const mtrLiveRows = computed(() => mtrHopRows(runningMtr.value?.live_json?.hops));
const mtrLiveCount = computed(() => runningMtr.value?.params_json?.count ?? 10);

let mtrLiveTimer: ReturnType<typeof setInterval> | null = null;
watch([runningMtr, () => props.tool], ([rm, tool]) => {
  if (mtrLiveTimer) { clearInterval(mtrLiveTimer); mtrLiveTimer = null; }
  if (rm && tool === "mtr") {
    mtrLiveTimer = setInterval(async () => {
      try { mtrTasks.value = await listMtrTasks(); } catch { /* 静默 */ }
    }, 2000);
  }
}, { immediate: true });

// 展开历史记录时渲染该任务的吞吐曲线。
// 列表接口不再带 progress_json（省流量），展开时懒加载单任务全量详情。
watch(expandedTaskId, async (id) => {
  if (id === null) return;
  const t = iperfTasks.value.find((x) => x.id === id);
  if (t && t.status === "done" && !t.progress_json) {
    try { Object.assign(t, await getIperfTask(id)); } catch { /* 静默 */ }
  }
  await nextTick();
  const el = document.getElementById(`hist-chart-${id}`);
  if (el && t && t.progress_json?.length) {
    const c = echarts.getInstanceByDom(el) || echarts.init(el);
    const { x, y, sendY, lost } = splitChartPoints(t.progress_json, t.direction || "forward");
    c.setOption(buildChartOption(x, y, sendY, lost), { notMerge: true });
    c.resize();
  }
});

// 切工具（打流↔MTR/命令）时 .lc-canvas 被 v-if 销毁重建，chart 实例失效。
// 切回打流后，任务若已 done（poll 已停），不会再有 renderChart 触发，
// 这里主动重渲染一次，避免图表空白。
watch(() => props.tool, async (t) => {
  if (t === "iperf") {
    await nextTick();
    if (chartPoints.value.length) renderChart();
  }
});

function nodeName(id: number | null): string {
  if (id === null) return "-";
  const n = nodes.value.find((x) => x.id === id);
  return n?.name || `#${id}`;
}

function fmtBytes(b: number | null | undefined): string {
  if (b == null) return "-";
  if (b >= 1e9) return (b / 1e9).toFixed(2) + " GB";
  if (b >= 1e6) return (b / 1e6).toFixed(1) + " MB";
  if (b >= 1e3) return (b / 1e3).toFixed(1) + " KB";
  return b.toFixed(0) + " B";
}

function fmtParams(t: IperfTask): string {
  const parts: string[] = [];
  parts.push(t.udp ? "UDP" : "TCP");
  if (t.bytes) parts.push(`数据量 ${t.bytes}`);
  else parts.push(`${t.duration}s`);
  if (t.parallel > 1) parts.push(`${t.parallel}流`);
  if (t.direction === "reverse") parts.push("反向");
  if (t.udp && t.bitrate) parts.push(`@${t.bitrate}`);
  return parts.join(" · ");
}

function resultMetrics(t: IperfTask): { label: string; value: string }[] {
  const r = t.result_json as any;
  if (!r || t.status !== "done") return [];
  if (r.suspicious) return [{ label: "提示", value: "数据异常（iperf3 统计虚高，请重测）" }];
  // speedtest 模式：下载/上传/延迟/抖动（speedtest-go 的 dl_speed/ul_speed 单位是 bytes/s，latency/jitter 是纳秒）
  if (t.mode === "speedtest") {
    const srv = r?.servers?.[0] || {};
    // speedtest-go 格式
    let dl: number | null = srv.dl_speed ?? null;
    let ul: number | null = srv.ul_speed ?? null;
    let lat: number | null = srv.latency ?? null;
    let jit: number | null = srv.jitter ?? null;
    let name: string = srv.name || "";
    let country: string = srv.country || "";
    // ookla speedtest-cli 格式（download.bandwidth 是 bytes/s，ping.latency 是 ms）
    if (dl == null && r?.download?.bandwidth != null) dl = r.download.bandwidth as number;
    if (ul == null && r?.upload?.bandwidth != null) ul = r.upload.bandwidth as number;
    if (lat == null && r?.ping?.latency != null) lat = (r.ping.latency as number) * 1e6;
    if (jit == null && r?.ping?.jitter != null) jit = (r.ping.jitter as number) * 1e6;
    if (!name && r?.server?.name) { name = r.server.name as string; country = (r.server.country as string) || ""; }
    const m: { label: string; value: string }[] = [];
    if (dl != null) m.push({ label: "下载", value: (dl * 8 / 1e6).toFixed(1) + " Mbps" });
    if (ul != null) m.push({ label: "上传", value: (ul * 8 / 1e6).toFixed(1) + " Mbps" });
    if (lat != null) m.push({ label: "延迟", value: (lat / 1e6).toFixed(1) + " ms" });
    if (jit != null) m.push({ label: "抖动", value: (jit / 1e6).toFixed(2) + " ms" });
    if (name) m.push({ label: "服务器", value: `${name}${country ? " · " + country : ""}` });
    return m;
  }
  const m: { label: string; value: string }[] = [];
  const isBytes = !!t.bytes;  // 数据量模式（-n）
  // 数据量模式：数据量放最前（核心，不强调时间）
  if (isBytes && r.total_bytes != null) m.push({ label: "数据量", value: fmtBytes(r.total_bytes) });
  // 速率：接收速率（真实）+ 发送速率（基准虚线）
  if (r.avg_bitrate != null) m.push({ label: "接收速率", value: (r.avg_bitrate / 1e6).toFixed(1) + " Mbps" });
  if (r.send_avg_bitrate != null) m.push({ label: "发送速率", value: (r.send_avg_bitrate / 1e6).toFixed(1) + " Mbps" });
  if (r.peak_bitrate != null) m.push({ label: "峰值速率", value: (r.peak_bitrate / 1e6).toFixed(1) + " Mbps" });
  // 时长模式：总数据量放最后（次要）
  if (!isBytes && r.total_bytes != null) m.push({ label: "总数据量", value: fmtBytes(r.total_bytes) });
  if (r.lost_pct != null) m.push({ label: "丢包率", value: r.lost_pct + "%" });
  if (r.jitter_ms != null) m.push({ label: "抖动", value: r.jitter_ms.toFixed(2) + " ms" });
  if (r.retransmits != null) m.push({ label: "重传", value: String(r.retransmits) });
  return m;
}

async function startMtr() {
  if (mtrNodeId.value === null || !mtrHost.value.trim()) { toast("节点和目标都要填喵~"); return; }
  const host = mtrHost.value.trim().replace(/：/g, ":").replace(/\s+/g, "");
  let target = host;
  if (mtrProtocol.value !== "icmp") {
    const p = parseInt(mtrPort.value.trim().replace(/：/g, ":"), 10);
    if (!p || p < 1 || p > 65535) { toast("TCP/UDP 要填端口号（1-65535）喵~"); return; }
    target = `${host}:${p}`;
  }
  try {
    await createMtrTask({
      node_id: mtrNodeId.value, target, protocol: mtrProtocol.value,
      params: { count: mtrCount.value, interval: mtrInterval.value, max_hops: mtrMaxHops.value, psize: mtrPsize.value },
    });
    toast("MTR 任务已下发");
    mtrHost.value = "";
    await refresh();
  } catch (e: any) { toast(e?.data?.detail || "下发失败"); }
}

async function startCmd() {
  if (cmdNodeId.value === null || !cmdText.value.trim()) { toast("节点和命令都要填喵~"); return; }
  try {
    await createCommand({ node_id: cmdNodeId.value, command: cmdText.value.trim() });
    toast("命令已下发");
    cmdText.value = "";
    await refresh();
  } catch { toast("下发失败"); }
}

// ── speedtest 服务器选择：「获取列表」让客户端节点跑 speedtest-go --list --json，解析成下拉 ──
const stServerId = ref<string>("");  // "" = 自动（延迟最低）
const stServerList = ref<{ id: string | number; name: string; country?: string }[]>([]);
const stListLoading = ref(false);
const stServerOptions = computed(() => [
  { value: "", label: "自动（延迟最低）" },
  ...stServerList.value.map((s) => ({ value: String(s.id), label: `${s.name}${s.country ? " · " + s.country : ""}` })),
]);
// 换客户端节点后旧列表作废
watch(iperfClientId, () => { stServerList.value = []; stServerId.value = ""; });

async function fetchStServers() {
  if (iperfClientId.value === null) { toast("先选客户端节点喵~"); return; }
  stListLoading.value = true;
  try {
    const cmd = await createCommand({
      node_id: iperfClientId.value,
      command: "speedtest-go --list 2>/dev/null || /opt/stella-agent/bin/speedtest-go --list",
    });
    // 轮询这条命令的结果（agent 1s 领取，--list 本身要约 10s）
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const list = await listCommands();
      const c = list.find((x) => x.id === cmd.id);
      if (c && (c.status === "done" || c.status === "failed")) {
        if (c.status === "done" && c.stdout?.trim()) {
          // speedtest-go --list 是纯文本表格：「[ 1345]  12386.43km 227ms \tHays, KS (United States) by …」
          // （--json 对 --list 不生效，v1.7.11 实测）；留 JSON 解析兜底兼容未来版本
          const out = c.stdout.trim();
          let arr: { id: string; name: string; country?: string }[] = [];
          try {
            const j = JSON.parse(out);
            const raw = Array.isArray(j) ? j : (j.servers || []);
            arr = raw.map((s: any) => ({ id: String(s.id), name: s.name || s.sponsor || `#${s.id}`, country: s.country }));
          } catch {
            const re = /^\[\s*(\d+)\]\s+[\d.]+km\s+(\d+)ms\s+\t(.+?)\s*$/gm;
            let mm: RegExpExecArray | null;
            while ((mm = re.exec(out)) !== null) {
              arr.push({ id: mm[1], name: `${mm[3].trim()} · ${mm[2]}ms` });
            }
          }
          stServerList.value = arr.slice(0, 30);
          toast(stServerList.value.length ? `拿到 ${stServerList.value.length} 个测速服务器喵~` : "列表是空的，用自动吧喵~");
        } else {
          toast("节点上没找到 speedtest-go，先在上方代装喵~");
        }
        stListLoading.value = false;
        return;
      }
    }
    toast("获取超时了喵~");
  } catch { toast("下发失败"); }
  stListLoading.value = false;
}
</script>

<template>
  <div class="tools">
    <div class="head"><h2>{{ toolTitle }}</h2><span class="sub">{{ toolHint }}</span></div>

    <!-- 打流测速 -->
    <section v-if="tool === 'iperf'" class="panel">
      <div class="p-head"><Icon name="zap" :size="15" /> 打流测速</div>

      <!-- 打流相关组件状态（全量组件在服务器页） -->
      <NodeComponents :nodes="nodes" :comps="['iperf3', 'speedtest']" style="border-bottom: 1px solid rgba(255,255,255,0.05);" @refresh="refresh" />

      <!-- 打流表单 -->
      <div class="p-body iperf-form">
        <!-- 第一组：模式 / 服务端 / 客户端 / 预制方案 -->
        <div class="form-row">
          <label>模式</label>
          <Dropdown v-model="iperfMode" :options="modeOptions" />
        </div>
        <div class="form-row" v-if="iperfMode === 'iperf3'">
          <label>服务端 <span class="tip" title="客户端要直连服务端的 5201 端口，所以服务端必须是公网节点（有公网 IP 或被穿透）">ⓘ</span></label>
          <Dropdown v-model="iperfServerId" :options="iperfServerOptions" />
        </div>
        <div v-if="iperfMode === 'iperf3' && !iperfServerOptions.length" class="hint-empty" style="padding: 0 2px;">
          没有在线的公网节点喵~ 在「服务器」页把节点设为公网（或确认公网节点在线）再来互打
        </div>
        <div class="form-row">
          <label>客户端</label>
          <Dropdown v-model="iperfClientId" :options="iperfMode === 'iperf3' ? iperfClientOptions : nodeOptions" />
        </div>
        <div class="form-row" v-if="iperfMode === 'speedtest'">
          <label>测速服务器 <span class="tip" title="默认自动选延迟最低的服务器；点「获取列表」从客户端节点拉取可选服务器">ⓘ</span></label>
          <Dropdown v-model="stServerId" :options="stServerOptions" />
          <button class="st-fetch" :disabled="stListLoading" @click="fetchStServers">{{ stListLoading ? "拉取中…" : "获取列表" }}</button>
        </div>
        <div class="form-row preset-row">
          <label>预制方案</label>
          <Dropdown :model-value="iperfPreset" :options="presetOptions" @update:model-value="onPresetChange" />
        </div>

        <!-- 参数组（换行，与上面一组分开） -->
        <div class="params-group">
          <div class="form-row">
            <label>测速模式 <span class="tip" title="按时长(-t)与按数据量(-n)互斥，二选一">ⓘ</span></label>
            <Dropdown v-model="iperfLimit" :options="limitOptions" />
          </div>
          <div class="form-row" v-if="iperfLimit === 'time'">
            <label>时长(s) <span class="tip" title="单次测速持续时间，默认 10s。长时间跑用 60s">ⓘ</span></label>
            <input v-model.number="iperfDuration" type="number" min="1" />
          </div>
          <div class="form-row" v-else>
            <label>数据量 (MB) <span class="tip" title="传指定数据量后停止（-n，单位 MB）。填纯数字，如 100 = 100MB">ⓘ</span></label>
            <input v-model="iperfBytes" placeholder="如 100" />
          </div>
          <div class="form-row">
            <label>并行流 <span class="tip" title="并发 TCP 流数。单流可能压不满带宽，多流能压出更高吞吐">ⓘ</span></label>
            <input v-model.number="iperfParallel" type="number" min="1" max="32" />
          </div>
          <div class="form-row" v-if="iperfMode === 'iperf3'">
            <label>方向 <span class="tip" title="正向=client 发 server 收；反向(-R)=server 发 client 收，测下行">ⓘ</span></label>
            <Dropdown v-model="iperfDirection" :options="directionOptions" />
          </div>
          <div class="form-row" v-if="iperfMode === 'iperf3'">
            <label>协议 <span class="tip" title="TCP 测吞吐；UDP 测丢包/抖动，需配目标带宽">ⓘ</span></label>
            <Dropdown v-model="iperfUdp" :options="protoOptions" />
          </div>
          <div class="form-row" v-if="iperfMode === 'iperf3'">
            <label>速率 (Mbps) <span class="tip" title="目标速率（-b，单位 Mbps）。UDP 必填（决定发送速率，默认 100）；TCP 可选（留空不限速，填了限速测）">ⓘ</span></label>
            <input v-model="iperfBitrate" :placeholder="iperfUdp ? '如 100（默认 100）' : '如 100，留空不限速'" />
          </div>

          <!-- 高级参数 -->
          <button class="adv-toggle" type="button" @click="advOpen = !advOpen">
            <Icon name="chevron" :size="13" :class="{ rot: advOpen }" /> 高级参数
          </button>
          <div v-if="advOpen" class="adv-grid">
            <div class="form-row">
              <label>端口 <span class="tip" title="server 监听端口（-p），默认 5201。改端口记得两端一致">ⓘ</span></label>
              <input v-model.number="iperfPort" type="number" min="1" max="65535" />
            </div>
            <div class="form-row" v-if="!iperfUdp">
              <label>TCP 窗口 <span class="tip" title="TCP 窗口大小（-w），如 256K/1M。高延迟跨海链路调大能提吞吐">ⓘ</span></label>
              <input v-model="iperfWindow" placeholder="如 256K" />
            </div>
            <div class="form-row">
              <label>缓冲区 <span class="tip" title="缓冲区长度（-l），默认 128KB(TCP)/8KB(UDP)，一般不用改">ⓘ</span></label>
              <input v-model="iperfLength" placeholder="默认" />
            </div>
            <div class="form-row" v-if="!iperfUdp">
              <label>预热 <span class="tip" title="忽略前 N 秒（-O），排除 TCP 慢启动阶段，测更稳定的吞吐">ⓘ</span></label>
              <input v-model.number="iperfOmit" type="number" min="0" />
            </div>
            <div class="form-row check-row" v-if="!iperfUdp">
              <label>零拷贝 <span class="tip" title="零拷贝模式（-Z），高速链路减少 CPU 拷贝，需两端支持">ⓘ</span></label>
              <input v-model="iperfZerocopy" type="checkbox" />
            </div>
          </div>
        </div>

        <button class="go-btn" @click="startIperf"><Icon name="zap" :size="14" /> 开始打流</button>
      </div>

      <!-- 实时曲线 -->
      <div v-if="activeTask && (activeTask.status === 'running' || activeTask.status === 'pending' || chartPoints.length)" class="live-chart">
        <div class="lc-head">
          <span>实时吞吐 · 任务 #{{ activeTask.id }}</span>
          <span v-if="phaseHint" class="lc-phase">{{ phaseHint }}</span>
          <span class="lc-st" :style="{ color: statusColor[activeTask.status] }">{{ statusLabel[activeTask.status] }}</span>
          <button v-if="activeTask.status === 'running' || activeTask.status === 'pending'" class="cancel-btn" @click="cancelTask">中止</button>
        </div>
        <!-- 重试说明：偶发控制连接 reset 时 agent 自动重试，这里回显原因和次数 -->
        <div v-if="retryEvents.length" class="retry-hint">
          <span v-for="e in retryEvents" :key="e.ts" class="retry-item">⚠️ 重试第 {{ e.attempt }} 次：{{ e.reason }}</span>
        </div>
        <div ref="chartRef" class="lc-canvas" />
        <!-- 指标条：running 显示实时累计值，pending 显示等待提示，done 显示完整汇总 -->
        <div class="metric-bar">
          <template v-if="activeTask.status === 'running'">
            <span class="metric"><span class="m-label">接收</span><b class="m-val">{{ liveThruput }}</b></span>
            <span v-if="liveSend" class="metric"><span class="m-label">发送</span><b class="m-val" style="color:#5ac8fa">{{ liveSend }}</b></span>
            <span v-if="liveAvg" class="metric"><span class="m-label">平均</span><b class="m-val">{{ liveAvg }}</b></span>
            <span v-if="livePeak" class="metric"><span class="m-label">峰值</span><b class="m-val">{{ livePeak }}</b></span>
            <span v-if="liveBytes" class="metric"><span class="m-label">已传</span><b class="m-val">{{ liveBytes }}</b></span>
            <span v-if="liveLoss" class="metric"><span class="m-label">丢包</span><b class="m-val">{{ liveLoss }}</b></span>
            <span v-if="liveJitter" class="metric"><span class="m-label">抖动</span><b class="m-val">{{ liveJitter }}</b></span>
          </template>
          <template v-else-if="activeTask.status === 'pending'">
            <span class="metric"><span class="m-label">状态</span><b class="m-val">{{ phaseHint || "排队中喵~" }}</b></span>
          </template>
          <template v-else-if="activeTask.status === 'done'">
            <span v-for="m in resultMetrics(activeTask)" :key="m.label" class="metric">
              <span class="m-label">{{ m.label }}</span><b class="m-val">{{ m.value }}</b>
            </span>
          </template>
        </div>
      </div>

      <!-- 历史打流记录 -->
      <div class="task-list">
        <div class="th">历史打流记录 <button class="more-link" @click="goRecords">更多记录 →</button></div>
        <template v-for="t in iperfRecent" :key="t.id">
          <div class="task-row" :class="{ open: expandedTaskId === t.id }" @click="toggleExpand(t.id)">
            <span class="t-dot" :style="{ background: statusColor[t.status] }" />
            <span class="t-name">
              <b class="t-id">#{{ t.id }}</b>
              <template v-if="t.mode === 'iperf3'">{{ nodeName(t.client_node_id) }} → {{ nodeName(t.server_node_id) }}</template>
              <template v-else>{{ nodeName(t.client_node_id) }} · speedtest</template>
            </span>
            <span class="t-params">{{ fmtParams(t) }}</span>
            <span class="t-time" :title="new Date(t.created_at).toLocaleString('zh-CN')">{{ fmtTime(t.created_at) }}</span>
            <span class="t-st">{{ statusLabel[t.status] }}</span>
            <span class="t-bw" v-if="t.status === 'done'">{{ fmtBandwidth(t) }}</span>
            <Icon name="chevron" :size="12" :class="{ rot: expandedTaskId === t.id }" class="t-expand" />
          </div>
          <!-- 展开：历史图表 + 结果指标 -->
          <div v-if="expandedTaskId === t.id" class="task-expand">
            <div v-if="t.status === 'done' && t.progress_json?.length" :id="`hist-chart-${t.id}`" class="hist-chart" />
            <div v-if="t.status === 'done'" class="metric-bar">
              <span v-for="m in resultMetrics(t)" :key="m.label" class="metric">
                <span class="m-label">{{ m.label }}</span><b class="m-val">{{ m.value }}</b>
              </span>
            </div>
            <div v-if="t.status === 'failed'" class="t-err">{{ (t.result_json as any)?.error }}</div>
          </div>
        </template>
        <div v-if="!iperfTasks.length" class="hint-empty">暂无打流记录</div>
      </div>
    </section>

    <!-- MTR -->
    <section v-else-if="tool === 'mtr'" class="panel">
      <div class="p-head"><Icon name="globe" :size="15" /> MTR 路径测试</div>
      <div class="p-body">
        <div class="form-row">
          <label>发起节点</label>
          <Dropdown v-model="mtrNodeId" :options="nodeOptions" />
        </div>
        <div class="form-row">
          <label>协议</label>
          <Dropdown v-model="mtrProtocol" :options="mtrProtoOptions" />
        </div>
        <div class="form-row">
          <label>主机</label>
          <input v-model="mtrHost" placeholder="如 8.8.8.8 或 example.com" @keydown.enter="startMtr" />
        </div>
        <div class="form-row" v-if="mtrProtocol !== 'icmp'">
          <label>端口</label>
          <input v-model="mtrPort" placeholder="如 443" style="width: 110px;" @keydown.enter="startMtr" />
        </div>
        <button class="adv-toggle" @click="mtrAdv = !mtrAdv">
          {{ mtrAdv ? "收起参数" : "参数" }}（-c {{ mtrCount }} 包 · -i {{ mtrInterval }}s · -m {{ mtrMaxHops }} 跳 · -s {{ mtrPsize }}B）
        </button>
        <div v-if="mtrAdv" class="mtr-adv">
          <div class="form-row"><label>包数 -c</label><input type="number" v-model.number="mtrCount" min="1" max="100" /></div>
          <div class="form-row"><label>间隔 -i（秒）</label><input type="number" v-model.number="mtrInterval" min="1" max="60" step="0.5" title="mtr 非 root 用户最小 1 秒" /></div>
          <div class="form-row"><label>最大跳数 -m</label><input type="number" v-model.number="mtrMaxHops" min="1" max="255" /></div>
          <div class="form-row"><label>包大小 -s（B）</label><input type="number" v-model.number="mtrPsize" min="24" max="9000" /></div>
        </div>
        <button class="go-btn" @click="startMtr"><Icon name="globe" :size="14" /> 开始 MTR</button>
      </div>

      <!-- 实时路径：agent --raw 每 ~2s 覆写快照，和终端 mtr 一样边跑边刷 -->
      <div v-if="runningMtr" class="mtr-live">
        <div class="th">
          实时路径 · #{{ runningMtr.id }} {{ runningMtr.target }}（{{ runningMtr.protocol.toUpperCase() }}）
          <span class="lc-phase">{{ runningMtr.status === "pending" ? "等待节点领取…" : `探测中 · 每跳 ${mtrLiveCount} 包` }}</span>
        </div>
        <div v-if="mtrLiveRows.length" class="mtr-table live">
          <div class="mtr-row mtr-hd"><span>跳</span><span>主机</span><span>Loss%</span><span>Snt</span><span>Last</span><span>Avg</span><span>Best</span><span>Wrst</span><span>StDev</span></div>
          <div v-for="h in mtrLiveRows" :key="h.hop" class="mtr-row">
            <span class="mtr-hop">{{ h.hop }}</span>
            <span class="mtr-host">{{ h.host }}</span>
            <span class="mtr-num" :class="{ bad: h.loss > 0 }">{{ h.loss.toFixed(1) }}</span>
            <span class="mtr-num">{{ h.snt ?? "-" }}</span>
            <span class="mtr-num">{{ h.last != null ? h.last.toFixed(1) : "-" }}</span>
            <span class="mtr-num">{{ h.avg != null ? h.avg.toFixed(1) : "-" }}</span>
            <span class="mtr-num">{{ h.best != null ? h.best.toFixed(1) : "-" }}</span>
            <span class="mtr-num">{{ h.wrst != null ? h.wrst.toFixed(1) : "-" }}</span>
            <span class="mtr-num">{{ h.stdev != null ? h.stdev.toFixed(1) : "-" }}</span>
          </div>
        </div>
        <div v-else class="hint-empty">正在发起探测…</div>
      </div>

      <div class="task-list">
        <div class="th">历史记录 <button class="more-link" @click="goRecords">更多记录 →</button></div>
        <template v-for="t in mtrRecent" :key="t.id">
          <div class="task-row" :class="{ open: expandedMtrId === t.id }" @click="toggleMtr(t.id)">
            <span class="t-dot" :style="{ background: statusColor[t.status] }" />
            <span class="t-name"><b class="t-id">#{{ t.id }}</b><span class="cmd-node">{{ nodeName(t.node_id) }}</span> {{ t.target }} <span class="t-params">{{ t.protocol.toUpperCase() }} · {{ t.params_json?.count ?? 10 }} 包</span></span>
            <span class="t-time" :title="new Date(t.created_at).toLocaleString('zh-CN')">{{ fmtTime(t.created_at) }}</span>
            <span class="t-st">{{ statusLabel[t.status] }}</span>
            <Icon name="chevron" :size="12" :class="{ rot: expandedMtrId === t.id }" class="t-expand" />
          </div>
          <div v-if="expandedMtrId === t.id" class="task-expand">
            <div class="mtr-params-line">
              {{ t.protocol.toUpperCase() }} · -c {{ t.params_json?.count ?? 10 }} 包/跳 · -i {{ t.params_json?.interval ?? 1 }}s · -m {{ t.params_json?.max_hops ?? 30 }} 跳 · -s {{ t.params_json?.psize ?? 64 }}B
            </div>
            <div v-if="t.status === 'done' && mtrRows(t).length" class="mtr-table">
              <div class="mtr-row mtr-hd"><span>跳</span><span>主机</span><span>Loss%</span><span>Snt</span><span>Last</span><span>Avg</span><span>Best</span><span>Wrst</span><span>StDev</span></div>
              <div v-for="h in mtrRows(t)" :key="h.hop" class="mtr-row">
                <span class="mtr-hop">{{ h.hop }}</span>
                <span class="mtr-host">{{ h.host }}</span>
                <span class="mtr-num" :class="{ bad: h.loss > 0 }">{{ h.loss.toFixed(1) }}</span>
                <span class="mtr-num">{{ h.snt ?? "-" }}</span>
                <span class="mtr-num">{{ h.last != null ? h.last.toFixed(1) : "-" }}</span>
                <span class="mtr-num">{{ h.avg != null ? h.avg.toFixed(1) : "-" }}</span>
                <span class="mtr-num">{{ h.best != null ? h.best.toFixed(1) : "-" }}</span>
                <span class="mtr-num">{{ h.wrst != null ? h.wrst.toFixed(1) : "-" }}</span>
                <span class="mtr-num">{{ h.stdev != null ? h.stdev.toFixed(1) : "-" }}</span>
              </div>
            </div>
            <div v-if="t.status === 'done' && !mtrRows(t).length" class="hint-empty">无路径数据（可能被目标过滤）</div>
            <div v-if="t.status === 'failed'" class="t-err">{{ (t.result_json as any)?.error }}</div>
          </div>
        </template>
        <div v-if="!mtrTasks.length" class="hint-empty">暂无 MTR 记录</div>
      </div>
    </section>

    <!-- 下发命令 -->
    <section v-else class="panel">
      <div class="p-head"><Icon name="terminal" :size="15" /> 下发命令 <span class="warn">⚠ 可执行任意命令</span></div>
      <div class="p-body">
        <div class="form-row">
          <label>目标节点</label>
          <Dropdown v-model="cmdNodeId" :options="nodeOptions" />
        </div>
        <div class="form-row">
          <label>命令</label>
          <input v-model="cmdText" placeholder="如 uptime 或 df -h" @keydown.enter="startCmd" />
        </div>
        <button class="go-btn" @click="startCmd"><Icon name="terminal" :size="14" /> 执行</button>
      </div>
      <div class="cmd-list">
        <div class="th">历史记录 <button class="more-link" @click="goRecords">更多记录 →</button></div>
        <template v-for="c in cmdRecent" :key="c.id">
          <div class="cmd-row clickable" @click="toggleCmd(c.id)">
            <span class="t-dot" :style="{ background: statusColor[c.status] }" />
            <span class="cmd-node">{{ nodeName(c.node_id) }}</span>
            <code class="cmd-text">{{ c.command }}</code>
            <span class="t-time">{{ fmtTime(c.created_at) }}</span>
            <span class="t-st">{{ statusLabel[c.status] }}</span>
            <Icon v-if="c.stdout || c.stderr" name="chevron" :size="12" class="t-expand" :class="{ rot: expandedCmdId === c.id }" />
          </div>
          <div v-if="expandedCmdId === c.id && (c.stdout || c.stderr)" class="cmd-expand">
            <pre v-if="c.stdout" class="cmd-out">{{ c.stdout }}</pre>
            <pre v-if="c.stderr" class="cmd-out err">{{ c.stderr }}</pre>
          </div>
        </template>
        <div v-if="!commands.length" class="hint-empty">暂无命令记录</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.tools { height: 100%; overflow-y: auto; padding: 22px 26px; }
.head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 18px; }
h2 { font-size: 19px; font-weight: 600; letter-spacing: 1px; }
.sub { color: var(--text-faint); font-size: 12px; }
.panel {
  background: var(--bg-raised); border: 1px solid rgba(255,255,255,0.06);
  border-radius: var(--radius); margin-bottom: 18px; overflow: hidden;
}
.p-head {
  display: flex; align-items: center; gap: 8px; padding: 12px 16px;
  font-size: 13.5px; font-weight: 600; border-bottom: 1px solid rgba(255,255,255,0.05);
}
.warn { font-size: 11px; color: var(--pink); font-weight: 400; margin-left: auto; }
.p-body { padding: 14px 16px; display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
.form-row { display: flex; flex-direction: column; gap: 4px; }
.form-row label { font-size: 11px; color: var(--text-faint); }
.form-row input, .form-row select {
  padding: 7px 11px; background: var(--bg-panel); border: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-sm); color: var(--text-hi); font-size: 13px; outline: none; min-width: 140px;
}
.form-row input:focus, .form-row select:focus { border-color: var(--accent-dim); }
.form-row select {
  appearance: none; -webkit-appearance: none; padding-right: 28px; cursor: pointer;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%238a94ab' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right 10px center;
}
.form-row select:hover { border-color: var(--accent-dim); }
.tip { color: var(--text-faint); cursor: help; font-style: normal; }
.st-fetch {
  background: transparent; border: 1px solid var(--accent-dim); color: var(--text-lo);
  border-radius: var(--radius-sm); padding: 3px 12px; font-size: 12px; cursor: pointer; flex-shrink: 0;
}
.st-fetch:hover:not(:disabled) { color: var(--pink); border-color: var(--pink); }
.st-fetch:disabled { opacity: 0.5; cursor: default; }
.iperf-form { align-items: flex-end; }
.preset-row { min-width: 210px; }
.preset-row select { min-width: 190px; }
.params-group {
  flex-basis: 100%; display: flex; flex-wrap: wrap; align-items: flex-end; gap: 12px;
  padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.06);
}
.adv-toggle {
  display: inline-flex; align-items: center; gap: 6px; flex-basis: 100%;
  background: transparent; border: 1px dashed rgba(255,255,255,0.15); border-radius: var(--radius-sm);
  color: var(--text-lo); font-size: 12px; padding: 6px 12px; cursor: pointer; width: fit-content;
  transition: all var(--transition);
}
.adv-toggle:hover { color: var(--accent); border-color: var(--accent-dim); }
.adv-toggle .rot { transform: rotate(90deg); }
.adv-grid { display: flex; flex-wrap: wrap; gap: 12px; width: 100%; }
.check-row { flex-direction: row; align-items: center; gap: 8px; }
.check-row input {
  appearance: none; -webkit-appearance: none;
  min-width: auto; width: 34px; height: 18px; border-radius: 999px;
  background: var(--bg-panel); border: 1px solid rgba(255,255,255,0.12);
  position: relative; cursor: pointer; transition: all 0.2s; flex-shrink: 0;
}
.check-row input::before {
  content: ""; position: absolute; top: 2px; left: 2px;
  width: 12px; height: 12px; border-radius: 50%;
  background: var(--text-faint); transition: all 0.2s;
}
.check-row input:checked { background: var(--pink); border-color: var(--pink); }
.check-row input:checked::before { left: 18px; background: var(--bg-base); }
.go-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 18px; border: none; border-radius: var(--radius-sm);
  background: var(--accent); color: var(--bg-base); font-weight: 600; font-size: 13px; cursor: pointer;
}
.go-btn:hover { opacity: 0.9; }
.task-list, .cmd-list { border-top: 1px solid rgba(255,255,255,0.05); padding: 6px 16px 12px; }
.th { font-size: 11px; color: var(--text-faint); padding: 8px 0 4px; letter-spacing: 1px; }
.task-row { display: flex; align-items: center; gap: 9px; padding: 6px 8px; font-size: 12.5px; cursor: pointer; border-radius: var(--radius-sm); }
.task-row:hover { background: var(--bg-raised); }
.task-row.open { background: var(--bg-raised); }
.t-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.t-name { flex: 1; color: var(--text-lo); }
.t-id { color: var(--accent-dim); font-weight: 600; margin-right: 4px; font-size: 11.5px; }
.t-params { color: var(--text-faint); font-size: 11px; }
.t-st { color: var(--text-faint); font-size: 11px; }
.t-bw { color: var(--pink); font-size: 12px; }
.t-expand { color: var(--text-faint); transition: transform 0.2s; flex-shrink: 0; }
.t-expand.rot { transform: rotate(90deg); }
.task-expand { padding: 4px 0 12px 16px; margin: 0 0 6px 3px; border-left: 2px solid rgba(255,255,255,0.06); }
.hist-chart { width: 100%; height: 220px; margin: 4px 0; }
.metric-bar { display: flex; flex-wrap: wrap; gap: 6px 20px; padding: 10px 0 4px; }
.metric { display: inline-flex; align-items: baseline; gap: 6px; font-size: 12px; }
.m-label { color: var(--text-faint); font-size: 11px; }
.m-val { color: var(--text-hi); font-weight: 600; font-size: 13px; }
.t-err { color: var(--text-faint); font-size: 11px; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hint-empty { color: var(--text-faint); font-size: 12px; padding: 8px 0; }
.cmd-row { display: flex; align-items: center; gap: 9px; padding: 6px 0; font-size: 12.5px; }
.cmd-row.clickable { cursor: pointer; border-radius: var(--radius-sm); }
.cmd-row.clickable:hover { background: rgba(255,255,255,0.03); }
.cmd-node { color: var(--text-faint); font-size: 11px; flex-shrink: 0; }
.t-time { color: var(--text-faint); font-size: 11px; flex-shrink: 0; font-family: var(--font-mono); }
.cmd-expand { margin-left: 16px; }
.cmd-out.err { color: var(--pink); }
.cmd-text { color: var(--accent); font-family: var(--font-mono); font-size: 12px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cmd-out {
  width: 100%; margin: 4px 0 4px 16px; padding: 8px; background: var(--bg-base);
  border-radius: var(--radius-sm); font-size: 11.5px; color: var(--text-lo);
  white-space: pre-wrap; word-break: break-all; font-family: var(--font-mono);
}

/* MTR 路径表 */
/* MTR 终端式九列表格（对齐 mtr -r 的 HOST/Loss%/Snt/Last/Avg/Best/Wrst/StDev） */
.mtr-table { display: flex; flex-direction: column; gap: 2px; margin: 6px 0; max-width: 720px; }
.mtr-row { display: grid; grid-template-columns: 30px minmax(150px, 1fr) repeat(7, 58px); gap: 6px; padding: 3px 6px; font-size: 12px; align-items: center; }
.mtr-row.mtr-hd { color: var(--text-faint); font-size: 11px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 5px; }
.mtr-hop { color: var(--text-faint); font-family: var(--font-mono); }
.mtr-host { color: var(--text-hi); font-family: var(--font-mono); word-break: break-all; }
.mtr-num { color: var(--text-lo); font-family: var(--font-mono); text-align: right; }
.mtr-num.bad { color: #ff5d6c; }
.mtr-table.live .mtr-row { background: rgba(255,255,255,0.015); border-radius: 4px; }
.mtr-live { padding: 10px 16px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.mtr-live .th { display: flex; align-items: center; gap: 10px; }
.mtr-params-line { font-size: 11px; color: var(--text-faint); font-family: var(--font-mono); margin: 2px 0 6px; }
.adv-toggle {
  align-self: flex-start; background: transparent; border: 1px solid rgba(255,255,255,0.1);
  color: var(--text-lo); border-radius: 999px; padding: 4px 12px; font-size: 11.5px;
  cursor: pointer; font-family: var(--font-mono); transition: all var(--transition);
}
.adv-toggle:hover { color: var(--text-hi); border-color: rgba(255,255,255,0.2); }
.mtr-adv { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 4px 16px; width: 100%; }
.mtr-adv input { width: 90px; }

/* 服务器组件列表 */
/* 服务器组件列表样式已搬到 NodeComponents.vue */
.th { font-size: 12px; color: var(--text-faint); margin-bottom: 4px; display: flex; align-items: center; justify-content: space-between; }
.more-link {
  background: none; border: none; color: var(--accent-dim); font-size: 11.5px;
  cursor: pointer; padding: 0; transition: color var(--transition);
}
.more-link:hover { color: var(--accent); }

/* 实时曲线 */
.live-chart { padding: 6px 16px 14px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.lc-head { display: flex; align-items: center; gap: 10px; font-size: 12.5px; padding: 6px 0; color: var(--text-hi); }
.lc-phase { font-size: 11px; color: var(--text-faint); }
.lc-st { font-size: 11px; }
.cancel-btn {
  margin-left: auto; background: transparent; color: #ff5d6c; border: 1px solid rgba(255,93,108,0.4);
  border-radius: 5px; font-size: 11px; padding: 2px 10px; cursor: pointer;
}
.cancel-btn:hover { background: rgba(255,93,108,0.12); }
.lc-summary { font-size: 12px; color: var(--text-lo); }
.retry-hint { display: flex; flex-direction: column; gap: 2px; padding: 0 0 6px; }
.retry-item { font-size: 11px; color: #ffb454; }
.lc-canvas { width: 100%; height: 260px; }
</style>
