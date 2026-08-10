<script setup lang="ts">
import { ref, computed } from "vue";
import { storeToRefs } from "pinia";
import { useNotesStore, buildTree, type TreeNode } from "../../stores/notes";
import DocTreeNode from "./DocTreeNode.vue";
import Icon from "../../shell/Icon.vue";
import { toast } from "../../composables/useToast";

const emit = defineEmits<{
  open: [id: string];
  showTrash: [];
  showAttachments: [];
  showGraph: [];
  newChild: [node: TreeNode | null];
  move: [node: TreeNode];
  del: [node: TreeNode];
  switched: [];
  fold: [];
}>();
const props = defineProps<{ currentId: string | null; trashOpen: boolean; attachOpen: boolean; graphOpen: boolean }>();

const store = useNotesStore();
// 标签筛选状态从 store 读取（由搜索栏的高级筛选面板驱动，列表栏不再放标签行）
const { docs, recent, searchQuery, searching, workspaces, workspaceId, tags, docTags, filterTagId } = storeToRefs(store);

// 筛选结果：标签 + 文本搜索可叠加（标签客户端筛，文本走后端搜索）
const tagFilteredDocs = computed(() => {
  if (!filterTagId.value) return docs.value;
  const ids = new Set(docTags.value.filter((r) => r.tag_id === filterTagId.value).map((r) => r.doc_id));
  return docs.value.filter((d) => ids.has(d.id));
});

// 平铺展示条件：搜索中 或 有标签筛选
const flatMode = computed(() => searching.value || !!filterTagId.value);

// ── 工作区切换器 ──
const wsMenuOpen = ref(false);
const currentWsName = computed(() =>
  workspaces.value.find((w) => w.id === workspaceId.value)?.name ?? "…"
);
async function switchWs(id: string) {
  wsMenuOpen.value = false;
  await store.switchWorkspace(id);
  emit("switched");
}
async function onNewWs() {
  const name = prompt("新工作区名字", "");
  if (name?.trim()) {
    wsMenuOpen.value = false;
    await store.addWorkspace(name.trim());
    emit("switched");
  }
}
async function onRenameWs() {
  const name = prompt("重命名工作区", currentWsName.value);
  if (name?.trim()) {
    wsMenuOpen.value = false;
    await store.renameCurrentWorkspace(name.trim());
  }
}
async function onDeleteWs() {
  wsMenuOpen.value = false;
  wsDeleteStep.value = "confirm"; // 第一次确认（点菜单=第一次，弹窗=第二次）
}

// 工作区删除弹窗状态：confirm 普通确认 / force 有笔记警告 / none 关闭
const wsDeleteStep = ref<"none" | "confirm" | "force">("none");

async function confirmDeleteWs(force: boolean) {
  const result = await store.deleteCurrentWorkspace(force);
  if (result === "has_trash") {
    wsDeleteStep.value = "force"; // 升级成回收站警告
  } else if (result === "not_empty") {
    wsDeleteStep.value = "none";
    toast("工作区里还有笔记，先清空再删");
  } else if (result === "deleted") {
    wsDeleteStep.value = "none";
    toast("工作区已删除");
    emit("switched");
  } else {
    wsDeleteStep.value = "none";
    toast("删除失败，稍后再试");
  }
}

// ── 区块折叠：⭐ 默认折叠 / 🕘 最近查看默认展开 / 全部笔记默认展开 ──
const LS_SECTIONS = "stella_sections";
const sections = ref<Record<string, boolean>>({
  ...{ fav: false, recent: true, tree: true },  // 默认值
  ...JSON.parse(localStorage.getItem(LS_SECTIONS) || "{}"),
});
function toggleSection(key: string) {
  sections.value[key] = !sections.value[key];
  localStorage.setItem(LS_SECTIONS, JSON.stringify(sections.value));
}

// 树：客户端从平铺列表构建
const tree = computed(() => buildTree(docs.value));
const favorites = computed(() => docs.value.filter((d) => d.is_favorite));

