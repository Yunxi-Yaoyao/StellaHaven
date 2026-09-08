<script setup lang="ts">
// External service connection; background controls remain independent.
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { api } from "../../api/client";
import { isAdmin } from "../home/auth";
import Icon from "../../shell/Icon.vue";
import ConnectionPanel from "./ConnectionPanel.vue";
import { displayBg } from "../home/auth";
import { DEFAULT_HOME_BG } from "../home/settings";

const status = ref<any>(null);
const loading = ref(true);
const error = ref("");
const manageOpen = ref(false);
const frameUrl = ref("");
const frameEl = ref<HTMLIFrameElement | null>(null);
const frameReady = ref(false);
const frameKey = ref(0);
let loadTimer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
onUnmounted(() => { disposed = true; clearTimeout(loadTimer); });

// 背景模式：solid（统一 #14171f）| image（主页背景图）
const BG_KEY = "stella_drive_bg_mode";
const bgMode = ref<'solid' | 'image'>(
  (localStorage.getItem(BG_KEY) as 'solid' | 'image') || 'solid'
);

// 背景 URL（复用主页壁纸，支持图片和视频）
const bgImage = computed(() => displayBg.value || DEFAULT_HOME_BG);

// 视频背景用 <video> 元素铺底（CSS background-image 播不了视频）
const isVideoBg = computed(() => bgImage.value.toLowerCase().endsWith('.mp4'));

// 容器背景：image+图片 用背景图；image+视频 交给 <video> 铺底；solid 用 #14171f
const pageStyle = computed(() => {
  if (bgMode.value === 'image' && !isVideoBg.value) {
    return {
      backgroundImage: `url(${bgImage.value})`,
      backgroundSize: 'cover',
      backgroundPosition: 'center',
    };
  }
  if (bgMode.value === 'image') {
    return {};  // 视频由 .bg-video 元素渲染
  }
  return { backgroundColor: '#14171f' };
});

function toggleBg() {
  bgMode.value = bgMode.value === 'solid' ? 'image' : 'solid';
  localStorage.setItem(BG_KEY, bgMode.value);
  applyIframeBg();
}

function clearIframeBg() {
  const doc = frameEl.value?.contentDocument;
  if (!doc) return;
  const html = doc.documentElement;
  const body = doc.body;
  const root = doc.getElementById('root');
  html.style.setProperty('background-color', '#14171f', 'important');
  body.style.setProperty('background-color', '#14171f', 'important');
  body.style.removeProperty('background-image');
  body.style.removeProperty('background-size');
  body.style.removeProperty('background-position');
  body.style.removeProperty('background-attachment');
  if (root) root.style.setProperty('background-color', '#14171f', 'important');
  html.removeAttribute('data-bg-mode');
}

function applyTransparentBg() {
  const f = frameEl.value;
  if (!f || !f.contentDocument || !f.contentDocument.body) return;
  const doc = f.contentDocument;
  const html = doc.documentElement;
  const body = doc.body;
  const root = doc.getElementById('root');
  html.style.setProperty('background-color', 'transparent', 'important');
  html.style.setProperty('color-scheme', 'normal', 'important');
  body.style.setProperty('background-color', 'transparent', 'important');
  body.style.removeProperty('background-image');
  body.style.removeProperty('background-size');
  body.style.removeProperty('background-position');
  body.style.removeProperty('background-attachment');
  if (root) root.style.setProperty('background-color', 'transparent', 'important');
  html.setAttribute('data-bg-mode', 'image');
}

// 背景图模式：让 iframe 内部 html/body/#root 全部透明，依赖外层背景图透进来。
// 同时强制 color-scheme:normal，避免 OpenList 的 light/dark meta 让浏览器给 iframe canvas 填默认色。
function applyIframeBg() {
  try {
    if (bgMode.value === 'image') applyTransparentBg(); else clearIframeBg();
  } catch { /* Cross-origin services manage their own theme. */ }
  const cw = frameEl.value?.contentWindow;
  if (cw && frameUrl.value) cw.postMessage({ type: 'stella-bg-mode', mode: bgMode.value }, new URL(frameUrl.value, location.origin).origin);
}

// iframe 加载完成 → 先铺好背景图（image 模式预加载图片后再淡入，避免先闪深色块），
// 再等 OpenList 内部深色主题就绪（注入 JS 打 data-stella-theme 标记）后淡入。
function onFrameLoad() {
  clearTimeout(loadTimer); applyIframeBg(); frameReady.value = true; loading.value = false;
  try {
    const text = frameEl.value?.contentDocument?.body?.innerText || '';
    if (text.trim().startsWith('{')) {
      const body = JSON.parse(text);
      if (body.detail) error.value = `OpenList 加载失败：${body.detail}`;
    }
  } catch { /* OpenList renders its own content. */ }
}

async function loadFrameUrl() {
  const result = await api<{url:string}>('/drive/login-url');
  if (disposed) return;
  frameReady.value = false;
  frameUrl.value = result.url;
  frameKey.value++; // same login URL still needs a fresh navigation/load event
  clearTimeout(loadTimer);
  loadTimer = setTimeout(() => { loading.value = false; frameReady.value = true; error.value = 'OpenList 加载较慢或连接异常，请重试'; }, 20000);
}
async function refresh() {
  if (loading.value && frameUrl.value) return;
  error.value = ''; loading.value = true;
  try { status.value = await api('/drive/status'); await loadFrameUrl(); }
  catch (e: any) { error.value = typeof e?.detail === 'string' ? e.detail : '连接加载失败，请重试'; }
  if (error.value) loading.value = false;
}
onMounted(refresh);
watch(bgImage, () => { if (bgMode.value === 'image') applyIframeBg(); });
</script>

