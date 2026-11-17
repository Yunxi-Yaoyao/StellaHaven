<script setup lang="ts">
import { ref, reactive, watch, computed, defineAsyncComponent, nextTick } from "vue";
import SideBar from "./shell/SideBar.vue";
import {notifyClientPreferenceChange} from './modules/settings/clientPreferenceEvents';
import {startClientPreferenceSync} from './modules/settings/clientPreferenceSync';
import ClientPreferenceStatus from './modules/settings/ClientPreferenceStatus.vue';
import {loginPrompt,consumeLoginTarget} from "./modules/auth/loginPrompt";
import LoginModal from "./modules/auth/LoginPage.vue";
import { refreshLoginStatus } from "./modules/auth/loginStatus";

import ExternalModuleCache from "./shell/ExternalModuleCache.vue";
import { loadNavigation, resetNavigation, navigationRows } from "./stores/navigation";
import CommandPalette from "./shell/LazyCommandPalette.vue";
const commandModules = computed(() => navigationRows.value.filter(row => row.visible).map(row => ({label:row.label,path:row.to})));
import { bgManagerOpen, settingsOpen } from "./modules/home/settings";
const BgManager = defineAsyncComponent(() => import("./modules/home/BgManager.vue"));
const bgManagerRequested = ref(bgManagerOpen.value);
// Retain the mounted manager after first use so closing preserves its draft state.
function focusBackgroundManager() {
  void nextTick(() => { if (bgManagerOpen.value) document.querySelector<HTMLButtonElement>('.bgm .x')?.focus(); });
}
watch(bgManagerOpen, open => { if (open) { bgManagerRequested.value = true; focusBackgroundManager(); } });
import { toasts } from "./composables/useToast";
import { auth, loggedIn, fetchMe, reportActivity, clearSecurity } from "./modules/home/auth";
import { startNotifications, stopNotifications } from "./stores/notifications";
import { useNotesStore } from "./stores/notes";
import { useRouter, useRoute } from "vue-router";
import { onMounted, onUnmounted } from "vue";

const notesStore = useNotesStore();
watch(()=>auth.suspended||auth.sessionClosing,blocked=>{if(blocked){clearSecurity();stopNotifications();}else if(auth.me){startNotifications();}},{flush:'sync'});
watch(() => [auth.me?.id, auth.sessionGeneration] as const, ([id, session], previous) => {
  if (id !== previous?.[0] || session !== previous?.[1]) {
    notesStore.resetSession();
    resetNavigation(); clearSecurity();
    if (id && !auth.sessionClosing) { void loadNavigation(); }
    if (id) startNotifications(); else stopNotifications();
    let cachedUser: string | undefined;
    try { cachedUser = JSON.parse(localStorage.getItem('stella_bootstrap') || '{}').userId; } catch { /* Invalid cache is discarded below. */ }
    if (!id || cachedUser !== id) localStorage.removeItem('stella_bootstrap');
  }
}, { flush: 'sync', immediate: true });
const router = useRouter();
const route = useRoute();
// Home overlays never survive route/owner changes or a blocking authentication UI.
watch(() => [route.name, loggedIn.value, loginPrompt.requested, auth.sessionGeneration] as const,
  (next, previous) => {
    if (next[0] !== 'home' || !next[1] || next[2] || (previous && next[3] !== previous[3])) {
      settingsOpen.value = false;
      bgManagerOpen.value = false;
      bgManagerRequested.value = false;
    }
  }, { flush: 'sync' });
const loginVisible=computed(()=>!auth.sessionClosing && (loginPrompt.requested || auth.suspended || (auth.checked && !loggedIn.value && !route.meta.public)));
async function closeLogin(){
 consumeLoginTarget();
 if(auth.suspended){auth.sessionClosing=true;auth.sessionGeneration++;auth.me=null;auth.suspended=false;auth.sessionClosing=false;}
 if(!route.meta.public)await router.replace("/");
 loginPrompt.requested=false;
}
function loginSuccess(firstRegistration=false){loginPrompt.requested=false;const target=consumeLoginTarget();if(target){window.location.assign(target);return;}if(firstRegistration&&auth.me){void router.push('/settings?section=first-use');return;}if(route.meta.legacyModule)void router.replace({path:route.fullPath,force:true});}
const notesHop = ref(route.name === 'notes');
watch(() => route.name, (next, previous) => { notesHop.value = next === 'notes' || previous === 'notes'; }, { flush: 'sync' });


