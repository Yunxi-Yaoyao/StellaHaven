<script setup lang="ts">
import SideBar from "./shell/SideBar.vue";
import { toasts } from "./composables/useToast";
</script>

<template>
  <div class="shell">
    <SideBar />
    <main class="content">
      <RouterView v-slot="{ Component }">
        <Transition name="fade" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>

    <!-- 全局轻提示（右下角） -->
    <div class="toast-stack">
      <TransitionGroup name="toast">
        <div v-for="t in toasts" :key="t.id" class="toast">{{ t.text }}</div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100%;
}
.content {
  flex: 1;
  overflow-y: auto;
  padding: 28px 32px;
}

/* 页面切换过渡 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--transition), transform var(--transition);
}
.fade-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 768px) {
  .content { padding: 18px 16px; }
}

/* ── 全局 toast ── */
.toast-stack {
  position: fixed;
  right: 20px;
  bottom: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 999;
}
.toast {
  padding: 10px 18px;
  border-radius: var(--radius-sm);
  background: var(--bg-raised);
  border: 1px solid var(--accent-dim);
  color: var(--text-hi);
  font-size: 12.5px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}
.toast-enter-active,
.toast-leave-active {
  transition: all var(--transition);
}
.toast-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(12px);
}
</style>
