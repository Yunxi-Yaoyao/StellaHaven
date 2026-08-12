<script setup lang="ts">
// 头像裁切浮窗：选图 → 拖动+缩放调方形取景 → canvas 裁出 256×256 → 上传
import { ref, computed } from "vue";

const emit = defineEmits<{ done: [url: string]; close: [] }>();

const imgSrc = ref("");       // 选中图的 objectURL
const natW = ref(0);
const natH = ref(0);
const zoom = ref(1);          // 显示缩放（相对 cover 基准）
const off = ref({ x: 0, y: 0 }); // 拖动偏移（px，显示坐标系）
const fileInput = ref<HTMLInputElement | null>(null);
const error = ref("");
const busy = ref(false);

let img: HTMLImageElement | null = null;
let dragStart: { px: number; py: number; ox: number; oy: number } | null = null;

const STAGE = 260; // 预览框边长（px）
const CIRCLE = 1.0; // 圆形取景框直径占比（对应 .ac-frame::after 的 width:100%——内切圆顶满景框）——裁剪以它为准

function pick(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (f) loadFile(f);
}

function onDrop(e: DragEvent) {
  const f = e.dataTransfer?.files?.[0];
  if (f) loadFile(f);
}

function loadFile(f: File) {
  if (!/\.(jpe?g|png|webp|gif)$/i.test(f.name)) {
    error.value = "仅支持 jpg/png/webp/gif 喵~";
    return;
  }
  error.value = "";
  img = new Image();
  img.onload = () => {
    natW.value = img!.naturalWidth;
    natH.value = img!.naturalHeight;
    imgSrc.value = URL.createObjectURL(f);
    zoom.value = 1;
    off.value = { x: 0, y: 0 };
  };
  img.src = URL.createObjectURL(f);
}

// cover 基准下的显示尺寸（未加 zoom）
const base = computed(() => {
  if (!natW.value) return { w: 0, h: 0 };
  const s = Math.max(STAGE / natW.value, STAGE / natH.value);
  return { w: natW.value * s, h: natH.value * s };
});

const disp = computed(() => ({ w: base.value.w * zoom.value, h: base.value.h * zoom.value }));

// 拖动边界：圆框能推到图片边缘（以圆框直径算，不是整个舞台）
const clampedOff = computed(() => {
  const circle = STAGE * CIRCLE;
  const maxX = Math.max(0, (disp.value.w - circle) / 2);
  const maxY = Math.max(0, (disp.value.h - circle) / 2);
  return {
    x: Math.min(maxX, Math.max(-maxX, off.value.x)),
    y: Math.min(maxY, Math.max(-maxY, off.value.y)),
  };
});

const imgStyle = computed(() => ({
  width: disp.value.w + "px",
  height: disp.value.h + "px",
  left: STAGE / 2 - disp.value.w / 2 + clampedOff.value.x + "px",
  top: STAGE / 2 - disp.value.h / 2 + clampedOff.value.y + "px",
}));