// 折叠状态记忆（localStorage）
const LS_EXPANDED = "stella_tree_expanded";
const expanded = ref<Set<string>>(new Set(JSON.parse(localStorage.getItem(LS_EXPANDED) || "[]")));
function toggle(id: string) {
  const s = new Set(expanded.value);
  if (s.has(id)) s.delete(id);
  else s.add(id);
  expanded.value = s;
  localStorage.setItem(LS_EXPANDED, JSON.stringify([...s]));
}

// 搜索命中高亮：关键词包 <mark>
function hl(text: string): string {
  const q = searchQuery.value.trim();
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return text;
  return (
    text.slice(0, i) +
    '<mark class="hl">' +
    text.slice(i, i + q.length) +
    "</mark>" +
    text.slice(i + q.length)
  );
}

// 高级筛选面板状态
const filterOpen = ref(false);
const usedTags = computed(() => {
  const used = new Set(docTags.value.map((r) => r.tag_id));
  return tags.value.filter((t) => used.has(t.id));
});
function toggleTag(id: string) {
  filterTagId.value = filterTagId.value === id ? null : id;
}
function clearFilters() {
  searchQuery.value = "";
  filterTagId.value = null;
  store.refreshList();
  filterOpen.value = false;
}

// ── 拖拽换父级 ──
async function onDropOnNode(target: TreeNode) {
  const id = store.draggingId;
  if (!id) return;
  const doc = store.docs.find((d) => d.id === id);
  if (doc) await store.moveTo(doc, target.id);
}

function onListDragOver(e: DragEvent) {
  // 落在节点行上由节点自己处理；其余区域都算「回根级」的合法落点
  if ((e.target as HTMLElement).closest(".row")) return;
  if (!store.draggingId) return;
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
}

async function onDropToRoot(e: DragEvent) {
  // 落在节点行上由节点自己处理（挂为子页），别抢
  if ((e.target as HTMLElement).closest(".row")) return;
  const id = e.dataTransfer?.getData("text/plain") || store.draggingId;
  if (!id) return;
  e.preventDefault();
  const doc = store.docs.find((d) => d.id === id);
  if (doc && doc.parent_id) await store.moveTo(doc, null);
  store.draggingId = null;
}

let debounceTimer: ReturnType<typeof setTimeout> | null = null;
function onSearchInput() {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => store.refreshList(), 300);
}
</script>

