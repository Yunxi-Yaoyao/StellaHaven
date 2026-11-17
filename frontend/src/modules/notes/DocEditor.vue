<script setup lang="ts">
import {notifyClientPreferenceChange} from '../settings/clientPreferenceEvents';
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount, onActivated, onDeactivated, toRef, defineAsyncComponent } from "vue";
import { auth } from "../home/auth";
import { useRoute, useRouter } from "vue-router";
const noteRoute = useRoute(), noteRouter = useRouter();
import { marked } from "marked";
import { localId } from "./localId";
import { draftReceipt } from "./draftReceipt";
import {PROJECT_ASSET_MIME,parseProjectAsset,createProjectAssetCopy} from "./projectAssetCopy";
import {copyProjectAsset} from "../../api/projectFiles";
import type { ConsumedDraft } from "../../api/notes";
let consumedDraft: ConsumedDraft | undefined;
let draftLineage = 0, receiptSequence = 0;
import { useNoteDraftChannel } from "./useNoteDraftChannel";
import { sanitizeNoteHtml } from "./noteHtml";
import { renderMermaidBlocks } from "./lazyMermaid";
import {guardPrivateMediaHtml,restorePrivateMediaHtml} from "../auth/privateMedia";
const RichEditor = defineAsyncComponent(() => import("./RichEditor.vue"));
import {
  getDoc, updateDoc, getDraft, toggleFavorite, type Doc,
} from "../../api/notes";
import { api } from "../../api/client";
import { ApiError } from "../../api/client";
import { getDeviceName, setDeviceName, getIpInfo } from "../../composables/useDraftSocket";
import { useNotesStore } from "../../stores/notes";
import { toast } from "../../composables/useToast";
import { openLightbox } from "../../composables/useLightbox";
import Icon from "../../shell/Icon.vue";
import TagBar from "./TagBar.vue";
import AutoDirectory from "./AutoDirectory.vue";
import VersionsPanel from "./VersionsPanel.vue";
const moreOpen = ref(false);
const infoOpen = ref(false);
const fullTitleOpen = ref(false);
const moreButton = ref<HTMLButtonElement | null>(null);
const titleEl = ref<HTMLTextAreaElement | null>(null);
const saveError = ref('');
const remoteUnconfirmed = ref(false);
const savePending = ref(false);
const infoDialog = ref<HTMLElement | null>(null);
let releaseInfoDialog: (() => void) | null = null;
watch(() => fullTitleOpen.value || infoOpen.value, async (open, _, onCleanup) => {
  if (!open) return;
  let cancelled = false;
  onCleanup(() => { cancelled = true; releaseInfoDialog?.(); releaseInfoDialog = null; });
  const trigger = infoOpen.value ? moreButton.value : document.activeElement as HTMLElement | null;
  await nextTick();
  if (cancelled || !infoDialog.value) return;
  const dialog = infoDialog.value;
  const inert: [HTMLElement, boolean][] = [];
  let branch: HTMLElement | null = dialog.parentElement;
  while (branch && branch !== document.body) {
    for (const sibling of Array.from(branch.parentElement?.children ?? [])) {
      if (sibling !== branch && sibling instanceof HTMLElement) { inert.push([sibling, sibling.inert]); sibling.inert = true; }
    }
    branch = branch.parentElement;
  }
  const overflow = document.body.style.overflow;
  document.body.style.overflow = 'hidden';
  const key = (e: KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); closeOverlays(); }
    if (e.key !== 'Tab') return;
    const targets = Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select,textarea,[tabindex="0"]')).filter(el => el.getClientRects().length);
    const first = targets[0] ?? dialog, last = targets[targets.length - 1] ?? dialog;
    if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog) || !e.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
      e.preventDefault(); (e.shiftKey ? last : first).focus();
    }
  };
  document.addEventListener('keydown', key, true);
  releaseInfoDialog = () => {
    document.removeEventListener('keydown', key, true);
    for (const [el, previous] of inert) el.inert = previous;
    document.body.style.overflow = overflow;
    if (trigger?.isConnected) trigger.focus({preventScroll:true});
  };
  dialog.focus();
});
onBeforeUnmount(() => { releaseInfoDialog?.(); releaseInfoDialog = null; });
const findOpen = ref(false);
const findQuery = ref('');
const findResult = ref('');
let findIndex = -1;
function resizeTitle() {
  const el = titleEl.value;
  if (!el) return;
  el.style.height = 'auto';
  // Keep the complete value, but never let an extreme title consume the body.
  el.style.height = Math.min(el.scrollHeight, 112) + 'px';
}
function onTitleInput(e: Event) {
  const el = e.target as HTMLTextAreaElement;
  if ((e as InputEvent).isComposing) return;
  const start = el.selectionStart;
  const normalized = el.value.replace(/[\r\n\u2028\u2029]+/g, ' ');
  title.value = normalized;
  if (el.value !== normalized) { el.value = normalized; el.setSelectionRange(Math.min(start, normalized.length), Math.min(start, normalized.length)); }
  resizeTitle();
}
function titleKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) e.preventDefault();
}
function closeOverlays() {
  moreOpen.value = false; infoOpen.value = false; fullTitleOpen.value = false; tocOpen.value = false; findOpen.value = false; versionsOpen.value = false; exportWin.value = false;
}
function menuAction(action: () => unknown) { moreOpen.value = false; void action(); }
function outsideMenu(e: PointerEvent) {
  if (!(e.target as Element).closest('.more-wrap')) moreOpen.value = false;
}
async function openFind() {
  if (!reading.value && editMode.value === 'markdown') { cmRef.value?.openFind(); return; }
  findOpen.value = true; await nextTick(); document.querySelector<HTMLInputElement>('.note-find input')?.focus();
}
function findNext() {
  const root = reading.value ? previewEl.value : document.querySelector<HTMLElement>(editMode.value === 'rich' ? '.rich-editor .ProseMirror' : '.cm-content');
  if (!root || !findQuery.value) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const matches: Range[] = []; let node: Node | null;
  const nodes: {node: Node; start: number; end: number}[] = [];
  let text = '';
  while ((node = walker.nextNode())) {
    const value = node.textContent || '';
    nodes.push({node, start:text.length, end:text.length + value.length}); text += value;
  }
  const query = findQuery.value.toLocaleLowerCase(), haystack = text.toLocaleLowerCase();
  for (let i = haystack.indexOf(query); i >= 0; i = haystack.indexOf(query, i + query.length)) {
    const start = nodes.find(n => n.start <= i && n.end > i);
    const end = nodes.find(n => n.start < i + query.length && n.end >= i + query.length);
    if (!start || !end) continue;
    const range = document.createRange(); range.setStart(start.node, i - start.start); range.setEnd(end.node, i + query.length - end.start); matches.push(range);
  }
  if (!matches.length) { findResult.value = '无匹配'; return; }
  findIndex = (findIndex + 1) % matches.length; const range = matches[findIndex]!;
  const selection = window.getSelection(); selection?.removeAllRanges(); selection?.addRange(range);
  range.startContainer.parentElement?.scrollIntoView({block:'center'});
  findResult.value = `${findIndex + 1} / ${matches.length}`;
}
const versionsOpen = ref(false);
function onVersionRestored(restored: Doc) {
  if (!ownsSession() || props.docId !== restored.id) return;
  ++editorEpoch; ++loadSequence; ++draftReadSequence;
  resetDraftSource();
  doc.value = restored;
  title.value = savedTitle.value = restored.title;
  content.value = savedContent.value = restored.content || '';
  savedAt.value = restored.updated_at_display ?? null;
  draftSynced.value = false; draftBanner.value = null;
  void loadBacklinks(); emit('saved');
}

const props = defineProps<{ docId: string }>();
const emit = defineEmits<{ saved: []; deleted: []; open: [id: string]; createChild: [id: string]; directory: []; history: [] }>();
const ownerId = auth.me?.id;
const ownerGeneration = auth.sessionGeneration;
const ownsSession = () => !!ownerId && auth.me?.id === ownerId && auth.sessionGeneration === ownerGeneration && !auth.suspended && !auth.sessionClosing;
let editorEpoch = 0, editRevision = 0, draftReadSequence = 0;
let editorActive = true;

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
watch([title, content], () => { ++editRevision; }, {flush: "sync"});
const savedTitle = ref("");
const savedContent = ref("");
const reading = ref(true); // 默认阅览，编辑方式单独记忆
const editMode = ref<"rich" | "markdown">(localStorage.getItem("stella_note_edit_mode") === "markdown" ? "markdown" : "rich");
const richRef = ref<InstanceType<typeof RichEditor> | null>(null);
const richLoaded = ref(false);
watch(reading, (value) => { if (!value && editMode.value === "rich") richLoaded.value = true; void nextTick(resizeTitle); });
watch(title, () => { void nextTick(resizeTitle); });
async function switchEditMode(mode: "rich" | "markdown") {
  if (editMode.value === "rich") richRef.value?.flush();
  editMode.value = mode;
  suggestMode.value = null;
  if (mode === "rich") richLoaded.value = true;
  notifyClientPreferenceChange('stella_note_edit_mode',mode);
  localStorage.setItem("stella_note_edit_mode", mode);
  await nextTick();
  if (mode === "rich") richRef.value?.focus(); else cmRef.value?.focus();
}

// 窄屏检测：窗口挤到放不下编辑双栏（左编辑器+右预览）→ 自动单栏（编辑只看编辑器）
// 断点 900px：双栏每边至少 ~430px 才不挤
const NARROW_BP = 900;
const narrow = ref(window.innerWidth <= NARROW_BP);
function onWinResize() {
  narrow.value = window.innerWidth <= NARROW_BP;
}

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

