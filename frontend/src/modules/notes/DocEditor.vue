<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, toRef } from "vue";
import { marked } from "marked";
import {
  getDoc, updateDoc, getDraft, type Doc,
} from "../../api/notes";
import { ApiError } from "../../api/client";
import { useDraftSocket, getDeviceName, setDeviceName, getIpInfo } from "../../composables/useDraftSocket";
import { useNotesStore } from "../../stores/notes";

const props = defineProps<{ docId: string }>();
const emit = defineEmits<{ saved: []; deleted: [] }>();

// 设备标签 = 设备名 · 公网IP · 地区（IP/地区异步查到后补上，缓存24h）
const deviceLabel = ref(getDeviceName());
function deviceNameOnly() {
  return deviceLabel.value.split(" · ")[0];
}
async function refreshDeviceLabel() {
  const info = await getIpInfo();
  deviceLabel.value = info
    ? `${deviceNameOnly()} · ${info.ip} · ${info.region}`
    : deviceNameOnly();
}
refreshDeviceLabel();

function renameDevice() {
  const name = prompt("给这台设备起个名字（会显示在草稿提示里）", deviceNameOnly());
  if (name?.trim()) {
    setDeviceName(name.trim());
    deviceLabel.value = name.trim();
    refreshDeviceLabel(); // 重新组合 IP+地区
  }
}

const doc = ref<Doc | null>(null);
const title = ref("");
const content = ref("");
const savedTitle = ref("");
const savedContent = ref("");
const mode = ref<"edit" | "split" | "preview">("split");
const statusText = ref("");
const conflictHint = ref("");

// 草稿提示条
const draftBanner = ref<{ device: string | null; updatedAt: string } | null>(null);
const draftPreview = ref<string | null>(null);

// 「忽略」持久化：按 文档+草稿时间戳 记住「这一版草稿别再提醒了」
// 草稿更新（新时间戳）后会重新提醒——忽略的是这一版，不是永远
const DISMISS_KEY = "stella_draft_dismissed";
function getDismissed(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(DISMISS_KEY) || "{}");
  } catch {
    return {};
  }
}
function isDismissed(docId: string, draftUpdatedAt: string): boolean {
  return getDismissed()[docId] === draftUpdatedAt;
}

const dirty = computed(() => title.value !== savedTitle.value || content.value !== savedContent.value);
const rendered = computed(() => marked.parse(content.value || "") as string);

// ── 加载文档 ──
async function load(id: string) {
  doc.value = await getDoc(id);
  title.value = doc.value.title;
  content.value = doc.value.content || "";
  savedTitle.value = doc.value.title;
  savedContent.value = doc.value.content || "";
  statusText.value = "";
  conflictHint.value = "";
  draftPreview.value = null;
  draftBanner.value =
    doc.value.has_draft && !isDismissed(doc.value.id, doc.value.draft_updated_at!)
      ? { device: doc.value.draft_device, updatedAt: doc.value.draft_updated_at! }
      : null;
}

watch(() => props.docId, (id) => id && load(id), { immediate: true });

// ── 草稿：输入 debounce 2.5s → WS 覆写草稿槽 ──
// 只在「脏了」（有未保存修改）时才同步——加载文档触发的 content 变化不算
let draftTimer: ReturnType<typeof setTimeout> | null = null;
watch(content, () => {
  if (!doc.value) return;
  if (draftTimer) clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    if (dirty.value) sendDraft(content.value);
  }, 2500);
});

// 别的设备保存了 → 静默重拉（本地没脏改才直接覆盖，脏了提示）
function onRemoteSaved() {
  if (!doc.value) return;
  if (!dirty.value) {
    load(props.docId);
    statusText.value = "已从另一设备同步 ✓";
  } else {
    conflictHint.value = "另一设备保存了新版本，你有未保存的修改";
  }
}

const { sendDraft } = useDraftSocket(toRef(props, "docId"), deviceLabel, onRemoteSaved);