<template>
  <div class="doc-list">
    <!-- 工作区切换器 -->
    <div class="ws-switcher">
      <button class="ws-current" @click="wsMenuOpen = !wsMenuOpen">
        <span class="ws-name">{{ currentWsName }}</span>
        <span class="ws-caret" :class="{ open: wsMenuOpen }">▾</span>
      </button>
      <button class="fold-list-btn" title="收起列表" @click="emit('fold')">«</button>
      <div v-if="wsMenuOpen" class="ws-menu">
        <div
          v-for="w in workspaces"
          :key="w.id"
          class="ws-opt"
          :class="{ on: w.id === workspaceId }"
          @click="switchWs(w.id)"
        >{{ w.name }}</div>
        <div class="ws-divider" />
        <div class="ws-opt action" @click="onNewWs"><Icon name="plus" :size="13" /> 新建工作区</div>
        <div class="ws-opt action" @click="onRenameWs"><Icon name="edit" :size="13" /> 重命名工作区</div>
        <div class="ws-opt action danger" @click="onDeleteWs"><Icon name="trash" :size="13" /> 删除工作区</div>
      </div>
    </div>

    <!-- 搜索栏 + 高级筛选按钮（悬浮面板：文本 + 标签） -->
    <div class="search-box">
      <input
        v-model="searchQuery"
        placeholder="搜索标题和正文…"
        @input="onSearchInput"
      />
      <button
        class="filter-btn"
        :class="{ on: filterOpen || filterTagId }"
        title="高级筛选"
        @click="filterOpen = !filterOpen"
      >⚙</button>

      <!-- 高级筛选悬浮面板 -->
      <div v-if="filterOpen" class="filter-panel">
        <div class="fp-label">文本</div>
        <input
          v-model="searchQuery"
          class="fp-input"
          placeholder="标题 / 正文关键词…"
          @input="onSearchInput"
        />
        <div class="fp-label">标签</div>
        <div class="fp-tags">
          <span
            v-for="t in usedTags"
            :key="t.id"
            class="ftag"
            :class="{ on: filterTagId === t.id }"
            :style="t.color && filterTagId !== t.id ? { color: t.color } : {}"
            @click="toggleTag(t.id)"
          >{{ t.name }}</span>
          <span v-if="!usedTags.length" class="fp-none">还没有标签</span>
        </div>
        <div class="fp-foot">
          <button class="fp-clear" @click="clearFilters">清除筛选</button>
          <button class="fp-done" @click="filterOpen = false">完成</button>
        </div>
      </div>
    </div>

    <button class="new-btn" @click="emit('newChild', null)"><Icon name="plus" :size="13" /> 新建笔记</button>

    <div class="items" @dragover="onListDragOver" @drop="onDropToRoot">
      <!-- 筛选中（文本搜索 / 标签 / 叠加）：平铺结果 -->
      <template v-if="flatMode">
        <div v-if="searching && filterTagId" class="search-hint">
          <span class="hint-text">「{{ searchQuery }}」+ 标签「{{ tags.find(t => t.id === filterTagId)?.name }}」</span>
          <button class="reset-btn" @click="clearFilters">重置 ✕</button>
        </div>
        <div v-else-if="filterTagId" class="search-hint">
          <span class="hint-text">标签「{{ tags.find(t => t.id === filterTagId)?.name }}」的笔记</span>
          <button class="reset-btn" @click="clearFilters">重置 ✕</button>
        </div>
        <div v-else-if="searching" class="search-hint">
          <span class="hint-text">搜索「{{ searchQuery }}」的结果</span>
          <button class="reset-btn" @click="clearFilters">重置 ✕</button>
        </div>
        <div
          v-for="doc in tagFilteredDocs"
          :key="doc.id"
          class="flat-item with-path"
          :class="{ active: doc.id === props.currentId }"
          @click="emit('open', doc.id)"
        >
          <span class="fi-title" v-html="hl(doc.title)"></span>
          <span class="fi-path">{{ store.pathOf(doc.id) }}</span>
        </div>
        <div v-if="!tagFilteredDocs.length" class="empty">没有命中的笔记</div>
      </template>

      <template v-else>
        <!-- ⭐ 星标区块（默认折叠） -->
        <div v-if="favorites.length" class="section">
          <div class="section-title clickable" @click="toggleSection('fav')">
            <span class="sec-caret" :class="{ open: sections.fav }">▸</span> <Icon name="star" :size="12" /> 星标
          </div>
          <template v-if="sections.fav">
            <div
              v-for="doc in favorites"
              :key="doc.id"
              class="flat-item fav"
              :class="{ active: doc.id === props.currentId }"
              @click="emit('open', doc.id)"
            >{{ doc.title }}</div>
          </template>
        </div>

        <!-- 🕘 最近查看区块（默认展开，最近 5 条） -->
        <div v-if="recent.length" class="section">
          <div class="section-title clickable" @click="toggleSection('recent')">
            <span class="sec-caret" :class="{ open: sections.recent }">▸</span> <Icon name="clock" :size="12" /> 最近查看
          </div>
          <template v-if="sections.recent">
            <div
              v-for="doc in recent.slice(0, 5)"
              :key="doc.id"
              class="flat-item"
              :class="{ active: doc.id === props.currentId }"
              @click="emit('open', doc.id)"
            >{{ doc.title }}</div>
          </template>
        </div>

        <!-- 目录树 -->
        <div class="section">
          <div class="section-title clickable" @click="toggleSection('tree')">
            <span class="sec-caret" :class="{ open: sections.tree }">▸</span> <Icon name="book" :size="13" /> 全部笔记
          </div>
          <template v-if="sections.tree">
            <DocTreeNode
              v-for="node in tree"
              :key="node.id"
              :node="node"
              :depth="0"
              :current-id="props.currentId"
              :expanded="expanded"
              @open="emit('open', $event)"
              @toggle="toggle"
              @new-child="emit('newChild', $event)"
              @move="emit('move', $event)"
              @del="emit('del', $event)"
              @drop-on="onDropOnNode"
            />
            <div v-if="tree.length === 0" class="empty">还没有笔记，点上面新建一篇吧</div>
          </template>
        </div>
      </template>
    </div>

    <div class="bottom-entries">
      <div class="trash-entry" :class="{ active: props.attachOpen }" @click="emit('showAttachments')">
        <Icon name="image" :size="13" /> 附件
      </div>
      <div class="trash-entry" :class="{ active: props.trashOpen }" @click="emit('showTrash')">
        <Icon name="trash" :size="13" /> 回收站
      </div>
      <div class="trash-entry" :class="{ active: props.graphOpen }" @click="emit('showGraph')">
        <Icon name="link" :size="13" /> 图谱
      </div>
    </div>

    <!-- 工作区删除：二次确认弹窗 -->
    <div v-if="wsDeleteStep !== 'none'" class="mask" @click.self="wsDeleteStep = 'none'">
      <div class="dialog">
        <template v-if="wsDeleteStep === 'confirm'">
          <div class="head">删除工作区「{{ currentWsName }}」？</div>
          <div class="body">删除后不可恢复。里面有笔记的话会先提醒你数量。</div>
          <div class="btns">
            <button class="danger" @click="confirmDeleteWs(false)">确认删除</button>
            <button class="cancel" @click="wsDeleteStep = 'none'">取消</button>
          </div>
        </template>
        <template v-else-if="wsDeleteStep === 'force'">
          <div class="head danger-text">「{{ currentWsName }}」里有 {{ store.docs.length + store.trash.length }} 篇笔记</div>
          <div class="body">删除工作区会将这些笔记<strong>一起永久删除，不可恢复</strong>。确定要删除吗？</div>
          <div class="btns">
            <button class="danger" @click="confirmDeleteWs(true)">确定删除（连笔记）</button>
            <button class="cancel" @click="wsDeleteStep = 'none'">取消</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.doc-list {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  background: var(--bg-panel);
  border-radius: var(--radius) 0 0 var(--radius);
  overflow: hidden;
}
.search-box { padding: 12px 12px 8px; position: relative; }
.search-box input:not(.fp-input) {
  width: 100%;
  padding: 8px 34px 8px 12px; /* 右侧给内嵌 ⚙ 留位 */
  border: none;
  border-radius: var(--radius-sm);
  background: var(--bg-raised);
  color: var(--text-hi);
  font-size: 14px;
  outline: none;
  transition: box-shadow var(--transition);
}
.search-box input:not(.fp-input):focus { box-shadow: 0 0 0 1.5px var(--accent-dim); }
/* ⚙ 内嵌在搜索栏右端 */
.filter-btn {
  position: absolute;
  right: 16px;
  top: 12px;
  bottom: 8px;
  width: 28px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  font-size: 13px;
  display: grid;
  place-items: center;
  transition: all var(--transition);
}
.filter-btn:hover, .filter-btn.on { color: var(--accent); background: var(--bg-panel); }
.filter-panel {
  position: absolute;
  top: 46px;
  left: 12px;
  right: 12px;
  z-index: 40;
  background: var(--bg-raised);
  border: 1px solid var(--accent-dim);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}
