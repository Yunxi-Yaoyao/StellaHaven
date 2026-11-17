<script setup lang="ts">
// 主页背景附件管理浮窗：拖拽上传 / 缩略图网格 / 单击选中 / 双击进裁剪预览 / 重命名 / 删除（默认不可删）
// 裁剪模型 = 源图分数区域（cx,cy 中心 + w,h 宽高），渲染时 cover-fit 铺满——窗口 resize 内容不散。
import { ref, computed, watch, effectScope, onBeforeUnmount, onDeactivated, onActivated, nextTick } from "vue";
import { bgManagerOpen, homeSettings, homeSaveErrors, siteBackground, type BgCrop } from "./settings";
import { auth, displayBg } from "./auth";

import { backgroundEntries, invalidateBackgroundEntries, backgroundMedia, backgroundThumbnail, storeBackgroundMedia, useBackgroundMedia, optimizeBackground, type BackgroundEntry as BgEntry } from "./backgroundMedia";
// The same manager operates either on the home preference or as a controlled,
// draft-only picker. Teleport inside the caller's native dialog top layer.
const props = withDefaults(defineProps<{ picker?: boolean; open?: boolean; selectedUrl?: string; protectedUrls?: string[]; teleportTo?: string | HTMLElement }>(), { picker: false, open: false, selectedUrl: '', protectedUrls: () => [], teleportTo: 'body' });
const emit = defineEmits<{ pick: [url: string]; close: [] }>();
const visible = computed(() => props.picker ? props.open : bgManagerOpen.value);
function closeManager() { if (props.picker) emit('close'); else bgManagerOpen.value = false; }
function deleteProtected(e: BgEntry) {
  if (e.isDefault || e.isSystem) return true;
  if (!props.picker) return false;
  // current_user is the single pinned owner. Shared/unknown ownership is never
  // deletion authority; preserve home/site and saved/current navigation refs.
  return e.owner !== auth.me?.id || [displayBg.value, auth.me?.home_bg, siteBackground.value, homeSettings.bgImage, ...props.protectedUrls].includes(e.url);
}
function pickDraft(e: BgEntry) {
  if (locked.value || !fence()()) return;
  emit('pick', e.url); closeManager();
}
const failedThumbnails = ref<Record<string, boolean>>({});
const list = backgroundEntries;
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

let lifecycle = 0;
let active = true;
function fence() {
  const generation = lifecycle, owner = auth.me?.id, session = auth.sessionGeneration, epoch = auth.requestEpoch;
  return () => active && generation === lifecycle && !!owner && owner === auth.me?.id && session === auth.sessionGeneration && epoch === auth.requestEpoch && !auth.sessionClosing && !auth.suspended;
}
onBeforeUnmount(() => { active = false; lifecycle++; });
onDeactivated(() => { active = false; lifecycle++; saving.value = false; });
onActivated(() => { active = true; });

const { source: previewSource, media: previewMedia } = useBackgroundMedia(computed(() => previewEntry.value?.url || ""));
let loadSequence = 0;
const loadError = ref(false);
async function readEntries(): Promise<BgEntry[]> {
  const r = await fetch('/homebg/');
  if (!r.ok) throw await responseError(r);
  const entries = await r.json();
  if (!Array.isArray(entries) || entries.some(e => !e || typeof e.id !== 'string' || typeof e.url !== 'string' || typeof e.name !== 'string')) throw new Error('图库返回不完整，尚未确认');
  return entries;
}
function publishEntries(entries: BgEntry[]) {
  loadSequence++; invalidateBackgroundEntries();
  list.value = entries;
  for (const e of entries) if (e.media) storeBackgroundMedia(e.media);
}
async function load() {
  const current = fence(), sequence = ++loadSequence;
  loadError.value = false;
  try {
    const entries = await readEntries();
    if (!current() || sequence !== loadSequence) return;
    publishEntries(entries);
    if (!selectedId.value) selectedId.value = list.value.find(e => e.url === (props.picker ? props.selectedUrl : displayBg.value))?.id ?? null;
  } catch (e) { if (current() && sequence === loadSequence) { loadError.value = true; errorMsg.value = e instanceof Error ? e.message : '图库加载失败'; } }
}
// Do not erase a failed draft/receipt when the user returns to the gallery.
watch(visible, v => { if (v) void load(); }, { immediate: true });
// Grid entries are active consumers only while visible; no media element downloads.
watch(() => visible.value ? list.value.map(e => e.url) : [], (urls, _, cleanup) => {
  const scope = effectScope();
  scope.run(() => { for (const url of urls) useBackgroundMedia(computed(() => url)); });
  cleanup(() => scope.stop());
}, { immediate: true });

