<script setup lang="ts">
import { ref, onMounted, onUnmounted, onActivated, onDeactivated, nextTick } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { storeToRefs } from "pinia";
import { useNotesStore, type TreeNode } from "../../stores/notes";
import DocList from "./DocList.vue";
import DocEditor from "./DocEditor.vue";
import TrashPanel from "./TrashPanel.vue";
import AttachmentsPanel from "./AttachmentsPanel.vue";
import GraphPanel from "./GraphPanel.vue";
import MoveDialog from "./MoveDialog.vue";
import ImportDialog from "./ImportDialog.vue";
import { auth } from "../home/auth";
import { isImportFilename, type ImportSource } from './import-helpers';

defineOptions({ name: 'NotesPage' });
const pageRoot = ref<HTMLElement | null>(null);
let scrollSnapshot: [HTMLElement, number, number][] = [];
onBeforeRouteLeave(() => {
  scrollSnapshot = Array.from(pageRoot.value?.querySelectorAll<HTMLElement>('.rich-editor,.cm-scroller,.preview,.items,.toc-list') ?? [])
    .map(el => [el, el.scrollTop, el.scrollLeft]);
});
const store = useNotesStore();
if (store.userId !== auth.me?.id) store.resetSession();
const { pendingDelete } = storeToRefs(store);
const currentId = ref<string | null>(null);
const LS_CURRENT = "stella_current_doc";
const trashOpen = ref(false);
const attachOpen = ref(false);
const graphOpen = ref(false);
const ready = ref(false);
const initError = ref('');
const active = ref(true);
const moving = ref<TreeNode | null>(null);
const importInput = ref<HTMLInputElement | null>(null);
const importing = ref<{ files: ImportSource[]; workspaceId: string; parentId: string | null } | null>(null);
const importBusy = ref(false);
function openImport(files: ImportSource[], parentId: string | null = null) {
  if (!files.length || importing.value || !store.workspaceId) return;
  importing.value = { files, workspaceId: store.workspaceId, parentId };
}
function pickedFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  openImport(Array.from(input.files ?? []));
  input.value = ''; // Picking the same filename again must work.
}
function captureDragOver(event: DragEvent) {
  if (store.draggingId || !event.dataTransfer?.types.includes('Files')) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'copy';
}
function captureDrop(event: DragEvent) {
  if (store.draggingId || !event.dataTransfer) return;
  const files: ImportSource[] = Array.from(event.dataTransfer.files);
  for (const item of Array.from(event.dataTransfer.items)) {
    const entry = item.webkitGetAsEntry?.();
    if (entry?.isDirectory) files.push({ name: entry.name, size: 0, isDirectory: true, arrayBuffer: async () => new ArrayBuffer(0) });
  }
  if (!files.length) return;
  const element = event.target instanceof Element ? event.target : null;
  const inList = !!element?.closest('.doc-list');
  // Only Markdown/text imports override editor drops; all other files retain attachments.
  if (!inList && !files.some(file => isImportFilename(file.name) || file.isDirectory)) return;
  event.preventDefault();
  event.stopPropagation(); // Never append imported Markdown to an open draft.
  const parentId = inList ? element?.closest<HTMLElement>('[data-import-parent]')?.dataset.importParent ?? null : null;
  openImport(files, parentId);
}

// 列表栏折叠（桌面记忆 + 移动端抽屉）
const listCollapsed = ref(
  localStorage.getItem("stella_list_fold") === "1" || window.innerWidth <= 768
);
function toggleList() {
  listCollapsed.value = !listCollapsed.value;
  localStorage.setItem("stella_list_fold", listCollapsed.value ? "1" : "0");
}

// 列表频道：任何文档变动（保存/新建/删除/还原）→ 刷新列表 + 回收站
let listWs: WebSocket | null = null;
let listWsTimer: ReturnType<typeof setTimeout> | null = null;
let listWsDead = false;