// 主页背景要铺满整个内容区，不吃全局 padding（其他页面保留内缩）
const flushPage = computed(() => route.name === "home");

// Confirmed expiry opens login in place; transport failures do not destroy drafts.
let sessionWatchdog: ReturnType<typeof setInterval> | undefined;
let stopPreferenceSync:(()=>void)|undefined;
const activityEvents = ['pointerdown', 'keydown', 'wheel', 'touchstart'];
onMounted(() => {
  stopPreferenceSync=startClientPreferenceSync();
  void refreshLoginStatus();
  for (const event of activityEvents) document.addEventListener(event, reportActivity, { passive: true, capture: true });
  sessionWatchdog = setInterval(async () => {
    if (!loggedIn.value) return;
    const ok = await fetchMe(); // fetchMe 内部会先 refresh 续命；refresh 也被吊销才 false
    if (!ok && auth.suspended) loginPrompt.requested = true;
  }, 30000);
});
onUnmounted(() => {
  stopPreferenceSync?.();
  clearInterval(sessionWatchdog);
  for (const event of activityEvents) document.removeEventListener(event, reportActivity, true);
});
import {vPrivateSrc} from "./modules/auth/privateMedia";
import { lightbox, closeLightbox } from "./composables/useLightbox";

// 放大器缩放/平移状态
const zoom = ref(1);
const pan = reactive({ x: 0, y: 0 });
watch(() => lightbox.src, () => {
  zoom.value = 1;
  pan.x = 0;
  pan.y = 0;
});

function zoomBy(f: number) {
  zoom.value = Math.min(5, Math.max(0.25, zoom.value * f));
}
function onWheel(e: WheelEvent) {
  e.preventDefault();
  zoomBy(e.deltaY < 0 ? 1.15 : 1 / 1.15);
}
function resetZoom() {
  zoom.value = 1;
  pan.x = 0;
  pan.y = 0;
}

// 拖动平移（放大后）
let panning: { sx: number; sy: number; ox: number; oy: number } | null = null;
function onImgPointerDown(e: PointerEvent) {
  if (zoom.value <= 1) return;
  panning = { sx: e.clientX, sy: e.clientY, ox: pan.x, oy: pan.y };
  (e.target as HTMLElement).setPointerCapture(e.pointerId);
}
function onImgPointerMove(e: PointerEvent) {
  if (!panning) return;
  pan.x = panning.ox + (e.clientX - panning.sx);
  pan.y = panning.oy + (e.clientY - panning.sy);
}
function onImgPointerUp() {
  panning = null;
}

