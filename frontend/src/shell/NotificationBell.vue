<script setup lang="ts">
// 通知铃铛：导航顶部入口，浮层传送到 body，避免侧栏层叠与裁剪。
// 数据源是全局 notifications store（WS 实时 + 30s 轮询兜底）。
import { nextTick, onBeforeUnmount, onMounted, ref, watch, useId } from "vue";
import { useRouter } from "vue-router";
import Icon from "./Icon.vue";
import NotificationDetail from "./NotificationDetail.vue";
import { notifications, notificationActions } from "../stores/notifications";
import type { NotificationOrigin } from './notificationMotion';
const origin=ref<NotificationOrigin>();
async function detailClosed(){
  selected.value=undefined;
  await nextTick();
  if(open.value&&origin.value?.element.isConnected)origin.value.element.focus();
  else trigger.value?.focus();
  origin.value=undefined;
}

const props = withDefaults(defineProps<{active?:boolean}>(), {active:true});
const open = ref(false);
const selected=ref<number>();
watch(() => props.active, value => { if (!value) {close(false);selected.value=undefined;} });
const root = ref<HTMLElement | null>(null);
const router = useRouter();
const panel = ref<HTMLElement | null>(null);
const trigger = ref<HTMLButtonElement | null>(null);
const panelId = useId();
const position = ref({ left:'8px', top:'8px', maxHeight:'420px' });
function place() {
  if (!open.value || !trigger.value) return;
  const rect = trigger.value.getBoundingClientRect();
  // Hidden mobile navigation must not leave a floating notification window behind.
  if (rect.right <= 0 || rect.left >= innerWidth) { close(false); return; }
  const width = Math.min(360, innerWidth - 16);
  const left = Math.max(8, Math.min(rect.left, innerWidth - width - 8));
  const top = Math.min(rect.bottom + 8, Math.max(8, innerHeight - 160));
  position.value = { left:`${left}px`, top:`${top}px`, maxHeight:`${Math.max(80, innerHeight - top - 8)}px` };
}
function close(restore = true) {
  open.value = false;
  if (restore) trigger.value?.focus();
}
function onKey(event: KeyboardEvent) {
  if (!open.value || selected.value) return;
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
  if (event.key === 'Tab') {
    const buttons = [...(panel.value?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || [])];
    const first = buttons[0], last = buttons.at(-1);
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value)) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
}
watch(() => router.currentRoute.value.fullPath, () => {close(false);selected.value=undefined;});

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
  if (!props.active) return;
  if (open.value) { close(); return; }
  open.value = true; place();
  await nextTick(); panel.value?.focus();
  await notificationActions.refreshList();
}

function openItem(id: number, event: MouseEvent) {
  if(selected.value===id)return;
  const element=event.currentTarget as HTMLElement;
  origin.value=panel.value?{element,rect:element.getBoundingClientRect(),panel:panel.value}:undefined;
  selected.value=id;
}

function onDocClick(e: Event) {
  if (!selected.value && !root.value?.contains(e.target as Node) && !panel.value?.contains(e.target as Node)) close(false);
}
onMounted(() => {
  document.addEventListener('pointerdown', onDocClick);
  document.addEventListener('keydown', onKey);
  window.addEventListener('resize', place);
  window.addEventListener('scroll', place, true);
});
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocClick);
  document.removeEventListener('keydown', onKey);
  window.removeEventListener('resize', place);
  window.removeEventListener('scroll', place, true);
});
</script>

<template>
  <div ref="root" class="bell-root">
    <button
      ref="trigger" aria-label="通知" aria-haspopup="dialog" :aria-expanded="open" :aria-controls="panelId" :inert="!!selected"
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

    <Teleport to="body"><Transition name="pop">
      <div v-if="open" :id="panelId" ref="panel" class="panel" :style="position" :inert="!!selected" :aria-hidden="selected ? 'true' : undefined" role="dialog" aria-label="通知" tabindex="-1" data-notification-panel>
        <div class="panel-head">
          <span class="panel-title">通知</span>
          <button
            class="read-all"
            :disabled="!notifications.unread"
            @click="notificationActions.readAll()"
          >
            全部已读
          </button>
          <button class="read-all" aria-label="关闭通知" @click="close()">关闭</button>
        </div>
        <div class="panel-body">
          <div v-if="!notifications.items.length" class="empty">还没有通知喵~</div>
          <button
            v-for="n in notifications.items"
            :key="n.id"
            class="item"
            :class="{ unread: !n.read }"
            @click="openItem(n.id, $event)"
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
    </Transition></Teleport>
    <NotificationDetail v-if="selected" :key="selected" :id="selected" :origin="origin" @close="detailClosed" />
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
  position: fixed;
  width: min(360px, calc(100vw - 16px));
  max-height: min(420px, calc(100dvh - 16px));
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--bg-panel, #1a1e28) 96%, transparent);
  backdrop-filter: var(--blur, blur(12px));
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
  overflow: hidden;
  /* Above navigation/content, below authentication and destructive dialogs. */
  z-index: 200;
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
@media(prefers-reduced-motion:reduce){.pop-enter-active,.pop-leave-active{transition:opacity .12s}.pop-enter-from,.pop-leave-to{transform:none}.item,.bell-btn{transition:none}}

button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
</style>
