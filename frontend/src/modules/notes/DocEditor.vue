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
import { openLightbox } from "../../composables/useLightbox";
import Icon from "../../shell/Icon.vue";
import TagBar from "./TagBar.vue";

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
const reading = ref(true); // 默认阅览模式（老婆的定稿），编辑双栏/阅览纯预览切换

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

const rendered = computed(() => {
  let html = marked.parse(content.value || "", { breaks: true }) as string;
  let hIdx = 0;
  html = html.replace(/<h([123])>/g, (_m, lv) => `<h${lv} id="toc-h${hIdx++}">`);
  // 附件链接 → 下载卡片
  html = html.replace(
    /<a href="\/attachments\/([0-9a-f-]{36})">([^<]*)<\/a>/g,
    (_m, id, name) => attachCardHtml(id, name)
  );
  html = html.replace(
    /\[\[([^\[\]]+)\]\]/g,
    '<a class="wikilink" data-title="$1">$1</a>'
  );
  return html;
});

// ── TOC 大纲 ──
const tocOpen = ref(false);
const tocItems = computed(() => {
  const items: { level: number; text: string; id: string }[] = [];
  const re = /^(#{1,3})\s+(.+)$/gm;
  let m;
  let i = 0;
  while ((m = re.exec(content.value || ""))) {
    items.push({ level: m[1].length, text: m[2].trim(), id: `toc-h${i++}` });
  }
  return items;
});

function jumpTo(id: string) {
  const preview = document.querySelector(".preview");
  const target = preview?.querySelector(`#${id}`);
  target?.scrollIntoView({ behavior: "smooth", block: "start" });
}

// 点预览：附件卡下载 / wikilink 跳转 / 图片放大
function onPreviewClick(e: MouseEvent) {
  const card = (e.target as HTMLElement).closest(".attach-card") as HTMLElement | null;
  if (card) {
    // 原原本本下载（download 属性强制保存，不打开预览）
    const a = document.createElement("a");
    a.href = card.dataset.url!;
    a.download = card.dataset.name || "";
    a.click();
    return;
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

// ── 工具栏 ──
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
  const isImg = file.type.startsWith("image/");
  const name = file.name || "paste.png";
  const placeholder = isImg ? `![上传中 ${name}…]()` : `[上传中 ${name}…]()`;
  content.value = content.value.slice(0, insertAt) + placeholder + content.value.slice(insertAt);

  const form = new FormData();
  form.append("file", file, name);
  try {
    const resp = await fetch(`/attachments/${doc.value.id}`, { method: "POST", body: form });
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
    content.value = content.value.replace(
      placeholder,
      isImg ? `![${filename}](${url})` : `[${filename}](${url})`
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

// 当前工作区名（面包屑第一级）
const wsName = computed(() =>
  store.workspaces.find((w) => w.id === store.workspaceId)?.name ?? "笔记本"
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
  loadAttachMeta();
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

const EXPORT_CSS = "body{max-width:720px;margin:40px auto;padding:0 20px;font-family:-apple-system,Inter,\"PingFang SC\",sans-serif;line-height:1.75;color:#222;font-size:15px}h1{font-size:24px;margin:26px 0 12px;padding-bottom:8px;border-bottom:1px solid #eee}h2{font-size:19px;margin:22px 0 10px}h3{font-size:16.5px;margin:18px 0 8px}p{margin:10px 0}ul,ol{padding-left:24px;margin:10px 0}li{margin:4px 0}blockquote{border-left:3px solid #ccc;padding:4px 0 4px 14px;color:#666;margin:14px 0}hr{border:none;height:1px;background:#ddd;margin:20px 0}img{max-width:100%;border-radius:8px;margin:12px 0}code{background:#f4f4f4;padding:2px 6px;border-radius:4px;font-size:13px}pre{background:#f4f4f4;padding:14px 18px;border-radius:8px;overflow:auto;margin:14px 0}pre code{background:none;padding:0}";

function buildHtml(attachMap?: Map<string, string>) {
  let body = rendered.value;
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

    <!-- 面包屑：永远显示（工作区 / 祖先… / 当前），根级次级统一 -->
    <div class="breadcrumb">
      <span class="crumb root"><Icon name="book" :size="11" /> {{ wsName }}</span>
      <template v-for="b in breadcrumb" :key="b.id">
        <span class="sep">/</span>
        <span class="crumb" @click="emit('open', b.id)">{{ b.title }}</span>
      </template>
      <span class="sep">/</span>
      <span class="crumb current">{{ doc.title }}</span>
    </div>

    <div class="toolbar">
      <!-- 编辑态：活的标题输入框；阅览态：纯文本（无光标，但允许选中复制） -->
      <input v-if="!reading" v-model="title" class="title-input" placeholder="无标题" />
      <div v-else class="title-input title-readonly">{{ title || "无标题" }}</div>
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
        <button class="mode-toggle" @click="exportWin = true">
          <Icon name="move" :size="13" style="transform:rotate(90deg)" /> 导出
        </button>
        <button class="del-btn" @click="remove">删除</button>
      </div>
    </div>

    <!-- 标签栏：当前笔记的标签 + 添加 -->
    <TagBar :doc-id="docId" />

    <!-- 工具栏（不记得语法也能写） -->
    <div v-show="!reading" class="editor-toolbar">
      <button
        v-for="t in toolbar"
        :key="t.text"
        class="tb-btn"
        :title="t.title"
        @mousedown.prevent="t.action()"
      >{{ t.text }}</button>
    </div>

    <div class="panes" :class="reading ? 'preview-only' : 'split'">
      <div v-show="!reading" class="input-wrap">
        <CmEditor
          ref="cmRef"
          v-model="content"
          @change="onCmChange"
          @paste="onPaste"
          @drop="onDrop"
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

    <!-- TOC 右缘把手（默认收着，有标题才出现） -->
    <div
      v-if="!tocOpen && tocItems.length"
      class="toc-strip"
      title="展开大纲"
      @click="tocOpen = true"
    >‹</div>

    <!-- TOC 大纲面板（从右缘把手滑出；点条目跳转后保持展开，» 丝滑收回） -->
    <Transition name="toc">
      <div v-if="tocOpen && tocItems.length" class="toc-panel">
        <div class="toc-head">
          <span class="toc-title">大纲</span>
          <button class="toc-close" title="收起大纲" @click="tocOpen = false">»</button>
        </div>
        <div
          v-for="t in tocItems"
          :key="t.id"
          class="toc-item"
          :style="{ paddingLeft: 10 + (t.level - 1) * 14 + 'px' }"
          @click="jumpTo(t.id)"
        >{{ t.text }}</div>
      </div>
    </Transition>

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
  overflow-y: auto;
  background: var(--bg-raised);
  border: 1px solid var(--accent-dim);
  border-right: none;
  border-radius: var(--radius-sm) 0 0 var(--radius-sm);
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.55);
  z-index: 26;
  padding: 8px 0;
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

/* 移动端：标题和操作按钮换行排列，不挤压 */
@media (max-width: 768px) {
  .toolbar { flex-wrap: wrap; gap: 8px; padding: 10px 12px; }
  .title-input { min-width: 0; flex: 1 1 100%; font-size: 15px; }
  .editor-toolbar { padding: 6px 12px; }
  .panes.split { flex-direction: column; }
  .panes.split .input-wrap { border-right: none; border-bottom: 1px solid rgba(255,255,255,0.05); }
  .breadcrumb { padding: 8px 12px 0; }
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
.crumb.root { color: var(--accent-dim); cursor: default; display: inline-flex; align-items: center; gap: 4px; }
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

/* markdown 渲染样式（字阶拉开 + 呼吸感，老婆验收版） */
.markdown-body {
  line-height: 1.75;
  font-size: 15px;
}
.markdown-body :deep(h1) {
  font-size: 24px;
  font-weight: 600;
  color: var(--text-hi);
  margin: 26px 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}
.markdown-body :deep(h2) {
  font-size: 19px;
  font-weight: 600;
  color: var(--accent);
  margin: 22px 0 10px;
}
.markdown-body :deep(h3) {
  font-size: 16.5px;
  font-weight: 600;
  color: var(--accent);
  margin: 18px 0 8px;
}
.markdown-body :deep(h4) {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-lo);
  margin: 14px 0 6px;
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
.markdown-body :deep(img) {
  max-width: 100%;
  border-radius: var(--radius-sm);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.35);
  margin: 12px auto; /* 图片居中（老婆定的） */
  display: block;
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
</style>
