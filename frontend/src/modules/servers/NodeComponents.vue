<script setup lang="ts">
// 节点组件状态列表：绿=已装，红=未装（在线可代装），灰=离线，无点=未知
// 打流测速页只传 ['iperf3','speedtest']，服务器页传全部五个。
import { ref } from "vue";
import { installComponent, listNodes, type Node } from "../../api/servers";
import { toast } from "../../composables/useToast";

export type CompKey = "iperf3" | "speedtest" | "ufw" | "docker" | "mtr";
const COMP_LABEL: Record<CompKey, string> = { iperf3: "iperf3", speedtest: "speedtest", ufw: "ufw", docker: "docker", mtr: "mtr" };

const props = defineProps<{ nodes: Node[]; comps: CompKey[] }>();
const emit = defineEmits<{ refresh: [] }>();

const installing = ref<Record<string, boolean>>({}); // "nodeId:component" -> 代装中

function compState(n: Node, key: CompKey): boolean | null {
  const c = n.components as any;
  if (!c) return null; // 未知（agent 未上报）
  if (key === "ufw") return c.firewall?.ufw?.installed ?? null;
  if (key === "docker") return c.docker?.installed ?? null;
  return typeof c[key] === "boolean" ? c[key] : null;
}

async function doInstall(n: Node, component: CompKey) {
  const k = `${n.id}:${component}`;
  if (installing.value[k]) return;
  installing.value[k] = true;
  try {
    await installComponent(n.id, component);
    toast(`已下发 ${component} 安装，agent 代装中喵~`);
    // 等 agent 代装 + 心跳上报新状态（最多轮询 ~30s）
    let tries = 0;
    const poll = setInterval(async () => {
      tries++;
      try {
        const list = await listNodes();
        const nn = list.find((x) => x.id === n.id);
        const done = component === "ufw"
          ? (nn?.components as any)?.firewall?.ufw?.installed === true
          : component === "docker"
            ? (nn?.components as any)?.docker?.installed === true
            : (nn?.components as any)?.[component] === true;
        if (done) {
          clearInterval(poll);
          installing.value[k] = false;
          toast(`${component} 已装好喵~`);
          emit("refresh");
        } else if (tries >= 30) {
          clearInterval(poll);
          installing.value[k] = false;
          toast(`${component} 安装可能失败，看看节点日志喵~`);
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
    <div class="nc-head">服务器组件（绿=已装，红=未装，悬浮红点可代装）</div>
    <div v-for="n in props.nodes" :key="n.id" class="nc-row">
      <span class="nc-name">
        <span class="nc-dot" :style="{ background: n.status === 'online' ? 'var(--pink)' : 'var(--text-faint)' }" />
        {{ n.name }}
        <span v-if="n.status !== 'online'" class="nc-off">离线</span>
      </span>
      <span
        v-for="comp in props.comps"
        :key="comp"
        class="comp"
        :class="{
          ok: compState(n, comp) === true,
          bad: compState(n, comp) === false && n.status === 'online',
          off: compState(n, comp) === false && n.status !== 'online',
          unknown: compState(n, comp) === null,
        }"
      >
        <span class="c-dot" />
        <span class="c-label">{{ COMP_LABEL[comp] }}</span>
        <button
          v-if="compState(n, comp) === false && n.status === 'online'"
          class="c-install"
          :disabled="installing[`${n.id}:${comp}`]"
          @click="doInstall(n, comp)"
        >{{ installing[`${n.id}:${comp}`] ? '安装中…' : '安装' }}</button>
      </span>
    </div>
    <div v-if="!props.nodes.length" class="hint-empty">还没有纳管服务器</div>
  </div>
</template>

<style scoped>
.node-comp-list { padding: 12px 16px; }
.nc-head { font-size: 12px; color: var(--text-faint); margin-bottom: 4px; }
.nc-row { display: flex; align-items: center; gap: 12px; padding: 5px 0; flex-wrap: wrap; }
.nc-name { display: flex; align-items: center; gap: 7px; width: 180px; color: var(--text-hi); font-size: 13px; }
.nc-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.nc-off { font-size: 10px; color: var(--text-faint); }
.comp {
  display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px;
  border-radius: 999px; font-size: 12px; border: 1px solid rgba(255,255,255,0.08);
  background: var(--bg-panel); color: var(--text-lo); position: relative; cursor: default;
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
.c-install {
  opacity: 0; transition: opacity 0.15s;
  background: #ff5d6c; color: #fff; border: none; border-radius: 5px;
  font-size: 11px; padding: 2px 8px; cursor: pointer; margin-left: 2px;
}
.comp.bad:hover .c-install { opacity: 1; }
.c-install:disabled { opacity: 0.6; cursor: default; }
.c-label { font-size: 11.5px; }
.hint-empty { font-size: 12px; color: var(--text-faint); padding: 4px 0; }
</style>
