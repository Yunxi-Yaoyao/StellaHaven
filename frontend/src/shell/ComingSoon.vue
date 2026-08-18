<script setup lang="ts">
// 建设中占位页：图库/网盘等未上线模块共用一套，避免差异化石山代码
import Icon from "./Icon.vue";
defineProps<{ icon: string; title: string; hint: string }>();
</script>

<template>
  <div class="page">
    <div class="icon"><Icon :name="icon" :size="40" /></div>
    <h1>{{ title }}</h1>
    <p class="hint">{{ hint }}</p>
    <div class="badge">建设中</div>
  </div>
</template>

<style scoped>
.page {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.icon { color: var(--text-lo); opacity: 0.85; }
h1 { font-size: 22px; font-weight: 600; letter-spacing: 2px; }
.hint { color: var(--text-lo); font-size: 13px; }
.badge {
  margin-top: 8px;
  padding: 4px 14px;
  border-radius: 999px;
  font-size: 11px;
  letter-spacing: 2px;
  color: var(--pink);
  border: 1px solid var(--pink);
  opacity: 0.7;
}
</style>
