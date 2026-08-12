<script setup lang="ts">
// 背景层：源图裁剪区域（crop 分数）渲染。窗口 resize 不重排——显示内容恒为那一块。
// 供三个主页主题共用；图片/视频同一套数学。
import { ref, computed, watch, onMounted, onUnmounted } from "vue";

export interface BgCrop { cx: number; cy: number; w: number; h: number; }

const props = defineProps<{ url: string; crop: BgCrop }>();

const host = ref<HTMLElement | null>(null);
const natW = ref(0);
const natH = ref(0);
const box = ref({ w: 0, h: 0 });
let ro: ResizeObserver | null = null;

const isVideo = computed(() => props.url.toLowerCase().endsWith(".mp4"));

watch(() => props.url, load, { immediate: true });
function load() {
  natW.value = 0;
  if (isVideo.value) {
    const v = document.createElement("video");
    v.muted = true;
    v.preload = "metadata";
    v.src = props.url;
    v.onloadedmetadata = () => { natW.value = v.videoWidth; natH.value = v.videoHeight; };
  } else {
    const i = new Image();
    i.onload = () => { natW.value = i.naturalWidth; natH.value = i.naturalHeight; };
    i.src = props.url;
  }
}

onMounted(() => {
  if (!host.value) return;
  box.value = { w: host.value.clientWidth, h: host.value.clientHeight };
  ro = new ResizeObserver(() => {
    if (host.value) box.value = { w: host.value.clientWidth, h: host.value.clientHeight };
  });
  ro.observe(host.value);
});
onUnmounted(() => ro?.disconnect());

// cover-fit 裁剪区：把源图的 crop 区域铺满容器（中心锚定，窗口变化只缩放不换内容）
const mediaStyle = computed(() => {
  if (!natW.value || !box.value.w) return { opacity: "0" };
  const srcW = props.crop.w * natW.value;
  const srcH = props.crop.h * natH.value;
  const s = Math.max(box.value.w / srcW, box.value.h / srcH);
  const dispW = natW.value * s;
  const dispH = natH.value * s;
  return {
    width: dispW + "px",
    height: dispH + "px",
    left: box.value.w / 2 - props.crop.cx * dispW + "px",
    top: box.value.h / 2 - props.crop.cy * dispH + "px",
    opacity: "1",
  };
});
</script>

<template>
  <div ref="host" class="bg-layer">
    <video v-if="isVideo" class="bg-media" :style="mediaStyle" :src="url" autoplay muted loop playsinline />
    <img v-else class="bg-media" :style="mediaStyle" :src="url" alt="" />
  </div>
</template>

<style scoped>
.bg-layer {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}
.bg-media {
  position: absolute;
  max-width: none;
  max-height: none;
  object-fit: fill; /* 尺寸已按比例算好，fill 不会变形 */
}
</style>
