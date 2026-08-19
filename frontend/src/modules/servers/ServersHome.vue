<script setup lang="ts">
// 服务器模块列表视图：总览 / 服务器 / 工具（二级），由路由 query 驱动（/status?view=...&tool=...）。
// 节点详情是独立子路由 /status/:id，不在此组件内。
import { computed } from "vue";
import { useRoute } from "vue-router";
import OverviewView from "./OverviewView.vue";
import ToolsView from "./ToolsView.vue";
import NodesView from "./NodesView.vue";
import RecordsView from "./RecordsView.vue";
import DockerView from "./DockerView.vue";

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
  <RecordsView v-else-if="tool === 'records'" :preset-node="presetNode" />
  <ToolsView v-else :tool="tool" :preset-node="presetNode" />
</template>
