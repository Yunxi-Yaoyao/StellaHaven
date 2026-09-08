<script setup lang="ts">
// Reuse the actual media element for dimensions; retain previous frame during quality changes.
import { ref, computed, watch, onMounted, onUnmounted, toRef, nextTick } from 'vue';
import { useBackgroundMedia } from './backgroundMedia';
export interface BgCrop { cx: number; cy: number; w: number; h: number }
const props = defineProps<{ url: string; crop: BgCrop }>();
const { source, poster, media } = useBackgroundMedia(toRef(props, 'url'));
const host = ref<HTMLElement | null>(null);
const box = ref({ w: 0, h: 0 });
interface Frame { url: string; w: number; h: number; ready: boolean }
const current = ref<Frame | null>(null);
const pending = ref<Frame | null>(null);
let ro: ResizeObserver | null = null;
let dead = false;
const isVideo = (url: string) => /\.(mp4|webm)(?:[?#]|$)/i.test(url);
const frames = computed(() => [current.value, pending.value].filter((item): item is Frame => !!item));
watch(source, url => {
  if (!url || current.value?.url === url) { pending.value = null; return; }
  pending.value = { url, w: 0, h: 0, ready: false };
}, { immediate: true });
function dimensions(event: Event, frame: Frame) {
  const el = event.currentTarget as HTMLVideoElement | HTMLImageElement;
  frame.w = el instanceof HTMLVideoElement ? el.videoWidth : el.naturalWidth;
  frame.h = el instanceof HTMLVideoElement ? el.videoHeight : el.naturalHeight;
}
function loaded(event: Event, frame: Frame) {
  dimensions(event, frame);
  if (dead || pending.value?.url !== frame.url) return;
  frame.ready = true;
  current.value = frame;
  pending.value = null;
  void nextTick(syncPlayback);
}
function failed(frame: Frame) {
  if (pending.value?.url !== frame.url) return;
  if (frame.url !== props.url && current.value?.url !== props.url) {
    pending.value = { url: props.url, w: 0, h: 0, ready: false };
  } else pending.value = null; // retain previous media/poster rather than a blank replacement
}
function fit(w: number, h: number) {
  if (!w || !h || !box.value.w) return { opacity: '0' };
  const cw = Math.max(.001, props.crop.w), ch = Math.max(.001, props.crop.h);
  const scale = Math.max(box.value.w / (cw * w), box.value.h / (ch * h));
  return { width: w * scale + 'px', height: h * scale + 'px',
    left: box.value.w / 2 - props.crop.cx * w * scale + 'px',
    top: box.value.h / 2 - props.crop.cy * h * scale + 'px', opacity: '1' };
}
const posterSize = ref({ w: 0, h: 0 });
const posterStyle = computed(() => fit(posterSize.value.w || media.value?.width || 0, posterSize.value.h || media.value?.height || 0));
function posterLoaded(event: Event) { const img=event.currentTarget as HTMLImageElement; posterSize.value={w:img.naturalWidth,h:img.naturalHeight}; }
function syncPlayback() {
  for (const video of host.value?.querySelectorAll('video') ?? []) {
    if (document.hidden || dead) video.pause();
    else void video.play().catch(() => {}); // muted autoplay failure leaves the poster visible
  }
}
onMounted(() => {
  if (!host.value) return;
  const measure = () => { if (host.value) box.value = { w: host.value.clientWidth, h: host.value.clientHeight }; };
  measure(); ro = new ResizeObserver(measure); ro.observe(host.value);
  document.addEventListener('visibilitychange', syncPlayback);
});
onUnmounted(() => {
  dead = true; ro?.disconnect(); document.removeEventListener('visibilitychange', syncPlayback);
  for (const video of host.value?.querySelectorAll('video') ?? []) { video.pause(); video.removeAttribute('src'); video.load(); }
});
</script>
<template>
  <div ref="host" class="bg-layer">
    <img v-if="poster && !current" class="bg-media bg-poster" :src="poster" :style="posterStyle" @load="posterLoaded" alt="" decoding="async" />
    <template v-for="frame in frames" :key="frame.url">
      <video v-if="isVideo(frame.url)" class="bg-media" :class="{ pending: !frame.ready && !!current }" :style="fit(frame.w,frame.h)" :src="frame.url" :poster="poster || undefined" preload="auto" autoplay muted loop playsinline @loadedmetadata="dimensions($event,frame)" @loadeddata="loaded($event,frame)" @error="failed(frame)" />
      <img v-else class="bg-media" :class="{ pending: !frame.ready && !!current }" :style="fit(frame.w,frame.h)" :src="frame.url" alt="" decoding="async" @load="loaded($event,frame)" @error="failed(frame)" />
    </template>
  </div>
</template>
<style scoped>
.bg-layer { position: absolute; inset: 0; overflow: hidden; pointer-events: none; }
.bg-media { position: absolute; max-width: none; max-height: none; object-fit: fill; }
.bg-media.pending { visibility: hidden; }
</style>
