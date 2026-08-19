<script setup lang="ts">
// 记录页：打流 / MTR / 命令 三类任务的统一时间线。
// 数据不另存，直接读三类任务表（每类后端只留最近 100 条）；5s 轮询让进行中的任务原地更新。
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import {
  listNodes, listIperfTasks, listMtrTasks, listCommands, mtrHopRows,
  type Node, type IperfTask, type MtrTask, type Command,
} from "../../api/servers";
import { fmtTime, fmtBandwidth, fmtParams, resultMetrics, TASK_STATUS } from "./record-helpers";
import Icon from "../../shell/Icon.vue";
import Dropdown from "../../shell/Dropdown.vue";

const props = defineProps<{ presetNode?: number | null }>();

const nodes = ref<Node[]>([]);
const iperfTasks = ref<IperfTask[]>([]);
const mtrTasks = ref<MtrTask[]>([]);
const commands = ref<Command[]>([]);

// ── 过滤 ──
type Kind = "all" | "iperf" | "mtr" | "command";
const kind = ref<Kind>("all");
const filterNode = ref<number | null>(props.presetNode ?? null);
const KIND_TABS: { key: Kind; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "iperf", label: "打流" },
  { key: "mtr", label: "MTR" },
  { key: "command", label: "命令" },
];
const nodeOptions = computed(() => [
  { value: 0, label: "全部节点" },
  ...nodes.value.map((n) => ({ value: n.id, label: n.name })),
]);

function nodeName(id: number | null): string {
  if (id === null) return "-";
  return nodes.value.find((x) => x.id === id)?.name || `#${id}`;
}

// ── 统一时间线 ──
interface Row {
  key: string;
  kind: Exclude<Kind, "all">;
  ts: string;
  nodeIds: (number | null)[];
  summary: string;
  result: string;
  status: string;
  raw: IperfTask | MtrTask | Command;
}
const rows = computed<Row[]>(() => {
  const out: Row[] = [];
  if (kind.value === "all" || kind.value === "iperf") {
    for (const t of iperfTasks.value) {
      out.push({
        key: `iperf-${t.id}`, kind: "iperf", ts: t.created_at,
        nodeIds: [t.server_node_id, t.client_node_id],
        summary: t.mode === "speedtest"
          ? `${nodeName(t.client_node_id)} speedtest`
          : `${nodeName(t.server_node_id)} → ${nodeName(t.client_node_id)} · ${fmtParams(t)}`,
        result: t.status === "done" ? fmtBandwidth(t) : "",
        status: t.status, raw: t,
      });
    }
  }
  if (kind.value === "all" || kind.value === "mtr") {
    for (const t of mtrTasks.value) {
      out.push({
        key: `mtr-${t.id}`, kind: "mtr", ts: t.created_at,
        nodeIds: [t.node_id],
        summary: `${nodeName(t.node_id)} → ${t.target} · ${t.protocol.toUpperCase()}`,
        result: "", status: t.status, raw: t,
      });
    }
  }
  if (kind.value === "all" || kind.value === "command") {
    for (const t of commands.value) {
      out.push({
        key: `cmd-${t.id}`, kind: "command", ts: t.created_at,
        nodeIds: [t.node_id],
        summary: t.command,
        result: "", status: t.status, raw: t,
      });
    }
  }
  return out
    .filter((r) => filterNode.value === null || filterNode.value === 0 || r.nodeIds.includes(filterNode.value))
    .sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());
});

// ── 展开 ──
const expanded = ref<string | null>(null);
function toggle(key: string) { expanded.value = expanded.value === key ? null : key; }

function mtrHops(t: MtrTask): { host: string; loss: number; snt: number | null; avg: number | null }[] {
  // mtrHopRows 兼容旧 --json 大写键和新 raw 聚合小写键；记录页只展示摘要四列
  const r = t.result_json as any;
  return mtrHopRows(r?.report?.hubs || r?.hubs).map((h) => ({ host: h.host, loss: h.loss, snt: h.snt, avg: h.avg }));
}

const KIND_LABEL: Record<string, string> = { iperf: "打流", mtr: "MTR", command: "命令" };

// ── 轮询 ──
let timer: ReturnType<typeof setInterval> | null = null;
async function refresh() {
  try {
    const [n, i, m, c] = await Promise.all([listNodes(), listIperfTasks(), listMtrTasks(), listCommands()]);
    nodes.value = n; iperfTasks.value = i; mtrTasks.value = m; commands.value = c;
  } catch { /* 静默 */ }
}
onMounted(() => { refresh(); timer = setInterval(refresh, 5000); });
onUnmounted(() => { if (timer) clearInterval(timer); });
// 外部（详情页「操作」）带 node 跳入时同步过滤器
watch(() => props.presetNode, (v) => { if (v) filterNode.value = v; }, { immediate: true });
</script>