// 渲染时把 [[标题]] 转成可点链接 + 给标题加锚点 id（TOC 用）
// breaks: true → 单回车即换行（老婆不习惯 markdown 默认要空一行）
// 附件链接 → 居中卡片（大图标+文件名，点击原样下载）
const attachMeta = ref<Record<string, { filename: string; mime: string }>>({});

const FILE_ICON_PATHS: Record<string, string> = {
  file: "M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z|M13 2v7h7",
  text: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z|M14 2v6h6|M16 13H8|M16 17H8",
  archive: "M21 8v13H3V8|M1 3h22v5H1z|M10 12h4",
  media: "M9 18V5l12-2v13|M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0z|M21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  pdf: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z|M14 2v6h6|M9 15l6-6|M9 9l6 6",
};

function iconKindFor(mime: string, filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  if (mime === "application/pdf" || ext === "pdf") return "pdf";
  if (/zip|rar|7z|tar|gz/.test(ext) || mime.includes("zip") || mime.includes("compressed")) return "archive";
  if (mime.startsWith("video/") || mime.startsWith("audio/")) return "media";
  if (mime.startsWith("text/") || /txt|md|log|json|csv/.test(ext)) return "text";
  return "file";
}

function attachCardHtml(id: string, fallbackName: string): string {
  const meta = attachMeta.value[id];
  const name = meta?.filename || fallbackName || "附件";
  const mime = meta?.mime || "";
  const kind = iconKindFor(mime, name);
  const paths = FILE_ICON_PATHS[kind].split("|").map((d) => `<path d="${d}"/>`).join("");
  return (
    `<span class="attach-card" data-url="/attachments/${id}" data-name="${name.replace(/"/g, "")}">` +
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>` +
    `<span class="attach-name">${name}</span>` +
    `</span>`
  );
}

// mermaid 代码块 → 占位 div（marked 默认渲染成 <pre><code>，这里换成 .mermaid 容器供 mermaid.js 渲染）
const mermaidRenderer = new marked.Renderer();
const _origCode = mermaidRenderer.code.bind(mermaidRenderer);
mermaidRenderer.code = (token: { text: string; lang?: string }) => {
  if (token.lang === "mermaid") {
    const escaped = token.text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return `<div class="mermaid">${escaped}</div>`;
  }
  return _origCode(token as Parameters<typeof _origCode>[0]);
};

const rendered = computed(() => {
  const md = content.value || "";
  let html = marked.parse(md, { breaks: true, renderer: mermaidRenderer }) as string;
  // 标题加锚点 id（hIdx 顺序和 marked.lexer 的 heading 顺序严格一致）
  let hIdx = 0;
  html = html.replace(/<h([123])>/g, (_m, lv) => {
    const id = `toc-h${hIdx++}`;
    return `<h${lv} id="${id}">`;
  });
  // 用 lexer 拿标题 + 源码偏移（offset 供编辑器跳转用）
  // 关键：lexer 只认真标题，代码块里的 # 注释不会被误当成标题 → id 和锚点对齐
  const toc: { level: number; text: string; id: string; offset: number }[] = [];
  let cursor = 0;
  let ti = 0;
  for (const t of marked.lexer(md, { breaks: true })) {
    if (t.type === "heading" && t.depth <= 3) {
      const idx = md.indexOf(t.raw, cursor);
      const offset = idx >= 0 ? idx : cursor;
      toc.push({ level: t.depth, text: t.text, id: `toc-h${ti++}`, offset });
      if (idx >= 0) cursor = idx + t.raw.length;
    }
  }
  tocItems.value = toc;
  // 附件链接 → 下载卡片
  html = html.replace(
    /<a href="\/attachments\/([0-9a-f-]{36})">([^<]*)<\/a>/g,
    (_m, id, name) => attachCardHtml(id, name)
  );
  html = html.replace(
    /\[\[([^\[\]]+)\]\]/g,
    '<a class="wikilink" data-title="$1">$1</a>'
  );
  return guardPrivateMediaHtml(sanitizeNoteHtml(html));
});

// ── mermaid 渲染：v-html 落 DOM 后，把 .mermaid 容器逐个渲染成 SVG ──
let mermaidGeneration = 0;
async function renderMermaid() {
  const generation = ++mermaidGeneration;
  const id = props.docId, source = content.value, epoch = editorEpoch;
  const current = () => generation === mermaidGeneration && id === props.docId &&
    source === content.value && epoch === editorEpoch && editorActive && ownsSession();
  await nextTick();
  if (!current() || !previewEl.value) return;
  await renderMermaidBlocks(previewEl.value, current);
}

// ── TOC 大纲 ──
const tocOpen = ref(false);
// TOC 条目由 rendered 计算时同步产出（id 与锚点严格对齐，offset 供编辑器跳转）
const tocItems = ref<{ level: number; text: string; id: string; offset: number }[]>([]);
// ⚠️ watch 必须在 tocItems 声明之后：rendered 内部引用 tocItems，watch 会立即读 computed，若在声明前会触发 TDZ
watch(rendered, () => { renderMermaid(); });

function jumpTo(id: string) {
  if (!reading.value && editMode.value === "rich") {
    const item = tocItems.value.find(t => t.id === id);
    if (item) {
      const label = document.createElement("span");
      label.innerHTML = sanitizeNoteHtml(marked.parseInline(item.text) as string);
      richRef.value?.scrollToHeading(label.textContent || item.text);
    }
    return;
  }
  // 1. 预览跳转（阅览模式 / 双栏的右侧）
  const preview = document.querySelector(".preview");
  const target = preview?.querySelector(`#${id}`);
  target?.scrollIntoView({ behavior: "smooth", block: "start" });
  // 2. 编辑器跳转（编辑双栏的左侧 / 窄屏单栏的编辑器）——两边同步滚
  const item = tocItems.value.find((t) => t.id === id);
  if (item) cmRef.value?.scrollToPos(item.offset);
}

// 编辑/预览滚动联动：编辑器滚多少比例，预览滚同样比例（老婆：不想滑两次）
const previewEl = ref<HTMLElement | null>(null);
watch(() => [noteRoute.hash, rendered.value, reading.value], async () => {
  await nextTick();
  if (!noteRoute.hash || noteRoute.query.doc !== props.docId || !reading.value) return;
  let hash: string;
  try { hash = decodeURIComponent(noteRoute.hash.slice(1)); } catch { return; }
  const slug = (text: string) => text.trim().toLowerCase().replace(/[^\p{L}\p{N} _-]/gu, '').replace(/\s/g, '-');
  const headings = Array.from(previewEl.value?.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6') ?? []);
  const heading = headings.find(h => h.id === hash || slug(h.textContent ?? '') === hash.toLowerCase() || h.textContent?.trim() === hash);
  heading?.scrollIntoView({ block: 'start' });
}, { flush: 'post' });
function onEditorScroll(ratio: number) {
  const p = previewEl.value;
  if (!p) return;
  p.scrollTop = ratio * (p.scrollHeight - p.clientHeight);
}

// 点预览：附件卡下载 / wikilink 跳转 / 图片放大
function onPreviewClick(e: MouseEvent) {
  const internal = (e.target as HTMLElement).closest('a[href]') as HTMLAnchorElement | null;
  if (internal && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) {
    const url = new URL(internal.href, location.href);
    if (url.origin === location.origin && url.pathname === '/notes' && url.searchParams.has('doc')) {
      e.preventDefault();
      void save().then(ok => { if (ok && ownsSession()) void noteRouter.push(url.pathname + url.search + url.hash); });
      return;
    }
  }
  const card = (e.target as HTMLElement).closest(".attach-card") as HTMLElement | null;
  if (card) {
    // 原原本本下载（download 属性强制保存，不打开预览）
    const a = document.createElement("a");
    a.href = card.dataset.url!;
    a.download = card.dataset.name || "";
    a.click();
    return;
  }
  // mermaid 流程图点击放大：内联 SVG 序列化成 data URI 塞进 lightbox（跟图片同一套滚轮缩放+拖动）
  const mermaidBlock = (e.target as HTMLElement).closest(".mermaid") as HTMLElement | null;
  if (mermaidBlock) {
    const svg = mermaidBlock.querySelector("svg");
    if (svg) {
      const svgStr = new XMLSerializer().serializeToString(svg);
      openLightbox("data:image/svg+xml;charset=utf-8," + encodeURIComponent(svgStr));
      return;
    }
  }
  const img = (e.target as HTMLElement).closest("img") as HTMLImageElement | null;
  if (img && img.src) {
    openLightbox(img.src); // 文章图片点击放大
    return;
  }
  const a = (e.target as HTMLElement).closest(".wikilink") as HTMLElement | null;
  if (!a) return;
  const t = a.dataset.title;
  const target = store.docs.find((d) => d.title === t);
  if (target) emit("open", target.id);
  else toast(`没有找到「${t}」这篇笔记`);
}

// ── [[ 双链补全 + / 斜杠命令（统一建议状态机）──
import type { EditorView } from "@codemirror/view";
import CmEditor from "./CmEditor.vue";

const cmRef = ref<InstanceType<typeof CmEditor> | null>(null);
const suggestMode = ref<"link" | "cmd" | null>(null);
const linkSuggests = ref<Doc[]>([]);
const curQuery = ref(""); // 当前 [[ 或 / 后面的查询词

const SLASH_CMDS = [
  { key: "h1", label: "标题 1", insert: "# " },
  { key: "h2", label: "标题 2", insert: "## " },
  { key: "h3", label: "标题 3", insert: "### " },
  { key: "ul", label: "无序列表", insert: "- " },
  { key: "todo", label: "待办事项", insert: "- [ ] " },
  { key: "ol", label: "有序列表", insert: "1. " },
  { key: "quote", label: "引用", insert: "> " },
  { key: "code", label: "代码块", insert: "```\n\n```" },
  { key: "hr", label: "分割线", insert: "\n---\n" },
];
const cmdSuggests = computed(() => {
  const q = curQuery.value.toLowerCase();
  return SLASH_CMDS.filter((c) => c.label.includes(q) || c.key.includes(q));
});

function onCmChange(view: EditorView) {
  const pos = view.state.selection.main.head;
  const line = view.state.doc.lineAt(pos);
  const lineText = line.text.slice(0, pos - line.from);

  // / 斜杠命令：行首以 / 开头
  const sm = lineText.match(/^\/(\S*)$/);
  if (sm) {
    suggestMode.value = "cmd";
    curQuery.value = sm[1];
    return;
  }
  // [[ 双链
  const before = view.state.doc.sliceString(Math.max(0, pos - 60), pos);
  const m = before.match(/\[\[([^\[\]]*)$/);
  if (m) {
    suggestMode.value = "link";
    curQuery.value = m[1];
    linkSuggests.value = store.docs
      .filter((d) => d.id !== props.docId && d.title.toLowerCase().includes(m[1].toLowerCase()))
      .slice(0, 6);
    return;
  }
  suggestMode.value = null;
}

function pickLink(target: Doc) {
  cmRef.value?.deleteBefore(2 + curQuery.value.length);
  cmRef.value?.insertText(`[[${target.title}]]`);
  suggestMode.value = null;
}

function pickCommand(cmd: (typeof SLASH_CMDS)[number]) {
  cmRef.value?.deleteBefore(1 + curQuery.value.length);
  cmRef.value?.insertText(cmd.insert);
  suggestMode.value = null;
}

async function toggleReading() {
  if (!reading.value) { if (!(await save())) return; }
  reading.value = !reading.value;
}

// ── 工具栏 ──
const richActions = ["bold", "italic", "code", "h1", "h2", "ul", "todo", "quote", "link", "image", "hr"];
const toolbar = [
  { text: "B", title: "加粗", action: () => cmRef.value?.wrapSelection("**", "**", "粗体") },
  { text: "I", title: "斜体", action: () => cmRef.value?.wrapSelection("*", "*", "斜体") },
  { text: "</>", title: "行内代码", action: () => cmRef.value?.wrapSelection("`", "`", "代码") },
  { text: "H1", title: "标题 1", action: () => cmRef.value?.linePrefix("# ") },
  { text: "H2", title: "标题 2", action: () => cmRef.value?.linePrefix("## ") },
  { text: "•", title: "无序列表", action: () => cmRef.value?.linePrefix("- ") },
  { text: "☑", title: "待办", action: () => cmRef.value?.linePrefix("- [ ] ") },
  { text: "❝", title: "引用", action: () => cmRef.value?.linePrefix("> ") },
  { text: "🔗", title: "链接", action: () => cmRef.value?.wrapSelection("[", "](https://)", "链接文字") },
  { text: "🖼", title: "图片", action: () => cmRef.value?.insertText("![描述](图片链接)") },
  { text: "—", title: "分割线", action: () => cmRef.value?.insertText("\n\n---\n\n") },
];

// ── 粘贴/拖拽上传：图片插 ![]()，其他文件插链接 []() ──
async function uploadOne(file: File, insertAt: number) {
  if (!doc.value) return;
  const targetDocId = doc.value.id;
  const isImg = file.type.startsWith("image/");
  const name = file.name || "paste.png";
  const placeholder = `上传中…${localId()}`;
  if (editMode.value === "rich" && !reading.value) {
    if (!richRef.value?.insertText(placeholder)) { toast("编辑器尚未就绪，请稍后重试喵~"); return; }
  } else {
    content.value = content.value.slice(0, insertAt) + placeholder + content.value.slice(insertAt);
  }

  const form = new FormData();
  form.append("file", file, name);
  try {
    const resp = await fetch(`/attachments/${targetDocId}`, { method: "POST", body: form });
    if (!resp.ok) {
      // 把后端的真实原因抛出来（413=超限等），不再只报「上传失败」
      let reason = `HTTP ${resp.status}`;
      try {
        const body = await resp.json();
        if (body?.detail) reason = body.detail;
      } catch { /* 非 JSON */ }
      throw new Error(reason);
    }
    const { url, filename } = await resp.json();
    if (doc.value?.id !== targetDocId) { toast("附件已上传到原笔记，请从附件面板插入引用喵~"); return; }
    const safeName = String(filename).replace(/[\\\[\]]/g, "\\$&");
    content.value = content.value.replace(
      placeholder,
      isImg ? `![${safeName}](${url})` : `[${safeName}](${url})`
    );
    toast(isImg ? "图片已上传 ✓" : `「${filename}」已上传 ✓`);
  } catch (e) {
    content.value = content.value.replace(placeholder, "");
    toast(`上传失败：${e instanceof Error ? e.message : "未知原因"}`);
  }
}

async function onPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items;
  if (!items) return;
  const fileItem = [...items].find((i) => i.kind === "file");
  if (!fileItem) return; // 不是文件就走默认粘贴
  e.preventDefault();
  const file = fileItem.getAsFile();
  if (!file) return;
  await uploadOne(file, cmRef.value?.getCursor() ?? content.value.length);
}

async function onDrop(e: DragEvent) {
  const files = e.dataTransfer?.files;
  if (!files?.length) return;
  e.preventDefault();
  for (const file of files) {
    await uploadOne(file, content.value.length); // 追加到末尾
  }
}

// ── 反链 ──
const backlinks = ref<Doc[]>([]);
async function loadBacklinks() {
  backlinks.value = await api<Doc[]>(`/documents/${props.docId}/backlinks`);
}

// 附件元信息（渲染下载卡片用：文件名 + mime → 图标类型）
async function loadAttachMeta() {
  const all = await api<{ id: string; filename: string; mime: string; doc_id: string }[]>(
    `/attachments/?workspace_id=${store.workspaceId}`
  );
  const map: Record<string, { filename: string; mime: string }> = {};
  for (const a of all) {
    if (a.doc_id === props.docId) map[a.id] = { filename: a.filename, mime: a.mime };
  }
  attachMeta.value = map;
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
  if (saveError.value) return saveError.value;
  if (savePending.value) return "正在保存…";
  if (dirty.value) return draftSynced.value ? "待保存 · 草稿已发送（尚未确认同步）" : "待保存 · 未同步";
  if (remoteUnconfirmed.value) return '本地已恢复上次保存内容 · 未重新确认远端';
  return savedAt.value ? `保存于 ${savedAgo.value}` : (doc.value ? "保存时间未知" : "");
});

// ── 面包屑 + 子页面（目录页 = 有子页面的文章页，同一个东西）──
const store = useNotesStore();
function currentEditor() {
  const epoch = editorEpoch, id = props.docId, workspace = store.workspaceId;
  return () => editorActive && ownsSession() && epoch === editorEpoch && props.docId === id && doc.value?.id === id && store.workspaceId === workspace && doc.value.workspace_id === workspace;
}
const projectCopy=createProjectAssetCopy({
  copy:copyProjectAsset,
  target:()=>editorActive&&ownsSession()?doc.value?.id??null:null,
  capture:()=>{const current=currentEditor(),epoch=auth.requestEpoch;return()=>current()&&epoch===auth.requestEpoch;},
  insert:markdown=>{richRef.value?.flush();content.value+=(content.value?"\n\n":"")+markdown;toast("图片已独立复制，原项目文件未移动");},
});
const {pending:projectCopyPending,busy:projectCopyBusy,error:projectCopyError}=projectCopy;
function projectDragOver(event:DragEvent){
  if(!event.dataTransfer?.types.includes(PROJECT_ASSET_MIME))return;
  event.preventDefault();event.stopPropagation();event.dataTransfer.dropEffect="copy";
}
function projectDrop(event:DragEvent){
  if(!event.dataTransfer?.types.includes(PROJECT_ASSET_MIME))return;
  event.preventDefault();event.stopPropagation();
  const asset=parseProjectAsset(event.dataTransfer.getData(PROJECT_ASSET_MIME));
  if(!asset){toast("项目图片拖放信息无效，请从项目文件重新拖入");return;}
  void projectCopy.start(asset);
}
function pendingProjectCopy(){
  if(!projectCopyPending.value)return false;
  toast("图片复制尚未确认，请先重试或取消这次插入");return true;
}
onBeforeUnmount(projectCopy.dispose);
function resetDraftSource() {
  consumedDraft = undefined; ++draftLineage; receiptSequence = 0;
  invalidateDraftRequests();
}

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
  store.allDocs.filter((d) => d.workspace_id === doc.value?.workspace_id && d.parent_id === props.docId)
);

const templateBusy = ref(false);
async function toggleTemplate() {
  if (templateBusy.value || !doc.value || !ownsSession()) return;
  templateBusy.value = true;
  try {
    if (!(await save())) return;
    const {saveAsTemplate} = await import('../../api/notes');
    await saveAsTemplate(doc.value.workspace_id, props.docId);
    await store.refreshList();
    toast('已复制到模板目录，原笔记保留');
  } catch { toast('模板复制失败，原笔记未改变，请重试'); }
  finally { templateBusy.value = false; }
}
// Deletion must await durable body persistence while this editor is still mounted.
async function prepareDeletion(): Promise<boolean> {
  const current = currentEditor();
  if (!doc.value || !current() || pendingProjectCopy()) return false;
  if (!(await save()) || !current()) return false;
  richRef.value?.flush();
  return !dirty.value && !savePending.value && !saveError.value;
}
defineExpose({ prepareNavigation: () => pendingProjectCopy() ? Promise.resolve(false) : save(), prepareDeletion });
const backlinksOpen = ref(false);
async function newChildPage() {
  if (!(await save())) return;
  emit("createChild", props.docId);
}

// 当前工作区名（面包屑第一级）
const wsName = computed(() =>
  store.workspaces.find((w) => w.id === store.workspaceId)?.name ?? "笔记本"
);

// ── 加载文档 ──
let loadSequence = 0;
async function load(id: string, background = false) {
  if (background && (dirty.value || savePending.value)) return;
  const initialTitle = title.value;
  const initialContent = content.value;
  const sequence = ++loadSequence;
  let loaded: Doc;
  try {
    loaded = await getDoc(id);
  } catch {
    if (sequence === loadSequence && props.docId === id) toast("笔记加载失败，请重新选择重试");
    return;
  }
  if (sequence !== loadSequence || props.docId !== id || !editorActive || !ownsSession() || loaded.workspace_id !== store.workspaceId) return;
  if (background && (savePending.value || dirty.value || title.value !== initialTitle || content.value !== initialContent)) return;
  resetDraftSource();
  doc.value = loaded;
  title.value = doc.value.title;
  content.value = doc.value.content || "";
  savedTitle.value = doc.value.title;
  savedContent.value = doc.value.content || "";
  savedAt.value = doc.value.updated_at_display ?? null;
  draftSynced.value = false;
  draftPreview.value = null;
  void loadBacklinks().catch(() => {});
  void loadAttachMeta().catch(() => {});
  draftBanner.value =
    doc.value.has_draft && !isDismissed(doc.value.id, doc.value.draft_updated_at!)
      ? { device: doc.value.draft_device, updatedAt: doc.value.draft_updated_at! }
      : null;
}

watch(() => props.docId, (newId, oldId) => {
  // Flush the old body with its frozen receipt before replacing the document scope.
  if (oldId && oldId !== newId) flushDraft();
  ++loadSequence; ++editorEpoch; ++draftReadSequence;
  if (oldId !== newId) { consumedDraft = undefined; ++draftLineage; receiptSequence = 0; doc.value = null; saveError.value = ""; }
  if (newId) load(newId);
}, { immediate: true });

onBeforeUnmount(() => { flushDraft(); pauseEditor(); });

// ── 编辑中：打字停 2.5s → 草稿槽（正文不动，草稿是影子）──
// ── 行为边界（切换/离开/Ctrl+S）→ 才落正文 + 弹 toast ──
let draftTimer: ReturnType<typeof setTimeout> | null = null;

function flushDraft() {
  richRef.value?.flush();
  /** 切走/销毁前：有未保存修改 → 保存落正文（toast 在 save() 里弹） */
  if (draftTimer) clearTimeout(draftTimer);
  draftTimer = null;
  if (ownsSession() && doc.value && dirty.value) {
    // fire-and-forget：组件可能正在销毁，emit 会丢，直接刷 store
    save().then((saved) => { if (saved && ownsSession()) return store.refreshList(); }).catch(() => {});
  }
}

watch([content, title], () => {
  if (!editorActive || !ownsSession() || !doc.value || content.value === savedContent.value) return;
  const forDoc = doc.value.id;
  if (draftTimer) clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    // 回调触发时世界可能已变：文档换了就不能发（防止交叉污染）
    if (editorActive && ownsSession() && content.value !== savedContent.value && doc.value?.id === forDoc && doc.value.workspace_id === store.workspaceId) {
      draftSynced.value = sendDraft(content.value, doc.value.updated_at, draftLineage);
    }
  }, 2500);
});