// ── 保存（手动，乐观锁）──
async function save() {
  if (!doc.value || !dirty.value) return;
  if (draftTimer) clearTimeout(draftTimer); // 保存成功后不再需要挂起的草稿同步
  try {
    const updated = await updateDoc(doc.value.id, doc.value.updated_at, {
      title: title.value,
      content: content.value,
    });
    doc.value = updated;
    savedTitle.value = updated.title;
    savedContent.value = updated.content || "";
    draftBanner.value = null; // 保存成功草稿槽已清
    statusText.value = "已保存 ✓ " + new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    conflictHint.value = "";
    emit("saved");
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      // 乐观锁兜底：静默重拉 DB（老婆定的：不弹打扰式提示）
      await load(props.docId);
      statusText.value = "版本冲突，已刷新为最新 ✓";
    } else {
      statusText.value = "保存失败，稍后再试";
    }
  }
}

// ── 草稿提示条动作 ──
async function viewDraft() {
  try {
    const d = await getDraft(props.docId);
    draftPreview.value = d.content;
  } catch {
    draftBanner.value = null; // 已过期
  }
}

async function adoptDraft() {
  try {
    const d = await getDraft(props.docId);
    content.value = d.content;
    draftPreview.value = null;
    draftBanner.value = null;
    await save(); // 采用 = 立刻落盘 + 清槽
  } catch {
    draftBanner.value = null;
  }
}

function dismissDraft() {
  // 记住「这版草稿我忽略了」——下次打开不再提醒，草稿更新后重新提醒
  if (doc.value?.draft_updated_at) {
    const m = getDismissed();
    m[doc.value.id] = doc.value.draft_updated_at;
    localStorage.setItem(DISMISS_KEY, JSON.stringify(m));
  }
  draftBanner.value = null;
  draftPreview.value = null;
}

// ── 删除 ──
async function remove() {
  if (!doc.value) return;
  await useNotesStore().remove(doc.value.id);
  emit("deleted");
}

// Ctrl+S
function onKey(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === "s") {
    e.preventDefault();
    save();
  }
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));

function fmtDraftTime(iso: string) {
  return new Date(iso).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
</script>

<template>
  <div class="editor" v-if="doc">
    <!-- 草稿提示条 -->
    <div v-if="draftBanner" class="draft-banner">
      <span>
        「{{ draftBanner.device || "某设备" }}」{{ fmtDraftTime(draftBanner.updatedAt) }} 有份未保存草稿
      </span>
      <button @click="viewDraft">查看</button>
      <button class="primary" @click="adoptDraft">采用并保存</button>
      <button @click="dismissDraft">忽略</button>
    </div>
    <!-- 草稿预览 -->
    <div v-if="draftPreview !== null" class="draft-preview">
      <div class="dp-head">草稿内容 <button @click="draftPreview = null">收起</button></div>
      <pre>{{ draftPreview }}</pre>
    </div>

    <!-- 冲突提示（本地脏时远端保存了） -->
    <div v-if="conflictHint" class="conflict-banner">⚠ {{ conflictHint }}</div>

    <div class="toolbar">
      <input v-model="title" class="title-input" placeholder="无标题" />
      <div class="actions">
        <div class="mode-switch">
          <button :class="{ on: mode === 'edit' }" @click="mode = 'edit'">编辑</button>
          <button :class="{ on: mode === 'split' }" @click="mode = 'split'">双栏</button>
          <button :class="{ on: mode === 'preview' }" @click="mode = 'preview'">预览</button>
        </div>
        <button class="save-btn" :disabled="!dirty" @click="save">
          {{ dirty ? "保存" : "已保存" }}
        </button>
        <button class="del-btn" @click="remove">删除</button>
      </div>
    </div>

    <div class="status-line">
      <span>{{ statusText }}</span>
      <span class="device" title="点击给这台设备起名" @click="renameDevice">{{ deviceLabel }}</span>
    </div>

    <div class="panes" :class="mode">
      <textarea
        v-show="mode !== 'preview'"
        v-model="content"
        class="input"
        placeholder="开始写…（输入停 2.5 秒自动存草稿，Ctrl+S 保存）"
      />
      <div v-show="mode !== 'edit'" class="preview markdown-body" v-html="rendered" />
    </div>
  </div>
</template>

<style scoped>
.editor {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-radius: 0 var(--radius) var(--radius) 0;
  overflow: hidden;
}

.draft-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  background: rgba(232, 160, 191, 0.08);
  border-bottom: 1px solid rgba(232, 160, 191, 0.25);
  font-size: 12.5px;
  color: var(--pink);
}
.draft-banner button {
  padding: 3px 12px;
  border-radius: 999px;
  border: 1px solid var(--pink);
  background: transparent;
  color: var(--pink);
  font-size: 11.5px;
  cursor: pointer;
}
.draft-banner button.primary { background: var(--pink); color: var(--bg-base); }
.draft-preview {
  padding: 12px 16px;
  background: var(--bg-raised);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  max-height: 200px;
  overflow-y: auto;
}
.dp-head { font-size: 12px; color: var(--text-lo); margin-bottom: 6px; display: flex; justify-content: space-between; }
.dp-head button { background: none; border: none; color: var(--accent); cursor: pointer; font-size: 12px; }
.draft-preview pre { white-space: pre-wrap; font-size: 12.5px; color: var(--text-lo); }

