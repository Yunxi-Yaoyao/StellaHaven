<script setup lang="ts">
import { computed, ref, inject } from "vue";
import {toast} from "../../composables/useToast";
import {projectCatalogKey,PROJECT_ASSET_MIME,dragProjectAsset} from "./projectAssetCopy";
const projectCatalog=inject(projectCatalogKey,null);
import { type TreeNode, useNotesStore } from "../../stores/notes";
import Icon from "../../shell/Icon.vue";

const props = defineProps<{
  node: TreeNode;
  depth: number;
  currentId: string | null;
  expanded: Set<string>;
  selecting?: boolean;
  selected?: string[];
}>();
const emit = defineEmits<{
  open: [id: string];
  toggle: [id: string];
  newChild: [node: TreeNode];
  move: [node: TreeNode];
  del: [node: TreeNode];
  dropOn: [target: TreeNode];
  select: [id:string];
}>();

// ── 拖拽换父级 ──
const store = useNotesStore();
const dragOver = ref(false);

function onDragStart(e: DragEvent) {
  store.draggingId = props.node.id;
  e.dataTransfer?.setData("text/plain", props.node.id);
  if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
  const project=projectCatalog?.projectFor(props.node.id);
  const asset=projectCatalog?.assetFor?.(props.node.id);
  if(asset&&e.dataTransfer){e.dataTransfer.setData(PROJECT_ASSET_MIME,JSON.stringify(asset));e.dataTransfer.effectAllowed='copyMove';}
  else if(project)dragProjectAsset(e,project,props.node.id);
}
function onDragEnd() {
  store.draggingId = null;
  dragOver.value = false;
}
function onDragOver(e: DragEvent) {
  if(!store.draggingId&&e.dataTransfer?.types.includes(PROJECT_ASSET_MIME)){e.preventDefault();e.dataTransfer.dropEffect="copy";return;}
  if (!store.draggingId || store.draggingId === props.node.id) return;
  e.preventDefault(); // 允许落下
  if (e.dataTransfer) e.dataTransfer.dropEffect = "move"; // 关键：声明 move，不然浏览器显示「松开以搜索」
  dragOver.value = true;
}
function onDragLeave() {
  dragOver.value = false;
}
function onDrop(e: DragEvent) {
  e.preventDefault();
  dragOver.value = false;
  if(!store.draggingId&&e.dataTransfer?.types.includes(PROJECT_ASSET_MIME)){
    e.stopPropagation();toast("请把项目图片拖到普通笔记正文，以独立复制附件；原项目图片不会移动。");return;
  }
  if (!store.draggingId || store.draggingId === props.node.id) return;
  const identity=projectCatalog?.identityFor ?? projectCatalog?.projectFor;
  const source=identity?.(store.draggingId), target=identity?.(props.node.id);
  if (source && source.id!==target?.id && !(source.id===store.draggingId&&!target)) {
    e.stopPropagation(); store.draggingId=null;
    toast(e.dataTransfer?.types.includes(PROJECT_ASSET_MIME) ? "请把项目图片拖到普通笔记正文，以独立复制附件；原项目图片不会移动。" : "暂不支持跨网页项目边界移动，原文件未改变。");
    return;
  }
  if(source&&store.draggingId!==source.id&&!window.confirm("项目内移动会改变相对引用，HTML/CSS/JS路径不会自动修复。继续？")){store.draggingId=null;return;}
  emit("dropOn", props.node);
  store.draggingId = null;
}

const isOpen = computed(() => props.expanded.has(props.node.id));
const hasKids = computed(() => props.node.children.length > 0);
</script>