// 别的设备保存了：本地干净就静默重拉；本地在编辑就弹个轻提示（不警告不动作）
function onRemoteSaved() {
  if (!editorActive || !ownsSession() || !doc.value) return;
  if (!dirty.value) {
    load(props.docId, true);
  } else {
    toast("另一台设备保存了这篇笔记的新版本");
  }
}

const { sendDraft, invalidate: invalidateDraftRequests } = useNoteDraftChannel(toRef(props, "docId"), toRef(store, "workspaceId"), deviceLabel, onRemoteSaved, (receipt, lineage, sequence) => {
  if (!editorActive || !ownsSession() || lineage !== draftLineage || sequence <= receiptSequence) return;
  consumedDraft = receipt;
  receiptSequence = sequence;
});

// ── 保存（乐观锁 PUT；切换保存和 Ctrl+S 都走这里）──
let saving: Promise<boolean> | null = null;
async function save(): Promise<boolean> {
  const entryEpoch = editorEpoch, entryId = doc.value?.id;
  while (saving) { if (!(await saving)) return false; }
  if (!editorActive || !ownsSession() || entryEpoch !== editorEpoch || entryId !== doc.value?.id || (doc.value && doc.value.workspace_id !== store.workspaceId)) return false;
  richRef.value?.flush();
  if (!doc.value) return true;
  if (!dirty.value) {
    if (saveError.value) { saveError.value = ''; remoteUnconfirmed.value = true; }
    return true;
  }
  if (draftTimer) clearTimeout(draftTimer);
  ++draftReadSequence; ++loadSequence;
  const id = doc.value.id;
  const token = doc.value.updated_at;
  const bodyChanged = content.value !== savedContent.value;
  const receipt = bodyChanged ? consumedDraft : undefined;
  const current = currentEditor();
  const payload = { ...(title.value !== savedTitle.value ? {title: title.value} : {}), ...(bodyChanged ? {content: content.value} : {}), ...(receipt ? {consumed_draft: receipt} : {}) };
  savePending.value = true;
  saving = (async () => {
    try {
      const updated = await updateDoc(id, token, payload);
      if (!ownsSession()) return false;
      // An old save completing after navigation must not replace the newly opened note.
      if (current()) {
        doc.value = updated;
        savedTitle.value = updated.title;
        savedContent.value = updated.content || "";
        savedAt.value = updated.updated_at_display ?? null;
        saveError.value = "";
        remoteUnconfirmed.value = false;
        draftSynced.value = false;
        draftBanner.value = updated.has_draft && updated.draft_updated_at && !isDismissed(id, updated.draft_updated_at)
          ? {device: updated.draft_device, updatedAt: updated.draft_updated_at} : null;
        if (bodyChanged) {
          // A late ACK for the saved snapshot must not become the source of future text.
          invalidateDraftRequests(); ++draftLineage; receiptSequence = 0;
          if (consumedDraft === receipt) consumedDraft = undefined;
        }
        void loadBacklinks().catch(() => {});
      }
      toast("已自动保存喵~");
      emit("saved");
      return true;
    } catch (e) {
      if (!current()) return false;
      saveError.value = e instanceof ApiError && e.status === 409 ? "版本冲突 · 本地修改保留，请复制或导出" : "保存失败 · 未同步，本地修改保留，请重试";
      toast(e instanceof ApiError && e.status === 409
        ? "另一设备已保存新版本，本地修改仍保留，请先复制或导出后再刷新喵~"
        : "保存失败，修改仍保留，请稍后重试喵~");
      return false;
    }
  })();
  try { return await saving; } finally { saving = null; savePending.value = false; }
}

