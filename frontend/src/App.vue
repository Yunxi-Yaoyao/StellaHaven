<script setup lang="ts">
import { ref, reactive, watch } from "vue";
import SideBar from "./shell/SideBar.vue";
import SettingsPanel from "./shell/SettingsPanel.vue";
import BgManager from "./modules/home/BgManager.vue";
import { toasts } from "./composables/useToast";
import { auth, loggedIn, fetchMe } from "./modules/home/auth";
import { useRouter } from "vue-router";
import { onMounted, onUnmounted } from "vue";

const router = useRouter();

// 会话巡检：被别处踢下线（refresh 已吊销）时，30 秒内感知并滚去登录页
let sessionWatchdog: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
  sessionWatchdog = setInterval(async () => {
    if (!loggedIn.value) return;
    const ok = await fetchMe(); // fetchMe 内部会先 refresh 续命；refresh 也被吊销才 false
    if (!ok && !auth.me) {
      router.push("/login");
    }
  }, 30000);
});
onUnmounted(() => clearInterval(sessionWatchdog));
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
  <div class="shell">
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

    <!-- 设置面板（右侧滑出） -->
    <SettingsPanel />
    <!-- 背景图库浮窗 -->
    <BgManager />

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

    <!-- 全局图片放大查看器：滚轮/按钮缩放 + 拖动平移 -->
    <div v-if="lightbox.src" class="lightbox" @click="closeLightbox" @wheel="onWheel">
      <img
        :src="lightbox.src"
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