// 桌面折叠（记忆）+ 移动端抽屉（不记忆）
const sidebarCollapsed = ref(localStorage.getItem("stella_sidebar_fold") === "1");
const mobileOpen = ref(false);
const notesPage = computed(() => route.name === 'notes');
const mobileQuery = window.matchMedia?.('(max-width: 768px)');
const mobileViewport = ref(mobileQuery?.matches ?? false);
const drawerActive = computed(() => mobileViewport.value && mobileOpen.value);
// Idle appearance belongs to the face, not the drawer's synchronized outer fade.
const handleIdle = ref(false);
const handleHovered = ref(false);
const handleFocused = ref(false);
// Restoring accessibility focus after a touch close must not pin the face bright.
// Track modality as a fallback for browsers without :focus-visible support.
let handleKeyboardInput = true;
function handleHasVisibleFocus() {
  if (!handleFocused.value) return false;
  try { return !!document.querySelector('.notes-handle:focus-visible'); }
  catch { return handleKeyboardInput; }
}
function handleInputModality(event: Event) {
  handleKeyboardInput = event.type === 'keydown';
  if (handleFocused.value) {
    if (handleKeyboardInput) { clearHandleTimer(); handleIdle.value = false; }
    else resetHandleIdle();
  }
}
let handleTimer: ReturnType<typeof setTimeout> | undefined;
function clearHandleTimer() { clearTimeout(handleTimer); handleTimer = undefined; }
function resetHandleIdle() {
  clearHandleTimer(); handleIdle.value = false;
  if (!mobileViewport.value || drawerActive.value || document.hidden || handleHovered.value || handleHasVisibleFocus()) return;
  handleTimer = setTimeout(() => { handleIdle.value = true; handleTimer = undefined; }, 3000);
}
function handleHover(event: PointerEvent, hovered: boolean) {
  if (event.pointerType !== 'mouse') return;
  handleHovered.value = hovered; resetHandleIdle();
}
function handleFocus(focused: boolean) { handleFocused.value = focused; resetHandleIdle(); }
function handleVisibility() { if (document.hidden) clearHandleTimer(); else resetHandleIdle(); }
watch([drawerActive, mobileViewport, () => route.fullPath], resetHandleIdle);
onMounted(() => {
  resetHandleIdle(); window.addEventListener('resize', resetHandleIdle);
  document.addEventListener('visibilitychange', handleVisibility);
  document.addEventListener('keydown', handleInputModality, true);
  document.addEventListener('pointerdown', handleInputModality, true);
});
onUnmounted(() => {
  clearHandleTimer(); window.removeEventListener('resize', resetHandleIdle);
  document.removeEventListener('visibilitychange', handleVisibility);
  document.removeEventListener('keydown', handleInputModality, true);
  document.removeEventListener('pointerdown', handleInputModality, true);
});
function closeMobile() {
  mobileOpen.value = false;
  void nextTick(() => {
    if (!loginVisible.value) document.querySelector<HTMLButtonElement>('.hamburger')?.focus();
    // Re-arm after inert is removed and the restored focus modality is known.
    resetHandleIdle();
  });
}
function drawerKeys(event: KeyboardEvent) {
  if (!drawerActive.value || loginVisible.value) return;
  // Teleported child dialogs own their keyboard interaction before the drawer.
  if (event.target instanceof Element && event.target.closest('[data-notification-panel], .detail-dialog[role="dialog"]')) return;
  if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); closeMobile(); return; }
  if (event.key !== 'Tab') return;
  const items = [...document.querySelectorAll<HTMLElement>('.sidebar a[href], .sidebar button:not([disabled])')].filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
  const first = items[0], last = items.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
}
function syncViewport() { mobileViewport.value = mobileQuery?.matches ?? false; if (!mobileViewport.value) mobileOpen.value = false; }
onMounted(() => { mobileQuery?.addEventListener('change', syncViewport); document.addEventListener('keydown', drawerKeys, true); });
onUnmounted(() => { mobileQuery?.removeEventListener('change', syncViewport); document.removeEventListener('keydown', drawerKeys, true); });
watch(drawerActive, async open => {
  if (open) { await nextTick(); document.querySelector<HTMLElement>('.sidebar .mobile-close')?.focus({ preventScroll: true }); }
});
// The initial router commit may briefly have no public meta. Only an actual
// login request or expiry closes a drawer, not that transient startup state.
watch(() => auth.suspended || loginPrompt.requested, visible => { if (visible) mobileOpen.value = false; });

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
  notifyClientPreferenceChange('stella_sidebar_fold',sidebarCollapsed.value ? '1' : '0');
  localStorage.setItem("stella_sidebar_fold", sidebarCollapsed.value ? "1" : "0");
}
</script>