function select(e: BgEntry) {
  if (locked.value || renamingId.value) return;
  selectedId.value = e.id;
}

async function upload(files: FileList | File[]) {
  if (locked.value || renamingId.value || !auth.me || auth.suspended || auth.sessionClosing) return;
  const current = fence();
  errorMsg.value = "";
  for (const f of Array.from(files)) {
    if (!current()) return;
    const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
    if (!["jpg", "jpeg", "png", "webp", "gif", "mp4"].includes(ext)) {
      errorMsg.value = `「${f.name}」格式不支持（仅 jpg/png/webp/gif/mp4）`;
      continue;
    }
    uploading.value = true;
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await fetch("/homebg/upload", { method: "POST", body: fd });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail ?? String(r.status));
      }
      const entry: BgEntry = await r.json();
      if (!current()) return;
      // The upload receipt supersedes both local and shared in-flight lists.
      publishEntries([...list.value.filter(e => e.id !== entry.id), entry]);
      selectedId.value = entry.id;
    } catch (e) { if (current()) errorMsg.value = `「${f.name}」上传未确认：${e instanceof Error ? e.message : "网络错误"}。请重新打开图库核对后再上传，避免重复。`; }
    finally { if (current()) uploading.value = false; }
  }
}

function onDrop(e: DragEvent) {
  dragOver.value = false;
  if (e.dataTransfer?.files?.length) upload(e.dataTransfer.files);
}

/* ── 裁剪预览 ── */
function openPreview(e: BgEntry) {
  if (locked.value || renamingId.value) return;
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
  // Prefer original metadata; variants retain the original aspect ratio.
  nat.value = { w: 0, h: 0 };
  const m = previewMedia.value;
  if (m?.width && m?.height) {
    nat.value = { w: m.width, h: m.height };
    initFromSettings();
  }

}