.fp-label { font-size: 11px; color: var(--text-faint); letter-spacing: 1px; margin-bottom: 6px; }
.fp-input {
  width: 100%;
  padding: 7px 10px;
  margin-bottom: 12px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--bg-panel);
  color: var(--text-hi);
  font-size: 13px;
  outline: none;
}
.fp-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 12px; }
.fp-none { font-size: 11px; color: var(--text-faint); }
.fp-foot { display: flex; justify-content: space-between; }
.fp-clear, .fp-done {
  padding: 5px 14px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
}
.fp-clear { border: 1px solid transparent; background: transparent; color: var(--text-faint); }
.fp-clear:hover { color: var(--pink); }
.fp-done { border: 1px solid var(--accent-dim); background: transparent; color: var(--accent); }
.search-hint {
  padding: 0 14px 6px;
  font-size: 11px;
  color: var(--text-faint);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.hint-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.reset-btn {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--text-faint);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: all var(--transition);
}
.reset-btn:hover { color: var(--pink); background: var(--bg-raised); }
.new-btn {
  margin: 4px 12px 10px;
  padding: 9px;
  border: 1px dashed var(--accent-dim);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--accent);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--transition);
}
.new-btn:hover { background: var(--bg-raised); }

.items { flex: 1; overflow-y: auto; padding: 0 8px; }
.section { margin-bottom: 10px; }
.section-title {
  font-size: 12px;
  color: var(--text-faint);
  letter-spacing: 1px;
  padding: 6px 10px 4px;
}
.section-title.clickable { cursor: pointer; user-select: none; }
.section-title.clickable:hover { color: var(--text-lo); }
.sec-caret {
  display: inline-block;
  font-size: 9px;
  transition: transform var(--transition);
}
.sec-caret.open { transform: rotate(90deg); }