// ── 草稿提示条动作 ──
async function readDraft(adopt: boolean) {
  const current = currentEditor(), revision = editRevision, sequence = ++draftReadSequence;
  if (!current() || savePending.value) return;
  const valid = () => current() && sequence === draftReadSequence && revision === editRevision;
  try {
    const d = await getDraft(props.docId);
    if (!valid()) return;
    if (!adopt) { draftPreview.value = d.content; return; }
    const receipt = await draftReceipt(d.content, d.updated_at);
    if (!valid()) return;
    resetDraftSource();
    consumedDraft = receipt;
    content.value = d.content;
    draftPreview.value = null;
    draftBanner.value = null;
    await save(); // One body transaction consumes only the adopted slot, if known.
  } catch (e) {
    if (!valid()) return;
    if (e instanceof ApiError && e.status === 404) { draftBanner.value = null; draftPreview.value = null; }
    else toast("草稿读取失败，本地内容保留，请重试");
  }
}
function viewDraft() { return readDraft(false); }
function adoptDraft() { return readDraft(true); }

function dismissDraft() {
  ++draftReadSequence;
  // 记住「这版草稿我忽略了」——下次打开不再提醒，草稿更新后重新提醒
  if (doc.value?.draft_updated_at) {
    const m = getDismissed();
    m[doc.value.id] = doc.value.draft_updated_at;
    localStorage.setItem(DISMISS_KEY, JSON.stringify(m));
  }
  draftBanner.value = null;
  draftPreview.value = null;
}

// ── 导出 ──
// 规则（老婆定的）：含本地附件 → 打包 zip（改写为相对路径）；纯文本 → 直接下对应格式
// 交互（老婆定的）：点导出 → 独立浮窗，左预览右选格式，确定才执行
const exportWin = ref(false);
const exportFormat = ref<"md" | "html" | "pdf" | "png">("md");
const ATTACH_RE = /\/attachments\/([0-9a-f-]{36})/g;

const FORMATS = [
  { key: "md", label: "Markdown", hint: "纯文本源文件，含本地图自动打 zip" },
  { key: "html", label: "HTML 网页", hint: "自带排版样式，含本地图自动打 zip" },
  { key: "pdf", label: "PDF", hint: "直接下载 PDF 文件，自动分页" },
  { key: "png", label: "PNG 长图", hint: "2x 清晰度整篇截图" },
] as const;

