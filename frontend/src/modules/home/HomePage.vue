<script setup lang="ts">
</script>

<template>
  <div class="page">
    <div class="icon">🏠</div>
    <h1>个人主页</h1>
    <p class="hint">云曦的小宇宙正在施工</p>
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
.icon { font-size: 42px; opacity: 0.85; }
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
