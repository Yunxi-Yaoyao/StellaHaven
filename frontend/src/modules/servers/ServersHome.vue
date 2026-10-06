<script setup lang="ts">
// 服务器模块列表视图：总览 / 服务器 / 工具（二级），由路由 query 驱动（/status?view=...&tool=...）。
// 节点详情是独立子路由 /status/:id，不在此组件内。
import { computed, defineAsyncComponent } from "vue";
import { useRoute } from "vue-router";
const OverviewView = defineAsyncComponent(() => import("./OverviewView.vue"));
const ToolsView = defineAsyncComponent(() => import("./ToolsView.vue"));
const NodesView = defineAsyncComponent(() => import("./NodesView.vue"));
const RecordsView = defineAsyncComponent(() => import("./RecordsView.vue"));
const DockerView = defineAsyncComponent(() => import("./DockerView.vue"));
const AlertsView = defineAsyncComponent(() => import("./AlertsView.vue"));

const route = useRoute();
const view = computed(() => (route.query.view as string) || "nodes");
const tool = computed(() => (route.query.tool as "iperf" | "mtr" | "command" | "records") || "iperf");
// 从详情页「操作」下拉跳入时预填节点：/status?view=tools&tool=mtr&node=20
const presetNode = computed(() => {
  const n = Number(route.query.node);
  return Number.isFinite(n) && n > 0 ? n : null;
});
</script>

<template>
  <OverviewView v-if="view === 'overview'" />
  <NodesView v-else-if="view === 'nodes'" />
  <DockerView v-else-if="view === 'docker'" />
  <AlertsView v-else-if="view === 'alerts'" />
  <RecordsView v-else-if="tool === 'records'" :preset-node="presetNode" />
  <ToolsView v-else :tool="tool" :preset-node="presetNode" />
</template>