<template>
  <div class="shell" :inert="loginVisible || auth.sessionClosing || settingsOpen || undefined" :aria-hidden="loginVisible || auth.sessionClosing || settingsOpen || undefined">
    <SideBar
      :collapsed="sidebarCollapsed"
      :mobile-open="mobileOpen"
      :notification-active="(!mobileViewport || drawerActive) && !loginVisible && !auth.sessionClosing && !settingsOpen"
      :inert="mobileViewport && !mobileOpen || undefined"
      :aria-hidden="mobileViewport && !mobileOpen || undefined"
      @toggle="toggleSidebar"
      @close-mobile="closeMobile"
    />

    <!-- 移动端遮罩 -->
    <div v-if="drawerActive" class="mobile-mask" @click="closeMobile" />
    <!-- 移动端汉堡按钮 -->
    <div class="notes-navigation" :class="{ 'drawer-open': drawerActive, 'handle-idle': handleIdle }" :inert="drawerActive || undefined" :aria-hidden="drawerActive || undefined">
      <button class="hamburger notes-handle" aria-label="打开导航" :aria-expanded="drawerActive" aria-controls="site-sidebar" :tabindex="drawerActive ? -1 : 0" @pointerenter="handleHover($event, true)" @pointerleave="handleHover($event, false)" @pointerdown="resetHandleIdle" @focus="handleFocus(true)" @blur="handleFocus(false)" @click="mobileOpen = true"><span class="notes-handle-face" aria-hidden="true">»</span></button>
    </div>


    <CommandPalette v-if="loggedIn" :modules="commandModules" />
    <!-- 背景图库浮窗 -->
    <BgManager v-if="bgManagerRequested" @vue:mounted="focusBackgroundManager" />

    <div class="content-region">
    <main class="content" :inert="drawerActive || undefined" :aria-hidden="drawerActive || undefined" :class="{ flush: flushPage, 'notes-content': notesPage, 'external-content': route.name === 'external-module' }">
      <ExternalModuleCache :key="auth.sessionGeneration" />
      <RouterView v-slot="{ Component }">
        <Transition name="fade" :css="!notesHop" :mode="notesHop ? undefined : 'out-in'">
          <!-- v-if otherwise assigns every dynamic route branch key 0.
               Use the rendered top-level record, not child names or queries,
               so KeepAlive separates Home/Notes without remounting layouts. -->
          <KeepAlive :key="`${auth.me?.id ?? 'guest'}:${auth.sessionGeneration}`" include="NotesPage,HomePage" :max="2">
            <component :is="Component" :key="route.matched[0]?.path" v-if="route.name !== 'external-module'" />
          </KeepAlive>
        </Transition>
      </RouterView>
    </main>
    <ClientPreferenceStatus v-if="loggedIn && !(route.name==='settings' && route.query.section==='backups')" compact :inert="drawerActive || undefined" :aria-hidden="drawerActive || undefined" />
    </div>

    <!-- 全局轻提示（右上角） -->
    <div class="toast-stack" role="status" aria-live="polite" aria-relevant="additions text">
      <TransitionGroup name="toast">
        <div v-for="t in toasts" :key="t.id" class="toast">{{ t.text }}</div>
      </TransitionGroup>
    </div>

    <!-- 全局图片放大查看器：滚轮/按钮缩放 + 拖动平移 -->
    <div v-if="lightbox.src" class="lightbox" @click="closeLightbox" @wheel="onWheel">
      <img
        v-private-src="lightbox.src"
        :style="{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }"
        :class="{ pannable: zoom > 1 }"
        @click.stop
        @pointerdown="onImgPointerDown"
        @pointermove="onImgPointerMove"
        @pointerup="onImgPointerUp"
      />
      <div class="zoom-bar" @click.stop>
        <button @click="zoomBy(1 / 1.25)">−</button>
        <span class="zoom-val" @click="resetZoom" title="点我复位">{{ Math.round(zoom * 100) }}%</span>
        <button @click="zoomBy(1.25)">＋</button>
      </div>
    </div>
  </div>
  <Teleport to="body"><div v-if="auth.sessionClosing" class="logout-pending" role="status" aria-live="polite">正在退出登录…</div></Teleport>
  <Teleport to="body"><Transition name="login-modal" :duration="{ enter: 260, leave: 180 }"><LoginModal v-if="loginVisible" @close="closeLogin" @success="loginSuccess" /></Transition></Teleport>
</template>

<style scoped>
.logout-pending { position: fixed; inset: 0; z-index: 900; display: grid; place-items: center; background: rgba(0,0,0,.35); backdrop-filter: blur(6px); color: var(--text-hi); }
.shell {
  --drawer-duration: 200ms;
  --drawer-easing: ease;
  --drawer-motion: var(--drawer-duration) var(--drawer-easing);
  display: flex;
  height: 100%;
}
.content-region {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
}
.content {
  min-width: 0;
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  padding: 28px 32px;
}
/* Scene-owned lines keep 24px end gaps; navigation keeps its existing inset. */
@media(min-width:769px) {
  .content:has(.settings-layout), .content:has(> .servers-page), .content:has(> .documentation) { padding-block:0; }
  .content :deep(.page:has(> .settings-layout)) { padding-block:0; display:grid; }
  .content :deep(.documentation) { position:relative; }
  .content :deep(.documentation)::after { content:''; position:absolute; left:279px; top:24px; bottom:24px; width:1px; background:var(--accent-dim); pointer-events:none; }
  .content :deep(.doc-directory) { border-right-color:transparent; }
}
@media(min-width:769px) and (max-width:900px) {
  .content :deep(.documentation)::after { left:234px; }
}
/* 主页全幅：去掉内缩，让背景铺到侧边栏/窗口边缘 */
.content.flush {
  padding: 0;
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
  /* The global navigation overlays content; no route reserves a top slot. */
  .content { padding: max(10px, env(safe-area-inset-top)) 12px max(10px, env(safe-area-inset-bottom)); }
  .content.flush { padding: 0; }
  /* Settings keep the existing edge handle and its +8px pointer hit area in
     a narrow, real gutter. Scope it to this scene; notes stay full-width. */
  .content:has(.settings-layout) { padding-left:max(28px, calc(env(safe-area-inset-left, 0px) + 28px)); }
  /* Embedded applications own their responsive layout. At 320px, the usual
     24px page inset clips native app controls; keep only device safe areas. */
  .content.external-content { padding: env(safe-area-inset-top, 0px) env(safe-area-inset-right, 0px) env(safe-area-inset-bottom, 0px) env(safe-area-inset-left, 0px); }
}