<template>
  <div class="drive-page" :class="{ 'image-mode': bgMode === 'image' }" :style="pageStyle">
    <video v-if="bgMode === 'image' && isVideoBg" class="bg-video" :src="bgImage" autoplay muted loop playsinline />
    <div class="frame-bar">
      <div class="frame-title"><Icon name="drive" :size="16" /><span>网盘 · OpenList</span><span class="chip">外部服务</span></div>
      <div class="frame-actions">
        <button class="manage-btn" @click="toggleBg">{{ bgMode === 'solid' ? '背景图' : '纯色' }}</button>
        <button class="manage-btn" :disabled="loading" @click="refresh">{{ loading ? "连接中…" : "重新连接" }}</button>
        <button v-if="isAdmin" class="manage-btn" @click="manageOpen = true">连接设置</button>
      </div>
    </div>
    <p v-if="error" class="hint" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint">加载连接…</p>
    <iframe v-if="frameUrl" :key="frameKey" ref="frameEl" title="OpenList 网盘" class="frame" :class="{ ready: frameReady }" :src="frameUrl" referrerpolicy="no-referrer" @load="onFrameLoad" />
    <ConnectionPanel v-if="manageOpen" kind="drive" @close="manageOpen = false" @saved="refresh" />
  </div>
</template>

<style scoped>
.drive-page {
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  position: relative; /* 视频背景 absolute 定位的锚点 */
}

/* 视频背景铺底（z-index 0，内容层 frame-bar/frame 在其上） */
.bg-video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  pointer-events: none;
  z-index: 0;
}
.drive-page.image-mode .frame-bar,
.drive-page.image-mode .frame,
.drive-page.image-mode .frame-stopped,
.drive-page.image-mode .center {
  position: relative;
  z-index: 1;
}

/* ── 已安装：顶栏 + iframe ── */
.frame-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px;
  background: var(--bg-panel);
  flex-shrink: 0;
  border-radius: 12px 12px 0 0;
  border: 1px solid rgba(201, 212, 232, 0.16);
  border-bottom: none;
  box-sizing: border-box;
}
.frame-title { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; }
.chip {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11.5px; font-weight: 500; padding: 2px 9px; border-radius: 999px;
}
.chip .dot { width: 6px; height: 6px; border-radius: 50%; }
.chip.ok { color: var(--accent); background: rgba(201, 212, 232, 0.1); }
.chip.ok .dot { background: #4ade80; }
.chip.bad { color: var(--text-lo); background: var(--bg-raised); }
.chip.bad .dot { background: var(--text-faint); }

.manage-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 14px; border-radius: var(--radius-sm);
  background: var(--bg-raised); border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--text-hi); font-size: 12.5px; cursor: pointer; transition: all var(--transition);
}
.manage-btn:hover { border-color: var(--accent-dim); }

.frame-actions { display: flex; align-items: center; gap: 8px; }

/* 背景图模式：顶栏透明，露出背景图（按钮仍保留深色底可读） */
.drive-page.image-mode .frame-bar { background: transparent; }
/* 背景图/视频模式：顶栏文字纯白 + 深色投影，亮/暗背景上都可读 */
.drive-page.image-mode .frame-title { color: #ffffff; text-shadow: 0 1px 2px rgba(0, 0, 0, 0.85), 0 0 10px rgba(0, 0, 0, 0.55); }
.drive-page.image-mode .chip.ok { color: #ffffff; text-shadow: 0 1px 2px rgba(0, 0, 0, 0.85), 0 0 10px rgba(0, 0, 0, 0.55); }
.drive-page.image-mode .chip.bad { color: #ffffff; text-shadow: 0 1px 2px rgba(0, 0, 0, 0.85), 0 0 10px rgba(0, 0, 0, 0.55); }

.frame { flex: 1; width: 100%; background: transparent; border-radius: 0 0 12px 12px; overflow: hidden; border: 1px solid rgba(201, 212, 232, 0.16); border-top: none; box-sizing: border-box; opacity: 0; transition: opacity 250ms ease; }
.frame.ready { opacity: 1; }
.frame-stopped {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; color: var(--text-faint);
}
.frame-stopped p { font-size: 13px; }

/* ── 未安装：中心 ── */
.center {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; text-align: center;
}
.center-icon { color: var(--text-lo); opacity: 0.9; }
.center h1 { font-size: 22px; font-weight: 600; letter-spacing: 1px; }
.hint { color: var(--text-lo); font-size: 13px; }

.btn {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 8px 18px; border-radius: var(--radius-sm);
  font-size: 13px; cursor: pointer; transition: all var(--transition);
}
.btn.primary {
  background: var(--accent); border: 1px solid var(--accent); color: var(--bg-base); font-weight: 600;
}
.btn.primary:hover { background: #dbe4f2; }
.btn.primary:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