function onDown(e: PointerEvent) {
  dragStart = { px: e.clientX, py: e.clientY, ox: clampedOff.value.x, oy: clampedOff.value.y };
  (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
}
function onMove(e: PointerEvent) {
  if (!dragStart) return;
  off.value = { x: dragStart.ox + (e.clientX - dragStart.px), y: dragStart.oy + (e.clientY - dragStart.py) };
}
function onUp() { dragStart = null; }

async function confirm() {
  if (!img) return;
  busy.value = true;
  // 显示坐标 → 源图坐标，裁「圆框看到的那块」（之前裁整个舞台方框，和圆框对不上）
  const scale = natW.value / disp.value.w; // 显示 → 源
  const cx = natW.value / 2 - clampedOff.value.x * scale;
  const cy = natH.value / 2 - clampedOff.value.y * scale;
  const side = Math.min(natW.value, natH.value, STAGE * CIRCLE * scale);
  const sx = Math.max(0, Math.min(natW.value - side, cx - side / 2));
  const sy = Math.max(0, Math.min(natH.value - side, cy - side / 2));

  const out = document.createElement("canvas");
  out.width = 256;
  out.height = 256;
  const ctx = out.getContext("2d")!;
  ctx.drawImage(img, sx, sy, side, side, 0, 0, 256, 256);

  out.toBlob(async (blob) => {
    if (!blob) { busy.value = false; return; }
    const fd = new FormData();
    fd.append("file", new File([blob], "avatar.png", { type: "image/png" }));
    const r = await fetch("/auth/avatar", { method: "POST", body: fd });
    busy.value = false;
    if (r.ok) {
      const u = await r.json();
      emit("done", u.avatar_url);
      emit("close");
    } else {
      error.value = (await r.json()).detail ?? "上传失败";
    }
  }, "image/png");
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div class="ac-mask" @click.self="emit('close')">
        <div class="ac" @dragover.prevent @drop.prevent="onDrop">
          <div class="ac-title">更换头像</div>

          <div v-if="!imgSrc" class="ac-pick" @click="fileInput?.click()">
            <input ref="fileInput" type="file" accept=".jpg,.jpeg,.png,.webp,.gif" hidden @change="pick" />
            点击选一张图，或直接拖进来（jpg/png/webp/gif）
          </div>

          <template v-else>
            <div
              class="ac-stage"
              :style="{ width: STAGE + 'px', height: STAGE + 'px' }"
              @pointerdown="onDown"
              @pointermove="onMove"
              @pointerup="onUp"
              @pointercancel="onUp"
            >
              <img class="ac-img" :src="imgSrc" :style="imgStyle" draggable="false" />
              <div class="ac-frame" />
            </div>
            <label class="ac-zoom">
              <span>缩放</span>
              <input v-model.number="zoom" type="range" min="1" max="3" step="0.01" />
              <span class="ac-zv">{{ Math.round(zoom * 100) }}%</span>
            </label>
          </template>

          <div v-if="error" class="ac-err">{{ error }}</div>
          <div class="ac-actions">
            <button class="btn ghost" @click="emit('close')">取消</button>
            <button v-if="imgSrc" class="btn" :disabled="busy" @click="confirm">{{ busy ? "上传中…" : "裁这个" }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ac-mask {
  position: fixed; inset: 0; z-index: 140;
  background: rgba(6, 10, 16, 0.55);
  display: flex; align-items: center; justify-content: center;
}
.ac {
  width: 340px;
  background: color-mix(in srgb, var(--bg-panel) 94%, transparent);
  backdrop-filter: var(--blur);
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 18px;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.55);
  padding: 20px 22px;
}
.ac-title { font-size: 15px; font-weight: 600; color: var(--text-hi); letter-spacing: 2px; margin-bottom: 14px; }
.ac-pick {
  border: 1.5px dashed rgba(255, 255, 255, 0.18);
  border-radius: 12px;
  padding: 40px 16px;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-lo);
  cursor: pointer;
  transition: all 220ms;
}
.ac-pick:hover { border-color: var(--accent-dim); color: var(--text-hi); }
.ac-stage {
  position: relative;
  margin: 0 auto;
  border-radius: 14px;
  overflow: hidden;
  cursor: grab;
  touch-action: none;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
}
.ac-stage:active { cursor: grabbing; }
.ac-img { position: absolute; user-select: none; }
.ac-frame {
  position: absolute; inset: 0;
  border-radius: 14px;
  pointer-events: none;
}
/* 圆形取景框：外圈遮暗 + 圆环描边，所见即头像 */
.ac-frame::before {
  content: "";
  position: absolute; inset: 0;
  border-radius: 14px;
  background: radial-gradient(circle at 50% 50%, transparent 99%, rgba(8, 12, 18, 0.55) 100%);
}
.ac-frame::after {
  content: "";
  position: absolute;
  left: 50%; top: 50%;
  width: 100%;
  aspect-ratio: 1;
  transform: translate(-50%, -50%);
  border: 2px solid rgba(255, 255, 255, 0.65);
  border-radius: 50%;
  box-shadow: 0 0 0 999px transparent;
}
.ac-zoom {
  margin-top: 12px;
  display: flex; align-items: center; gap: 10px;
  font-size: 12px; color: var(--text-lo);
}
.ac-zoom input { flex: 1; accent-color: var(--accent); }
.ac-zv { width: 38px; text-align: right; }
.ac-err { margin-top: 10px; font-size: 12px; color: #e8a0bf; }
.ac-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.btn {
  padding: 8px 18px; border-radius: 10px; border: none;
  background: var(--accent); color: #141824;
  font-size: 13px; font-weight: 600; cursor: pointer; font-family: inherit;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.ghost { background: transparent; color: var(--text-lo); border: 1px solid rgba(255, 255, 255, 0.12); font-weight: 400; }
.fade-enter-active, .fade-leave-active { transition: opacity 240ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
