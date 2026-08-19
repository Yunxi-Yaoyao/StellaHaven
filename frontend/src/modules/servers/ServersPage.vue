<script setup lang="ts">
// 服务器模块布局：左侧列表栏（只渲染一次）+ 右侧子路由视图。
// 列表三视图在 /status（ServersHome），节点详情在 /status/:id（NodeDetailView）。
import ServersSideBar from "./ServersSideBar.vue";
</script>

<template>
  <div class="servers-page">
    <ServersSideBar />
    <div class="view-body">
      <router-view />
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

/* 移动端：二级侧栏改顶部横排 tab（ServersSideBar 配合），内容吃满宽度 */
@media (max-width: 768px) {
  .servers-page { flex-direction: column; }
  .view-body { min-height: 0; }
}
</style>
