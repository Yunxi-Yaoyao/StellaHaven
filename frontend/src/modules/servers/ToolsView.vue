<script setup lang="ts">
import HelpHint from "../settings/HelpHint.vue";
import { createPoller } from "./polling";
// 工具页：打流测速 / MTR / 下发命令（由 tool prop 决定渲染哪一个）
import { waitForTask } from "./taskWait";
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from "vue";
import * as echarts from "./chartRuntime";
import {
  listNodes, listIperfTasks, getIperfTask, createIperfTask, cancelIperfTask, listMtrTasks, createMtrJob, getMtrTask,
  listCommands, createCommand,
  mtrHopRows, type Node, type IperfTask, type MtrTask, type Command, type MtrHopRow,
} from "../../api/servers";
import { useRouter } from "vue-router";
import { toast } from "../../composables/useToast";
import Icon from "../../shell/Icon.vue";
import Dropdown from "../../shell/Dropdown.vue";
import { componentInstalled } from "./serverState";
import NodeComponents from "./NodeComponents.vue";
import SpeedtestProgress, { throughputResultError } from "./SpeedtestProgress.vue";

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
const iperfRecent = computed(() => activePlusRecent(iperfTasks.value.map(t => t.id === activeTask.value?.id ? { ...t, ...activeTask.value, progress_json: chartPoints.value } : t)));
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
const iperfSubmitting = ref(false);
const iperfError = ref('');
const iperfPollError = ref('');
const iperfCancelling = ref(false);
const cancelRequested = ref(false);
const iperfBusy = computed(() => iperfSubmitting.value || !!activeTask.value && ['pending','running'].includes(activeTask.value.status) || iperfTasks.value.some(t => ['pending','running'].includes(t.status)));
function throughputError(e: unknown, fallback: string) {
  const detail = (e as {detail?: unknown})?.detail;
  return `${typeof detail === 'string' ? detail : fallback}喵~`;
}

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
  onlineNodes().filter((n) => iperfMode.value === 'speedtest' || n.id !== iperfServerId.value).map((n) => ({ value: n.id, label: n.name + (n.net_type === "public" ? " · 公网" : "") })));
watch(iperfClientOptions, options => {
  if (!options.some(o=>o.value===iperfClientId.value)) iperfClientId.value=options[0]?.value ?? null;
});
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
let chartObserver: ResizeObserver | null = null;
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
    return t.server_started ? "服务端已领取，等待监听与客户端连接喵~" : "等待服务端领取任务喵~";
  }
  if (t.status === "running") {
    if (t.mode === "speedtest") return stageNote.value || "测速运行中，等待 CLI 返回结果喵~";
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
  if (!Number.isFinite(last.bitrate) || last.bitrate < 0) return "数据异常";
  return (last.bitrate / 1e6).toFixed(1) + " Mbps";
});
const liveSend = computed(() => {
  const clientPts = chartPoints.value.filter((p) => !p.retry && !p.note && (p.role || "client") !== "server");
  const serverPts = chartPoints.value.filter((p) => !p.retry && !p.note && p.role === "server");
  const sendPts = chartDir.value === "reverse" ? serverPts : clientPts;
  const last = sendPts[sendPts.length - 1];
  if (!last) return null;
  if (!Number.isFinite(last.bitrate) || last.bitrate < 0) return "数据异常";
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
  if (pts.some((p) => !Number.isFinite(p.bitrate) || p.bitrate < 0)) return "数据异常";
  const sum = pts.reduce((a, p) => a + p.bitrate, 0);
  return (sum / pts.length / 1e6).toFixed(1) + " Mbps";
});
const livePeak = computed(() => {
  const pts = recvPoints(chartPoints.value, chartDir.value);
  if (!pts.length) return null;
  if (pts.some((p) => !Number.isFinite(p.bitrate) || p.bitrate < 0)) return "数据异常";
  return (Math.max(...pts.map((p) => p.bitrate)) / 1e6).toFixed(1) + " Mbps";
});
const liveBytes = computed(() => {
  const pts = recvPoints(chartPoints.value, chartDir.value);
  if (!pts.length) return null;
  if (pts.some((p) => !Number.isFinite(p.bitrate) || p.bitrate < 0)) return "数据异常";
  // 每秒一个点，每点 bitrate 是 bits/s（代表该秒流量），累计数据量 = Σbitrate/8（bytes）
  const totalBits = pts.reduce((a, p) => a + p.bitrate, 0);
  return fmtBytes(totalBits / 8);
});

// MTR 表单（主机/端口分栏，tcp/udp 才显示端口；全角冒号容错）
const mtrNodeId = ref<number | null>(null);
const mtrExtraNodes = ref<number[]>([]);
const mtrMissingNodes = computed(() => nodes.value.filter(n => [mtrNodeId.value, ...mtrExtraNodes.value].includes(n.id) && componentInstalled(n.components?.mtr) === false));
const mtrSubmitting = ref(false);
const mtrError = ref('');
const mtrJobTasks = ref<MtrTask[]>([]);
const mtrResultIndex = ref(0);
const isActiveMtr = (t: MtrTask) => ['pending', 'running'].includes(t.status);
const mtrBusy = computed(() => mtrSubmitting.value || mtrJobTasks.value.some(isActiveMtr) || mtrTasks.value.some(isActiveMtr));
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

const statusError = ref('');
const statusPoll = createPoller(refreshStatus, 5000);
function refresh() { return statusPoll.run(); }
function onVisibility() {
  if(document.hidden) {statusPoll.stop();stopPoll();mtrPoll.stop();}
  else {statusPoll.start();if(activeTask.value && ["pending","running"].includes(activeTask.value.status)) startPoll();
    if(props.tool==="mtr" && runningMtr.value) mtrPoll.start();}
}


