<script setup lang="ts">
// 侧边栏：Stella 的门面。三段式——名片区 / 导航区 / 扩展区
// collapsed=true → 收成图标栏；移动端由 App 控制 mobile-open 覆盖层
import Icon from "./Icon.vue";
import NotificationBell from "./NotificationBell.vue";
import { auth, fetchMe, loggedIn, currentAvatar } from "../modules/home/auth";
import { computed, ref } from "vue";
import { navigation, loadNavigation, navigationRows, builtinNavigation, isNavigationActive } from "../stores/navigation";

// 未登录显示站点名 StellaHaven；登录后昵称优先、回退用户名
const displayName = computed(() =>
  loggedIn.value ? (auth.me?.display_name || auth.me?.username || "云曦") : "StellaHaven"
);

defineProps<{ collapsed: boolean; mobileOpen: boolean }>();
const emit = defineEmits<{ toggle: []; closeMobile: [] }>();

function preloadNotes(to: string) {
  if (to === '/notes' && loggedIn.value) void import('../modules/notes/NotesPage.vue');
}
const navigationReady = computed(() => auth.checked && !auth.sessionClosing && (loggedIn.value ? navigation.loaded : !auth.error));
const navigationError = computed(() => !auth.sessionClosing ? (auth.error || (loggedIn.value ? navigation.error : '')) : '');
const navItems = computed(() => navigationReady.value ? (loggedIn.value ? navigationRows.value : builtinNavigation).filter(row => row.visible) : []);
const retrying = ref(false);
async function retryNavigation() { retrying.value=true;try { if(auth.error || !auth.checked)await fetchMe(); if(auth.me&&!auth.error)await loadNavigation(); } finally { retrying.value=false; } }
</script>

<template>
  <aside class="sidebar" :class="{ collapsed, 'mobile-open': mobileOpen }">
    <!-- 一段：个人名片（未登录=?头像+StellaHaven；登录=头像+昵称） -->
    <div class="profile">
      <div class="avatar">
        <img v-if="loggedIn" :src="currentAvatar" alt="头像" />
        <span v-else class="avatar-ghost">?</span>
      </div>
      <div class="who">
        <div class="name">{{ displayName }}</div>
        <div class="motto">「把星光收进面板里」</div>
      </div>
    </div>

    <div class="divider" />

    <!-- 二段：导航 -->
    <nav class="nav">
      <div v-if="navigationError" class="nav-message" role="alert">{{navigationError}} <button :disabled="retrying" @click="retryNavigation">重试</button></div>
      <div v-else-if="!navigationReady" class="nav-placeholder" role="status" aria-label="正在加载导航">正在加载导航…<span v-for="n in 4" :key="n" aria-hidden="true" /></div>
      <RouterLink
        v-for="item in navItems"
        :key="item.id"
        :title="item.label"
        :to="item.to"
        class="nav-item"
        :class="{ active: isNavigationActive($route.path, item.to) }"
        @mouseenter="preloadNotes(item.to)" @focus="preloadNotes(item.to)"
        @click="emit('closeMobile')"
      >
        <span class="icon"><Icon :name="item.icon" :size="17" /></span>
        <span class="label">{{ item.label }}</span>
      </RouterLink>
    </nav>



    <!-- 底行：账号位 + 折叠钮同一行 -->
    <div class="bottom-row">
      <RouterLink :to="loggedIn ? '/settings' : '/login'" class="account" @click="emit('closeMobile')">
        <span class="acc-avatar">
          <img v-if="loggedIn" :src="currentAvatar" alt="头像" />
          <span v-else class="acc-ghost">?</span>
        </span>
        <span class="acc-name">{{ loggedIn ? "已登录喵~" : "未登录哟~" }}</span>
      </RouterLink>
      <NotificationBell v-if="loggedIn" />
      <button class="fold-btn" :title="collapsed ? '展开侧栏' : '收起侧栏'" @click="emit('toggle')">
        {{ collapsed ? "»" : "«" }}
      </button>
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
  overflow: hidden;
  display: grid;
  place-items: center;
  font-size: 19px;
  color: var(--bg-base);
  background: linear-gradient(135deg, var(--accent), var(--pink));
  box-shadow: 0 0 16px rgba(201, 212, 232, 0.25);
}
.avatar img { width: 100%; height: 100%; object-fit: cover; display: block; }
.avatar-ghost {
  font-size: 19px;
  color: var(--bg-base);
  font-weight: 600;
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
  flex: 1; min-height: 0; overflow-y: auto;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  color: var(--text-lo);
  transition: all var(--transition);
  /* button reset：网盘占位项是 <button>，补齐对齐/字体/边框，和 <a> 导航项视觉一致 */
  width: 100%;
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: inherit;
  line-height: inherit;
  text-align: left;
  cursor: pointer;
}
.nav-message,.nav-placeholder{padding:10px 12px;font-size:12px;color:var(--text-lo)}
.nav-placeholder span{display:block;height:32px;margin:10px 0;border-radius:6px;background:var(--bg-raised);opacity:.5}
.nav-message button{font:inherit;cursor:pointer;color:var(--text-hi);background:var(--bg-raised);border:1px solid var(--accent-dim);border-radius:5px;padding:4px 8px}
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
.label { font-size: 14.5px; letter-spacing: 0.5px; }
.settings-entry {
  border: none;
  background: transparent;
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  width: 100%;
}