/* 工作区切换器 */
.ws-switcher { position: relative; padding: 10px 12px 2px; display: flex; gap: 6px; }
.ws-current {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--bg-raised);
  color: var(--text-hi);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.fold-list-btn {
  padding: 0 10px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  font-size: 13px;
}
.fold-list-btn:hover { background: var(--bg-raised); color: var(--accent); }
.ws-caret { transition: transform var(--transition); color: var(--text-faint); }
.ws-caret.open { transform: rotate(180deg); }
.ws-menu {
  position: absolute;
  top: 48px;
  left: 12px;
  right: 12px;
  background: var(--bg-raised);
  border: 1px solid var(--accent-dim);
  border-radius: var(--radius-sm);
  overflow: hidden;
  z-index: 30;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}
.ws-opt {
  padding: 9px 14px;
  font-size: 13px;
  color: var(--text-lo);
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: flex;
  align-items: center;
  gap: 8px;
}
.ws-opt:hover { background: var(--bg-panel); color: var(--text-hi); }
.ws-opt.on { color: var(--accent); }
.ws-opt.action { font-size: 12px; }
.ws-opt.danger:hover { color: var(--pink); }
.ws-divider { height: 1px; background: var(--bg-panel); margin: 4px 0; }

/* 标签筛选行 */
.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  padding: 0 12px 8px;
}
.ftag {
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--bg-raised);
  font-size: 11px;
  color: var(--text-lo);
  cursor: pointer;
  transition: all var(--transition);
}
.ftag:hover { color: var(--text-hi); }
.ftag.on { background: var(--accent-dim); color: var(--bg-base); }

/* 工作区删除弹窗 */
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
.dialog .head { padding: 14px 18px; font-size: 14px; font-weight: 600; }
.dialog .head.danger-text { color: var(--pink); }
.dialog .body { padding: 0 18px 14px; font-size: 13px; color: var(--text-lo); }
.dialog .body strong { color: var(--pink); }
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
.flat-item {
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
  color: var(--text-lo);
  transition: background var(--transition);
}
.flat-item:hover { background: var(--bg-raised); color: var(--text-hi); }
.flat-item.active { background: var(--bg-raised); color: var(--accent); box-shadow: inset 2px 0 0 var(--accent); }
.flat-item.with-path { display: flex; flex-direction: column; gap: 1px; align-items: stretch; }
.flat-item .fi-title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.flat-item .fi-path {
  font-size: 10.5px;
  color: var(--text-faint);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.flat-item :deep(mark.hl) {
  background: rgba(232, 160, 191, 0.22);
  color: var(--pink);
  border-radius: 3px;
  padding: 0 1px;
}
.empty { padding: 24px 12px; text-align: center; color: var(--text-faint); font-size: 12px; }

.trash-entry {
  flex: 1;
  padding: 12px 16px;
  font-size: 12.5px;
  color: var(--text-lo);
  cursor: pointer;
  transition: all var(--transition);
}
.bottom-entries {
  display: flex;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}
.trash-entry:hover, .trash-entry.active { color: var(--text-hi); background: var(--bg-raised); }

@media (max-width: 768px) {
  .doc-list {
    width: 78vw;
    max-width: 320px;
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 85;
    border-radius: 0;
    box-shadow: 8px 0 24px rgba(0, 0, 0, 0.5);
  }
}
</style>