function previewLoaded(event: Event) {
  if (nat.value.w) return;
  const el = event.target;
  const m = previewMedia.value;
  if (m?.width && m?.height) nat.value = { w: m.width, h: m.height };
  else if (el instanceof HTMLVideoElement) nat.value = { w: el.videoWidth, h: el.videoHeight };
  else if (el instanceof HTMLImageElement) nat.value = { w: el.naturalWidth, h: el.naturalHeight };
  initFromSettings();
}
function initFromSettings() {
  const c = props.picker ? undefined : homeSettings.bgCrop;
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
  if (props.picker) return { width: "100%", height: "100%", left: "0", top: "0", objectFit: "contain" as const };
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

const saving = ref(false);
const pendingPick = ref<{ url: string; crop?: BgCrop; acknowledged: boolean; phase: 'write' | 'read' | 'local'; serverValue?: NonNullable<typeof auth.me> } | null>(null);
watch([() => auth.me?.id, () => auth.sessionGeneration, () => auth.requestEpoch, () => auth.sessionClosing, () => auth.suspended], () => {
  lifecycle++; loadSequence++; saving.value = false; pendingPick.value = null; libraryOperation.value = null; deleteTarget.value = null; uploading.value = false;
  previewEntry.value = null; renamingId.value = null; renameDraft.value = ''; selectedId.value = null; errorMsg.value = '';
}, { flush: 'sync' });
async function responseError(r: Response) {
  const body = await r.json().catch(() => ({}));
  return new Error(body.detail || `请求失败 (${r.status})`);
}
async function saveMyBg(url: string, crop?: BgCrop) {
  if (saving.value || !auth.me || auth.suspended || auth.sessionClosing) return false;
  const current = fence();
  const op = pendingPick.value ||= { url, crop, acknowledged: false, phase: 'write' };
  op.serverValue = undefined;
  saving.value = true; errorMsg.value = '';
  try {
    if (op.phase === 'write') {
      // A response may be lost after commit: recover through GET, never blind PATCH.
      op.phase = 'read'; loadSequence++;
      const r = await fetch('/auth/me', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ home_bg: op.url }) });
      if (!current()) return false;
      if (!r.ok) {
        if (r.status >= 400 && r.status < 500 && ![408,409].includes(r.status)) op.phase = 'write';
        throw await responseError(r);
      }
      op.acknowledged = true;
    }
    if (op.phase === 'read') {
      const r = await fetch('/auth/me');
      if (!r.ok) throw await responseError(r);
      const me = await r.json();
      if (!current()) return false;
      if (me?.id !== auth.me?.id) throw new Error('账号不匹配，未应用背景');
      if (typeof me.home_bg !== 'string') throw new Error('背景返回不完整，尚未确认');
      if (me.home_bg !== op.url) {
        op.serverValue = me;
        if (!op.acknowledged) op.phase = 'write';
        throw new Error('背景尚未确认，选择已保留');
      }
      auth.me = me;
      op.phase = 'local';
    }
    if (!current()) return false;
    if (op.crop) {
      // The existing crop is device-scoped. Do not publish it until disk readback.
      const value = JSON.stringify(op.crop);
      try {
        localStorage.setItem('stella_home_bgcrop', value);
        if (localStorage.getItem('stella_home_bgcrop') !== value) throw new Error('readback mismatch');
      } catch { throw new Error('账号背景已保存，但取景未保存到当前设备；取景已保留，请重试本地保存。'); }
      homeSettings.bgCrop = { ...op.crop };
      await nextTick();
      if (!current()) return false;
      if (homeSaveErrors.bgCrop) throw new Error(homeSaveErrors.bgCrop);
    }
    pendingPick.value = null;
    previewEntry.value = null;
    bgManagerOpen.value = false;
    return true;
  } catch (e) {
    if (current()) errorMsg.value = e instanceof Error ? e.message : '保存失败，选择已保留';
    return false;
  } finally { if (current()) saving.value = false; }
}
const pickRetryLabel = computed(() => pendingPick.value?.phase === 'local' ? '重试本地保存' : pendingPick.value?.phase === 'read' ? '重试确认' : '重试保存');
async function retryPick() { if (pendingPick.value) await saveMyBg(pendingPick.value.url); }

async function applyCrop() {
  const e = previewEntry.value;
  if (props.picker) { if (e) pickDraft(e); return; }
  if (e) await saveMyBg(e.url, { cx: cx.value, cy: cy.value, w: cropW.value, h: cropH.value });
}

async function confirmPick() {
  const e = list.value.find((x) => x.id === selectedId.value);
  if (props.picker) { if (e) pickDraft(e); return; }
  if (e) await saveMyBg(e.url);
}