function connectListWs() {
  if (!store.workspaceId || listWsDead) return;
  if (listWs && listWs.readyState <= WebSocket.OPEN) return; // 已有活连接不重复开
  const proto = location.protocol === "https:" ? "wss" : "ws";
  listWs = new WebSocket(`${proto}://${location.host}/ws/list/${store.workspaceId}`);
  listWs.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "list_changed") {
        if (importBusy.value) return; // ImportDialog refreshes once after the batch.
        store.refreshList();
        store.refreshTrash();
      }
    } catch {
      /* 忽略坏消息 */
    }
  };
  const socket = listWs;
  listWs.onclose = () => {
    if (listWs !== socket) return;
    listWs = null;
    if (!listWsDead) listWsTimer = setTimeout(connectListWs, 3000);
  };
}

function stopListWs() {
  listWsDead = true;
  if (listWsTimer) clearTimeout(listWsTimer);
  listWsTimer = null;
  if (listWs) { listWs.onclose = null; listWs.onmessage = null; listWs.close(); }
  listWs = null;
}
async function initialize() {
  initError.value = '';
  try {
    await store.bootstrap();
    const saved = localStorage.getItem(LS_CURRENT);
    currentId.value = saved && store.docs.some(d => d.id === saved) ? saved : store.docs[0]?.id ?? null;
    ready.value = true;
    if (active.value) { listWsDead = false; connectListWs(); }
  } catch { initError.value = '笔记加载失败，请重试喵~'; }
}
onMounted(initialize);
onActivated(() => {
  active.value = true;
  void nextTick(() => { for (const [el, top, left] of scrollSnapshot) { el.scrollTop = top; el.scrollLeft = left; } });
  if (!ready.value) return; // Initial activation is handled by initialize.
  listWsDead = false;
  connectListWs();
  void Promise.allSettled([store.refreshList(), store.refreshRecent(), store.refreshWorkspaces(), store.refreshTags()]);
});
onDeactivated(() => { active.value = false; stopListWs(); });
onUnmounted(() => { active.value = false; stopListWs(); });

// 切换工作区 → 列表频道重连 + 关掉所有面板（图谱/附件/回收站都是旧工作区的数据）+ 打开新工作区的第一篇
async function onWsSwitched() {
  stopListWs();
  listWsDead = !active.value;
  connectListWs();
  trashOpen.value = false;
  attachOpen.value = false;
  graphOpen.value = false;
  currentId.value = store.docs[0]?.id ?? null;
  if (currentId.value) localStorage.setItem(LS_CURRENT, currentId.value);
}

async function onOpen(id: string) {
  trashOpen.value = false;
  attachOpen.value = false;
  graphOpen.value = false;
  currentId.value = id;
  localStorage.setItem(LS_CURRENT, id); // 记住正在看的
  // 移动端打开笔记后自动收起列表抽屉
  if (window.innerWidth <= 768) listCollapsed.value = true;
  // 打开 → 服务端已戳 last_viewed_at，稍后刷新最近查看
  setTimeout(() => store.refreshRecent(), 300);
}

async function onNewChild(node: TreeNode | null) {
  trashOpen.value = false;
  const doc = await store.createNew(node ? node.id : undefined);
  currentId.value = doc.id;
}

function onMove(node: TreeNode) {
  moving.value = node;
}

function onDel(node: TreeNode) {
  store.requestDelete(node as any);
}

function onSaved() {
  store.refreshList();
}

function onDeleted() {
  currentId.value = store.docs[0]?.id ?? null;
}
</script>