function confirmExport() {
  const f = exportFormat.value;
  if (f === "md") exportMd();
  else if (f === "html") exportHtml();
  else if (f === "pdf") doExportPdf();
  else doExportPng();
}

function download(filename: string, content: string | Blob, mime: string) {
  const blob = content instanceof Blob ? content : new Blob([content], { type: mime });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

function localAttachIds(): string[] {
  return [...new Set([...(content.value.matchAll(ATTACH_RE))].map((m) => m[1]))];
}

const EXPORT_CSS = "body{max-width:720px;margin:40px auto;padding:0 20px;font-family:-apple-system,Inter,\"PingFang SC\",sans-serif;line-height:1.75;color:#222;font-size:15px}h1{font-size:30px;margin:30px 0 14px;padding-bottom:10px;border-bottom:1px solid #eee}h2{font-size:24px;margin:26px 0 12px}h3{font-size:21px;margin:20px 0 9px}p{margin:10px 0}ul,ol{padding-left:24px;margin:10px 0}li{margin:4px 0}blockquote{border-left:3px solid #ccc;padding:4px 0 4px 14px;color:#666;margin:14px 0}hr{border:none;height:1px;background:#ddd;margin:20px 0}img{max-width:100%;border-radius:8px;margin:12px auto;display:block}code{background:#f4f4f4;padding:2px 6px;border-radius:4px;font-size:13px}pre{background:#f4f4f4;padding:14px 18px;border-radius:8px;overflow:auto;margin:14px 0}pre code{background:none;padding:0}";

function buildHtml(attachMap?: Map<string, string>) {
  let body = restorePrivateMediaHtml(rendered.value);
  if (attachMap) {
    for (const [id, fname] of attachMap) {
      body = body.replaceAll(`/attachments/${id}`, `attachments/${fname}`);
    }
  }
  return `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>${title.value}</title><style>${EXPORT_CSS}</style></head><body>${body}</body></html>`;
}

async function packZip(innerName: string, innerContent: string) {
  const { default: JSZip } = await import("jszip");
  const zip = new JSZip();
  const ids = localAttachIds();
  const map = new Map<string, string>();
  const folder = zip.folder("attachments")!;
  for (const id of ids) {
    const resp = await fetch(`/attachments/${id}`);
    const blob = await resp.blob();
    const ext = (blob.type.split("/")[1] || "bin").replace("svg+xml", "svg");
    const fname = `${id.slice(0, 8)}.${ext}`;
    folder.file(fname, blob);
    map.set(id, fname);
  }
  return { zip, map, innerName, innerContent };
}

async function exportMd() {
  exportWin.value = false;
  const base = title.value || "未命名";
  const ids = localAttachIds();
  if (!ids.length) {
    download(`${base}.md`, `# ${base}\n\n${content.value}`, "text/markdown");
    return;
  }
  let md = `# ${base}\n\n${content.value}`;
  const { zip, map, innerName } = await packZip(`${base}.md`, md);
  for (const [id, fname] of map) md = md.replaceAll(`/attachments/${id}`, `attachments/${fname}`);
  zip.file(innerName, md);
  download(`${base}-含附件.zip`, await zip.generateAsync({ type: "blob" }), "application/zip");
  toast("已打包导出（含本地图片）✓");
}

async function exportHtml() {
  exportWin.value = false;
  const base = title.value || "未命名";
  const ids = localAttachIds();
  if (!ids.length) {
    download(`${base}.html`, buildHtml(), "text/html");
    return;
  }
  const { zip, map, innerName } = await packZip(`${base}.html`, "");
  zip.file(innerName, buildHtml(map));
  download(`${base}-含附件.zip`, await zip.generateAsync({ type: "blob" }), "application/zip");
  toast("已打包导出（含本地图片）✓");
}

async function doExportPng() {
  const el = document.querySelector(".export-preview-body") as HTMLElement;
  if (!el) return;
  const { default: html2canvas } = await import("html2canvas");
  const canvas = await html2canvas(el, { backgroundColor: "#ffffff", scale: 2 });
  canvas.toBlob((b) => b && download(`${title.value || "未命名"}.png`, b, "image/png"));
  exportWin.value = false;
  toast("PNG 已导出 ✓");
}

async function doExportPdf() {
  const el = document.querySelector(".export-preview-body") as HTMLElement;
  if (!el) return;
  const { default: html2canvas } = await import("html2canvas");
  const { jsPDF } = await import("jspdf");

  const canvas = await html2canvas(el, { backgroundColor: "#ffffff", scale: 2 });
  const pdf = new jsPDF("p", "mm", "a4");
  const pageW = 210;
  const pageH = 297;
  const imgH = (canvas.height * pageW) / canvas.width;
  const imgData = canvas.toDataURL("image/jpeg", 0.92);

  // 长内容按 A4 分页切片
  let position = 0;
  pdf.addImage(imgData, "JPEG", 0, position, pageW, imgH);
  let remaining = imgH - pageH;
  while (remaining > 0) {
    position -= pageH;
    pdf.addPage();
    pdf.addImage(imgData, "JPEG", 0, position, pageW, imgH);
    remaining -= pageH;
  }
  pdf.save(`${title.value || "未命名"}.pdf`);
  exportWin.value = false;
  toast("PDF 已导出 ✓");
}

// ── 星标切换（轻量端点，不动 updated_at 不碰正在编辑的内容）──
async function toggleFav() {
  if (!doc.value) return;
  const updated = await toggleFavorite(doc.value.id);
  // 只更新星标状态和令牌，本地的 title/content 编辑现场不动
  doc.value = { ...updated };
  useNotesStore().refreshList();
}

// All editor/list/tree deletion uses the same choice and scope dialog.
function remove() {
  if (!doc.value) return;
  const store = useNotesStore();
  store.requestDelete(doc.value);
}

// Ctrl+S
function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") { closeOverlays(); moreButton.value?.focus(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === "f" && reading.value) { e.preventDefault(); void openFind(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === "s") {
    e.preventDefault();
    save();
  }
}
let listenersActive = false;
let activatedOnce = false;
function resumeEditor() {
  if (listenersActive || !ownsSession()) return;
  editorActive = true;
  listenersActive = true;
  onWinResize();
  nowTick.value = Date.now();
  window.addEventListener("keydown", onKey);
  window.addEventListener("resize", onWinResize);
  document.addEventListener("pointerdown", outsideMenu);
  tickTimer = setInterval(() => (nowTick.value = Date.now()), 30000); // 「几分钟前」自己走
  renderMermaid();
}
function pauseEditor() {
  editorActive = false;
  ++editorEpoch; ++draftReadSequence;
  invalidateDraftRequests();
  listenersActive = false;
  ++loadSequence;
  if (draftTimer) clearTimeout(draftTimer);
  draftTimer = null;
  window.removeEventListener("keydown", onKey);
  window.removeEventListener("resize", onWinResize);
  document.removeEventListener("pointerdown", outsideMenu);
  if (tickTimer) clearInterval(tickTimer);
  tickTimer = null;
}
watch(() => [store.workspaceId, auth.me?.id, auth.sessionGeneration, auth.requestEpoch, auth.suspended, auth.sessionClosing], () => {
  ++editorEpoch; ++draftReadSequence; ++loadSequence;
  resetDraftSource();
  if (draftTimer) clearTimeout(draftTimer);
  draftTimer = null;
}, {flush:"sync"});
onMounted(resumeEditor);
onActivated(() => {
  resumeEditor();
  if (activatedOnce && ownsSession()) void load(props.docId, true);
  activatedOnce = true;
});
onDeactivated(() => { versionsOpen.value=false; closeOverlays(); flushDraft(); pauseEditor(); });

