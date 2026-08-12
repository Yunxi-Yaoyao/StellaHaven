<script setup lang="ts">
// 主页背景附件管理浮窗：拖拽上传 / 缩略图网格 / 单击选中 / 双击进裁剪预览 / 重命名 / 删除（默认不可删）
// 裁剪模型 = 源图分数区域（cx,cy 中心 + w,h 宽高），渲染时 cover-fit 铺满——窗口 resize 内容不散。
import { ref, computed, watch, onMounted } from "vue";
import { bgManagerOpen, homeSettings } from "./settings";

interface BgEntry {
  id: string;
  name: string;
  ext: string;
  url: string;
  isDefault: boolean;
}

const list = ref<BgEntry[]>([]);
const selectedId = ref<string | null>(null);
const previewEntry = ref<BgEntry | null>(null);
const renamingId = ref<string | null>(null);
const renameDraft = ref("");
const dragOver = ref(false);
const uploading = ref(false);
const errorMsg = ref("");
const fileInput = ref<HTMLInputElement | null>(null);

const isVideo = (e: BgEntry | null) => !!e && e.ext === "mp4";

/* ── 裁剪预览状态（源图分数区域） ── */
const nat = ref({ w: 0, h: 0 });          // 源图/源视频尺寸
const stage = ref({ w: 0, h: 0 });        // 预览舞台尺寸
const cropW = ref(1);                      // 裁剪区宽（源图宽分数）
const cropH = ref(1);                      // 裁剪区高（源图高分数）
const sliderX = ref(50);                   // 中心点滑杆 0-100
const sliderY = ref(50);
const zoom = ref(100);                     // 缩放滑杆：100=整张图

const cx = computed(() => cropW.value / 2 + (sliderX.value / 100) * (1 - cropW.value));
const cy = computed(() => cropH.value / 2 + (sliderY.value / 100) * (1 - cropH.value));

async function load() {
  const r = await fetch("/homebg/");
  list.value = await r.json();
  const cur = list.value.find((e) => e.url === homeSettings.bgImage);
  selectedId.value = cur?.id ?? list.value[0]?.id ?? null;
}

onMounted(load);
watch(bgManagerOpen, (v) => { if (v) { load(); errorMsg.value = ""; } });

function select(e: BgEntry) {
  selectedId.value = e.id;
  renamingId.value = null;
}

async function upload(files: FileList | File[]) {
  errorMsg.value = "";
  for (const f of Array.from(files)) {
    const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
    if (!["jpg", "jpeg", "png", "webp", "gif", "mp4"].includes(ext)) {
      errorMsg.value = `「${f.name}」格式不支持（仅 jpg/png/webp/gif/mp4）`;
      continue;
    }
    uploading.value = true;
    const fd = new FormData();
    fd.append("file", f);
    const r = await fetch("/homebg/upload", { method: "POST", body: fd });
    uploading.value = false;
    if (!r.ok) {
      errorMsg.value = `「${f.name}」上传失败：${(await r.json()).detail ?? r.status}`;
      continue;
    }
    const entry = await r.json();
    list.value.push(entry);
    selectedId.value = entry.id;
  }
}

function onDrop(e: DragEvent) {
  dragOver.value = false;
  if (e.dataTransfer?.files?.length) upload(e.dataTransfer.files);
}

/* ── 裁剪预览 ── */
function openPreview(e: BgEntry) {
  previewEntry.value = e;
  // 舞台 = 主页内容区真实宽高比（扣侧栏，实测 main）
  const main = document.querySelector("main");
  const mr = main?.getBoundingClientRect();
  const aspect = mr ? mr.width / mr.height : 16 / 9;
  stage.value = {
    w: Math.min(window.innerWidth * 0.84, window.innerHeight * 0.62 * aspect),
    h: 0,
  };
  stage.value.h = stage.value.w / aspect;
  // 读源尺寸
  nat.value = { w: 0, h: 0 };
  if (isVideo(e)) {
    const v = document.createElement("video");
    v.muted = true; v.preload = "metadata"; v.src = e.url;
    v.onloadedmetadata = () => { nat.value = { w: v.videoWidth, h: v.videoHeight }; initFromSettings(); };
  } else {
    const img = new Image();
    img.onload = () => { nat.value = { w: img.naturalWidth, h: img.naturalHeight }; initFromSettings(); };
    img.src = e.url;
  }
}