.conflict-banner {
  padding: 8px 16px;
  background: rgba(232, 160, 191, 0.1);
  color: var(--pink);
  font-size: 12.5px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.title-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-hi);
  font-size: 17px;
  font-weight: 600;
}
.actions { display: flex; gap: 8px; align-items: center; }
.mode-switch { display: flex; background: var(--bg-raised); border-radius: var(--radius-sm); padding: 2px; }
.mode-switch button {
  padding: 4px 12px;
  border: none;
  background: transparent;
  color: var(--text-lo);
  font-size: 12px;
  border-radius: 6px;
  cursor: pointer;
}
.mode-switch button.on { background: var(--bg-panel); color: var(--accent); }
.save-btn {
  padding: 6px 18px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: var(--bg-base);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity var(--transition);
}
.save-btn:disabled { opacity: 0.35; cursor: default; }
.del-btn {
  padding: 6px 12px;
  border: 1px solid var(--text-faint);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-lo);
  font-size: 12px;
  cursor: pointer;
}
.del-btn:hover { border-color: var(--pink); color: var(--pink); }

.status-line {
  display: flex;
  justify-content: space-between;
  padding: 4px 16px;
  font-size: 11px;
  color: var(--text-faint);
}
.status-line .device { cursor: pointer; }
.status-line .device:hover { color: var(--accent); }

.panes { flex: 1; display: flex; overflow: hidden; }
.input {
  flex: 1;
  resize: none;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-hi);
  padding: 16px;
  font-size: 14px;
  line-height: 1.8;
  font-family: "SF Mono", "JetBrains Mono", Consolas, monospace;
}
.panes.split .input { border-right: 1px solid rgba(255, 255, 255, 0.05); }
.preview {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

/* markdown 渲染样式（克制版） */
.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3) {
  color: var(--accent);
  margin: 18px 0 8px;
}
.markdown-body :deep(p) { margin: 8px 0; }
.markdown-body :deep(code) {
  background: var(--bg-raised);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12.5px;
}
.markdown-body :deep(pre) {
  background: var(--bg-base);
  padding: 12px 16px;
  border-radius: var(--radius-sm);
  overflow-x: auto;
  margin: 10px 0;
}
.markdown-body :deep(pre code) { background: none; padding: 0; }
.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--accent-dim);
  padding-left: 12px;
  color: var(--text-lo);
  margin: 10px 0;
}
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 22px; margin: 8px 0; }
.markdown-body :deep(a) { color: var(--pink); }
</style>