<template>
  <div ref="pageRoot" class="notes-page" :aria-busy="!ready" @dragover.capture="captureDragOver" @drop.capture="captureDrop">
    <input ref="importInput" type="file" accept=".md,.txt" multiple hidden @change="pickedFiles" />
    <ImportDialog v-if="importing" v-bind="importing" @busy="importBusy = $event" @close="importing = null" />
    <!-- 列表收起时的窄条把手 -->
    <div v-if="listCollapsed" class="list-strip" title="展开列表" @click="toggleList">»</div>
    <DocList
      v-show="!listCollapsed" :style="!ready ? { pointerEvents: 'none', opacity: .65 } : undefined"
      :current-id="currentId"
      :trash-open="trashOpen"
      :attach-open="attachOpen"
      :graph-open="graphOpen"
      @open="onOpen"
      @show-trash="trashOpen = true; attachOpen = false; graphOpen = false"
      @show-attachments="attachOpen = true; trashOpen = false; graphOpen = false"
      @show-graph="graphOpen = true; trashOpen = false; attachOpen = false"
      @new-child="onNewChild"
      @move="onMove"
      @del="onDel"
      @switched="onWsSwitched"
      @fold="toggleList"
      @import="importInput?.click()"
    />
    <GraphPanel v-if="graphOpen" @close="graphOpen = false" @open="onOpen" />
    <AttachmentsPanel v-else-if="attachOpen" @close="attachOpen = false" @open="onOpen" />
    <TrashPanel v-else-if="trashOpen" @close="trashOpen = false" />
    <DocEditor
      v-else-if="currentId"
      :key="currentId"
      :doc-id="currentId"
      @saved="onSaved"
      @deleted="onDeleted"
      @open="onOpen"
    />
    <div v-else class="blank">
      <div class="blank-icon">📝</div>
      <p>{{ initError || (ready ? '选一篇，或者新建一篇开始写' : '正在载入笔记…') }}</p>
      <button v-if="initError" @click="initialize">重试</button>
    </div>

    <!-- 移动对话框 -->
    <MoveDialog v-if="moving" :node="moving" @done="moving = null" @cancel="moving = null" />

    <!-- 删除三选框（有下挂时） -->
    <div v-if="pendingDelete" class="mask" @click.self="pendingDelete = null">
      <div class="dialog">
        <div class="head">删除「{{ pendingDelete.doc.title }}」</div>
        <div class="body">这篇下面还挂着 {{ pendingDelete.childCount }} 篇子页面，怎么处理？</div>
        <div class="btns">
          <button class="danger" @click="store.doDelete(pendingDelete.doc.id, true).then(onDeleted)">
            一起删除（{{ pendingDelete.childCount + 1 }} 篇进回收站）
          </button>
          <button @click="store.doDelete(pendingDelete.doc.id, false).then(onDeleted)">
            仅删此篇 · 子页上移一级
          </button>
          <button class="cancel" @click="pendingDelete = null">取消</button>
        </div>
      </div>
    </div>
  </div>

</template>

<style scoped>
.notes-page {
  display: flex;
  height: calc(100vh - 56px);
  border-radius: var(--radius);
  overflow: hidden;
  position: relative;
}
.blank {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: var(--bg-panel);
  border-radius: 0 var(--radius) var(--radius) 0;
  color: var(--text-faint);
}
.blank-icon { font-size: 36px; opacity: 0.6; }
.loading { height: 100%; display: grid; place-items: center; color: var(--text-faint); }

/* 列表收起窄条把手 */
.list-strip {
  width: 26px;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  background: var(--bg-panel);
  border-radius: var(--radius) 0 0 var(--radius);
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  color: var(--text-faint);
  cursor: pointer;
  transition: all var(--transition);
}
.list-strip:hover { color: var(--accent); background: var(--bg-raised); }
@media (max-width: 768px) {
  .list-strip {
    position: fixed;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    height: 64px;
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    z-index: 75;
    box-shadow: 2px 0 10px rgba(0, 0, 0, 0.35);
  }
}

.mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: grid;
  place-items: center;
  z-index: 100;
}
.dialog {
  width: 380px;
  background: var(--bg-panel);
  border: 1px solid var(--bg-raised);
  border-radius: var(--radius);
  overflow: hidden;
}
.head { padding: 14px 18px; font-size: 14px; font-weight: 600; }
.body { padding: 0 18px 14px; font-size: 13px; color: var(--text-lo); }
.btns { display: flex; flex-direction: column; gap: 8px; padding: 0 18px 16px; }
.btns button {
  padding: 9px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--accent-dim);
  background: transparent;
  color: var(--accent);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--transition);
}
.btns button:hover { background: var(--bg-raised); }
.btns button.danger { border-color: var(--pink); color: var(--pink); }
.btns button.cancel { border-color: var(--text-faint); color: var(--text-faint); }
</style>