type LibraryOperation = { kind: 'rename' | 'delete'; id: string; url: string; name: string; phase: 'write' | 'read'; acknowledged: boolean; serverEntries?: BgEntry[] };
const libraryOperation = ref<LibraryOperation | null>(null);
const deleteTarget = ref<BgEntry | null>(null);
const deletePanel = ref<HTMLElement>();
const locked = computed(() => saving.value || uploading.value || !!pendingPick.value || !!libraryOperation.value);
const libraryRetryLabel = computed(() => libraryOperation.value?.phase === 'read' ? '重试确认' : libraryOperation.value?.kind === 'delete' ? '确认删除' : '重试重命名');
function startRename(e: BgEntry) {
  if (locked.value || renamingId.value && renamingId.value !== e.id) return;
  renamingId.value = e.id;
  renameDraft.value = e.name;
}
async function commitRename(e: BgEntry) {
  if (locked.value) return;
  const name = renameDraft.value.trim();
  if (!name) { errorMsg.value = '名称不能为空，输入已保留'; return; }
  if (name === e.name) { renamingId.value = null; return; }
  libraryOperation.value = { kind:'rename', id:e.id, url:e.url, name, phase:'write', acknowledged:false };
  await runLibraryOperation();
}
async function runLibraryOperation() {
  const op = libraryOperation.value;
  if (!op || saving.value || !auth.me || auth.sessionClosing || auth.suspended) return;
  const current = fence();
  op.serverEntries = undefined;
  saving.value = true; errorMsg.value = ''; loadSequence++; invalidateBackgroundEntries();
  try {
    if (op.phase === 'write') {
      op.phase = 'read';
      const r = await fetch(`/homebg/${encodeURIComponent(op.id)}`, op.kind === 'delete' ? {method:'DELETE'} : {
        method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:op.name}),
      });
      if (!current()) return;
      if (!r.ok) {
        if (r.status >= 400 && r.status < 500 && ![404,408,409].includes(r.status)) op.phase = 'write';
        throw await responseError(r);
      }
      op.acknowledged = true;
    }
    const entries = await readEntries();
    if (!current()) return;
    const target = entries.find(e => e.id === op.id);
    const verified = op.kind === 'delete' ? !target : target?.name === op.name && target.url === op.url;
    if (!verified) {
      // A confirmed write is never replayed because of a failed/eventually stale GET.
      if (op.kind === 'rename') op.serverEntries = entries;
      if (!op.acknowledged) op.phase = 'write';
      throw new Error(op.kind === 'delete' ? '目标仍存在，尚未确认删除。请核对后再确认。' : '名称尚未确认，输入已保留。');
    }
    publishEntries(entries);
    if (op.kind === 'delete') {
      if (selectedId.value === op.id) selectedId.value = list.value[0]?.id ?? null;
      deleteTarget.value = null;
    } else if (renameDraft.value.trim() === op.name) { renamingId.value = null; renameDraft.value = ''; }
    libraryOperation.value = null;
  } catch (e) {
    if (current()) errorMsg.value = `${e instanceof Error ? e.message : '操作失败'}${op.phase === 'read' ? '；结果待确认，重试只读取状态。' : ''}`;
  } finally { if (current()) saving.value = false; }
}
const canEditRejected = computed(() => !saving.value && (pendingPick.value?.phase === 'write' || libraryOperation.value?.kind === 'rename' && libraryOperation.value.phase === 'write'));
const canUseServer = computed(() => !saving.value && !!(pendingPick.value?.serverValue || libraryOperation.value?.serverEntries));
function useServerCurrent() {
  if (!canUseServer.value || !auth.me || auth.suspended || auth.sessionClosing) return;
  const me = pendingPick.value?.serverValue;
  // Explicitly discard the frozen choice, not a confirmation of its old write.
  // The crop belongs to this device: do not apply the abandoned crop intent.
  if (me) {
    if (me.id !== auth.me.id) return;
    auth.me = me;
    pendingPick.value = null; previewEntry.value = null;
    selectedId.value = list.value.find(e => e.url === me.home_bg)?.id ?? null;
  } else if (libraryOperation.value?.serverEntries) {
    publishEntries(libraryOperation.value.serverEntries);
    libraryOperation.value = null; renamingId.value = null; renameDraft.value = ''; deleteTarget.value = null;
    if (!list.value.some(e => e.id === selectedId.value)) selectedId.value = null;
  }
  errorMsg.value = '';
}
function editRejected() {
  if (!canEditRejected.value) return;
  pendingPick.value = null; libraryOperation.value = null; errorMsg.value = '';
}
async function retryLibrary() {
  const op = libraryOperation.value;
  if (op?.kind === 'delete' && op.phase === 'write' && !deleteTarget.value) {
    deleteTarget.value = { id:op.id, url:op.url, name:op.name, isDefault:false, ext:'' };
    await nextTick(); deletePanel.value?.focus();
    return;
  }
  await runLibraryOperation();
}
async function remove(e: BgEntry) {
  if (deleteProtected(e) || locked.value || renamingId.value) return;
  deleteTarget.value = { ...e };
  errorMsg.value = '';
  await nextTick(); deletePanel.value?.focus();
}
async function confirmDelete() {
  const e = deleteTarget.value;
  if (!e || deleteProtected(e) || saving.value) return;
  libraryOperation.value ||= { kind:'delete', id:e.id, url:e.url, name:e.name, phase:'write', acknowledged:false };
  await runLibraryOperation();
}
function closeDelete() {
  if (saving.value) return;
  deleteTarget.value = null;
  if (libraryOperation.value?.phase === 'write') { libraryOperation.value = null; errorMsg.value = ''; }
  void nextTick(() => document.querySelector<HTMLButtonElement>('.bgm .x')?.focus());
}
function deleteKeys(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeDelete(); }
  if (event.key !== 'Tab') return;
  const buttons = Array.from(deletePanel.value?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || []);
  const first = buttons[0], last = buttons[buttons.length - 1];
  if (event.shiftKey && (document.activeElement === first || document.activeElement === deletePanel.value)) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
}
</script>

