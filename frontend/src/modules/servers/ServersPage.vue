<script setup lang="ts">
// 服务器模块布局：左侧列表栏（只渲染一次）+ 右侧子路由视图。
// 列表三视图在 /status（ServersHome），节点详情在 /status/:id（NodeDetailView）。
import ServersSideBar from "./ServersSideBar.vue";
import {computed} from 'vue';
import {useRoute} from 'vue-router';
const route=useRoute();
const filesScroll=computed(()=>route.name==='status'&&route.query.view==='files');
</script>

<template>
  <div class="servers-page">
    <ServersSideBar />
    <div class="view-body" :class="{'files-scroll':filesScroll}">
      <router-view />
    </div>
  </div>
</template>

<style scoped>
.servers-page {
  height: 100%;
  min-height: 0;
  display: flex;
  gap: var(--secondary-nav-gap);
  overflow: hidden;
}
.view-body {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  padding-block:28px;
  display: flex;
}
.view-body > * { flex: 1; min-width: 0; min-height: 0; }
/* Only the file view needs this shared scrollport. Other server pages retain
   their existing nested scroll containers and chart/layout sizing contracts. */
.view-body.files-scroll { display: block; overflow-y: auto; overflow-x: hidden; overscroll-behavior-y: contain; }
.view-body.files-scroll > * { box-sizing: border-box; min-height: 100%; }

/* 移动端：二级侧栏改顶部横排 tab（ServersSideBar 配合），内容吃满宽度 */
@media (max-width: 768px) {
  .servers-page { flex-direction: column; }
  .view-body { min-height: 0; padding-block:0; }
}
</style>