<template>
  <div class="node">
    <div
      class="row"
      :data-import-parent="node.id"
      :class="{ active: node.id === currentId, 'drag-over': dragOver }"
      :style="{ paddingLeft: 10 + depth * 16 + 'px' }"
      :draggable="!selecting"
      @click="selecting ? emit('select', node.id) : emit('open', node.id)"
      @dragstart="onDragStart"
      @dragend="onDragEnd"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    >
      <span
        class="caret"
        :class="{ open: isOpen, leaf: !hasKids }"
        @click.stop="hasKids && emit('toggle', node.id)"
      >
        <Icon v-if="hasKids" name="chevron" :size="12" />
      </span>
      <input v-if="selecting" type="checkbox" :aria-label="`选择笔记：${node.title}`" :checked="selected?.includes(node.id)" :disabled="node.id === store.templateRootId" @click.stop="emit('select', node.id)" />
      <!-- 类型图标：有下挂=文件夹，没下挂=文档（统一线性风） -->
      <span class="type-icon" :class="{ folder: hasKids }">
        <Icon :name="hasKids ? 'folder' : 'note'" :size="13" />
      </span>
      <span class="text">{{ node.title }}</span>
      <span class="indicators">
        <Icon v-if="node.is_favorite" name="star" :size="11" class="star" />
        <span v-if="node.has_draft" class="draft-dot" title="有未保存草稿">●</span>
      </span>
      <!-- hover 才出现的操作 -->
      <span v-if="!selecting" class="actions">
        <button title="新建子页面" @click.stop="emit('newChild', node)"><Icon name="plus" :size="12" /></button>
        <button title="移动到…" @click.stop="emit('move', node)"><Icon name="move" :size="12" /></button>
        <button title="删除" @click.stop="emit('del', node)"><Icon name="trash" :size="12" /></button>
      </span>
    </div>
    <template v-if="hasKids && isOpen">
      <DocTreeNode
        v-for="kid in node.children"
        :key="kid.id"
        :node="kid"
        :depth="depth + 1"
        :current-id="currentId"
        :expanded="expanded"
        :selecting="selecting"
        :selected="selected"
        @select="emit('select', $event)"
        @open="emit('open', $event)"
        @toggle="emit('toggle', $event)"
        @new-child="emit('newChild', $event)"
        @move="emit('move', $event)"
        @del="emit('del', $event)"
        @drop-on="emit('dropOn', $event)"
      />
    </template>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 7px 8px 7px 0;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--transition);
  position: relative;
}
.row:hover { background: var(--bg-raised); }
.row.active {
  background: var(--bg-raised);
  box-shadow: inset 2px 0 0 var(--accent);
}
.row.drag-over {
  background: var(--bg-raised);
  box-shadow: inset 0 0 0 1.5px var(--accent);
}
.caret {
  width: 14px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-faint);
  transition: transform var(--transition);
}
.caret.open { transform: rotate(90deg); }
.caret.leaf { visibility: hidden; } /* 叶子页留位不显示，保持对齐 */
.type-icon {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  color: var(--text-lo);
}
.type-icon.folder { color: var(--accent); }
.text {
  font-size: 14.5px;
  white-space: normal;
  overflow-wrap: anywhere;
  line-height: 1.5;
  flex: 1;
  min-width: 0;
}
.indicators {
  margin-left: auto;
  padding-left: 6px;
  flex-shrink: 0;
  display: flex;
  gap: 5px;
  align-items: center;
}
.star { color: var(--accent); }
.draft-dot { color: var(--pink); font-size: 10px; }
.actions {
  display: flex;
  position: absolute;
  right: 6px;
  top: 5px;
  opacity: 0;
  pointer-events: none;
  background: var(--bg-raised);
  border-radius: 4px;
  gap: 2px;
}
.row:hover .actions, .row:focus-within .actions { opacity: 1; pointer-events: auto; }
.row:hover .indicators, .row:focus-within .indicators { visibility: hidden; }
.indicators:empty { display: none; }
.caret, .type-icon, .indicators { margin-top: 3px; }
.actions button {
  min-width: 24px;
  min-height: 24px;
  border: none;
  background: transparent;
  color: var(--text-lo);
  font-size: 12px;
  padding: 2px 5px;
  border-radius: 4px;
  cursor: pointer;
}
.actions button:hover { background: var(--bg-panel); color: var(--text-hi); }
.actions button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
@media (hover: none) {
  .row { padding-bottom: 40px; }
  .actions { top: auto; bottom: 4px; opacity: 1; pointer-events: auto; }
  .actions button { min-width: 32px; min-height: 32px; }
}
</style>