function fmtDraftTime(iso: string) {
  return new Date(iso).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
</script>

<template>
  <div class="editor" v-if="doc">
    <VersionsPanel v-if="versionsOpen" :doc="doc" :dirty="dirty" @close="versionsOpen=false" @restored="onVersionRestored" />

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

    <!-- 面包屑：永远显示（工作区 / 祖先… / 当前），根级次级统一 -->
    <div class="breadcrumb">
      <button class="crumb root directory-button" @click="emit('directory')" aria-label="笔记目录"><Icon name="book" :size="11" /> {{ wsName }} ▾</button>
      <template v-for="b in breadcrumb" :key="b.id">
        <span class="sep">/</span>
        <span class="crumb" @click="emit('open', b.id)">{{ b.title }}</span>
      </template>

    </div>

    <div class="toolbar">
      <span class="page-kind" :title="childDocs.length ? '目录页' : '文章页'" :aria-label="childDocs.length ? '目录页' : '文章页'"><Icon :name="childDocs.length ? 'folder' : 'note'" :size="20" /></span>
      <!-- 编辑态：活的标题输入框；阅览态：纯文本（无光标，但允许选中复制） -->
      <textarea v-if="!reading" ref="titleEl" v-model="title" class="title-input" rows="1" aria-label="笔记标题" placeholder="无标题" @input="onTitleInput" @compositionend="onTitleInput" @keydown="titleKey" />
      <button v-else class="title-input title-readonly" title="展开完整标题" aria-label="展开完整标题" @click="fullTitleOpen=true">{{ title || "无标题" }}</button>
      <div class="actions">
        <button class="mode-toggle" @click="toggleReading"><Icon :name="reading ? 'edit' : 'eye'" :size="13" /> {{ reading ? "编辑" : "阅览" }}</button>
        <div class="more-wrap">
          <button ref="moreButton" class="mode-toggle more-toggle" aria-label="更多" :aria-expanded="moreOpen" aria-controls="note-more-menu" @click="moreOpen=!moreOpen">•••</button>
          <div v-if="moreOpen" id="note-more-menu" class="note-more-menu" aria-label="笔记操作">
            <button @click="menuAction(() => emit('directory'))">笔记目录与附件</button>
            <button :disabled="!tocItems.length" @click="menuAction(() => tocOpen=true)">大纲</button>
            <button @click="menuAction(openFind)">文内查找</button>
            <button @click="menuAction(() => versionsOpen=true)">版本历史</button>
            <button @click="menuAction(toggleFav)">{{ doc.is_favorite ? '取消星标' : '设为星标' }}</button>
            <button :disabled="templateBusy" @click="menuAction(toggleTemplate)">复制到模板目录</button>
            <button @click="menuAction(() => exportWin=true)">导出</button>
            <button @click="menuAction(() => infoOpen=true)">文档信息与标签</button>
            <button class="danger" @click="menuAction(remove)">删除</button>
          </div>
        </div>
      </div>
    </div>

    <AutoDirectory :docs="store.allDocs" :doc-id="doc.id" :workspace-id="doc.workspace_id" :user-id="ownerId || ''" :has-body="!!content.trim()" @open="emit('open', $event)" @create-child="newChildPage" />

    <!-- 标签栏：当前笔记的标签 + 添加 -->
    <div v-if="store.tagsOf(docId).length" class="tag-summary" aria-label="笔记标签"><button v-for="tag in store.tagsOf(docId)" :key="tag.id" @click="infoOpen = true">{{ tag.name }}</button></div>

    <!-- 工具栏（不记得语法也能写） -->
    <div v-show="!reading" class="edit-mode-tabs" role="group" aria-label="编辑方式">
      <button :class="{ active: editMode === 'rich' }" :aria-pressed="editMode === 'rich'" @click="switchEditMode('rich')">所见即所得</button>
      <button :class="{ active: editMode === 'markdown' }" :aria-pressed="editMode === 'markdown'" @click="switchEditMode('markdown')">Markdown</button>
    </div>
    <div v-show="!reading" class="editor-toolbar">
      <button
        v-for="(t, i) in toolbar"
        :key="t.text"
        class="tb-btn"
        :title="t.title"
        @mousedown.prevent="editMode === 'rich' ? richRef?.exec(richActions[i]!) : t.action()"
      >{{ t.text }}</button>
    </div>

    <div v-if="projectCopyPending" class="project-copy-status" role="status"><span>{{projectCopyBusy ? "正在独立复制图片…" : (projectCopyError || "图片复制待确认")}}</span> <button v-if="!projectCopyBusy" @click="projectCopy.retry">重试图片复制</button> <button :disabled="projectCopyBusy" @click="projectCopy.discard">取消这次插入</button><small>原项目文件不移动；取消不删除可能已经复制的附件。</small></div>
    <div class="panes" @dragover.capture="projectDragOver" @drop.capture="projectDrop" :class="reading ? 'preview-only' : (editMode === 'rich' ? 'rich-only' : (narrow ? 'edit-single' : 'split'))">
      <RichEditor v-if="richLoaded" v-show="!reading && editMode === 'rich'" ref="richRef" :key="doc.id" :doc-id="doc.id" v-model="content" @paste="onPaste" @drop="onDrop" />
      <div v-show="!reading && editMode === 'markdown'" class="input-wrap">
        <CmEditor
          ref="cmRef"
          v-model="content"
          @change="onCmChange"
          @paste="onPaste"
          @drop="onDrop"
          @scroll="onEditorScroll"
        />
        <!-- [[ 双链补全 -->
        <div v-if="suggestMode === 'link' && linkSuggests.length" class="suggests">
          <div
            v-for="s in linkSuggests"
            :key="s.id"
            class="sug"
            @mousedown.prevent="pickLink(s)"
          >{{ s.title }}</div>
        </div>
        <!-- / 斜杠命令 -->
        <div v-else-if="suggestMode === 'cmd' && cmdSuggests.length" class="suggests">
          <div
            v-for="c in cmdSuggests"
            :key="c.key"
            class="sug"
            @mousedown.prevent="pickCommand(c)"
          >{{ c.label }}</div>
        </div>
      </div>
      <!-- 窄屏编辑单栏：预览隐藏（要看预览切回阅览模式） -->
      <div v-show="reading || (editMode === 'markdown' && !narrow)" ref="previewEl" class="preview markdown-body" v-html="rendered" @click="onPreviewClick" />
    </div>

    <!-- Backlinks remain optional navigation, never injected into Markdown. -->
    <section v-if="backlinks.length" class="backlinks-panel">
      <button class="backlinks-toggle" :aria-expanded="backlinksOpen" @click="backlinksOpen = !backlinksOpen"><Icon name="link" :size="13" /><span>被 {{ backlinks.length }} 篇文章引用</span><Icon name="chevron" :size="12" /></button>
      <ul v-if="backlinksOpen" class="backlinks-list">
        <li v-for="b in backlinks" :key="b.id"><button @click="emit('open', b.id)"><Icon name="note" :size="13" /><span>{{b.title}}</span></button></li>
      </ul>
    </section>

    <!-- 常驻状态条：保存于几分钟前 · 字数 · 来源 -->
    <div v-if="!reading || dirty || saveError || remoteUnconfirmed" class="status-bar" :class="{error:saveError}" role="status" aria-live="polite">
      <span class="state">{{ statusLeft }}</span>
      <span v-if="!reading && editMode === 'markdown' && narrow" class="narrow-hint" title="窗口较窄，已自动切换为单栏（编辑只看编辑器）">单栏</span>
      <button v-if="dirty || saveError" class="retry-save" @click="save">重试保存</button>
    </div>

    <!-- TOC 大纲面板（从右缘把手滑出；点条目跳转后保持展开，» 丝滑收回） -->
    <div v-if="tocOpen" class="note-overlay-shade" @click="tocOpen=false" />
    <Transition name="toc">
      <div v-if="tocOpen && tocItems.length" class="toc-panel">
        <div class="toc-head">
          <span class="toc-title">大纲</span>
          <button class="toc-close" title="收起大纲" @click="tocOpen = false">»</button>
        </div>
        <!-- 标题栏固定，只有条目区滚动（标题/关闭按钮不再被滚出视野） -->
        <div class="toc-list">
          <div
            v-for="t in tocItems"
            :key="t.id"
            class="toc-item"
            :style="{ paddingLeft: 10 + (t.level - 1) * 14 + 'px' }"
            @click="jumpTo(t.id); tocOpen = false"
          >{{ t.text }}</div>
        </div>
      </div>
    </Transition>

    <div v-if="findOpen" class="note-find"><input v-model="findQuery" aria-label="文内查找" placeholder="查找正文" @input="findIndex=-1;findResult=''" @keydown.enter="findNext" /><button @click="findNext">下一处</button><span>{{ findResult }}</span><button aria-label="关闭查找" @click="findOpen=false">×</button></div>
    <div v-if="fullTitleOpen || infoOpen" class="note-dialog-mask" @click.self="closeOverlays">
      <section ref="infoDialog" class="note-info-dialog" role="dialog" aria-modal="true" :aria-label="fullTitleOpen ? '完整标题' : '文档信息'" tabindex="-1">
        <div class="note-dialog-head"><strong>{{ fullTitleOpen ? '完整标题' : '文档信息' }}</strong><button aria-label="关闭" @click="closeOverlays">×</button></div>
        <div class="note-dialog-body">
          <p class="full-title">{{ title || '无标题' }}</p>
          <template v-if="infoOpen"><p>{{ wordCount }} 字 · {{ statusLeft }}</p><p>创建：{{ doc.created_at }}</p><p>更新：{{ savedAt }}</p><p>来源：{{ deviceLabel }} <button @click="renameDevice">重命名来源</button></p><h3>标签</h3><TagBar :doc-id="docId" /></template>
        </div>
      </section>
    </div>
    <!-- 导出窗口：独立浮窗，左预览 / 右选格式 + 确定取消 -->
    <div v-if="exportWin" class="export-mask" @click.self="exportWin = false">
      <div class="export-window">
        <div class="ew-titlebar">
          <span class="ew-title">导出 · {{ title || "未命名" }}</span>
          <button class="ew-close" @click="exportWin = false">×</button>
        </div>
        <div class="ew-body">
          <!-- 左栏：预览 -->
          <div class="export-preview-body markdown-body">
            <h1>{{ title || "未命名" }}</h1>
            <div v-html="rendered"></div>
          </div>
          <!-- 右栏：格式选择 + 确定取消 -->
          <div class="ew-side">
            <div class="ew-side-title">导出格式</div>
            <label
              v-for="f in FORMATS"
              :key="f.key"
              class="fmt-opt"
              :class="{ on: exportFormat === f.key }"
            >
              <input type="radio" :value="f.key" v-model="exportFormat" />
              <span class="fmt-label">{{ f.label }}</span>
              <span class="fmt-hint">{{ f.hint }}</span>
            </label>
            <div class="ew-actions">
              <button class="confirm" @click="confirmExport">确定导出</button>
              <button class="cancel" @click="exportWin = false">取消</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.edit-mode-tabs { display: flex; gap: 3px; padding: 6px 16px; border-bottom: 1px solid var(--bg-raised); flex-shrink: 0; }
.edit-mode-tabs button { border: 0; background: transparent; color: var(--text-lo); padding: 6px 12px; border-radius: var(--radius-sm); font: inherit; font-size: 13px; cursor: pointer; }
.edit-mode-tabs button.active { background: var(--bg-raised); color: var(--accent); }
.panes.rich-only { display: flex; flex-direction: column; }
.editor {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-radius: 0 var(--radius) var(--radius) 0;
  overflow: hidden;
  position: relative;
}

/* TOC 右缘把手（收起态） */
.toc-strip {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 22px;
  height: 64px;
  display: grid;
  place-items: center;
  background: var(--bg-raised);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-right: none;
  border-radius: var(--radius-sm) 0 0 var(--radius-sm);
  color: var(--text-faint);
  cursor: pointer;
  z-index: 26;
  transition: all var(--transition);
}
.toc-strip:hover { color: var(--accent); width: 26px; }

/* TOC 大纲面板：从右缘把手处滑出（贴右缘浮出，不挤开内容） */
.toc-panel {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 210px;
  max-height: 60%;
  display: flex;
  flex-direction: column;
  background: var(--bg-raised);
  border: 1px solid var(--accent-dim);
  border-right: none;
  border-radius: var(--radius-sm) 0 0 var(--radius-sm);
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.55);
  z-index: 26;
  padding: 8px 0;
}
/* 标题栏固定 + 条目区独立滚动（标题/关闭按钮不被滚走） */
.toc-head { flex-shrink: 0; }
.toc-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
/* 展开/收起双向丝滑动画（慢一点更优雅） */
.toc-enter-active, .toc-leave-active {
  transition: transform 320ms cubic-bezier(0.22, 1, 0.36, 1), opacity 320ms ease;
}
.toc-enter-from, .toc-leave-to {
  transform: translateY(-50%) translateX(105%);
  opacity: 0;
}
.toc-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 12px 8px;
}
.toc-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-lo);
  letter-spacing: 1.5px;
}
/* 收起控件：小药丸 »，比 × 温柔 */
.toc-close {
  border: 1px solid var(--text-faint);
  background: transparent;
  color: var(--text-faint);
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
  padding: 3px 8px;
  border-radius: 999px;
  transition: all var(--transition);
}
.toc-close:hover {
  color: var(--accent);
  border-color: var(--accent-dim);
  background: var(--bg-panel);
}
.toc-item {
  font-size: 12.5px;
  color: var(--text-lo);
  padding: 5px 12px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: all var(--transition);
}
.toc-item:hover { background: var(--bg-panel); color: var(--accent); }