function initFromSettings() {
  const c = homeSettings.bgCrop;
  if (c && c.w < 1) {
    cropW.value = c.w;
    cropH.value = c.h;
    sliderX.value = (c.cx - c.w / 2) / (1 - c.w) * 100 || 50;
    sliderY.value = (c.cy - c.h / 2) / (1 - c.h) * 100 || 50;
    zoom.value = 100 / c.w;
  } else {
    cropW.value = 1; cropH.value = 1;
    sliderX.value = 50; sliderY.value = 50;
    zoom.value = 100;
  }
}

// 缩放变化：重算 cropW/H（保持舞台宽高比），越界时收边
watch(zoom, () => {
  if (!nat.value.w || !stage.value.w) return;
  let w = Math.min(1, 100 / zoom.value);
  let h = w * (nat.value.w / nat.value.h) * (stage.value.h / stage.value.w);
  if (h > 1) {
    h = 1;
    w = Math.min(1, h * (nat.value.h / nat.value.w) * (stage.value.w / stage.value.h));
  }
  cropW.value = w;
  cropH.value = h;
});

// 舞台内媒体的精确布局（与 BgLayer 同一份 cover-fit 数学）
const mediaStyle = computed(() => {
  if (!nat.value.w || !stage.value.w) return { opacity: "0" };
  const srcW = cropW.value * nat.value.w;
  const srcH = cropH.value * nat.value.h;
  const s = Math.max(stage.value.w / srcW, stage.value.h / srcH);
  const dispW = nat.value.w * s;
  const dispH = nat.value.h * s;
  return {
    width: dispW + "px",
    height: dispH + "px",
    left: stage.value.w / 2 - cx.value * dispW + "px",
    top: stage.value.h / 2 - cy.value * dispH + "px",
  };
});

function applyCrop() {
  const e = previewEntry.value;
  if (e) {
    homeSettings.bgImage = e.url;
    homeSettings.bgCrop = { cx: cx.value, cy: cy.value, w: cropW.value, h: cropH.value };
  }
  previewEntry.value = null;
  bgManagerOpen.value = false;
}

function confirmPick() {
  const e = list.value.find((x) => x.id === selectedId.value);
  if (e) homeSettings.bgImage = e.url;
  bgManagerOpen.value = false;
}

function startRename(e: BgEntry) {
  renamingId.value = e.id;
  renameDraft.value = e.name;
}

