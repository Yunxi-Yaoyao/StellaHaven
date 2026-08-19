<script setup lang="ts">
// 服务器模块左侧列表栏：总览 / 服务器 / 工具（二级），可折叠，与笔记样式统一。
// ServersPage 和节点详情页共用，点击项通过路由切换视图。
import { ref, computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import Icon from "../../shell/Icon.vue";

const route = useRoute();
const router = useRouter();

const collapsed = ref(localStorage.getItem("stella_servers_fold") === "1");
function toggleCollapsed() {
  collapsed.value = !collapsed.value;
  localStorage.setItem("stella_servers_fold", collapsed.value ? "1" : "0");
}

// 工具二级展开（记忆）；当前在工具视图时强制展开（否则子项高亮看不见）
const toolsOpen = ref(localStorage.getItem("stella_tools_open") === "1");

const view = computed(() => (route.query.view as string) || "nodes");
const tool = computed(() => (route.query.tool as string) || "iperf");
// 详情页（/status/:id）时列表视图不高亮
const inDetail = computed(() => route.name === "status-node");

// 进入工具视图自动展开子项（含刷新直达/详情页跳入），不收起记忆、只是展示
watch(() => route.query.view, (v) => { if (v === "tools") toolsOpen.value = true; }, { immediate: true });

function goView(v: string) {
  router.push({ path: "/status", query: { view: v } });
}
function goTool(t: string) {
  toolsOpen.value = true;
  localStorage.setItem("stella_tools_open", "1");
  router.push({ path: "/status", query: { view: "tools", tool: t } });
}
// 点「工具」：展开子项 + 跳到默认子项（打流）
function toggleTools() {
  if (!toolsOpen.value) {
    goTool("iperf");
    return;
  }
  toolsOpen.value = false;
  localStorage.setItem("stella_tools_open", "0");
}
</script>

<template>
  <!-- 收起窄条把手 -->
  <div v-if="collapsed" class="list-strip" title="展开列表" @click="toggleCollapsed">»</div>

  <!-- 列表栏 -->
  <aside v-show="!collapsed" class="servers-bar">
    <button class="fold-btn" title="收起列表" @click="toggleCollapsed">«</button>

    <button class="bar-item" :class="{ active: !inDetail && view === 'overview' }" @click="goView('overview')">
      <Icon name="activity" :size="15" /><span class="bi-label">总览</span>
    </button>

    <button class="bar-item" :class="{ active: !inDetail && view === 'nodes' }" @click="goView('nodes')">
      <Icon name="server" :size="15" /><span class="bi-label">服务器</span>
    </button>

    <button class="bar-item" :class="{ active: !inDetail && view === 'docker' }" @click="goView('docker')">
      <Icon name="box" :size="15" /><span class="bi-label">Docker</span>
    </button>

    <button class="bar-item" :class="{ 'active-parent': !inDetail && view === 'tools' }" @click="toggleTools">
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
      <button class="bar-item sub" :class="{ active: view === 'tools' && tool === 'records' }" @click="goTool('records')">
        <span class="bi-label">记录</span>
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
/* 父项高亮（比子项淡）：工具视图下「工具」也有位置感 */
.bar-item.active-parent { color: var(--accent); opacity: 0.85; }
.bi-label { flex: 1; }
.vi-arrow { opacity: 0.6; }
.bar-item.sub { padding-left: 30px; font-size: 12.5px; }

/* 移动端：横排 tab 条。桌面折叠记忆在移动端不生效——始终展开成 tab（v-show 内联 none 用 !important 盖掉） */
@media (max-width: 768px) {
  .list-strip { display: none; }
  .servers-bar {
    display: flex !important;
    width: auto;
    flex-direction: row;
    flex-wrap: wrap;
    align-items: center;
    padding: 8px 10px;
    gap: 6px;
    border-right: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  }
  .fold-btn { display: none; }
  .bar-item { padding: 6px 10px; font-size: 12.5px; }
  .bar-item.sub { padding-left: 10px; }
  .bi-label { flex: none; }
}
</style>