/* 账号位（底行） */
.bottom-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px; flex-shrink: 0;
}
.bottom-row .fold-btn { margin-top: 0; flex-shrink: 0; }
.account {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  text-decoration: none;
  transition: all var(--transition);
}
.account:hover { background: var(--bg-raised); }
.acc-avatar {
  width: 30px; height: 30px;
  border-radius: 50%;
  overflow: hidden;
  flex-shrink: 0;
  display: grid; place-items: center;
  background: var(--bg-raised);
  border: 1px solid var(--accent-dim);
}
.acc-avatar img { width: 100%; height: 100%; object-fit: cover; display: block; }
.acc-ghost { color: var(--text-faint); font-size: 14px; }
.acc-name {
  font-size: 13.5px;
  color: var(--text-lo);
  letter-spacing: 0.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.account:hover .acc-name { color: var(--text-hi); }
.sidebar.collapsed .acc-name { display: none; }
.sidebar.collapsed .account { justify-content: center; padding: 8px 0; }

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

/* ── 折叠态（桌面手动收） ── */
.sidebar.collapsed { width: var(--sidebar-w-fold); padding: 16px 8px; }
.sidebar.collapsed .who,
.sidebar.collapsed .label,
.sidebar.collapsed .extra-hint { display: none; }
.sidebar.collapsed .profile { justify-content: center; padding: 0; }
.sidebar.collapsed .extra { border: none; }
.sidebar.collapsed .divider { margin: 12px 4px; }

.fold-btn {
  margin-top: 10px;
  padding: 5px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  font-size: 13px;
  transition: all var(--transition);
}
.fold-btn:hover { background: var(--bg-raised); color: var(--accent); }

/* ── 移动端：侧边栏变覆盖抽屉 ── */
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 90;
    width: var(--sidebar-w);
    transform: translateX(-105%);
    transition: transform var(--transition);
    box-shadow: 8px 0 24px rgba(0, 0, 0, 0.5);
  }
  .sidebar.mobile-open { transform: translateX(0); }
  /* 移动端折叠态不生效，展开始终全宽 */
  .sidebar.collapsed { width: var(--sidebar-w); }
  .sidebar.collapsed .who,
  .sidebar.collapsed .label,
  .sidebar.collapsed .extra-hint { display: block; }
  .fold-btn { display: none; } /* 移动端用遮罩关闭 */
}
</style>
