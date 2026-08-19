<script setup lang="ts">
// 节点组件状态列表：绿=已装（带版本号），红=未装（在线可代装），灰=离线，无点=未知
// 打流测速页只传 ['iperf3','speedtest']，服务器页传全部五个。
// 0.6.2 起 agent 上报 {installed, version}；兼容旧布尔上报。
// 代装失败会拉最近一次失败任务的 error 展示（可收起）；触屏设备安装按钮常驻（无 hover）。
import { onMounted, ref } from "vue";
import { installComponent, listComponentInstalls, listNodes, type ComponentTask, type Node } from "../../api/servers";
import { toast } from "../../composables/useToast";

export type CompKey = "iperf3" | "speedtest" | "ufw" | "docker" | "mtr";
const COMP_LABEL: Record<CompKey, string> = { iperf3: "iperf3", speedtest: "speedtest", ufw: "ufw", docker: "docker", mtr: "mtr" };

const props = defineProps<{ nodes: Node[]; comps: CompKey[] }>();
const emit = defineEmits<{ refresh: [] }>();

const installing = ref<Record<string, boolean>>({}); // "nodeId:component" -> 代装中
// 最近一次失败的代装任务（"nodeId:component" -> task），用于失败原因展示
const lastFail = ref<Record<string, ComponentTask>>({});
const failOpen = ref<Record<string, boolean>>({}); // 失败详情展开

onMounted(async () => {
  try {
    const tasks = await listComponentInstalls();
    const map: Record<string, ComponentTask> = {};
    for (const t of tasks) {
      const k = `${t.node_id}:${t.component}`;
      if (t.status === "failed" && (!map[k] || t.id > map[k].id)) map[k] = t;
    }
    lastFail.value = map;
  } catch { /* 列表拉不到就不显示失败提示 */ }
});

/** 组件状态：兼容旧布尔上报和 0.6.2 的 {installed, version} */
function compInfo(n: Node, key: CompKey): { installed: boolean | null; version: string } {
  const c = n.components as any;
  if (!c) return { installed: null, version: "" };
  let v: any;
  if (key === "ufw") v = c.firewall?.ufw;
  else if (key === "docker") v = c.docker;
  else v = c[key];
  if (v == null) return { installed: null, version: "" };
  if (typeof v === "boolean") return { installed: v, version: "" }; // 旧 agent
  return { installed: v.installed ?? null, version: v.version || "" };
}

async function doInstall(n: Node, component: CompKey) {
  const k = `${n.id}:${component}`;
  if (installing.value[k]) return;
  installing.value[k] = true;
  try {
    await installComponent(n.id, component);
    toast(`已下发 ${component} 安装，agent 代装中喵~`);
    // 等 agent 代装 + 心跳上报新状态（最多轮询 ~60s，docker 拉包慢）
    let tries = 0;
    const poll = setInterval(async () => {
      tries++;
      try {
        const list = await listNodes();
        const nn = list.find((x) => x.id === n.id);
        const done = nn ? compInfo(nn, component).installed === true : false;
        if (done) {
          clearInterval(poll);
          installing.value[k] = false;
          delete lastFail.value[k];
          toast(`${component} 已装好喵~`);
          emit("refresh");
        } else if (tries >= 30) {
          clearInterval(poll);
          installing.value[k] = false;
          // 拉最新失败任务的真实错误展示出来
          try {
            const tasks = await listComponentInstalls();
            const ft = tasks.filter((t) => t.node_id === n.id && t.component === component && t.status === "failed")
              .sort((a, b) => b.id - a.id)[0];
            if (ft) {
              lastFail.value = { ...lastFail.value, [k]: ft };
              failOpen.value = { ...failOpen.value, [k]: true };
            }
          } catch { /* ignore */ }
          toast(`${component} 安装可能失败，展开红点看原因喵~`);
          emit("refresh");
        }
      } catch { /* 继续 */ }
    }, 2000);
  } catch {
    installing.value[k] = false;
    toast("下发安装失败");
  }
}
</script>