/* 移动端遮罩 + 汉堡 */
.mobile-mask {
  display: none;
}
.hamburger {
  display: none;
}
.notes-navigation { display: none; }
@media (max-width: 768px) {
  .mobile-mask {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    /* Global drawer (90) and mask must cover the notes directory (85). */
    z-index: 88;
  }
  .hamburger {
    display: block;
    position: fixed;
    left: 12px;
    top: 12px;
    z-index: 87;
    width: 38px;
    height: 38px;
    border-radius: 50%;
    border: 1px solid var(--accent-dim);
    background: var(--bg-raised);
    color: var(--accent);
    font-size: 16px;
    cursor: pointer;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.4);
  }
  .content.notes-content {
    /* Navigation overlays the reader; its preference never changes page geometry. */
    padding: max(10px, env(safe-area-inset-top)) 12px max(10px, env(safe-area-inset-bottom));
    overflow: hidden;
  }
  .notes-navigation {
    /* Above the open directory (85), below the drawer mask (88) and modals. */
    display: block; position: fixed; z-index: 87;
    top: 50%; transform: translateY(-50%); left: env(safe-area-inset-left, 0px);
    opacity: 1; visibility: visible;
    transition: opacity var(--drawer-motion), visibility 0s;
  }
  .notes-navigation.drawer-open { opacity: 0; visibility: hidden; pointer-events: none; transition: opacity var(--drawer-motion), visibility 0s linear var(--drawer-duration); }
  .notes-navigation button { display: flex; align-items: center; justify-content: center; height: 64px; width: 16px; padding: 0; border: 0; background: transparent; color: var(--accent); cursor: pointer; touch-action: manipulation; }
  .notes-navigation .hamburger { position: static; border-radius: 0; box-shadow: none; }
  .notes-handle::after { content: ''; position: absolute; inset: 0 -8px 0 0; }
  .notes-handle-face { display: flex; align-items: center; justify-content: center; box-sizing: border-box; width: 100%; height: 100%; font-size: 13px; border: 1px solid var(--accent-dim); border-left: 0; border-radius: 0 8px 8px 0; background: var(--bg-raised); opacity: 1; transition: opacity 600ms ease; }
  .handle-idle .notes-handle-face { opacity: .28; }
  .notes-navigation button:focus-visible { outline: 2px solid var(--accent); outline-offset: -3px; }
}
@media (prefers-reduced-motion: reduce) { .shell { --drawer-duration: 0ms; } .notes-handle-face { transition: none; } }

/* ── 全局 toast ── */
.toast-stack {
  position: fixed;
  right: max(20px, env(safe-area-inset-right));
  top: max(20px, env(safe-area-inset-top));
  max-width: min(380px, calc(100vw - 32px));
  pointer-events: none;
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
  font-size: 14px;
  overflow-wrap: anywhere;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}
.toast-enter-active,
.toast-leave-active {
  transition: opacity 180ms ease, transform 220ms ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(28px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(12px);
}

@media (prefers-reduced-motion: reduce) { .toast-enter-active,.toast-leave-active,.toast-move { transition:none; } }

/* 图片放大查看器 */
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(0, 0, 0, 0.82);
  display: grid;
  place-items: center;
  cursor: zoom-out;
  overflow: hidden;
}
.lightbox img {
  max-width: 92vw;
  max-height: 92vh;
  border-radius: var(--radius-sm);
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.6);
  transition: transform 120ms ease-out;
}
.lightbox img.pannable { cursor: grab; }
.zoom-bar {
  position: fixed;
  bottom: 22px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px;
  background: rgba(27, 31, 42, 0.9);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 999px;
  backdrop-filter: blur(10px);
}
.zoom-bar button {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-hi);
  font-size: 15px;
  cursor: pointer;
  transition: background var(--transition);
}
.zoom-bar button:hover { background: var(--bg-raised); }
.zoom-val {
  font-size: 12px;
  color: var(--text-lo);
  min-width: 42px;
  text-align: center;
  cursor: pointer;
}
</style>
