<script setup lang="ts">
// 服务器模块左侧列表栏：总览 / 服务器 / 工具（二级），可折叠，与笔记样式统一。
// ServersPage 和节点详情页共用，点击项通过路由切换视图。
import { ref, computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import Icon from "../../shell/Icon.vue";
import Dropdown from "../../shell/Dropdown.vue";
import {notifyClientPreferenceChange} from '../settings/clientPreferenceEvents';

const route = useRoute();
const router = useRouter();

const collapsed = ref(localStorage.getItem("stella_servers_fold") === "1");
function toggleCollapsed() {
  collapsed.value = !collapsed.value;
  notifyClientPreferenceChange('stella_servers_fold',collapsed.value ? '1' : '0');
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
  notifyClientPreferenceChange('stella_tools_open','1');
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
  notifyClientPreferenceChange('stella_tools_open','0');
  localStorage.setItem("stella_tools_open", "0");
}
// Mobile uses the same existing routes, including the speedtest mode inside iperf.
const mobileOptions = [
 {value:'overview',label:'总览'},{value:'nodes',label:'服务器'},{value:'files',label:'文件管理'},{value:'docker',label:'Docker'},{value:'alerts',label:'告警'},
 {value:'iperf',label:'打流 / 测速',desc:'工具'},{value:'mtr',label:'MTR',desc:'工具'},{value:'command',label:'命令',desc:'工具'},{value:'records',label:'记录',desc:'工具'},
];
const mobileValue=computed(()=>inDetail.value?'':view.value==='tools'?tool.value:view.value);
function mobileNavigate(value:string|number|boolean){const key=String(value);if(['iperf','mtr','command','records'].includes(key))goTool(key);else goView(key);}
</script>

<template>
  <div class="servers-mobile-nav st-secondary-mobile"><span>服务器</span><Dropdown :model-value="mobileValue" :options="mobileOptions" @update:model-value="mobileNavigate" /></div>
  <div v-if="collapsed" class="servers-expand"><button type="button" class="fold-btn" aria-label="展开列表" title="展开列表" :aria-expanded="false" @click="toggleCollapsed"><Icon name="chevron" :size="16" /></button></div>
  <aside v-show="!collapsed" class="servers-bar st-secondary-nav" aria-label="服务器导航">
    <div class="st-secondary-heading"><h2>服务器</h2><button type="button" class="fold-btn" aria-label="收起列表" title="收起列表" :aria-expanded="true" @click="toggleCollapsed">«</button></div>

    <button type="button" class="bar-item st-secondary-item" :class="{ active: !inDetail && view === 'overview' }" @click="goView('overview')">
      <Icon name="activity" :size="15" /><span class="bi-label">总览</span>
    </button>

    <button type="button" class="bar-item st-secondary-item" :class="{ active: !inDetail && view === 'nodes' }" @click="goView('nodes')">
      <Icon name="server" :size="15" /><span class="bi-label">服务器</span>
    </button>

    <button type="button" class="bar-item st-secondary-item" :class="{ active: !inDetail && view === 'files' }" @click="goView('files')">
      <Icon name="folder" :size="15" /><span class="bi-label">文件管理</span>
    </button>

    <button type="button" class="bar-item st-secondary-item" :class="{ active: !inDetail && view === 'docker' }" @click="goView('docker')">
      <Icon name="box" :size="15" /><span class="bi-label">Docker</span>
    </button>

    <button type="button" class="bar-item st-secondary-item" :class="{ active: !inDetail && view === 'alerts' }" @click="goView('alerts')">
      <Icon name="bell" :size="15" /><span class="bi-label">告警</span>
    </button>

    <button type="button" class="bar-item st-secondary-item" :class="{ 'active-parent': !inDetail && view === 'tools' }" :aria-expanded="toolsOpen" @click="toggleTools">
      <Icon name="zap" :size="15" /><span class="bi-label">工具</span>
      <Icon :name="toolsOpen ? 'chevron-down' : 'chevron'" :size="12" class="vi-arrow" />
    </button>
    <div v-if="toolsOpen" class="st-secondary-subnav">
      <button type="button" class="bar-item sub st-secondary-item is-sub" :class="{ active: view === 'tools' && tool === 'iperf' }" @click="goTool('iperf')">
        <span class="bi-label">打流</span>
      </button>
      <button type="button" class="bar-item sub st-secondary-item is-sub" :class="{ active: view === 'tools' && tool === 'mtr' }" @click="goTool('mtr')">
        <span class="bi-label">MTR</span>
      </button>
      <button type="button" class="bar-item sub st-secondary-item is-sub" :class="{ active: view === 'tools' && tool === 'command' }" @click="goTool('command')">
        <span class="bi-label">命令</span>
      </button>
      <button type="button" class="bar-item sub st-secondary-item is-sub" :class="{ active: view === 'tools' && tool === 'records' }" @click="goTool('records')">
        <span class="bi-label">记录</span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.servers-bar { padding-top:32px; }
.servers-expand { flex:none; align-self:flex-start; }
.fold-btn { display:inline-flex; align-items:center; justify-content:center; flex:none; width:32px; height:32px; padding:0; border:1px solid transparent; border-radius:6px; background:transparent; color:var(--text-lo); font-size:16px; cursor:pointer; }
.fold-btn:hover { background:var(--control-hover,var(--bg-raised)); color:var(--accent); }
.fold-btn:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.bi-label { flex:1; }.vi-arrow { flex:none; }
@media(max-width:768px){.servers-bar,.servers-expand{display:none!important}.servers-mobile-nav{margin-bottom:0}}
</style>