<template>
  <div class="rec-page">
    <h2>记录</h2>
    <p class="rec-sub">打流 / MTR / 命令 统一时间线 · 每类保留最近 100 条</p>

    <!-- 过滤器 -->
    <div class="rec-filter">
      <div class="kind-tabs">
        <button v-for="t in KIND_TABS" :key="t.key" class="kind-chip" :class="{ active: kind === t.key }" @click="kind = t.key">{{ t.label }}</button>
      </div>
      <Dropdown :model-value="filterNode ?? 0" :options="nodeOptions" @update:model-value="(v: number) => filterNode = v || null" />
    </div>

    <!-- 时间线 -->
    <div class="rec-list">
      <template v-for="r in rows" :key="r.key">
        <div class="rec-row" :class="{ open: expanded === r.key }" @click="toggle(r.key)">
          <span class="r-kind" :class="`k-${r.kind}`">{{ KIND_LABEL[r.kind] }}</span>
          <span class="r-node">{{ r.kind === 'command' ? nodeName((r.raw as Command).node_id) : r.kind === 'mtr' ? nodeName((r.raw as MtrTask).node_id) : '' }}</span>
          <span class="r-summary">{{ r.summary }}</span>
          <span v-if="r.result" class="r-result">{{ r.result }}</span>
          <span class="r-time" :title="new Date(r.ts).toLocaleString('zh-CN')">{{ fmtTime(r.ts) }}</span>
          <span class="r-st" :class="TASK_STATUS[r.status]?.cls">{{ TASK_STATUS[r.status]?.label || r.status }}</span>
          <Icon name="chevron" :size="12" class="r-expand" :class="{ rot: expanded === r.key }" />
        </div>

        <!-- 展开详情 -->
        <div v-if="expanded === r.key" class="rec-detail">
          <!-- 打流：指标卡片 -->
          <template v-if="r.kind === 'iperf'">
            <div v-if="resultMetrics(r.raw as IperfTask).length" class="metric-grid">
              <div v-for="m in resultMetrics(r.raw as IperfTask)" :key="m.label" class="metric-cell">
                <div class="mc-label">{{ m.label }}</div>
                <div class="mc-value">{{ m.value }}</div>
              </div>
            </div>
            <div v-if="(r.raw as IperfTask).status === 'failed'" class="r-err">{{ ((r.raw as IperfTask).result_json as any)?.error || "任务失败" }}</div>
            <div v-if="['pending','running'].includes((r.raw as IperfTask).status)" class="r-hint">任务进行中，到工具·打流页看实时曲线喵~</div>
          </template>
          <!-- MTR：跳数表 -->
          <template v-else-if="r.kind === 'mtr'">
            <div v-if="mtrHops(r.raw as MtrTask).length" class="mtr-table">
              <div class="mtr-row mtr-hd"><span>跳</span><span>主机</span><span>丢包</span><span>发包</span><span>平均</span></div>
              <div v-for="(h, i) in mtrHops(r.raw as MtrTask)" :key="i" class="mtr-row">
                <span class="mtr-hop">{{ i + 1 }}</span>
                <span class="mtr-host">{{ h.host }}</span>
                <span class="mtr-loss" :class="{ bad: h.loss > 0 }">{{ h.loss.toFixed(1) }}%</span>
                <span class="mtr-avg">{{ h.snt ?? "-" }}</span>
                <span class="mtr-avg">{{ h.avg != null ? h.avg.toFixed(1) + " ms" : "-" }}</span>
              </div>
            </div>
            <div v-else-if="(r.raw as MtrTask).status === 'done'" class="r-hint">无路径数据（可能被目标过滤）</div>
            <div v-else-if="(r.raw as MtrTask).status === 'failed'" class="r-err">{{ ((r.raw as MtrTask).result_json as any)?.error || "任务失败" }}</div>
            <div v-else class="r-hint">任务进行中喵~</div>
          </template>
          <!-- 命令：输出 -->
          <template v-else>
            <pre v-if="(r.raw as Command).stdout" class="r-out">{{ (r.raw as Command).stdout }}</pre>
            <pre v-if="(r.raw as Command).stderr" class="r-out err">{{ (r.raw as Command).stderr }}</pre>
            <div v-if="!(r.raw as Command).stdout && !(r.raw as Command).stderr" class="r-hint">
              {{ (r.raw as Command).status === 'done' ? '（无输出）' : '任务进行中喵~' }}
            </div>
            <div v-if="(r.raw as Command).exit_code !== null" class="r-hint">exit code: {{ (r.raw as Command).exit_code }}</div>
          </template>
        </div>
      </template>
      <div v-if="!rows.length" class="rec-empty">暂无记录喵~</div>
    </div>
  </div>