<template>
  <Teleport :to="teleportTo">
    <Transition name="fade">
      <div v-if="visible" class="bgm-mask" :data-home-theme="homeSettings.theme" @click.self="closeManager">
        <div class="bgm" :class="{ 'is-picker': picker }" :inert="!!previewEntry || !!deleteTarget" @dragover.prevent="dragOver = true" @dragleave="dragOver = false" @drop.prevent="onDrop">
          <div class="bgm-head">
            <div class="bgm-title">{{ picker ? "选择导航背景" : "背景图库" }}</div>
            <button type="button" class="x" title="关闭" @click="closeManager">✕</button>
          </div>

          <p v-if="picker" class="picker-hint">选择仅改导航草稿，不更改主页或取景。上传、重命名、删除会立即修改共享图库，取消导航设置不会撤销这些操作。</p>
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
          <div v-if="errorMsg && !previewEntry && !deleteTarget" class="err" role="alert">{{ errorMsg }}
            <button type="button" v-if="pendingPick" class="btn ghost" :disabled="saving" @click="retryPick">{{ pickRetryLabel }}</button>
            <button type="button" v-else-if="libraryOperation" class="btn ghost" :disabled="saving" @click="retryLibrary">{{ libraryRetryLabel }}</button>
            <button type="button" v-else-if="loadError" class="btn ghost" @click="load">重试加载</button>
            <button type="button" v-if="canEditRejected" class="btn ghost" @click="editRejected">继续修改</button>
            <button type="button" v-if="canUseServer" class="btn ghost" title="放弃这次修改，采用最近成功读取的服务器状态；不会重新发送修改" @click="useServerCurrent">采用服务器当前值</button>
          </div>

          <!-- 缩略图网格 -->
          <div class="grid">
            <div
              v-for="e in list"
              :key="e.id"
              class="cell"
              :class="{ on: selectedId === e.id, editing: renamingId === e.id }"
              @click="select(e)"
              @dblclick="openPreview(e)"
            >
              <div class="thumb">
                <img v-if="backgroundThumbnail(e.url) && !failedThumbnails[e.url]" :src="backgroundThumbnail(e.url)" :alt="e.name" loading="lazy" @error="picker && (failedThumbnails[e.url] = true)"/>
                <button v-else-if="picker && failedThumbnails[e.url]" type="button" class="thumb-placeholder thumb-retry" @click.stop="delete failedThumbnails[e.url]">缩略图加载失败 · 重试</button>
                <span v-else class="thumb-placeholder">{{ isVideo(e) ? '视频 · 暂无缩略图' : '暂无缩略图' }}</span>
                <span v-if="e.isDefault" class="def-tag">默认</span>
              </div>
              <div class="meta">
                <input
                  v-if="renamingId === e.id"
                  v-model="renameDraft"
                  class="rename-input"
                  autofocus
                  :readonly="!!libraryOperation"
                  @keydown.enter="commitRename(e)"
                  @keydown.esc.stop="!locked && (renamingId = null)"
                  @click.stop
                  @dblclick.stop
                />
                <span v-else class="name" :title="e.name" @dblclick.stop="startRename(e)">{{ e.name }}</span>
                <span class="ext" :data-ext="e.ext">[{{ e.ext }}]</span>
              </div>
              <div v-if="['queued', 'processing'].includes(backgroundMedia[e.url]?.status || '')" class="media-status" role="status">处理中…</div>
              <div v-if="backgroundMedia[e.url]?.status === 'error'" class="media-status" role="alert">
                {{ backgroundMedia[e.url]?.error || '处理失败' }}
                <button type="button" class="btn ghost" @click.stop="optimizeBackground(e.url)">重试</button>
              </div>
              <div v-if="renamingId === e.id" class="rename-actions" @click.stop>
                <button type="button" class="btn ghost" :disabled="locked" @click="commitRename(e)">保存名称</button>
                <button type="button" class="btn ghost" :disabled="locked" @click="renamingId = null">取消</button>
              </div>
              <div class="cell-ops">
                <button type="button" class="op" :disabled="locked" title="重命名" @click.stop="startRename(e)">✎</button>
                <button type="button" v-if="!e.isDefault" :disabled="locked || !!renamingId || deleteProtected(e)" class="op danger" title="删除" @click.stop="remove(e)">🗑</button>
              </div>
            </div>
          </div>

          <div class="bgm-foot">
            <button type="button" class="btn ghost" @click="closeManager">取消</button>
            <button type="button" class="btn" :disabled="!selectedId || locked || !!renamingId" @click="confirmPick">{{ saving ? '保存中…' : picker ? '选择此背景' : '确定更换' }}</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 双击 = 裁剪预览：盖主页同款遮罩 + 组件 mock，滑杆/拖动调整「源图区域」 -->
    <Transition name="fade">
      <div v-if="visible && previewEntry" class="preview-mask" :data-home-theme="homeSettings.theme">
        <div class="crop-wrap" :style="{ width: stage.w + 'px' }">
          <div class="crop-stage" :style="{ width: stage.w + 'px', height: stage.h + 'px' }">
            <video
              v-if="isVideo(previewEntry)"
              class="crop-media"
              :src="previewSource"
              :style="mediaStyle"
              :poster="previewMedia?.poster || undefined" @loadedmetadata="previewLoaded"
              autoplay muted loop playsinline
            />
            <img v-else class="crop-media" :src="previewSource" :style="mediaStyle" alt="" @load="previewLoaded" />
            <div v-if="!picker" class="crop-scrim" />
            <!-- 主页组件 mock：构图预览用 -->
            <div v-if="!picker" class="mock-panel">
              <div class="mk-badge">云曦 · YUNXI'S</div>
              <div class="mk-title">StellaHaven</div>
              <div class="mk-vinyl" />
              <div class="mk-line w60" />
              <div class="mk-line w45" />
              <div class="mk-line w50" />
              <div class="mk-progress" />
              <div class="mk-btns"><i /><i /></div>
            </div>
            <div v-if="!picker" class="mk-miku">Miku</div>
            <div v-if="!picker" class="crop-pos">宽 {{ (cropW * 100).toFixed(0) }}% · 中心 {{ (cx * 100).toFixed(0) }}%·{{ (cy * 100).toFixed(0) }}%</div>
          </div>
          <div v-if="!picker" class="crop-sliders">
            <label class="cs-row">
              <span class="cs-label">缩放</span>
              <input v-model.number="zoom" :disabled="locked" type="range" min="100" max="400" step="1" class="cs-slider" />
              <span class="cs-val">{{ zoom.toFixed(0) }}%</span>
            </label>
            <label class="cs-row">
              <span class="cs-label">横向</span>
              <input v-model.number="sliderX" :disabled="locked" type="range" min="0" max="100" step="0.5" class="cs-slider" />
              <span class="cs-val">{{ sliderX.toFixed(0) }}%</span>
            </label>
            <label class="cs-row">
              <span class="cs-label">纵向</span>
              <input v-model.number="sliderY" :disabled="locked" type="range" min="0" max="100" step="0.5" class="cs-slider" />
              <span class="cs-val">{{ sliderY.toFixed(0) }}%</span>
            </label>
          </div>
          <div v-if="errorMsg" class="err" role="alert">{{ errorMsg }}
            <button type="button" v-if="pendingPick" class="btn ghost" :disabled="saving" @click="retryPick">{{ pickRetryLabel }}</button>
            <button type="button" v-if="canEditRejected" class="btn ghost" @click="editRejected">继续修改</button>
            <button type="button" v-if="canUseServer" class="btn ghost" title="放弃这次修改及未保存取景，不会重新发送修改" @click="useServerCurrent">采用服务器当前值</button>
          </div>
          <div class="crop-actions">
            <button type="button" class="btn ghost" @click="previewEntry = null">取消</button>
            <button type="button" class="btn" :disabled="locked" @click="applyCrop">{{ saving ? '保存中…' : picker ? '选择此背景' : '使用这个取景' }}</button>
          </div>
        </div>
      </div>
    </Transition>
    <!-- Same in-app modal/focus pattern as the note deletion confirmation. -->
    <div v-if="visible && deleteTarget" class="bgm-delete-mask" :data-home-theme="homeSettings.theme" @click.self="closeDelete">
      <section ref="deletePanel" class="bgm bgm-delete" role="dialog" aria-modal="true" aria-label="删除背景" tabindex="-1" @keydown="deleteKeys">
        <h3>删除背景</h3>
        <p>仅删除「{{ deleteTarget.name }}」这一项及其背景文件；不可恢复。不会删除其他背景。</p>
        <p v-if="picker">这是共享图库删除，不只是移除导航选择。此窗口已知的主页、站点背景及已保存/草稿引用已禁删；其他窗口的后续改动不在此检查内。删除后文件不可恢复，取消导航设置不会恢复文件。</p>
        <p v-if="errorMsg" class="err" role="alert">{{ errorMsg }}</p>
        <div class="bgm-foot">
          <button type="button" class="btn ghost" :disabled="saving" @click="closeDelete">{{ libraryOperation?.phase === 'read' ? '关闭' : '取消' }}</button>
          <button type="button" class="btn" :disabled="saving" @click="confirmDelete">{{ saving ? '处理中…' : libraryOperation ? libraryRetryLabel : '确认删除' }}</button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.bgm-delete-mask { position:fixed; inset:0; z-index:140; display:flex; align-items:center; justify-content:center; background:#04070cd9; }
.bgm-delete { width:420px; color:var(--text-hi); overflow-y:auto; }
.bgm-delete p { overflow-wrap:anywhere; line-height:1.65; }
.cell.editing { grid-column:1 / -1; }
.rename-actions { display:flex; flex-wrap:wrap; gap:4px; padding:4px; }
.rename-actions .btn { padding:5px 7px; font-size:11px; }
@media (hover:none) { .cell-ops { opacity:1 !important; } }

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

.thumb-retry { width:100%; border:0; background:transparent; cursor:pointer; padding:8px; }
@media(max-width:480px) {
  .bgm.is-picker .grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .bgm.is-picker .cell:has(.media-status[role="alert"]) { grid-column:1 / -1; }
}
.picker-hint { color:var(--text-lo); font-size:12px; line-height:1.6; margin:10px 0 0; }
.bgm-head, .drop, .bgm-foot { flex-shrink:0; }
.grid {
  min-height:0;
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
.thumb-placeholder { display: grid; place-items: center; height: 100%; font-size: 12px; color: var(--text-faint); }
.media-status { padding: 0 10px 8px; font-size: 11px; color: var(--text-lo); overflow-wrap: anywhere; }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
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
  max-width:92vw; max-height:92dvh; overflow-y:auto; padding:2px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: stretch;
}
.crop-stage {
  flex-shrink:0;
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
/* Keep the existing light preview for daybreak/coastline. Dark home themes
   carry their local palette through both Teleports without recoloring the shell. */
.preview-mask:is([data-home-theme="nightfall"], [data-home-theme="classic"]) .crop-scrim {
  background: linear-gradient(to right, var(--bg-base), color-mix(in srgb, var(--bg-base) 94%, transparent) 30%, color-mix(in srgb, var(--bg-base) 55%, transparent) 60%, transparent);
}
.preview-mask:is([data-home-theme="nightfall"], [data-home-theme="classic"]) .crop-pos { background:var(--bg-panel); color:var(--text-lo); }
.preview-mask:is([data-home-theme="nightfall"], [data-home-theme="classic"]) .mk-title { color:var(--accent); }
.preview-mask:is([data-home-theme="nightfall"], [data-home-theme="classic"]) .mk-badge { background:var(--home-warm); color:var(--bg-base); }
.preview-mask:is([data-home-theme="nightfall"], [data-home-theme="classic"]) .mk-line { background:color-mix(in srgb, var(--accent) 35%, transparent); }
.preview-mask:is([data-home-theme="nightfall"], [data-home-theme="classic"]) .mk-miku { color:var(--text-lo); border-color:var(--accent-dim); }
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
