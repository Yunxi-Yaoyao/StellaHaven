<script setup lang="ts">
// 服务器模块左侧列表栏：总览 / 服务器 / 工具（二级），可折叠，与笔记样式统一。
// ServersPage 和节点详情页共用，点击项通过路由切换视图。
import { ref, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import Icon from "../../shell/Icon.vue";

const route = useRoute();
const router = useRouter();

const collapsed = ref(localStorage.getItem("stella_servers_fold") === "1");
function toggleCollapsed() {
  collapsed.value = !collapsed.value;
  localStorage.setItem("stella_servers_fold", collapsed.value ? "1" : "0");
}

// 工具二级展开（记忆）
const toolsOpen = ref(localStorage.getItem("stella_tools_open") === "1");
function toggleTools() {
  toolsOpen.value = !toolsOpen.value;
  localStorage.setItem("stella_tools_open", toolsOpen.value ? "1" : "0");
}

const view = computed(() => (route.query.view as string) || "nodes");
const tool = computed(() => (route.query.tool as string) || "iperf");

const emit = defineEmits<{ navigate: [] }>();
function goView(v: string) {
  emit("navigate");
  router.push({ path: "/status", query: { view: v } });
}
function goTool(t: string) {
  emit("navigate");
  router.push({ path: "/status", query: { view: "tools", tool: t } });
}
</script>

<template>
  <!-- 收起窄条把手 -->
  <div v-if="collapsed" class="list-strip" title="展开列表" @click="toggleCollapsed">»</div>

  <!-- 列表栏 -->
  <aside v-show="!collapsed" class="servers-bar">
    <button class="fold-btn" title="收起列表" @click="toggleCollapsed">«</button>
    <div class="bar-head">服务器</div>

    <button class="bar-item" :class="{ active: view === 'overview' }" @click="goView('overview')">
      <Icon name="activity" :size="15" /><span class="bi-label">总览</span>
    </button>

    <button class="bar-item" :class="{ active: view === 'nodes' }" @click="goView('nodes')">
      <Icon name="server" :size="15" /><span class="bi-label">服务器</span>
    </button>

    <button class="bar-item" @click="toggleTools">
      <Icon name="zap" :size="15" /><span class="bi-label">工具</span>
      <Icon :name="toolsOpen ? 'chevron-down' : 'chevron'" :size="12" class="vi-arrow" />
    </button>
    <template v-if="toolsOpen">
      <button class="bar-item sub" :class="{ active: view === 'tools' && tool === 'iperf' }" @click="goTool('iperf')">
        <span class="bi-label">打流</span>
      </button>
      <button class="bar-item sub" :class="{ active: view === 'tools' && tool === 'mtr' }" @click="goTool('mtr')">
        <span class="bi-label">MTR</span>
      </button>
      <button class="bar-item sub" :class="{ active: view === 'tools' && tool === 'command' }" @click="goTool('command')">
        <span class="bi-label">命令</span>
      </button>
    </template>
  </aside>
</template>

<style scoped>
/* 收起窄条把手（与笔记 list-strip 一致） */
.list-strip {
  width: 26px;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  background: var(--bg-panel);
  border-radius: var(--radius) 0 0 var(--radius);
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  color: var(--text-faint);
  cursor: pointer;
  transition: all var(--transition);
}
.list-strip:hover { color: var(--accent); background: var(--bg-raised); }
.servers-bar {
  width: 132px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  padding: 16px 10px;
  gap: 4px;
  background: var(--bg-panel);
  border-right: 1px solid rgba(255, 255, 255, 0.05);
}
.fold-btn {
  align-self: flex-end;
  background: transparent; border: none;
  color: var(--text-faint); font-size: 14px; cursor: pointer;
  padding: 2px 8px 6px; transition: color var(--transition);
}
.fold-btn:hover { color: var(--accent); }
.bar-head {
  font-size: 13px; font-weight: 600; letter-spacing: 1px;
  padding: 2px 10px 10px; color: var(--text-hi);
}
.bar-item {
  display: flex; align-items: center; gap: 9px;
  padding: 9px 12px; border: none; border-radius: var(--radius-sm);
  background: transparent; color: var(--text-lo); font-size: 13.5px;
  cursor: pointer; text-align: left; transition: all var(--transition);
}
.bar-item:hover { background: var(--bg-raised); color: var(--text-hi); }
.bar-item.active { background: var(--bg-raised); color: var(--accent); }
.bi-label { flex: 1; }
.vi-arrow { opacity: 0.6; }
.bar-item.sub { padding-left: 30px; font-size: 12.5px; }
</style>