/* 导出窗口遮罩（组件内 scoped，之前用别处的 .mask 没样式 → 挤到文章下方） */
.export-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: grid;
  place-items: center;
  z-index: 100;
}

/* 导出窗口：独立浮窗（标题栏 + 左预览右格式），弹出带缩放动画不突兀 */
.export-window {
  width: min(880px, 94vw);
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--bg-raised);
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
  animation: win-in 220ms ease;
}
@keyframes win-in {
  from { transform: scale(0.96) translateY(10px); opacity: 0; }
  to { transform: scale(1) translateY(0); opacity: 1; }
}
.ew-titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  border-bottom: 1px solid var(--bg-raised);
  background: var(--bg-raised);
}
.ew-title { font-size: 13.5px; font-weight: 600; letter-spacing: 0.5px; }
.ew-close {
  border: none;
  background: transparent;
  color: var(--text-faint);
  font-size: 16px;
  cursor: pointer;
  padding: 0 4px;
}
.ew-close:hover { color: var(--pink); }

/* 双栏主体 */
.ew-body {
  flex: 1;
  display: flex;
  gap: 14px;
  padding: 14px 18px;
  overflow: hidden;
  min-height: 0;
}
.export-preview-body {
  flex: 1.4;
  overflow-y: auto;
  padding: 20px 24px;
  background: #ffffff;
  color: #222;
  border-radius: var(--radius-sm);
  font-family: -apple-system, Inter, "PingFang SC", sans-serif;
  line-height: 1.7;
  min-height: 220px;
}
.export-preview-body :deep(h1) { color: #222; margin: 0 0 12px; }
.export-preview-body :deep(*) { color: #222; }

.ew-side {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 210px;
}
.ew-side-title {
  font-size: 11px;
  color: var(--text-faint);
  letter-spacing: 1px;
  padding-bottom: 2px;
}
.fmt-opt {
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-rows: auto auto;
  column-gap: 8px;
  align-items: center;
  padding: 9px 12px;
  border: 1px solid var(--bg-raised);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition);
}
.fmt-opt:hover { border-color: var(--accent-dim); }
.fmt-opt.on { border-color: var(--accent); background: var(--bg-raised); }
.fmt-opt input { accent-color: var(--accent); margin: 0; grid-row: span 2; }
.fmt-label { font-size: 13px; color: var(--text-hi); }
.fmt-hint { font-size: 10.5px; color: var(--text-faint); }
.ew-actions {
  margin-top: auto;
  display: flex;
  gap: 8px;
  padding-top: 10px;
}
.ew-actions .confirm {
  flex: 1;
  padding: 9px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: var(--bg-base);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.ew-actions .cancel {
  padding: 9px 18px;
  border: 1px solid var(--text-faint);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-lo);
  font-size: 13px;
  cursor: pointer;
}

/* 窄屏：双栏改上下 */
@media (max-width: 768px) {
  .ew-body { flex-direction: column; overflow-y: auto; }
  .export-preview-body { min-height: 180px; max-height: 40vh; }
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
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 0.3px;
}
/* 阅览态标题：纯文本，无光标但可选中复制 */
.title-readonly {
  cursor: default;
  user-select: text;
  -webkit-user-select: text;
  padding: 1px 0; /* 对齐 input 的默认内边距 */
}
/* 阅览态正文：防任何光标色，选中复制照常 */
.panes.preview-only .preview {
  caret-color: transparent;
  user-select: text;
  -webkit-user-select: text;
}
.actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
/* 所有操作按钮统一 inline-flex，图标/文字/混合按钮都垂直居中——修手机端不齐 */
.actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 30px;
  box-sizing: border-box;
}
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
.export-wrap { position: relative; display: inline-flex; }
.export-menu {
  position: absolute;
  top: 34px;
  right: 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  background: var(--bg-raised);
  border: 1px solid var(--accent-dim);
  border-radius: var(--radius-sm);
  overflow: hidden;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}
.export-menu button {
  padding: 8px 16px;
  border: none;
  background: transparent;
  color: var(--text-lo);
  font-size: 12.5px;
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
}
.export-menu button:hover { background: var(--bg-panel); color: var(--accent); }
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
  padding: 8px 16px;
  font-size: 11.5px;
  color: var(--text-faint);
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  background: var(--bg-base);
}
.status-bar .state { color: var(--text-lo); }
.status-bar .narrow-hint {
  margin-left: 8px;
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid var(--accent-dim);
  color: var(--accent-dim);
  font-size: 10.5px;
  letter-spacing: 0.5px;
}
.status-bar .right { margin-left: auto; }
.status-bar .device { cursor: pointer; }
.status-bar .device:hover { color: var(--accent); }

.panes { flex: 1; display: flex; overflow: hidden; }

/* 窄屏编辑单栏：只显示编辑器，预览隐藏（预览只在阅览模式出现） */
.panes.edit-single .input-wrap { flex: 1; }

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
.crumb.root { color: var(--accent-dim); cursor: default; display: inline-flex; align-items: center; gap: 4px; }
.sep { opacity: 0.4; }

.page-kind { display: inline-flex; color: var(--accent); flex-shrink: 0; }
.backlinks-panel { flex-shrink: 0; padding: 6px 16px; border-top: 1px solid var(--bg-raised); }
.backlinks-toggle { display: flex; gap: 7px; align-items: center; padding: 5px 0; border: 0; background: transparent; color: var(--text-lo); font: inherit; font-size: 12px; cursor: pointer; }
.backlinks-list { list-style: none; padding: 4px 0; margin: 0; max-height: 140px; overflow: auto; }
.backlinks-list button { display: flex; align-items: center; gap: 7px; width: 100%; text-align: left; padding: 7px; border: 0; background: transparent; color: var(--accent); cursor: pointer; font: inherit; font-size: 12px; }
.backlinks-list button:hover { background: var(--bg-raised); }
.backlinks-list span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.input-wrap { position: relative; flex: 1; display: flex; }
.editor-toolbar {
  display: flex;
  gap: 4px;
  padding: 6px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  flex-wrap: wrap;
}
.tb-btn {
  min-width: 28px;
  padding: 4px 9px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-lo);
  font-size: 12.5px;
  cursor: pointer;
  transition: all var(--transition);
}
.tb-btn:hover { background: var(--bg-raised); color: var(--accent); }
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

/* 编辑双栏：预览跟随编辑器联动滚动，预览滚动条冗余 → 隐藏，只留编辑器一条（老婆定的） */
.panes.split .preview {
  scrollbar-width: none; /* Firefox */
}
.panes.split .preview::-webkit-scrollbar {
  display: none; /* Chrome/Safari */
}

/* markdown 渲染样式（字阶拉开 + 呼吸感，老婆验收版） */
.markdown-body {
  line-height: 1.75;
  font-size: 15px;
}
.markdown-body :deep(h1) {
  font-size: 30px;
  font-weight: 600;
  color: var(--text-hi);
  margin: 30px 0 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}
.markdown-body :deep(h2) {
  font-size: 24px;
  font-weight: 600;
  color: var(--accent);
  margin: 26px 0 12px;
}
.markdown-body :deep(h3) {
  font-size: 21px;
  font-weight: 600;
  color: var(--accent);
  margin: 20px 0 9px;
}
.markdown-body :deep(h4) {
  font-size: 18.5px;
  font-weight: 600;
  color: var(--text-lo);
  margin: 16px 0 7px;
}
.markdown-body :deep(h1:first-child), .markdown-body :deep(h2:first-child),
.markdown-body :deep(h3:first-child) { margin-top: 4px; }
.markdown-body :deep(p) { margin: 10px 0; }
.markdown-body :deep(code) {
  background: var(--bg-raised);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}
