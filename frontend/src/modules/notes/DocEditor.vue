<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, onUnmounted, toRef } from "vue";
import { marked } from "marked";
import {
  getDoc, updateDoc, getDraft, toggleFavorite, type Doc,
} from "../../api/notes";
import { api } from "../../api/client";
import { ApiError } from "../../api/client";
import { useDraftSocket, getDeviceName, setDeviceName, getIpInfo } from "../../composables/useDraftSocket";
import { useNotesStore } from "../../stores/notes";
import { toast } from "../../composables/useToast";
import Icon from "../../shell/Icon.vue";

const props = defineProps<{ docId: string }>();
const emit = defineEmits<{ saved: []; deleted: []; open: [id: string] }>();

// 设备标签 = 「IP-地区 来源」（来源 = 起过的名字或浏览器名；IP/地区异步查到后补上，缓存24h）
const deviceLabel = ref(getDeviceName());
async function refreshDeviceLabel() {
  const name = getDeviceName();
  const info = await getIpInfo();
  deviceLabel.value = info
    ? `${info.ip}-${info.region} ${name}`
    : name;
}
refreshDeviceLabel();

function renameDevice() {
  const name = prompt("给这个来源起个名字（如：苏菲 / 台式机）", localStorage.getItem("stella_device") || "");
  if (name?.trim()) {
    setDeviceName(name.trim());
    refreshDeviceLabel(); // 重新组合标签
  }
}

const doc = ref<Doc | null>(null);
const title = ref("");
const content = ref("");
const savedTitle = ref("");
const savedContent = ref("");
const reading = ref(false); // false=编辑（双栏） true=阅览（纯预览）

// 常驻状态条数据：保存时间 + 草稿暂存标记 + 相对时间 ticker
const savedAt = ref<string | null>(null);
const draftSynced = ref(false);
const nowTick = ref(Date.now());
let tickTimer: ReturnType<typeof setInterval> | null = null;

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

// 渲染时把 [[标题]] 转成可点链接
const rendered = computed(() => {
  let html = marked.parse(content.value || "") as string;
  html = html.replace(
    /\[\[([^\[\]]+)\]\]/g,
    '<a class="wikilink" data-title="$1">$1</a>'
  );
  return html;
});

// 点预览里的 wikilink → 跳目标页
function onPreviewClick(e: MouseEvent) {
  const a = (e.target as HTMLElement).closest(".wikilink") as HTMLElement | null;
  if (!a) return;
  const t = a.dataset.title;
  const target = store.docs.find((d) => d.title === t);
  if (target) emit("open", target.id);
  else toast(`没有找到「${t}」这篇笔记`);
}

// ── [[ 自动补全 ──
const inputEl = ref<HTMLTextAreaElement | null>(null);
const linkSuggests = ref<Doc[]>([]);
const suggestPos = ref<{ start: number; query: string } | null>(null);

