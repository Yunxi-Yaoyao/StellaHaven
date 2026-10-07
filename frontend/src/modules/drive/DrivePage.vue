<script setup lang="ts">
// External service connection; background controls remain independent.
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { api } from "../../api/client";
import { useRouter } from 'vue-router';
const router = useRouter();
import {readDriveBackground,DRIVE_BACKGROUND_EVENT} from "./driveBackground";

import { displayBg } from "../home/auth";
import { DEFAULT_HOME_BG } from "../home/settings";

const status = ref<any>(null);
const loading = ref(true);
const error = ref("");

const frameUrl = ref("");
const frameEl = ref<HTMLIFrameElement | null>(null);
const frameReady = ref(false);
const frameKey = ref(0);
let loadTimer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
onUnmounted(() => { disposed = true; clearTimeout(loadTimer); window.removeEventListener(DRIVE_BACKGROUND_EVENT,syncBackground); window.removeEventListener("storage",syncBackground); });

// 背景模式：solid（统一 #14171f）| image（主页背景图）
const bgMode = ref(readDriveBackground());
function syncBackground(){bgMode.value=readDriveBackground();}

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

// One authority inside the authenticated OpenList frame owns reversible background changes.
// The parent only sends the selected mode; it must not overwrite the original theme.
function applyIframeBg() {
  const cw = frameEl.value?.contentWindow;
  if (cw && frameUrl.value) cw.postMessage({ type: 'stella-bg-mode', mode: bgMode.value }, new URL(frameUrl.value, location.origin).origin);
}

// iframe 加载完成 → 先铺好背景图（image 模式预加载图片后再淡入，避免先闪深色块），
// 再等 OpenList 内部深色主题就绪（注入 JS 打 data-stella-theme 标记）后淡入。
function onFrameLoad() {
  clearTimeout(loadTimer); error.value = ''; applyIframeBg(); frameReady.value = true; loading.value = false;
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
onMounted(()=>{window.addEventListener(DRIVE_BACKGROUND_EVENT,syncBackground);window.addEventListener("storage",syncBackground);void refresh();});
watch([bgImage,bgMode],applyIframeBg);
</script>

<template>
 <div class="drive-page" :class="{'image-mode':bgMode==='image'}" :style="pageStyle">
  <video v-if="bgMode==='image'&&isVideoBg" class="bg-video" :src="bgImage" autoplay muted loop playsinline/>
  <div v-if="error" class="recovery"><p role="alert">{{error}}</p><button :disabled="loading" @click="refresh">重新连接</button><button @click="router.push({path:'/settings',query:{section:'navigation',module:'drive'}})">连接设置</button></div>
  <iframe v-if="frameUrl" :key="frameKey" ref="frameEl" title="OpenList 网盘" class="frame" :class="{ready:frameReady}" :src="frameUrl" referrerpolicy="no-referrer" @load="onFrameLoad" @error="error='OpenList 加载失败，请重新连接';loading=false"/>
 </div>
</template>
<style scoped>
.drive-page{height:100%;min-height:0;overflow:hidden;display:flex;flex-direction:column;position:relative}.bg-video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;pointer-events:none;z-index:0}.frame{flex:1;min-height:0;width:100%;border:0;box-sizing:border-box;background:transparent;position:relative;z-index:1;opacity:0;transition:opacity 250ms ease}.frame.ready{opacity:1}.recovery{position:relative;z-index:2;padding:16px;background:var(--bg-panel);color:var(--text-lo);font-size:13px}.recovery p{margin:0 0 12px}.recovery button{padding:7px 12px;margin-right:8px;background:var(--bg-raised);color:var(--text-hi);border:1px solid #ffffff20;border-radius:7px;cursor:pointer}
</style>