.markdown-body :deep(pre) {
  background: var(--bg-base);
  padding: 14px 18px;
  border-radius: var(--radius-sm);
  overflow-x: auto;
  margin: 14px 0;
}
.markdown-body :deep(pre code) { background: none; padding: 0; }
/* mermaid 流程图：可点击放大（cursor 提示），缩放到列宽 */
.markdown-body :deep(.mermaid) {
  cursor: zoom-in;
  margin: 14px 0;
  overflow-x: auto;
}
.markdown-body :deep(.mermaid svg) {
  max-width: 100%;
  height: auto;
}
.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--accent-dim);
  padding: 4px 0 4px 14px;
  color: var(--text-lo);
  margin: 14px 0;
}
.markdown-body :deep(ul), .markdown-body :deep(ol) {
  padding-left: 24px;
  margin: 10px 0;
}
.markdown-body :deep(li) { margin: 4px 0; }
.markdown-body :deep(li::marker) { color: var(--accent-dim); }
.markdown-body :deep(hr) {
  border: none;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent-dim), transparent);
  opacity: 0.4;
  margin: 20px 0;
}
.markdown-body :deep(a) { color: var(--pink); }
.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 14px 0;
  font-size: 14px;
}
.markdown-body :deep(th) {
  background: var(--bg-raised);
  color: var(--accent);
  font-weight: 600;
  text-align: left;
  padding: 8px 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.markdown-body :deep(td) {
  padding: 8px 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  color: var(--text-lo);
}
.markdown-body :deep(tr:nth-child(even) td) { background: rgba(255, 255, 255, 0.02); }
.markdown-body :deep(input[type="checkbox"]) {
  accent-color: var(--pink);
  margin-right: 4px;
}
.markdown-body :deep(img) {
  max-width: 100%;
  border-radius: var(--radius-sm);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.35);
  margin: 12px auto; /* 图片居中（老婆定的） */
  display: block;
  cursor: zoom-in; /* 悬浮提示可放大 */
  transition: transform var(--transition), box-shadow var(--transition);
}
.markdown-body :deep(img:hover) {
  transform: scale(1.015);
  box-shadow: 0 4px 20px rgba(201, 212, 232, 0.25);
}
/* 附件下载卡片：大图标 + 文件名在下，点击原样下载 */
.markdown-body :deep(.attach-card) {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 150px;
  margin: 14px auto; /* 附件居中 */
  padding: 16px 12px 12px;
  background: var(--bg-raised);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all var(--transition);
  color: var(--accent-dim);
}
.markdown-body :deep(.attach-card:hover) {
  border-color: var(--accent-dim);
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
}
.markdown-body :deep(.attach-card svg) {
  width: 40px;
  height: 40px;
}
.markdown-body :deep(.attach-card .attach-name) {
  font-size: 12px;
  color: var(--text-lo);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 移动端：标题和操作按钮换行排列，不挤压 */
@media (max-width: 768px) {
  .toolbar { flex-wrap: wrap; gap: 8px; padding: 10px 12px; }
  /* 标题独占整行（否则被按钮挤成竖排）。注意：媒体查询不加权重，本块在 .title-input 基础规则之前，
     必须用 .toolbar .title-input 提权重才能盖住后面的 flex:1（8.20 实锤竖排根因） */
  .toolbar .title-input { min-width: 0; flex: 1 1 100%; font-size: 17px; word-break: break-word; overflow-wrap: anywhere; }
  .editor-toolbar { padding: 6px 12px; overflow-x: auto; }
  .panes.split { flex-direction: column; }
  .panes.split .input-wrap { border-right: none; border-bottom: 1px solid rgba(255,255,255,0.05); }
  .breadcrumb { padding: 8px 12px 0; flex-wrap: wrap; row-gap: 4px; }
  /* 状态条：来源标签可能很长（IP+地名），允许换行 + 截断 */
  .status-bar { flex-wrap: wrap; row-gap: 2px; padding: 8px 12px; }
  .status-bar .device { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
/* Compact chrome and bounded long-title handling. Keep actions unwrapped. */
.editor,.panes,.input-wrap,.preview{min-width:0;min-height:0}
.toolbar{flex:0 0 auto;flex-wrap:nowrap;gap:10px;padding:7px 16px;align-items:start}
.toolbar .title-input{min-width:0;flex:1 1 0;width:0;font:inherit;font-size:20px;font-weight:600;line-height:1.4;letter-spacing:0;text-align:left;margin:0;padding:6px 0;overflow-wrap:anywhere;word-break:break-word}
.toolbar textarea.title-input{resize:none;max-height:112px;overflow-y:auto;box-sizing:border-box}
.toolbar .title-readonly{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer;padding-block:0}
.page-kind{padding-top:10px}
.actions{flex:0 0 auto;flex-wrap:nowrap;gap:6px}
.actions .mode-toggle{min-height:40px;height:40px;padding:0 10px;white-space:nowrap}
.more-wrap{position:relative}
.note-more-menu{position:absolute;right:0;top:44px;width:224px;max-width:calc(100vw - 32px);max-height:min(70dvh,440px);overflow-y:auto;z-index:80;padding:4px;border-radius:10px;background:var(--bg-raised);border:1px solid var(--accent-dim);box-shadow:0 12px 40px #0008}
.note-more-menu button{display:flex;justify-content:start;width:100%;min-height:44px;height:auto;border:0;background:transparent;color:var(--text-hi);font:inherit;font-size:14px;padding:10px 12px;border-radius:6px;text-align:left}
.note-more-menu button:hover{background:var(--bg-panel)}
.note-more-menu button:disabled{opacity:.45}
.note-more-menu .danger{color:var(--pink);border-top:1px solid var(--text-faint)}
.breadcrumb{flex:0 0 auto;flex-wrap:nowrap;white-space:nowrap;overflow:hidden;padding:3px 16px 0;min-width:0;height:31px;box-sizing:border-box}
.crumb{min-width:0;overflow:hidden;text-overflow:ellipsis;flex-shrink:1}
.crumb.root{flex-shrink:0;max-width:45%}
.crumb.root.directory-button{border:1px solid #e4bd88;border-radius:6px;background:#efd3ab;font:inherit;padding:2px 7px;color:#49351f;cursor:pointer;min-height:24px}
.crumb.root.directory-button:hover{background:#f5dfbf;color:#382712}
.directory-button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.preview{font-size:16px;line-height:1.8;overflow-wrap:anywhere}
.preview :deep(table){display:block;overflow-x:auto;max-width:100%}
.preview :deep(pre){white-space:pre;overflow-wrap:normal}
.tag-summary{display:flex;flex:0 0 auto;gap:5px;padding:2px 16px;overflow-x:auto}
.tag-summary button{border:0;border-radius:999px;background:var(--bg-raised);color:var(--accent);padding:3px 9px;font:inherit;font-size:11px;white-space:nowrap}
.status-bar{flex:0 0 auto;min-height:32px;gap:8px;padding:5px 12px}
.status-bar .state{overflow-wrap:anywhere}
.status-bar.error .state{color:var(--pink)}
.retry-save{flex-shrink:0;margin-left:auto;background:transparent;border:1px solid var(--accent-dim);color:var(--accent);border-radius:6px;min-height:32px}
.note-dialog-mask{position:fixed;inset:0;z-index:110;display:grid;place-items:center;background:#0009;padding:16px}
.note-info-dialog{width:min(600px,100%);max-height:82dvh;display:flex;flex-direction:column;min-width:0;background:var(--bg-panel);border:1px solid var(--accent-dim);border-radius:12px}
.note-dialog-head{display:flex;align-items:center;justify-content:space-between;padding:8px 16px;flex-shrink:0}
.note-dialog-head button{border:0;background:transparent;color:var(--text-hi);font-size:22px;width:44px;height:44px}
.note-dialog-body{overflow-y:auto;padding:0 16px 16px;overflow-wrap:anywhere;font-size:14px}
.full-title{white-space:pre-wrap;user-select:text}
.note-overlay-shade{position:absolute;inset:0;z-index:25;background:#0008}
.toc-panel{top:0;bottom:0;transform:none;max-height:none;width:min(300px,85%);border-radius:0}
.toc-close{min-height:40px;min-width:44px}
.toc-item{min-height:44px;display:flex;align-items:center;white-space:normal;overflow-wrap:anywhere}
.note-find{flex-shrink:0;display:flex;align-items:center;gap:6px;padding:6px 12px;background:var(--bg-raised);font-size:12px}
.note-find input{min-width:0;width:100%;background:var(--bg-panel);color:var(--text-hi);border:1px solid var(--accent-dim);border-radius:5px;padding:7px}
.note-find button{flex-shrink:0;min-height:36px;background:transparent;color:var(--accent);border:0;white-space:nowrap}
.ew-title{min-width:0;overflow-wrap:anywhere}.ew-close{flex-shrink:0}
@media(max-width:768px){
.toolbar{flex-wrap:nowrap;padding:6px 12px;gap:6px}
.toolbar .title-input{flex:1 1 0;font-size:17px;line-height:1.4}
.page-kind{display:none}
.breadcrumb{padding:2px 12px 0;flex-wrap:nowrap}
.preview{padding:8px 16px 20px}
.preview :deep(h1){font-size:27px}.preview :deep(h2){font-size:23px}
.editor-toolbar{flex-wrap:nowrap;flex-shrink:0;padding:3px 12px}.tb-btn{flex-shrink:0;min-height:36px}
.edit-mode-tabs{padding:3px 12px}.edit-mode-tabs button{min-height:36px}
.draft-banner{flex-wrap:wrap}
}
</style>