async function refreshStatus(signal: AbortSignal) {
  try {
    const [n,i,c] = await Promise.all([
      listNodes(signal), listIperfTasks(signal), listCommands(signal), mtrPoll.run(),
    ]);
    if (signal.aborted) return;
    nodes.value=n; iperfTasks.value=i; commands.value=c;
    if (!activeTask.value) {
      const running = i.find(t => ['pending','running'].includes(t.status));
      if (running) {
        activeTaskId.value = running.id; activeTask.value = running;
        chartPoints.value = running.progress_json || []; progressCursor = chartPoints.value.length;
        startPoll();
      }
    }
    // 默认选中：服务端选唯一公网在线节点（多台公网时选第一台），客户端选第一台在线（且≠服务端）
    if (iperfServerId.value === null || !iperfServerOptions.value.some((o) => o.value === iperfServerId.value)) {
      iperfServerId.value = iperfServerOptions.value[0]?.value ?? null;
    }
    if (iperfClientId.value === null || !iperfClientOptions.value.some((o) => o.value === iperfClientId.value)) {
      iperfClientId.value = iperfClientOptions.value[0]?.value ?? null;
    }
    if (mtrNodeId.value === null && nodes.value.length) mtrNodeId.value = nodes.value[0].id;
    if (cmdNodeId.value === null && nodes.value.length) cmdNodeId.value = nodes.value[0].id;
    statusError.value = '';
  } catch { if (!signal.aborted) statusError.value = '节点与任务刷新失败，已保留上次结果，正在重试喵~'; }
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

onMounted(() => { if (!document.hidden) statusPoll.start(); document.addEventListener("visibilitychange", onVisibility); });
watch(nodes, applyPresetNode);
onUnmounted(() => {
  statusPoll.stop();
  document.removeEventListener("visibilitychange", onVisibility);
  stopPoll();
  mtrPoll.stop();
  disposed = true;
  chart?.dispose();
  chartObserver?.disconnect();
});

function onlineNodes() { return nodes.value.filter((n) => n.status === 'online'); }

async function startIperf() {
  if (iperfBusy.value) return;
  iperfError.value = '';
  if (iperfMode.value === "iperf3" && (iperfServerId.value === null || iperfClientId.value === null)) {
    toast("互打需要选服务端和客户端喵~"); return;
  }
  if (iperfMode.value === "speedtest" && iperfClientId.value === null) {
    toast("选一个节点跑 speedtest 喵~"); return;
  }
  if (iperfMode.value === 'iperf3' && (!Number.isInteger(iperfParallel.value) || iperfParallel.value < 1 || iperfParallel.value > 16)) {
    iperfError.value = '并行流必须为 1–16 的整数喵~'; return;
  }
  iperfSubmitting.value = true;
  try {
    const t = await createIperfTask(iperfMode.value === 'speedtest' ? {
      server_node_id: null, client_node_id: iperfClientId.value!, mode: 'speedtest', speedtest_server: stServerId.value || null,
    } : {
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
      speedtest_server: null,
    });
    if (disposed) return;
    toast("打流任务已下发");
    // 开始实时跟踪
    activeTaskId.value = t.id;
    activeTask.value = t;
    cancelRequested.value = false; iperfPollError.value = '';
    chartPoints.value = [];
    progressCursor = 0;
    startPoll();
    await refresh();
  } catch (e: any) {
    if (!disposed) iperfError.value = throughputError(e, e?.status === 409 ? '已有打流任务进行中，等它跑完再试' : '下发失败，请重试；参数已保留');
  } finally { iperfSubmitting.value = false; }
}

// 实时进度游标：独立于 chartPoints.length——之前直接用数组长度当 cursor，
// 两次轮询并发时旧请求带回重复点把长度推高，后续点被永久跳过（发送端虚线最常丢）。
let progressCursor = 0;
let disposed = false;
const iperfPoll = createPoller(async signal => {
  const id=activeTaskId.value;
  if (id===null || props.tool!=="iperf") return;
  try {
    const t=await getIperfTask(id,{progressAfter:progressCursor, signal});
    if(signal.aborted || activeTaskId.value!==id) return;
    activeTask.value=t;
    iperfPollError.value='';
    if(t.progress_json?.length) {
      chartPoints.value=chartPoints.value.concat(t.progress_json);
      progressCursor+=t.progress_json.length;
      renderChart();
    }
    if(["done","failed","cancelled"].includes(t.status)) {
      try {
        const full=await getIperfTask(id,{signal});
        if(signal.aborted) return;
        if(full.progress_json?.length) {chartPoints.value=full.progress_json;progressCursor=full.progress_json.length;renderChart();}
      } catch { /* keep the last complete progress on a failed tail fetch */ }
      if(signal.aborted) return;
      stopPoll(); await refresh();
    }
  } catch { if(!signal.aborted && !disposed) iperfPollError.value='进度刷新失败，已保留上次数据，正在重试喵~'; }
},1000);
function startPoll() { if(!disposed && !document.hidden && props.tool==="iperf") iperfPoll.start(); }
function stopPoll() { iperfPoll.stop(); }

async function cancelTask() {
  if (activeTaskId.value === null || iperfCancelling.value || cancelRequested.value) return;
  const id = activeTaskId.value;
  iperfCancelling.value = true; iperfError.value = '';
  try {
    await cancelIperfTask(id);
    if (disposed || activeTaskId.value !== id) return;
    cancelRequested.value = true;
    const task = await getIperfTask(id);
    if (disposed || activeTaskId.value !== id) return;
    activeTask.value = task;
    if (task.progress_json) { chartPoints.value = task.progress_json; progressCursor = chartPoints.value.length; renderChart(); }
    if (['done','failed','cancelled'].includes(task.status)) stopPoll();
    await refresh();
  } catch (e) { if(!disposed) iperfError.value=throughputError(e, cancelRequested.value ? '已请求中止，但状态确认失败；正在刷新' : '中止失败，请重试'); }
  finally { iperfCancelling.value = false; }
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
  const thruPts = recvPts;  // 接收端尚无样本时留空，发送速率仍由独立虚线展示
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
  return recv;
}

function renderChart() {
  if (!chartRef.value || activeTask.value?.mode === 'speedtest') return;
  // 每次动态获取实例：切工具/路由时 .lc-canvas 会被 v-if 销毁重建，
  // 模块级缓存的 chart 会指向已销毁的旧元素，setOption 打在空气上 → 图表空白。
  // getInstanceByDom 按当前 DOM 取实例，元素重建了就重新 init。
  chart = echarts.getInstanceByDom(chartRef.value) || echarts.init(chartRef.value);
  const dir = activeTask.value?.direction || "forward";
  const { x, y, sendY, lost } = splitChartPoints(chartPoints.value, dir);
  chart.setOption(buildChartOption(x, y, sendY, lost), { notMerge: true });
}
watch(chartRef, async el => {
  chartObserver?.disconnect(); chart?.dispose(); chart = null;
  if (!el) return;
  await nextTick();
  if (disposed || chartRef.value !== el) return;
  renderChart();
  if (typeof ResizeObserver !== 'undefined') {
    chartObserver = new ResizeObserver(() => { if (el.clientWidth > 0) chart?.resize(); });
    chartObserver.observe(el);
  }
});

const statusLabel: Record<string, string> = { pending: "等待领取", running: "执行中", done: "完成", failed: "失败", cancelled: "已中止" };
const statusColor: Record<string, string> = { pending: "var(--accent-dim)", running: "var(--pink)", done: "var(--pink)", failed: "var(--text-faint)", cancelled: "var(--accent-dim)" };
function throughputStatus(t: IperfTask): string { return throughputResultError(t) ? 'failed' : t.status; }

function fmtBandwidth(t: IperfTask): string {
  const r = t.result_json as any;
  if (t.status !== "done" || !r || throughputResultError(t)) return "-";
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
const runningMtr = computed(() => mtrJobTasks.value[mtrResultIndex.value] || null);
const mtrLiveRows = computed(() => runningMtr.value?.status === 'done' ? mtrRows(runningMtr.value) : mtrHopRows(runningMtr.value?.live_json?.hops));
const mtrLiveCount = computed(() => runningMtr.value?.params_json?.count ?? 10);

const mtrPoll = createPoller(async signal => {
  const ids = mtrJobTasks.value.map(t => t.id);
  try {
    const rows=await listMtrTasks(signal);
    const missing = ids.filter(id => !rows.some(t => t.id === id));
    const exact = await Promise.all(missing.map(id => getMtrTask(id, signal)));
    if(signal.aborted || disposed || ids.join(',') !== mtrJobTasks.value.map(t=>t.id).join(',')) return;
    mtrTasks.value=rows.map(fresh => {
      const old=mtrTasks.value.find(t=>t.id===fresh.id);
      return old && !isActiveMtr(old) && isActiveMtr(fresh) ? old : fresh;
    }); mtrError.value='';
    if (!ids.length) {
      const active=rows.find(isActiveMtr);
      if (active) mtrJobTasks.value=rows.filter(t=> t.id===active.id || (active.job_id && t.job_id===active.job_id)).sort((a,b)=>a.id-b.id);
    } else if (ids.join(',') === mtrJobTasks.value.map(t=>t.id).join(',')) {
      mtrJobTasks.value=mtrJobTasks.value.map(old => {
        const fresh=[...rows,...exact].find(t=>t.id===old.id);
        return fresh && (isActiveMtr(old) || !isActiveMtr(fresh)) ? fresh : old;
      });
    }
  } catch {
    if(!signal.aborted && !disposed) mtrError.value='手动记录刷新失败，已保留上次结果；稍后重试。';
  }
},2000);
watch(() => `${props.tool}:${mtrJobTasks.value.some(isActiveMtr)}`, () => {
  mtrPoll.stop();
  if(mtrJobTasks.value.some(isActiveMtr) && props.tool==="mtr" && !document.hidden && !disposed) mtrPoll.start();
});
watch(() => props.tool, () => {
  stopPoll();
  if(props.tool==="iperf" && activeTask.value && ["pending","running"].includes(activeTask.value.status)) startPoll();
});

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
  if (t.mode === 'speedtest') return t.speedtest_server ? `服务器 #${t.speedtest_server}` : '自动选择服务器';
  const parts: string[] = [];
  parts.push(t.udp ? "UDP" : "TCP");
  if (t.bytes) parts.push(`目标 ${t.bytes}${/^\d+(\.\d+)?$/.test(t.bytes) ? ' MiB' : '（二进制单位）'}`);
  else parts.push(`${t.duration}s`);
  if (t.parallel > 1) parts.push(`${t.parallel}流`);
  if (t.direction === "reverse") parts.push("反向");
  if (t.udp && t.bitrate) parts.push(`每流 @${t.bitrate}`);
  return parts.join(" · ");
}

function resultMetrics(t: IperfTask): { label: string; value: string }[] {
  const r = t.result_json as any;
  if (!r || t.status !== "done" || throughputResultError(t)) return [];
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
  if (mtrBusy.value) return;
  if (mtrMissingNodes.value.length) { mtrError.value = '所选探测节点未安装 MTR，请先在下方下发组件安装。'; return; }
  if (mtrNodeId.value === null || !mtrHost.value.trim()) { toast("节点和目标都要填喵~"); return; }
  const host = mtrHost.value.trim().replace(/：/g, ":").replace(/\s+/g, "");
  let target = host;
  if (mtrProtocol.value !== "icmp") {
    const p = parseInt(mtrPort.value.trim().replace(/：/g, ":"), 10);
    if (!p || p < 1 || p > 65535) { toast("TCP/UDP 要填端口号（1-65535）喵~"); return; }
    target = `${host}:${p}`;
  }
  mtrSubmitting.value = true; mtrError.value = '';
  try {
    const tasks = await createMtrJob({
      node_ids: [...new Set([mtrNodeId.value, ...mtrExtraNodes.value])], target, protocol: mtrProtocol.value,
      params: { count: mtrCount.value, interval: mtrInterval.value, max_hops: mtrMaxHops.value, psize: mtrPsize.value },
    });
    if(disposed) return;
    mtrJobTasks.value=tasks; mtrResultIndex.value=0;
    mtrTasks.value=[...tasks,...mtrTasks.value.filter(t=>!tasks.some(n=>n.id===t.id))];
    toast("MTR 任务已下发");
    // Preserve the form draft after admission and completion.
    await refresh();
  } catch (e: any) { if(!disposed) mtrError.value=typeof e?.detail==='string' ? e.detail : e?.data?.detail || '下发失败，请重试；参数已保留。'; }
  finally { mtrSubmitting.value=false; }
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

// ── speedtest 服务器选择：通过现有命令通道执行本实例选择的 speedtest-go --list ──
const stServerId = ref<string>("");  // "" = 自动（延迟最低）
const stServerList = ref<{ id: string | number; name: string; country?: string }[]>([]);
const stListLoading = ref(false);
const stListError = ref('');
const stListCount = ref(0);
const stServerOptions = computed(() => [
  { value: "", label: "自动（延迟最低）" },
  ...stServerList.value.map((s) => ({ value: String(s.id), label: `${s.name}${s.country ? " · " + s.country : ""} · #${s.id}` })),
]);
// 换客户端节点后旧列表作废
let commandLifecycle = new AbortController();
onUnmounted(() => commandLifecycle.abort());
watch(iperfClientId, () => { commandLifecycle.abort(); commandLifecycle = new AbortController(); stListLoading.value = false; stListError.value = ''; stListCount.value = 0; stServerList.value = []; stServerId.value = ""; });

async function fetchStServers() {
  if (stListLoading.value) return;
  stListCount.value = 0;
  if (iperfClientId.value === null) { stListError.value='先选客户端节点喵~'; return; }
  if (nodes.value.find(n => n.id === iperfClientId.value)?.platform?.toLowerCase() === 'windows') {
    stListError.value='服务器列表目前仅支持 Linux 节点；Windows 的执行器路径与命令引用尚未验证，不下发此列表命令喵~';
    return;
  }
  const signal = commandLifecycle.signal;
  stListLoading.value = true;
  stListError.value = '';
  try {
    const cmd = await createCommand({
      node_id: iperfClientId.value,
      // Agent supplies the already-selected, instance-relative executable. Choose
      // once in the real command handler; a failed --list must not run another copy.
      command: "if [ -z \"${STELLA_SPEEDTEST_GO:-}\" ]; then printf '%s\\n' '当前 Agent 未提供可用 speedtest-go 执行器；请检查组件和 Agent 版本' >&2; exit 127; fi; \"$STELLA_SPEEDTEST_GO\" --list",
    });
    if (signal.aborted) return;
    const c = await waitForTask(async s => (await listCommands(s)).find(x => x.id === cmd.id), { signal, timeoutMs: 60000 });
    if (signal.aborted) return;
        if (c.status === "done" && (c.exit_code ?? 0) === 0 && c.stdout?.trim()) {
          // speedtest-go --list 是纯文本表格：「[ 1345]  12386.43km 227ms \tHays, KS (United States) by …」
          // （--json 对 --list 不生效，v1.7.11 实测）；留 JSON 解析兜底兼容未来版本
          const out = c.stdout.trim();
          let arr: { id: string; name: string; country?: string }[] = [];
          try {
            const j = JSON.parse(out);
            const raw = Array.isArray(j) ? j : (j.servers || []);
            arr = raw.map((s: any) => ({ id: String(s.id), name: s.name || s.sponsor || `#${s.id}`, country: s.country }));
          } catch {
            const re = /^\s*\[\s*(\d+)\]\s+[\d.]+\s*km\s+([\d.]+)\s*ms\s+(.+?)\s*$/gm;
            let mm: RegExpExecArray | null;
            while ((mm = re.exec(out)) !== null) {
              arr.push({ id: mm[1], name: `${mm[3].trim()} · ${mm[2]}ms` });
            }
          }
          stServerList.value = arr.filter(s=>/^[1-9]\d*$/.test(s.id));
          if (!stServerList.value.length) stListError.value='节点没有返回可识别的服务器列表，可以重试或使用自动选择喵~';
          else stListCount.value = stServerList.value.length;
        } else {
          stListError.value=`获取服务器列表失败：${c.stderr || (c.exit_code ? `节点命令退出码 ${c.exit_code}` : '节点未返回列表，请检查组件或网络后重试')}喵~`;
        }
        stListLoading.value = false;
        return;

  } catch (e) { if (signal.aborted) return; stListError.value=throughputError(e, e instanceof Error ? e.message : '获取列表失败，请重试'); }
  stListLoading.value = false;
}
</script>

<template>
  <div class="tools server-content">
    <div class="head"><h2>{{ toolTitle }}</h2><span class="sub">{{ toolHint }}</span></div>
    <p v-if="statusError" role="alert">{{ statusError }} <button class="mini-btn" @click="refresh">重试</button></p>

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
          <label>服务端 <HelpHint label="服务端说明">客户端要直连服务端的 5201 端口，所以服务端必须是公网节点（有公网 IP 或被穿透）</HelpHint></label>
          <Dropdown v-model="iperfServerId" :options="iperfServerOptions" />
        </div>
        <div v-if="iperfMode === 'iperf3' && !iperfServerOptions.length" class="hint-empty" style="padding: 0 2px;">
          没有在线的公网节点喵~ 在「服务器」页把节点设为公网（或确认公网节点在线）再来互打
        </div>
        <div class="form-row">
          <label>客户端</label>
          <Dropdown v-model="iperfClientId" :options="iperfMode === 'iperf3' ? iperfClientOptions : nodeOptions" />
        </div>
        <div class="form-row st-server-field" v-if="iperfMode === 'speedtest'">
          <label>测速服务器 <HelpHint label="测速服务器说明">默认自动选延迟最低的服务器；点「获取列表」从客户端节点拉取可选服务器</HelpHint></label>
          <div class="st-server-controls"><Dropdown v-model="stServerId" :options="stServerOptions" :title="stServerOptions.find(o=>o.value===stServerId)?.label" />
          <button class="st-fetch" :disabled="stListLoading || iperfClientId === null" @click="fetchStServers">{{ stListLoading ? "拉取中喵~" : stListCount ? "重新获取" : "获取列表" }}</button></div>
        </div>
        <p v-if="iperfMode === 'speedtest' && stListCount" class="st-list-status" role="status">已获取 {{ stListCount }} 个测速服务器喵~</p>
        <p v-if="iperfMode === 'speedtest' && stListError" class="iperf-error" role="status">{{ stListError }}</p>
        <div class="form-row preset-row" v-if="iperfMode === 'iperf3'">
          <label>预制方案</label>
          <Dropdown :model-value="iperfPreset" :options="presetOptions" @update:model-value="onPresetChange" />
        </div>

        <!-- 参数组（换行，与上面一组分开） -->
        <div class="params-group" v-if="iperfMode === 'iperf3'">
          <div class="form-row">
            <label>测速模式 <HelpHint label="测速模式说明">按时长(-t)与按数据量(-n)互斥，二选一</HelpHint></label>
            <Dropdown v-model="iperfLimit" :options="limitOptions" />
          </div>
          <div class="form-row" v-if="iperfLimit === 'time'">
            <label>时长(s) <HelpHint label="时长(s)说明">单次测速持续时间，默认 10s。长时间跑用 60s</HelpHint></label>
            <input v-model.number="iperfDuration" type="number" min="1" />
          </div>
          <div class="form-row" v-else>
            <label>数据量 (MiB) <HelpHint label="数据量 (MiB)说明">iperf3 的 -n 是至少传输的目标量，实际可能超调，并非严格流量上限。纯数字 100 = 100MiB；K/M/G 后缀分别为 KiB/MiB/GiB，按 1024 进位。最终统计的 MB/GB 为十进制，和输入目标单位不同喵~</HelpHint></label>
            <input v-model="iperfBytes" placeholder="如 100" />
          </div>
          <div class="form-row">
            <label>并行流 <HelpHint label="并行流说明">并发流数为 1–16。单流可能压不满带宽，多流能压出更高吞吐；UDP 目标速率按每流计算</HelpHint></label>
            <input v-model.number="iperfParallel" type="number" min="1" max="16" step="1" />
          </div>
          <div class="form-row" v-if="iperfMode === 'iperf3'">
            <label>方向 <HelpHint label="方向说明">正向=client 发 server 收；反向(-R)=server 发 client 收，测下行</HelpHint></label>
            <Dropdown v-model="iperfDirection" :options="directionOptions" />
          </div>
          <div class="form-row" v-if="iperfMode === 'iperf3'">
            <label>协议 <HelpHint label="协议说明">TCP 测吞吐；UDP 测丢包/抖动，需配目标带宽</HelpHint></label>
            <Dropdown v-model="iperfUdp" :options="protoOptions" />
          </div>
          <div class="form-row" v-if="iperfMode === 'iperf3'">
            <label>速率 (Mbps) <HelpHint label="速率 (Mbps)说明">每流目标速率（-b，单位 Mbps，K/M/G 按十进制）。UDP 默认每流 100Mbps；2 流的合计目标约为每流的 2 倍，并非总限速硬保证。TCP 可选，留空不设置速率目标喵~</HelpHint></label>
            <input v-model="iperfBitrate" :placeholder="iperfUdp ? '如 100（默认 100）' : '如 100，留空不限速'" />
          </div>

          <!-- 高级参数 -->
          <button class="adv-toggle" type="button" @click="advOpen = !advOpen">
            <Icon name="chevron" :size="13" :class="{ rot: advOpen }" /> 高级参数
          </button>
          <div v-if="advOpen" class="adv-grid">
            <div class="form-row">
              <label>端口 <HelpHint label="端口说明">server 监听端口（-p），默认 5201。改端口记得两端一致</HelpHint></label>
              <input v-model.number="iperfPort" type="number" min="1" max="65535" />
            </div>
            <div class="form-row" v-if="!iperfUdp">
              <label>TCP 窗口 <HelpHint label="TCP 窗口说明">TCP 窗口大小（-w），如 256K/1M。高延迟跨海链路调大能提吞吐</HelpHint></label>
              <input v-model="iperfWindow" placeholder="如 256K" />
            </div>
            <div class="form-row">
              <label>缓冲区 <HelpHint label="缓冲区说明">缓冲区长度（-l），默认 128KB(TCP)/8KB(UDP)，一般不用改</HelpHint></label>
              <input v-model="iperfLength" placeholder="默认" />
            </div>
            <div class="form-row" v-if="!iperfUdp">
              <label>预热 <HelpHint label="预热说明">忽略前 N 秒（-O），排除 TCP 慢启动阶段，测更稳定的吞吐</HelpHint></label>
              <input v-model.number="iperfOmit" type="number" min="0" />
            </div>
            <div class="form-row check-row" v-if="!iperfUdp">
              <label>零拷贝 <HelpHint label="零拷贝说明">零拷贝模式（-Z），高速链路减少 CPU 拷贝，需两端支持</HelpHint></label>
              <input v-model="iperfZerocopy" type="checkbox" />
            </div>
          </div>
        </div>

        <button class="go-btn st-button is-primary" :disabled="iperfBusy" :aria-busy="iperfSubmitting" @click="startIperf"><Icon name="zap" :size="14" /> {{ iperfSubmitting ? '正在下发喵~' : iperfBusy ? '测速任务进行中喵~' : iperfMode === 'speedtest' ? '开始测速' : '开始打流' }}</button>
        <p v-if="iperfError" class="iperf-error" role="alert">{{ iperfError }}</p>
      </div>

      <!-- 实时曲线 -->
      <div v-if="activeTask" class="live-chart">
        <div class="lc-head">
          <span>{{ activeTask.mode === 'speedtest' ? '公共测速' : '实时吞吐' }} · {{ nodeName(activeTask.client_node_id) }} · #{{ activeTask.id }}</span>
          <span v-if="phaseHint && activeTask.mode !== 'speedtest'" class="lc-phase">{{ phaseHint }}</span>
          <span class="lc-st" :style="{ color: statusColor[throughputStatus(activeTask)] }">{{ statusLabel[throughputStatus(activeTask)] }}喵~</span>
          <button v-if="activeTask.status === 'running' || activeTask.status === 'pending'" class="cancel-btn" :disabled="iperfCancelling || cancelRequested" @click="cancelTask">{{ iperfCancelling ? '正在中止喵~' : cancelRequested ? '等待中止确认喵~' : '中止' }}</button>
        </div>
        <p v-if="iperfPollError" class="iperf-error" role="status">{{ iperfPollError }}</p>
        <!-- 重试说明：偶发控制连接 reset 时 agent 自动重试，这里回显原因和次数 -->
        <div v-if="retryEvents.length" class="retry-hint">
          <span v-for="e in retryEvents" :key="e.ts" class="retry-item">⚠️ 重试第 {{ e.attempt }} 次：{{ e.reason }}</span>
        </div>
        <p v-if="activeTask.mode !== 'speedtest' && throughputResultError(activeTask)" class="iperf-error" role="alert">{{ throughputResultError(activeTask) }}喵~</p>
        <p v-if="activeTask.status === 'cancelled'" class="lc-summary" role="status">测试已中止，保留已收到的数据喵~</p>
        <SpeedtestProgress v-if="activeTask.mode === 'speedtest'" :task="activeTask" :points="chartPoints" :metrics="resultMetrics(activeTask)" />
        <div v-else ref="chartRef" class="lc-canvas" />
        <!-- 指标条：running 显示实时累计值，pending 显示等待提示，done 显示完整汇总 -->
        <div v-if="activeTask.mode !== 'speedtest'" class="metric-bar">
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
            <span class="t-dot" :style="{ background: statusColor[throughputStatus(t)] }" />
            <span class="t-name">
              <b class="t-id">#{{ t.id }}</b>
              <template v-if="t.mode === 'iperf3'">{{ nodeName(t.client_node_id) }} → {{ nodeName(t.server_node_id) }}</template>
              <template v-else>{{ nodeName(t.client_node_id) }} · speedtest</template>
            </span>
            <span class="t-params">{{ fmtParams(t) }}</span>
            <span class="t-time" :title="new Date(t.created_at).toLocaleString('zh-CN')">{{ fmtTime(t.created_at) }}</span>
            <span class="t-st">{{ statusLabel[throughputStatus(t)] }}</span>
            <span class="t-bw" v-if="t.status === 'done' && !throughputResultError(t)">{{ fmtBandwidth(t) }}</span>
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
            <div v-if="throughputResultError(t)" class="t-err" role="alert">{{ throughputResultError(t) }}喵~</div>
          </div>
        </template>
        <div v-if="!iperfTasks.length" class="hint-empty">暂无打流记录</div>
      </div>
    </section>

    <!-- MTR -->
    <section v-else-if="tool === 'mtr'" class="panel">
      <div class="p-head"><Icon name="globe" :size="15" /> MTR 路径测试</div>
      <div class="p-body mtr-form">
        <div class="form-row">
          <label>发起节点</label>
          <Dropdown v-model="mtrNodeId" :options="nodeOptions" />
        </div>
        <div class="form-row">
          <label>协议</label>
          <Dropdown v-model="mtrProtocol" :options="mtrProtoOptions" />
        </div>
        <div class="form-row mtr-host-field">
          <label>主机</label>
          <input v-model="mtrHost" placeholder="如 8.8.8.8 或 example.com" @keydown.enter="startMtr" />
        </div>
        <div class="form-row" v-if="mtrProtocol !== 'icmp'">
          <label>端口</label>
          <input v-model="mtrPort" placeholder="如 443" style="width: 110px;" @keydown.enter="startMtr" />
        </div>
        <button class="go-btn mtr-go st-button is-primary" :disabled="mtrBusy" :aria-busy="mtrBusy" @click="startMtr">
          <Icon name="globe" :size="14" /> {{ mtrSubmitting ? '正在下发…' : mtrBusy ? 'MTR 作业进行中' : '开始 MTR' }}
        </button>
        <fieldset class="mtr-nodes">
          <legend>同时从其他节点探测（一次最多 8 个）</legend>
          <label v-for="n in onlineNodes().filter(n=>n.id!==mtrNodeId)" :key="n.id">
            <input v-model="mtrExtraNodes" type="checkbox" :value="n.id" :disabled="!mtrExtraNodes.includes(n.id) && mtrExtraNodes.length >= 7" />{{ n.name }}
          </label>
        </fieldset>
        <div v-if="mtrBusy" class="run-progress" role="progressbar" aria-label="MTR 作业执行中，完成时间未知"><span /></div>
        <p v-if="mtrError" class="mtr-error" role="status">{{ mtrError }}</p>
        <button class="adv-toggle" @click="mtrAdv = !mtrAdv">
          {{ mtrAdv ? "收起参数" : "参数" }}（-c {{ mtrCount }} 包 · -i {{ mtrInterval }}s · -m {{ mtrMaxHops }} 跳 · -s {{ mtrPsize }}B）
        </button>
        <div v-if="mtrAdv" class="mtr-adv">
          <div class="form-row"><label>包数 -c</label><input type="number" v-model.number="mtrCount" min="1" max="100" /></div>
          <div class="form-row"><label>间隔 -i（秒）</label><input type="number" v-model.number="mtrInterval" min="1" max="60" step="0.5" title="mtr 非 root 用户最小 1 秒" /></div>
          <div class="form-row"><label>最大跳数 -m</label><input type="number" v-model.number="mtrMaxHops" min="1" max="255" /></div>
          <div class="form-row"><label>包大小 -s（B）</label><input type="number" v-model.number="mtrPsize" min="24" max="9000" /></div>
        </div>

      </div>

      <NodeComponents v-if="mtrMissingNodes.length" :nodes="mtrMissingNodes" :comps="['mtr']" @refresh="refresh" />
      <!-- 实时路径：agent --raw 每 ~2s 覆写快照，和终端 mtr 一样边跑边刷 -->
      <div v-if="runningMtr" class="mtr-live">
        <div class="mtr-result-nav" v-if="mtrJobTasks.length > 1">
          <button aria-label="上一个节点" :disabled="mtrResultIndex===0" @click="mtrResultIndex--">←</button>
          <span>{{ mtrResultIndex + 1 }} / {{ mtrJobTasks.length }} · {{ mtrJobTasks.filter(t=>!isActiveMtr(t)).length }} 个节点已结束</span>
          <button aria-label="下一个节点" :disabled="mtrResultIndex===mtrJobTasks.length-1" @click="mtrResultIndex++">→</button>
        </div>
        <Transition name="node-result" mode="out-in">
        <div :key="runningMtr.id" class="mtr-node-result">
        <div class="th">
          {{ nodeName(runningMtr.node_id) }} · #{{ runningMtr.id }} {{ runningMtr.target }}（{{ runningMtr.protocol.toUpperCase() }}）
          <span class="lc-phase">{{ runningMtr.status === 'pending' ? '等待节点领取…' : runningMtr.status === 'running' ? `探测中 · 每跳 ${mtrLiveCount} 包` : statusLabel[runningMtr.status] }}</span>
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
        <div v-else class="hint-empty">{{ runningMtr.status === 'failed' ? (runningMtr.result_json as any)?.error || '任务失败' : runningMtr.status === 'done' ? '无路径数据（可能被目标过滤）' : '正在发起探测…' }}</div>
        </div>
        </Transition>
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
        <button class="go-btn st-button is-primary" @click="startCmd"><Icon name="terminal" :size="14" /> 执行</button>
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

<style scoped src="./serverPage.css"></style>
<style scoped>
.iperf-form > .form-row { flex:1 1 170px; min-width:0; max-width:240px; }
.iperf-form > .st-server-field { flex:2 1 320px; max-width:none; }
.iperf-form :deep(.dd-btn) { width:100%;min-width:0;min-height:38px; }
.iperf-form :deep(.dd-menu) { width:max-content;min-width:100%;max-width:min(520px,calc(100vw - 72px)); }
.iperf-form :deep(.dd-item-label) { white-space:normal;overflow-wrap:anywhere; }
.panel:has(.dd-menu) { overflow:visible; }
.st-server-controls { display:flex;gap:8px;min-width:0; }
.st-server-controls :deep(.dd) { flex:1;min-width:0; }
.st-fetch { min-height:38px; }
.st-list-status { flex-basis:100%;margin:4px 0;font-size:13px;color:var(--accent);line-height:1.6; }
.iperf-form .params-group .form-row { flex:1 1 140px;min-width:0;max-width:210px; }
.iperf-form .form-row input { width:100%;min-width:0;box-sizing:border-box; }
.iperf-form .check-row input { width:34px; }
.iperf-form .go-btn { flex:none;margin:0;min-height:38px; }
.iperf-form .go-btn[aria-busy=true]::after { position:static;flex:none; }
.iperf-error { flex-basis:100%;margin:4px 0;font-size:13px;color:var(--danger);line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere; }
.lc-head { flex-wrap:wrap; }
.lc-head > span:first-child { min-width:0;overflow-wrap:anywhere; }
.cancel-btn { min-height:36px; }
.cancel-btn:disabled { opacity:.6;cursor:default; }
.t-err { max-width:none;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--danger);font-size:13px; }
.task-row .t-name { min-width:0;overflow-wrap:anywhere; }
@media(max-width:600px){
 .head{flex-wrap:wrap;gap:4px}.iperf-form>.form-row,.iperf-form>.st-server-field{flex-basis:100%;max-width:none}
 .iperf-form .params-group .form-row{flex:1 1 120px;max-width:none}.iperf-form :deep(.dd-menu){max-width:calc(100vw - 72px);width:100%}
 .task-list .task-row{display:grid;grid-template-columns:7px minmax(0,1fr) auto}.task-row .t-params{grid-column:2;grid-row:2}.task-row .t-time{grid-column:2;grid-row:3}.task-row .t-st{grid-column:3;grid-row:2}.task-row .t-bw{grid-column:3;grid-row:3}.task-row .t-expand{grid-column:3;grid-row:1}
}
.mtr-form .form-row { flex: 0 1 150px; min-width: 0; }
.mtr-form .mtr-host-field { flex: 1 1 220px; }
.mtr-form .form-row input { min-width: 0; width: 100%; box-sizing: border-box; }
.mtr-form :deep(.dd-btn) { min-width: 0; width: 100%; box-sizing: border-box; }
.mtr-form .adv-toggle { min-width: 0; max-width: 100%; white-space: normal; text-align: left; }
.mtr-form .mtr-go { flex: 0 0 auto; margin: 0; }
.mtr-go:disabled { opacity: .75; cursor: default; }
.mtr-nodes { flex-basis: 100%; display: flex; flex-wrap: wrap; gap: 10px; margin: 0; padding: 8px 0 0; border: 0; min-width: 0; }
.mtr-nodes legend { color: var(--text-lo); font-size: 12px; }
.mtr-nodes label { display: inline-flex; align-items: center; gap: 6px; min-height: 32px; font-size: 13px; color: var(--text-hi); }
.mtr-error { flex-basis: 100%; margin: 0; font-size: 13px; color: #e9a2a2; }
.run-progress { flex-basis: 100%; height: 3px; overflow: hidden; background: var(--bg-panel); border-radius: 3px; }
.run-progress span { display: block; height: 100%; width: 30%; background: var(--accent); animation: run-sweep 1.5s ease-in-out infinite alternate; }
@keyframes run-sweep { to { transform: translateX(230%); } }
.mtr-result-nav { display: flex; align-items: center; gap: 12px; padding: 10px 16px; color: var(--text-lo); font-size: 12px; }
.mtr-result-nav button { border: 1px solid var(--accent-dim); background: var(--bg-panel); color: var(--text-hi); border-radius: var(--radius-sm); min-width: 36px; min-height: 36px; cursor: pointer; }
.mtr-result-nav button:disabled { opacity: .4; cursor: default; }
.mtr-node-result { min-height: 100px; }
.node-result-enter-active,.node-result-leave-active { transition: opacity 140ms ease, transform 140ms ease; }
.node-result-enter-from { opacity: 0; transform: translateX(8px); }
.node-result-leave-to { opacity: 0; transform: translateX(-8px); }
@media (prefers-reduced-motion: reduce) { .run-progress span { animation: none; width: 100%; opacity: .5; } .node-result-enter-active,.node-result-leave-active { transition: none; } }
@media (max-width: 600px) { .mtr-form .form-row { flex: 1 1 120px; } .mtr-form .mtr-host-field { flex-basis: 100%; }.mtr-form .mtr-go { flex-basis:auto; } }
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
.tools > .head,.tools .p-head,.tools .p-body { width:100%;max-width:1040px;margin-inline:auto;box-sizing:border-box; }
.p-body { padding: 14px 16px; display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
.form-row { display: flex; flex-direction: column; gap: 4px; }
.form-row label { display:inline-flex;align-items:center;min-height:36px;font-size:14px;color:var(--text-lo); }
.form-row input, .form-row select {
  padding: 7px 11px; background: var(--bg-panel); border: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-sm); color: var(--text-hi); font-size:14px;min-height:38px;outline:none;min-width:140px;
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
.go-btn:not(.st-button) {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 18px; border: none; border-radius: var(--radius-sm);
  background: var(--accent); color: var(--bg-base); font-weight: 600; font-size: 13px; cursor: pointer;
}
.go-btn:not(.st-button):hover { opacity: 0.9; }
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
.task-expand .t-err { color: var(--danger); font-size: 13px; max-width: none; white-space: pre-wrap; overflow-wrap:anywhere; }
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
/* 移动端：九列约 620px 必然超出 393 屏宽，整表可横向滑动 */
@media (max-width: 768px) {
  .mtr-table { overflow-x: auto; max-width: 100%; }
  .mtr-table .mtr-row { min-width: 620px; }
}
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
