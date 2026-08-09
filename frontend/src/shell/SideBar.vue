<script setup lang="ts">
// 侧边栏：Stella 的门面。三段式——名片区 / 导航区 / 扩展区
import Icon from "./Icon.vue";

const navItems = [
  { to: "/", icon: "home", label: "个人主页" },
  { to: "/notes", icon: "note", label: "笔记" },
  { to: "/gallery", icon: "image", label: "图库" },
  { to: "/status", icon: "activity", label: "服务器状态" },
];
</script>

<template>
  <aside class="sidebar">
    <!-- 一段：个人名片 -->
    <div class="profile">
      <div class="avatar">云</div>
      <div class="who">
        <div class="name">云曦</div>
        <div class="motto">「把星光收进面板里」</div>
      </div>
    </div>

    <div class="divider" />

    <!-- 二段：导航 -->
    <nav class="nav">
      <RouterLink
        v-for="item in navItems"
        :key="item.to"
        :to="item.to"
        class="nav-item"
        :class="{ active: $route.path === item.to }"
      >
        <span class="icon"><Icon :name="item.icon" :size="16" /></span>
        <span class="label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div class="spacer" />

    <!-- 三段：扩展小模块位 -->
    <div class="extra">
      <div class="extra-hint">更多模块 · 装饰阶段</div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: var(--sidebar-w);
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 20px 14px;
  background: color-mix(in srgb, var(--bg-panel) 82%, transparent);
  backdrop-filter: var(--blur);
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  transition: width var(--transition);
}

/* ── 名片区 ── */
.profile {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 8px;
}
.avatar {
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 19px;
  color: var(--bg-base);
  background: linear-gradient(135deg, var(--accent), var(--pink));
  box-shadow: 0 0 16px rgba(201, 212, 232, 0.25);
}
.name {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 1px;
}
.motto {
  font-size: 11px;
  color: var(--text-lo);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 130px;
}

.divider {
  height: 1px;
  margin: 16px 8px;
  background: linear-gradient(90deg, transparent, var(--accent-dim), transparent);
  opacity: 0.35;
}

/* ── 导航区 ── */
.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  color: var(--text-lo);
  transition: all var(--transition);
}
.nav-item:hover {
  background: var(--bg-raised);
  color: var(--text-hi);
  transform: translateX(2px);
}
.nav-item.active {
  background: var(--bg-raised);
  color: var(--accent);
  box-shadow: inset 2px 0 0 var(--accent);
}
.icon { width: 22px; text-align: center; display: inline-flex; align-items: center; justify-content: center; }
.label { font-size: 13.5px; letter-spacing: 0.5px; }

.spacer { flex: 1; }

/* ── 扩展区 ── */
.extra {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  border: 1px dashed var(--text-faint);
  text-align: center;
}
.extra-hint {
  font-size: 11px;
  color: var(--text-faint);
  letter-spacing: 1px;
}

/* ── 窄屏折叠成图标栏 ── */
@media (max-width: 768px) {
  .sidebar { width: var(--sidebar-w-fold); padding: 16px 8px; }
  .who, .label, .extra-hint { display: none; }
  .profile { justify-content: center; padding: 0; }
  .extra { border: none; }
}
</style>
