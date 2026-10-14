<script setup lang="ts">
import { ref, reactive, watch, computed, defineAsyncComponent } from "vue";
import SideBar from "./shell/SideBar.vue";
import {loginPrompt} from "./modules/auth/loginPrompt";
const LoginModal=defineAsyncComponent(()=>import("./modules/auth/LoginPage.vue"));
import AdminElevationModal from "./shell/AdminElevationModal.vue";
import ExternalModuleCache from "./shell/ExternalModuleCache.vue";
import { loadNavigation, resetNavigation, navigationRows } from "./stores/navigation";
import CommandPalette from "./shell/LazyCommandPalette.vue";
const commandModules = computed(() => navigationRows.value.filter(row => row.visible).map(row => ({label:row.label,path:row.to})));
import { bgManagerOpen, settingsOpen } from "./modules/home/settings";
const BgManager = defineAsyncComponent(() => import("./modules/home/BgManager.vue"));
const bgManagerRequested = ref(bgManagerOpen.value);
// Retain the mounted manager after first use so closing preserves its draft state.
watch(bgManagerOpen, open => { if (open) bgManagerRequested.value = true; });
import { toasts } from "./composables/useToast";
import { auth, loggedIn, fetchMe, reportActivity, loadSecurity, clearSecurity } from "./modules/home/auth";
import { startNotifications, stopNotifications } from "./stores/notifications";
import { useNotesStore } from "./stores/notes";
import { useRouter, useRoute } from "vue-router";
import { onMounted, onUnmounted } from "vue";

const notesStore = useNotesStore();
watch(()=>auth.suspended||auth.sessionClosing,blocked=>{if(blocked){clearSecurity();stopNotifications();}else if(auth.me){startNotifications();void loadSecurity().catch(()=>{});}},{flush:'sync'});
watch(() => [auth.me?.id, auth.sessionGeneration] as const, ([id, session], previous) => {
  if (id !== previous?.[0] || session !== previous?.[1]) {
    notesStore.resetSession();
    resetNavigation(); clearSecurity();
    if (id && !auth.sessionClosing) { void loadNavigation(); void loadSecurity().catch(() => {}); }
    if (id) startNotifications(); else stopNotifications();
    let cachedUser: string | undefined;
    try { cachedUser = JSON.parse(localStorage.getItem('stella_bootstrap') || '{}').userId; } catch { /* Invalid cache is discarded below. */ }
    if (!id || cachedUser !== id) localStorage.removeItem('stella_bootstrap');
  }
}, { flush: 'sync', immediate: true });
const router = useRouter();
// The legacy theme gear only redirects; its embedded form belongs to SettingsPage.
watch(settingsOpen, open => {
  if (!open) return;
  settingsOpen.value = false;
  void router.push({ path: '/settings', query: { section: 'navigation', module: 'home' } });
}, { immediate: true });
const route = useRoute();
const loginVisible=computed(()=>!auth.sessionClosing && (loginPrompt.requested || auth.suspended || (auth.checked && !loggedIn.value && !route.meta.public)));
async function closeLogin(){
 if(auth.suspended){auth.sessionClosing=true;auth.sessionGeneration++;auth.me=null;auth.suspended=false;auth.sessionClosing=false;}
 if(!route.meta.public)await router.replace("/");
 loginPrompt.requested=false;
}
function loginSuccess(){loginPrompt.requested=false;if(route.meta.legacyModule)void router.replace({path:route.fullPath,force:true});}
const notesHop = ref(route.name === 'notes');
watch(() => route.name, (next, previous) => { notesHop.value = next === 'notes' || previous === 'notes'; }, { flush: 'sync' });


// 主页背景要铺满整个内容区，不吃全局 padding（其他页面保留内缩）
const flushPage = computed(() => route.name === "home");

// Confirmed expiry opens login in place; transport failures do not destroy drafts.
let sessionWatchdog: ReturnType<typeof setInterval> | undefined;
const activityEvents = ['pointerdown', 'keydown', 'wheel', 'touchstart'];
onMounted(() => {
  for (const event of activityEvents) document.addEventListener(event, reportActivity, { passive: true, capture: true });
  sessionWatchdog = setInterval(async () => {
    if (!loggedIn.value) return;
    const ok = await fetchMe(); // fetchMe 内部会先 refresh 续命；refresh 也被吊销才 false
    if (!ok && auth.suspended) loginPrompt.requested = true;
  }, 30000);
});
onUnmounted(() => {
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

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
  localStorage.setItem("stella_sidebar_fold", sidebarCollapsed.value ? "1" : "0");
}
</script>

<template>
  <div class="shell" :inert="loginVisible || auth.sessionClosing || undefined" :aria-hidden="loginVisible || auth.sessionClosing || undefined">
    <SideBar
      :collapsed="sidebarCollapsed"
      :mobile-open="mobileOpen"
      @toggle="toggleSidebar"
      @close-mobile="mobileOpen = false"
    />

    <!-- 移动端遮罩 -->
    <div v-if="mobileOpen" class="mobile-mask" @click="mobileOpen = false" />
    <!-- 移动端汉堡按钮 -->
    <button v-if="!mobileOpen" class="hamburger" @click="mobileOpen = true">☰</button>

    <AdminElevationModal />
    <CommandPalette v-if="loggedIn" :modules="commandModules" />
    <!-- 背景图库浮窗 -->
    <BgManager v-if="bgManagerRequested" />

    <main class="content" :class="{ flush: flushPage }">
      <ExternalModuleCache :key="auth.sessionGeneration" />
      <RouterView v-slot="{ Component }">
        <Transition name="fade" :css="!notesHop" :mode="notesHop ? undefined : 'out-in'">
          <KeepAlive :key="`${auth.me?.id ?? 'guest'}:${auth.sessionGeneration}`" include="NotesPage" :max="1">
            <component :is="Component" v-if="route.name !== 'external-module'" />
          </KeepAlive>
        </Transition>
      </RouterView>
    </main>

    <!-- 全局轻提示（右下角） -->
    <div class="toast-stack">
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
  <Teleport to="body"><LoginModal v-if="loginVisible" @close="closeLogin" @success="loginSuccess" /></Teleport>
</template>

<style scoped>
.logout-pending { position: fixed; inset: 0; z-index: 900; display: grid; place-items: center; background: rgba(0,0,0,.35); backdrop-filter: blur(6px); color: var(--text-hi); }
.shell {
  display: flex;
  height: 100%;
}
.content {
  min-width: 0;
  flex: 1;
  overflow-y: auto;
  padding: 28px 32px;
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
  /* 顶部留出固定位：内容不许滑到汉堡按钮底下（left:12 + 38 + 8 间隙） */
  .content { padding: 58px 12px 14px; }
}

/* 移动端遮罩 + 汉堡 */
.mobile-mask {
  display: none;
}
.hamburger {
  display: none;
}
@media (max-width: 768px) {
  .mobile-mask {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    z-index: 80;
  }
  .hamburger {
    display: block;
    position: fixed;
    left: 12px;
    top: 12px;
    z-index: 75;
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