<template>
  <div class="node-comp-list">
    <div class="nc-head">服务器组件（绿=已装，红=未装，在线可代装）</div>
    <div v-for="n in props.nodes" :key="n.id" class="nc-row">
      <span class="nc-name">
        <span class="nc-dot" :style="{ background: n.status === 'online' ? 'var(--pink)' : 'var(--text-faint)' }" />
        {{ n.name }}
        <span v-if="n.status !== 'online'" class="nc-off">离线</span>
      </span>
      <div class="nc-chips">
        <div v-for="comp in props.comps" :key="comp" class="comp-wrap">
          <span
            class="comp"
            :class="{
              ok: compInfo(n, comp).installed === true,
              bad: compInfo(n, comp).installed === false && n.status === 'online',
              off: compInfo(n, comp).installed === false && n.status !== 'online',
              unknown: compInfo(n, comp).installed === null,
            }"
          >
            <span class="c-dot" />
            <span class="c-label">{{ COMP_LABEL[comp] }}</span>
            <span v-if="compInfo(n, comp).version" class="c-ver">{{ compInfo(n, comp).version }}</span>
            <button
              v-if="compInfo(n, comp).installed === false && n.status === 'online'"
              class="c-install"
              :disabled="installing[`${n.id}:${comp}`]"
              @click="doInstall(n, comp)"
            >{{ installing[`${n.id}:${comp}`] ? '安装中…' : '安装' }}</button>
            <button
              v-if="lastFail[`${n.id}:${comp}`] && compInfo(n, comp).installed !== true"
              class="c-fail"
              :title="'上次安装失败，点击查看原因'"
              @click="failOpen[`${n.id}:${comp}`] = !failOpen[`${n.id}:${comp}`]"
            >!</button>
          </span>
          <div
            v-if="failOpen[`${n.id}:${comp}`] && lastFail[`${n.id}:${comp}`]"
            class="c-fail-log"
          >上次代装失败（#{{ lastFail[`${n.id}:${comp}`].id }}）：{{ lastFail[`${n.id}:${comp}`].error || "无错误详情" }}</div>
        </div>
      </div>
    </div>
    <div v-if="!props.nodes.length" class="hint-empty">还没有纳管服务器</div>
  </div>
</template>

<style scoped>
.node-comp-list { padding: 12px 16px; }
.nc-head { font-size: 12px; color: var(--text-faint); margin-bottom: 4px; }
.nc-row { display: flex; align-items: flex-start; gap: 12px; padding: 5px 0; }
.nc-name { display: flex; align-items: center; gap: 7px; width: 180px; flex-shrink: 0; color: var(--text-hi); font-size: 13px; padding-top: 5px; }
.nc-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.nc-off { font-size: 10px; color: var(--text-faint); }
.nc-chips { display: flex; flex-wrap: wrap; gap: 6px; flex: 1; min-width: 0; }
.comp-wrap { display: flex; flex-direction: column; gap: 2px; }
.comp {
  display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px;
  border-radius: 999px; font-size: 12px; border: 1px solid rgba(255,255,255,0.08);
  background: var(--bg-panel); color: var(--text-lo); position: relative;
}
.c-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.comp.ok .c-dot { background: #3ddc84; }
.comp.ok { color: #3ddc84; border-color: rgba(61,220,132,0.3); }
.comp.bad .c-dot { background: #ff5d6c; }
.comp.bad { color: #ff5d6c; border-color: rgba(255,93,108,0.3); }
.comp.off .c-dot { background: #ff5d6c; opacity: 0.5; }
.comp.off { color: var(--text-faint); border-color: rgba(255,255,255,0.08); opacity: 0.7; }
.comp.unknown .c-dot { background: var(--text-faint); }
.comp.unknown { color: var(--text-faint); }
.c-ver { font-size: 10.5px; opacity: 0.75; font-family: var(--font-mono, monospace); }
.c-install {
  background: #ff5d6c; color: #fff; border: none; border-radius: 5px;
  font-size: 11px; padding: 2px 8px; cursor: pointer; margin-left: 2px;
}
.c-install:disabled { opacity: 0.6; cursor: default; }
.c-fail {
  background: transparent; border: 1px solid #ff5d6c; color: #ff5d6c; border-radius: 50%;
  width: 16px; height: 16px; font-size: 10px; line-height: 1; cursor: pointer; padding: 0;
}
.c-fail-log {
  font-size: 11px; color: #ff8b97; background: rgba(255,93,108,0.08);
  border: 1px solid rgba(255,93,108,0.25); border-radius: 6px; padding: 5px 8px;
  max-width: 340px; word-break: break-all; white-space: pre-wrap;
}
.c-label { font-size: 11.5px; }
.hint-empty { font-size: 12px; color: var(--text-faint); padding: 4px 0; }

/* 桌面端：安装按钮悬浮才现（保持列表干净）；触屏没有 hover → 常驻显示（8.20 手机点不到实锤） */
@media (hover: hover) {
  .c-install { opacity: 0; transition: opacity 0.15s; }
  .comp.bad:hover .c-install { opacity: 1; }
}

/* 移动端：节点名单独占一行，组件 chips 整行折行排列，不再被名字挤窄 */
@media (max-width: 768px) {
  .nc-row { flex-direction: column; gap: 4px; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
  .nc-name { width: auto; padding-top: 0; }
  .nc-chips { width: 100%; }
  .c-fail-log { max-width: 100%; }
}
</style>
