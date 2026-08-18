<script setup lang="ts">
// 服务器模块：总览 / 服务器 / 工具（二级），左侧列表栏由 ServersSideBar 负责，视图由路由 query 驱动。
// 节点详情作为内部视图（点卡片进入，URL 不变，刷新回列表）。
import { ref, computed } from "vue";
import { useRoute } from "vue-router";
import ServersSideBar from "./ServersSideBar.vue";
import OverviewView from "./OverviewView.vue";
import ToolsView from "./ToolsView.vue";
import NodesView from "./NodesView.vue";
import NodeDetailView from "./NodeDetailView.vue";

const route = useRoute();
const view = computed(() => (route.query.view as string) || "nodes");
const tool = computed(() => (route.query.tool as "iperf" | "mtr" | "command") || "iperf");

// 当前查看的节点（点卡片进入详情，URL 不变）
const currentNodeId = ref<number | null>(null);
function openNode(id: number) { currentNodeId.value = id; }
function closeNode() { currentNodeId.value = null; }
</script>

<template>
  <div class="servers-page">
    <!-- 左侧列表栏（总览/工具/服务器） -->
    <ServersSideBar @navigate="closeNode" />

    <!-- 右侧内容区 -->
    <div class="view-body">
      <!-- 详情视图（点卡片进入，URL 保持 /status，刷新回列表） -->
      <NodeDetailView v-if="currentNodeId !== null" :node-id="currentNodeId" @back="closeNode" />
      <!-- 列表视图 -->
      <template v-else>
        <OverviewView v-if="view === 'overview'" />
        <NodesView v-else-if="view === 'nodes'" @open="openNode" />
        <ToolsView v-else :tool="tool" />
      </template>
    </div>
  </div>
</template>

<style scoped>
.servers-page {
  height: 100%;
  display: flex;
  overflow: hidden;
}
.view-body {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  display: flex;
}
.view-body > * { flex: 1; min-width: 0; }
</style>
