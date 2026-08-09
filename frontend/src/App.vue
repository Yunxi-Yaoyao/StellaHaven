<script setup lang="ts">
import SideBar from "./shell/SideBar.vue";
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
</style>
