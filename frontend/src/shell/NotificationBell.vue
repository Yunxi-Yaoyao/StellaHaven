<script setup lang="ts">
// 通知铃铛：挂在侧栏底行，未读角标 + 上弹出下拉面板。
// 数据源是全局 notifications store（WS 实时 + 30s 轮询兜底）。
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import Icon from "./Icon.vue";
import { notifications, notificationActions } from "../stores/notifications";

const open = ref(false);
const root = ref<HTMLElement | null>(null);
const router = useRouter();

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#e5605c",
  warning: "#d9a03f",
  info: "#5cb88a",
};

function relTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

async function toggle() {
  open.value = !open.value;
  if (open.value) await notificationActions.refreshList();
}

async function openItem(id: number, link: string | null) {
  await notificationActions.readOne(id);
  open.value = false;
  if (link) router.push(link);
}

function onDocClick(e: MouseEvent) {
  if (root.value && !root.value.contains(e.target as Node)) open.value = false;
}
onMounted(() => document.addEventListener("pointerdown", onDocClick));
onBeforeUnmount(() => document.removeEventListener("pointerdown", onDocClick));
</script>

<template>
  <div ref="root" class="bell-root">
    <button
      class="bell-btn"
      :class="{ active: open }"
      :title="notifications.unread ? `${notifications.unread} 条未读通知` : '通知'"
      @click="toggle"
    >
      <Icon :name="notifications.unread ? 'bell-ring' : 'bell'" :size="16" />
      <span v-if="notifications.unread" class="badge">
        {{ notifications.unread > 99 ? "99+" : notifications.unread }}
      </span>
    </button>

    <Transition name="pop">
      <div v-if="open" class="panel">
        <div class="panel-head">
          <span class="panel-title">通知</span>
          <button
            class="read-all"
            :disabled="!notifications.unread"
            @click="notificationActions.readAll()"
          >
            全部已读
          </button>
        </div>
        <div class="panel-body">
          <div v-if="!notifications.items.length" class="empty">还没有通知喵~</div>
          <button
            v-for="n in notifications.items"
            :key="n.id"
            class="item"
            :class="{ unread: !n.read }"
            @click="openItem(n.id, n.link)"
          >
            <span class="dot" :style="{ background: SEVERITY_COLORS[n.severity] || '#9aa3b5' }" />
            <span class="item-main">
              <span class="item-title">{{ n.title }}</span>
              <span class="item-body">{{ n.body }}</span>
              <span class="item-ts">{{ relTime(n.ts) }}</span>
            </span>
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.bell-root { position: relative; display: flex; }

.bell-btn {
  position: relative;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: var(--text-dim, #9aa3b5);
  cursor: pointer;
  transition: background var(--transition, 0.2s), color var(--transition, 0.2s);
}
.bell-btn:hover, .bell-btn.active {
  background: rgba(255, 255, 255, 0.06);
  color: var(--accent, #c9d4e8);
}

.badge {
  position: absolute;
  top: -3px;
  right: -5px;
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  border-radius: 8px;
  background: #e5605c;
  color: #fff;
  font-size: 10px;
  font-weight: 600;
  line-height: 15px;
  text-align: center;
  box-shadow: 0 0 0 2px var(--bg-base, #14171f);
}

.panel {
  position: absolute;
  bottom: 40px;
  left: 0;
  width: 320px;
  max-height: 420px;
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--bg-panel, #1a1e28) 96%, transparent);
  backdrop-filter: var(--blur, blur(12px));
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
  overflow: hidden;
  z-index: 60;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.panel-title { font-size: 13px; font-weight: 600; color: var(--accent, #c9d4e8); }
.read-all {
  border: none;
  background: none;
  color: var(--text-dim, #9aa3b5);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 6px;
}
.read-all:hover:not(:disabled) { color: var(--accent, #c9d4e8); background: rgba(255,255,255,0.05); }
.read-all:disabled { opacity: 0.4; cursor: default; }

.panel-body { overflow-y: auto; }
.empty { padding: 28px 0; text-align: center; font-size: 13px; color: var(--text-dim, #9aa3b5); }

.item {
  display: flex;
  gap: 10px;
  width: 100%;
  padding: 11px 14px;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s;
}
.item:hover { background: rgba(255, 255, 255, 0.04); }
.item.unread { background: rgba(201, 212, 232, 0.05); }
.item.unread:hover { background: rgba(201, 212, 232, 0.09); }

.dot {
  flex-shrink: 0;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-top: 6px;
}
.item-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.item-title { font-size: 13px; font-weight: 500; color: #e8ecf4; }
.item-body {
  font-size: 12px;
  color: var(--text-dim, #9aa3b5);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.item-ts { font-size: 11px; color: #5c6474; }

.pop-enter-active, .pop-leave-active { transition: opacity 0.16s, transform 0.16s; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(6px); }

@media (max-width: 720px) {
  .panel { position: fixed; left: 12px; right: 12px; bottom: 76px; width: auto; }
}
</style>