</template>

<style scoped>
.rec-page { padding: 4px 2px; }
.rec-sub { margin: 2px 0 14px; font-size: 12px; color: var(--text-faint); font-weight: 400; }

/* 过滤器 */
.rec-filter { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.kind-tabs { display: flex; gap: 4px; background: var(--bg-panel); border-radius: 999px; padding: 3px; }
.kind-chip {
  background: transparent; border: none; color: var(--text-lo);
  border-radius: 999px; padding: 5px 14px; font-size: 12.5px; cursor: pointer;
  transition: all var(--transition);
}
.kind-chip:hover { color: var(--text-hi); }
.kind-chip.active { background: var(--bg-raised); color: var(--accent); }

/* 时间线行 */
.rec-list { display: flex; flex-direction: column; gap: 6px; }
.rec-row {
  display: flex; align-items: center; gap: 10px;
  background: var(--bg-panel); border: 1px solid rgba(255,255,255,0.05);
  border-radius: var(--radius-sm); padding: 10px 14px; cursor: pointer;
  transition: border-color var(--transition);
}
.rec-row:hover { border-color: var(--accent-dim); }
.rec-row.open { border-color: var(--accent-dim); border-radius: var(--radius-sm) var(--radius-sm) 0 0; }
.r-kind {
  flex-shrink: 0; font-size: 11px; padding: 2px 8px; border-radius: 999px;
  background: rgba(158,183,229,0.12); color: var(--accent);
}
.r-kind.k-mtr { background: rgba(255,158,199,0.12); color: var(--pink); }
.r-kind.k-command { background: rgba(158,229,178,0.10); color: #9ee5b2; }
.r-node { flex-shrink: 0; font-size: 11.5px; color: var(--text-faint); min-width: 0; }
.r-summary { flex: 1; min-width: 0; font-size: 13px; color: var(--text-hi); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: var(--font-mono, monospace); }
.r-result { flex-shrink: 0; font-size: 12px; color: var(--accent); font-weight: 475; }
.r-time { flex-shrink: 0; font-size: 11.5px; color: var(--text-faint); }
.r-st { flex-shrink: 0; font-size: 11.5px; }
.r-st.st-pending { color: var(--text-faint); }
.r-st.st-running { color: var(--pink); }
.r-st.st-done { color: var(--text-lo); }
.r-st.st-failed { color: #e58a8a; }
.r-st.st-cancelled { color: var(--text-faint); }
.r-expand { flex-shrink: 0; color: var(--text-faint); transition: transform var(--transition); }
.r-expand.rot { transform: rotate(90deg); }

/* 展开详情 */
.rec-detail {
  background: var(--bg-panel); border: 1px solid var(--accent-dim); border-top: none;
  border-radius: 0 0 var(--radius-sm) var(--radius-sm);
  padding: 12px 14px; margin-top: -6px;
}
.metric-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 8px; }
.metric-cell { background: var(--bg-raised); border-radius: var(--radius-sm); padding: 8px 12px; }
.mc-label { font-size: 11px; color: var(--text-faint); }
.mc-value { font-size: 14px; color: var(--text-hi); font-weight: 475; margin-top: 2px; }
.mtr-table { display: flex; flex-direction: column; gap: 2px; font-size: 12.5px; }
.mtr-row { display: grid; grid-template-columns: 40px 1fr 70px 56px 90px; gap: 8px; padding: 4px 6px; border-radius: 4px; }
@media (max-width: 768px) {
  .mtr-table { overflow-x: auto; }
  .mtr-table .mtr-row { min-width: 380px; }
}
.mtr-hd { color: var(--text-faint); font-size: 11px; }
.mtr-hop { color: var(--text-faint); }
.mtr-host { color: var(--text-hi); font-family: var(--font-mono, monospace); }
.mtr-loss { color: var(--text-lo); }
.mtr-loss.bad { color: #e58a8a; }
.mtr-avg { color: var(--text-lo); }
.r-out {
  margin: 0 0 8px; padding: 10px 12px; background: var(--bg-raised);
  border-radius: var(--radius-sm); font-size: 12px; color: var(--text-lo);
  white-space: pre-wrap; word-break: break-all; max-height: 320px; overflow: auto;
}
.r-out.err { color: #e58a8a; }
.r-err { color: #e58a8a; font-size: 12.5px; }
.r-hint { color: var(--text-faint); font-size: 12px; }
.rec-empty { padding: 40px 0; text-align: center; color: var(--text-faint); font-size: 13px; }
</style>