function onInputForLinks() {
  const el = inputEl.value;
  if (!el) return;
  const before = content.value.slice(0, el.selectionStart);
  const m = before.match(/\[\[([^\[\]]*)$/);
  if (!m) {
    suggestPos.value = null;
    linkSuggests.value = [];
    return;
  }
  const q = m[1];
  suggestPos.value = { start: el.selectionStart - m[0].length, query: q };
  linkSuggests.value = store.docs
    .filter((d) => d.id !== props.docId && d.title.toLowerCase().includes(q.toLowerCase()))
    .slice(0, 6);
}

function pickLink(target: Doc) {
  const el = inputEl.value;
  if (!el || !suggestPos.value) return;
  const { start } = suggestPos.value;
  const afterCaret = content.value.slice(el.selectionStart);
  content.value = content.value.slice(0, start) + `[[${target.title}]]` + afterCaret;
  suggestPos.value = null;
  linkSuggests.value = [];
  // 光标归位到链接后
  const pos = start + target.title.length + 4;
  requestAnimationFrame(() => {
    el.focus();
    el.setSelectionRange(pos, pos);
  });
}

// ── 反链 ──
const backlinks = ref<Doc[]>([]);
async function loadBacklinks() {
  backlinks.value = await api<Doc[]>(`/documents/${props.docId}/backlinks`);
}

// 字数：CJK 每字算 1，拉丁/数字按词算
const wordCount = computed(() => {
  const cjk = (content.value.match(/[一-鿿]/g) || []).length;
  const latin = (content.value.replace(/[一-鿿]/g, " ").match(/[a-zA-Z0-9]+/g) || []).length;
  return cjk + latin;
});

// 「保存于几分钟前」（nowTick 每 30s 刷新一次，相对时间会自己走）
const savedAgo = computed(() => {
  if (!savedAt.value) return "";
  const min = Math.floor((nowTick.value - new Date(savedAt.value).getTime()) / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} 小时前`;
  return new Date(savedAt.value).toLocaleDateString("zh-CN");
});

const statusLeft = computed(() => {
  if (dirty.value) return draftSynced.value ? "编辑中 · 草稿已暂存" : "编辑中…";
  return savedAt.value ? `保存于 ${savedAgo.value}` : "";
});

// ── 面包屑 + 子页面（目录页 = 有子页面的文章页，同一个东西）──
const store = useNotesStore();

const breadcrumb = computed(() => {
  // 从 parent_id 一路向上走，拼出祖先链
  const chain: { id: string; title: string }[] = [];
  let cur = doc.value;
  let guard = 0;
  while (cur?.parent_id && guard++ < 20) {
    const parent = store.docs.find((d) => d.id === cur!.parent_id);
    if (!parent) break;
    chain.unshift({ id: parent.id, title: parent.title });
    cur = parent;
  }
  return chain;
});

const childDocs = computed(() =>
  store.docs.filter((d) => d.parent_id === props.docId)
);

// ── 加载文档 ──
async function load(id: string) {
  doc.value = await getDoc(id);
  title.value = doc.value.title;
  content.value = doc.value.content || "";
  savedTitle.value = doc.value.title;
  savedContent.value = doc.value.content || "";
  savedAt.value = doc.value.updated_at;
  draftSynced.value = false;
  draftPreview.value = null;
  loadBacklinks();
  draftBanner.value =
    doc.value.has_draft && !isDismissed(doc.value.id, doc.value.draft_updated_at!)
      ? { device: doc.value.draft_device, updatedAt: doc.value.draft_updated_at! }
      : null;
}

watch(() => props.docId, (newId, oldId) => {
  // 切走前先把旧文档的挂起草稿冲出去（此 watcher 注册早于 WS 重连，socket 还连着旧文档）
  if (oldId && oldId !== newId) flushDraft();
  if (newId) load(newId);
}, { immediate: true });

onBeforeUnmount(() => flushDraft());

// ── 编辑中：打字停 2.5s → 草稿槽（正文不动，草稿是影子）──
// ── 行为边界（切换/离开/Ctrl+S）→ 才落正文 + 弹 toast ──
let draftTimer: ReturnType<typeof setTimeout> | null = null;

function flushDraft() {
  /** 切走/销毁前：有未保存修改 → 保存落正文（toast 在 save() 里弹） */
  if (draftTimer) clearTimeout(draftTimer);
  draftTimer = null;
  if (doc.value && dirty.value) {
    // fire-and-forget：组件可能正在销毁，emit 会丢，直接刷 store
    save().then(() => useNotesStore().refreshList()).catch(() => {});
  }
}

watch([content, title], () => {
  if (!doc.value || !dirty.value) return;
  const forDoc = doc.value.id;
  if (draftTimer) clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    // 回调触发时世界可能已变：文档换了就不能发（防止交叉污染）
    if (dirty.value && doc.value?.id === forDoc) {
      sendDraft(content.value);
      draftSynced.value = true;
    }
  }, 2500);
});

// 别的设备保存了：本地干净就静默重拉；本地在编辑就弹个轻提示（不警告不动作）
function onRemoteSaved() {
  if (!doc.value) return;
  if (!dirty.value) {
    load(props.docId);
  } else {
    toast("另一台设备保存了这篇笔记的新版本");
  }
}

const { sendDraft } = useDraftSocket(toRef(props, "docId"), deviceLabel, onRemoteSaved);

// ── 保存（乐观锁 PUT；切换保存和 Ctrl+S 都走这里）──
async function save() {
  if (!doc.value || !dirty.value) return;
  if (draftTimer) clearTimeout(draftTimer);
  try {
    const updated = await updateDoc(doc.value.id, doc.value.updated_at, {
      title: title.value,
      content: content.value,
    });
    doc.value = updated;
    savedTitle.value = updated.title;
    savedContent.value = updated.content || "";
    savedAt.value = updated.updated_at;
    draftSynced.value = false;
    draftBanner.value = null; // 保存成功草稿槽已清
    loadBacklinks(); // 双链可能变了
    toast("已自动保存 ✓");
    emit("saved");
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      // 乐观锁兜底：静默重拉 DB（老婆定的：不弹打扰式提示）
      await load(props.docId);
      toast("版本冲突，已刷新为最新");
    } else {
      toast("保存失败，稍后再试");
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

// ── 星标切换（轻量端点，不动 updated_at 不碰正在编辑的内容）──
async function toggleFav() {
  if (!doc.value) return;
  const updated = await toggleFavorite(doc.value.id);
  // 只更新星标状态和令牌，本地的 title/content 编辑现场不动
  doc.value = { ...updated };
  useNotesStore().refreshList();
}

// ── 删除（有下挂走 NotesPage 的三选弹窗）──
async function remove() {
  if (!doc.value) return;
  const store = useNotesStore();
  if (store.childCount(doc.value.id) > 0) {
    store.requestDelete(doc.value); // 弹窗接管，后续由 NotesPage 收尾
  } else {
    await store.doDelete(doc.value.id, true);
    emit("deleted");
  }
}

// Ctrl+S
function onKey(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === "s") {
    e.preventDefault();
    save();
  }
}
onMounted(() => {
  window.addEventListener("keydown", onKey);
  tickTimer = setInterval(() => (nowTick.value = Date.now()), 30000); // 「几分钟前」自己走
});
onUnmounted(() => {
  window.removeEventListener("keydown", onKey);
  if (tickTimer) clearInterval(tickTimer);
});

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

    <!-- 面包屑：祖先路径，可点击跳转 -->
    <div v-if="breadcrumb.length" class="breadcrumb">
      <template v-for="b in breadcrumb" :key="b.id">
        <span class="crumb" @click="emit('open', b.id)">{{ b.title }}</span>
        <span class="sep">/</span>
      </template>
      <span class="crumb current">{{ doc.title }}</span>
    </div>

    <div class="toolbar">
      <input v-model="title" class="title-input" placeholder="无标题" />
      <div class="actions">
        <button
          class="star-btn"
          :class="{ fav: doc.is_favorite }"
          :title="doc.is_favorite ? '取消星标' : '设为星标'"
          @click="toggleFav"
        >
          <Icon name="star" :size="15" />
        </button>
        <button class="mode-toggle" @click="reading = !reading">
          <Icon :name="reading ? 'edit' : 'eye'" :size="13" /> {{ reading ? "编辑" : "阅览" }}
        </button>
        <button class="del-btn" @click="remove">删除</button>
      </div>
    </div>

    <div class="panes" :class="reading ? 'preview-only' : 'split'">
      <div v-show="!reading" class="input-wrap">
        <textarea
          ref="inputEl"
          v-model="content"
          class="input"
          placeholder="开始写…（打字存草稿 · 切换笔记自动保存 · [[标题]] 建双链）"
          @input="onInputForLinks"
          @blur="suggestPos = null"
        />
        <!-- [[ 自动补全下拉 -->
        <div v-if="suggestPos && linkSuggests.length" class="suggests">
          <div
            v-for="s in linkSuggests"
            :key="s.id"
            class="sug"
            @mousedown.prevent="pickLink(s)"
          >{{ s.title }}</div>
        </div>
      </div>
      <div class="preview markdown-body" v-html="rendered" @click="onPreviewClick" />
    </div>

    <!-- 反链：哪些页面链接到了这篇 -->
    <div v-if="backlinks.length" class="children-strip">
      <span class="label"><Icon name="link" :size="11" /> 被引用</span>
      <span
        v-for="b in backlinks"
        :key="b.id"
        class="chip backlink"
        @click="emit('open', b.id)"
      >{{ b.title }}</span>
    </div>

    <!-- 子页面区块：有子页面 = 这篇就是目录页 -->
    <div v-if="childDocs.length" class="children-strip">
      <span class="label"><Icon name="folder" :size="11" /> 子页面</span>
      <span
        v-for="kid in childDocs"
        :key="kid.id"
        class="chip"
        @click="emit('open', kid.id)"
      >{{ kid.title }}</span>
    </div>

    <!-- 常驻状态条：保存于几分钟前 · 字数 · 来源 -->
    <div class="status-bar">
      <span class="state">{{ statusLeft }}</span>
      <span class="right">{{ wordCount }} 字 · </span>
      <span class="device" title="点击给这个来源起名" @click="renameDevice">{{ deviceLabel }}</span>
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
.star-btn {
  padding: 5px 10px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: pointer;
  color: var(--text-faint);
  transition: all var(--transition);
  display: inline-flex;
  align-items: center;
}
.star-btn:hover { color: var(--text-hi); background: var(--bg-raised); }
.star-btn.fav { color: var(--pink); }
.mode-toggle {
  padding: 6px 16px;
  border: 1px solid var(--accent-dim);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--accent);
  font-size: 12.5px;
  cursor: pointer;
  transition: all var(--transition);
}
.mode-toggle:hover { background: var(--bg-raised); }
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

.status-bar {
  display: flex;
  align-items: center;
  padding: 7px 16px;
  font-size: 11px;
  color: var(--text-faint);
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  background: var(--bg-base);
}
.status-bar .state { color: var(--text-lo); }
.status-bar .right { margin-left: auto; }
.status-bar .device { cursor: pointer; }
.status-bar .device:hover { color: var(--accent); }

.panes { flex: 1; display: flex; overflow: hidden; }

.breadcrumb {
  padding: 8px 16px 0;
  font-size: 11.5px;
  color: var(--text-faint);
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.crumb { cursor: pointer; transition: color var(--transition); }
.crumb:hover { color: var(--accent); }
.crumb.current { color: var(--text-lo); cursor: default; }
.sep { opacity: 0.4; }

.children-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}
.children-strip .label { font-size: 11px; color: var(--text-faint); letter-spacing: 1px; }
.children-strip .chip {
  padding: 4px 12px;
  border-radius: 999px;
  background: var(--bg-raised);
  font-size: 12px;
  color: var(--accent);
  cursor: pointer;
  transition: all var(--transition);
}
.children-strip .chip:hover { background: var(--accent-dim); color: var(--bg-base); }
.chip.backlink { color: var(--pink); }
.input-wrap { position: relative; flex: 1; display: flex; }
.suggests {
  position: absolute;
  top: 44px;
  left: 16px;
  min-width: 200px;
  background: var(--bg-raised);
  border: 1px solid var(--accent-dim);
  border-radius: var(--radius-sm);
  overflow: hidden;
  z-index: 20;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}
.sug {
  padding: 8px 14px;
  font-size: 13px;
  color: var(--text-lo);
  cursor: pointer;
}
.sug:hover { background: var(--bg-panel); color: var(--accent); }
.markdown-body :deep(.wikilink) {
  color: var(--accent);
  border-bottom: 1px dashed var(--accent-dim);
  cursor: pointer;
}
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
.markdown-body :deep(img) {
  max-width: 100%;
  border-radius: var(--radius-sm);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.35);
  margin: 10px 0;
  display: block;
}
</style>