async function commitRename(e: BgEntry) {
  const name = renameDraft.value.trim();
  renamingId.value = null;
  if (!name || name === e.name) return;
  const r = await fetch(`/homebg/${e.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (r.ok) e.name = (await r.json()).name;
}

async function remove(e: BgEntry) {
  if (e.isDefault) return;
  if (!confirm(`删除背景「${e.name}」？`)) return;
  const r = await fetch(`/homebg/${e.id}`, { method: "DELETE" });
  if (r.ok) {
    list.value = list.value.filter((x) => x.id !== e.id);
    if (selectedId.value === e.id) selectedId.value = list.value[0]?.id ?? null;
  } else {
    errorMsg.value = (await r.json()).detail ?? "删除失败";
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="bgManagerOpen" class="bgm-mask" @click.self="bgManagerOpen = false">
        <div class="bgm" @dragover.prevent="dragOver = true" @dragleave="dragOver = false" @drop.prevent="onDrop">
          <div class="bgm-head">
            <div class="bgm-title">背景图库</div>
            <button class="x" title="关闭" @click="bgManagerOpen = false">✕</button>
          </div>

          <!-- 拖拽上传区 -->
          <div class="drop" :class="{ over: dragOver }" @click="fileInput?.click()">
            <input
              ref="fileInput"
              type="file"
              accept=".jpg,.jpeg,.png,.webp,.gif,.mp4"
              multiple
              hidden
              @change="(e) => { const t = e.target as HTMLInputElement; if (t.files) upload(t.files); t.value = ''; }"
            />
            <span v-if="uploading">上传中…</span>
            <span v-else>拖文件到这里，或点击选择（jpg / png / webp / gif / mp4）</span>
          </div>
          <div v-if="errorMsg" class="err">{{ errorMsg }}</div>

          <!-- 缩略图网格 -->
          <div class="grid">
            <div
              v-for="e in list"
              :key="e.id"
              class="cell"
              :class="{ on: selectedId === e.id }"
              @click="select(e)"
              @dblclick="openPreview(e)"
            >
              <div class="thumb">
                <video v-if="isVideo(e)" :src="e.url" muted preload="metadata" />
                <img v-else :src="e.url" :alt="e.name" loading="lazy" />
                <span v-if="e.isDefault" class="def-tag">默认</span>
              </div>
              <div class="meta">
                <input
                  v-if="renamingId === e.id"
                  v-model="renameDraft"
                  class="rename-input"
                  autofocus
                  @keydown.enter="commitRename(e)"
                  @keydown.esc="renamingId = null"
                  @blur="commitRename(e)"
                  @click.stop
                  @dblclick.stop
                />
                <span v-else class="name" :title="e.name" @dblclick.stop="startRename(e)">{{ e.name }}</span>
                <span class="ext" :data-ext="e.ext">[{{ e.ext }}]</span>
              </div>
              <div class="cell-ops">
                <button class="op" title="重命名" @click.stop="startRename(e)">✎</button>
                <button v-if="!e.isDefault" class="op danger" title="删除" @click.stop="remove(e)">🗑</button>
              </div>
            </div>
          </div>

          <div class="bgm-foot">
            <button class="btn ghost" @click="bgManagerOpen = false">取消</button>
            <button class="btn" :disabled="!selectedId" @click="confirmPick">确定更换</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 双击 = 裁剪预览：盖主页同款遮罩 + 组件 mock，滑杆/拖动调整「源图区域」 -->
    <Transition name="fade">
      <div v-if="previewEntry" class="preview-mask">
        <div class="crop-wrap">
          <div class="crop-stage" :style="{ width: stage.w + 'px', height: stage.h + 'px' }">
            <video
              v-if="isVideo(previewEntry)"
              class="crop-media"
              :src="previewEntry!.url"
              :style="mediaStyle"
              autoplay muted loop playsinline
            />
            <img v-else class="crop-media" :src="previewEntry!.url" :style="mediaStyle" alt="" />
            <div class="crop-scrim" />
            <!-- 主页组件 mock：构图预览用 -->
            <div class="mock-panel">
              <div class="mk-badge">云曦 · YUNXI'S</div>
              <div class="mk-title">StellaHaven</div>
              <div class="mk-vinyl" />
              <div class="mk-line w60" />
              <div class="mk-line w45" />
              <div class="mk-line w50" />
              <div class="mk-progress" />
              <div class="mk-btns"><i /><i /></div>
            </div>
            <div class="mk-miku">Miku</div>
            <div class="crop-pos">宽 {{ (cropW * 100).toFixed(0) }}% · 中心 {{ (cx * 100).toFixed(0) }}%·{{ (cy * 100).toFixed(0) }}%</div>
          </div>
          <div class="crop-sliders">
            <label class="cs-row">
              <span class="cs-label">缩放</span>
              <input v-model.number="zoom" type="range" min="100" max="400" step="1" class="cs-slider" />
              <span class="cs-val">{{ zoom.toFixed(0) }}%</span>
            </label>
            <label class="cs-row">
              <span class="cs-label">横向</span>
              <input v-model.number="sliderX" type="range" min="0" max="100" step="0.5" class="cs-slider" />
              <span class="cs-val">{{ sliderX.toFixed(0) }}%</span>
            </label>
            <label class="cs-row">
              <span class="cs-label">纵向</span>
              <input v-model.number="sliderY" type="range" min="0" max="100" step="0.5" class="cs-slider" />
              <span class="cs-val">{{ sliderY.toFixed(0) }}%</span>
            </label>
          </div>
          <div class="crop-actions">
            <button class="btn ghost" @click="previewEntry = null">取消</button>
            <button class="btn" @click="applyCrop">使用这个取景</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.bgm-mask {
  position: fixed; inset: 0; z-index: 120;
  background: rgba(6, 10, 16, 0.55);
  display: flex; align-items: center; justify-content: center;
}
.bgm {
  width: 620px; max-width: 92vw; max-height: 84vh;
  background: color-mix(in srgb, var(--bg-panel) 94%, transparent);
  backdrop-filter: var(--blur);
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 18px;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.55);
  padding: 20px 22px;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.bgm-head { display: flex; align-items: center; justify-content: space-between; }
.bgm-title { font-size: 16px; font-weight: 600; color: var(--text-hi); letter-spacing: 2px; }
.x {
  width: 30px; height: 30px; border-radius: 8px; border: none;
  background: transparent; color: var(--text-lo); cursor: pointer; font-size: 13px;
}
.x:hover { background: rgba(255, 255, 255, 0.06); color: var(--text-hi); }

.drop {
  margin-top: 16px;
  border: 1.5px dashed rgba(255, 255, 255, 0.18);
  border-radius: 12px;
  padding: 18px;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-lo);
  cursor: pointer;
  transition: all 220ms;
}
.drop:hover, .drop.over { border-color: var(--accent-dim); background: rgba(255, 255, 255, 0.04); color: var(--text-hi); }
.err { margin-top: 8px; font-size: 12px; color: #d98a9e; }

.grid {
  margin-top: 14px;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  overflow-y: auto;
  padding: 2px;
}
.cell {
  position: relative;
  border-radius: 12px;
  border: 2px solid transparent;
  background: rgba(255, 255, 255, 0.03);
  cursor: pointer;
  transition: all 200ms;
  overflow: hidden;
}
.cell:hover { background: rgba(255, 255, 255, 0.06); }
.cell.on { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent); }
.thumb { height: 96px; overflow: hidden; }
.thumb img, .thumb video { width: 100%; height: 100%; object-fit: cover; display: block; }
.def-tag {
  position: absolute; top: 6px; left: 6px;
  padding: 1px 8px; border-radius: 999px;
  font-size: 10px; letter-spacing: 1px;
  background: rgba(22, 32, 44, 0.75); color: #e8ecf4;
}
.meta {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 10px 9px;
}
.name {
  flex: 1; min-width: 0;
  font-size: 12.5px; color: var(--text-hi);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.ext {
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 6px;
  letter-spacing: 0.5px;
}
.ext[data-ext="mp4"] { color: #9ec3e8; background: rgba(120, 170, 220, 0.14); }
.ext[data-ext="gif"] { color: #e8b48a; background: rgba(230, 170, 110, 0.14); }
.ext[data-ext="png"] { color: #a8d8b0; background: rgba(140, 210, 150, 0.14); }
.ext[data-ext="jpeg"], .ext[data-ext="jpg"] { color: #d8a8c8; background: rgba(220, 160, 200, 0.14); }
.ext[data-ext="webp"] { color: #b8c8e8; background: rgba(150, 175, 230, 0.14); }
.rename-input {
  flex: 1; min-width: 0;
  padding: 3px 7px;
  border-radius: 7px;
  border: 1px solid var(--accent-dim);
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-hi);
  font-size: 12.5px; font-family: inherit; outline: none;
}
.cell-ops {
  position: absolute; top: 6px; right: 6px;
  display: flex; gap: 4px;
  opacity: 0; transition: opacity 180ms;
}
.cell:hover .cell-ops { opacity: 1; }
.op {
  width: 24px; height: 24px; border-radius: 7px; border: none;
  background: rgba(22, 32, 44, 0.8); color: #c9d4e8;
  font-size: 11px; cursor: pointer;
}
.op:hover { background: rgba(40, 56, 76, 0.9); }
.op.danger:hover { background: rgba(120, 50, 65, 0.9); }

.bgm-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.btn {
  padding: 8px 20px; border-radius: 10px; border: none;
  background: var(--accent); color: #141824;
  font-size: 13px; font-weight: 600; cursor: pointer;
  font-family: inherit; transition: all 200ms;
}
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn.ghost { background: transparent; color: var(--text-lo); border: 1px solid rgba(255, 255, 255, 0.12); font-weight: 400; }
.btn.ghost:hover { color: var(--text-hi); }

.preview-mask {
  position: fixed; inset: 0; z-index: 130;
  background: rgba(4, 7, 12, 0.82);
  display: flex; align-items: center; justify-content: center;
}
.crop-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: stretch;
}
.crop-stage {
  position: relative;
  max-width: 92vw;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.6);
}
.crop-media {
  position: absolute;
  max-width: none;
  max-height: none;
  object-fit: fill;
  user-select: none;
  pointer-events: none;
}
.crop-scrim {
  position: absolute; inset: 0; pointer-events: none;
  background: linear-gradient(to right,
    rgba(247, 250, 252, 0.97) 0%,
    rgba(247, 250, 252, 0.94) 30%,
    rgba(247, 250, 252, 0.55) 46%,
    rgba(247, 250, 252, 0) 62%);
}
.crop-pos {
  position: absolute; right: 14px; top: 12px;
  font-size: 11.5px; color: #55707f;
  background: rgba(255, 255, 255, 0.7);
  padding: 3px 10px; border-radius: 8px;
  pointer-events: none;
}
.crop-sliders { display: flex; flex-direction: column; gap: 8px; }
.cs-row { display: flex; align-items: center; gap: 10px; }
/* 主页组件 mock（构图预览用，简化版） */
.mock-panel { position: absolute; left: 6%; top: 9%; pointer-events: none; }
.mk-badge {
  display: inline-block; padding: 4px 10px;
  background: #16202c; color: #f2f6fa;
  font-size: 10px; letter-spacing: 3px; border-radius: 3px;
}
.mk-title {
  margin-top: 10px; font-family: Georgia, serif;
  font-size: 52px; font-weight: 600; color: #5d93ad; letter-spacing: 2px;
}
.mk-vinyl {
  margin-top: 18px; margin-left: 60px;
  width: 180px; height: 180px; border-radius: 50%;
  background: repeating-radial-gradient(circle, #11161d 0 1.6px, #1d2530 1.6px 3.1px);
  box-shadow: 0 10px 26px rgba(28, 43, 58, 0.35);
}
.mk-line { height: 9px; border-radius: 5px; background: rgba(93, 130, 150, 0.35); margin-top: 12px; }
.mk-line.w60 { width: 60%; }
.mk-line.w45 { width: 45%; }
.mk-line.w50 { width: 50%; }
.mk-progress {
  margin-top: 20px; width: 70%; height: 5px; border-radius: 3px;
  background: linear-gradient(90deg, #7fb3c8 60%, rgba(93,147,173,0.2) 60%);
}
.mk-btns { margin-top: 14px; display: flex; gap: 10px; }
.mk-btns i {
  width: 30px; height: 30px; border-radius: 50%;
  border: 1px solid rgba(93, 147, 173, 0.4);
  background: rgba(255, 255, 255, 0.55);
}
.mk-miku {
  position: absolute; right: 0; bottom: 0;
  width: 21%; height: 72%;
  border: 1.5px dashed rgba(93, 147, 173, 0.55);
  border-radius: 12px 12px 0 0;
  color: rgba(93, 147, 173, 0.8);
  font-size: 12px; letter-spacing: 2px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(127, 179, 200, 0.08);
  pointer-events: none;
}
.cs-label { font-size: 12px; color: var(--text-lo); width: 28px; flex-shrink: 0; }
.cs-val { font-size: 11.5px; color: var(--text-lo); width: 36px; text-align: right; flex-shrink: 0; }
.cs-slider {
  flex: 1;
  appearance: none;
  height: 4px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.14);
  outline: none;
  cursor: pointer;
}
.cs-slider::-webkit-slider-thumb {
  appearance: none;
  width: 14px; height: 14px; border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 1px 5px rgba(0, 0, 0, 0.4);
}
.crop-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.fade-enter-active, .fade-leave-active { transition: opacity 260ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
