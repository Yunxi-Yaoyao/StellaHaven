<script setup lang="ts">
import { computed } from "vue";
import { type TreeNode } from "../../stores/notes";
import Icon from "../../shell/Icon.vue";

const props = defineProps<{
  node: TreeNode;
  depth: number;
  currentId: string | null;
  expanded: Set<string>;
}>();
const emit = defineEmits<{
  open: [id: string];
  toggle: [id: string];
  newChild: [node: TreeNode];
  move: [node: TreeNode];
  del: [node: TreeNode];
}>();

const isOpen = computed(() => props.expanded.has(props.node.id));
const hasKids = computed(() => props.node.children.length > 0);
</script>

<template>
  <div class="node">
    <div
      class="row"
      :class="{ active: node.id === currentId }"
      :style="{ paddingLeft: 10 + depth * 16 + 'px' }"
      @click="emit('open', node.id)"
    >
      <span
        class="caret"
        :class="{ open: isOpen, leaf: !hasKids }"
        @click.stop="hasKids && emit('toggle', node.id)"
      >
        <Icon v-if="hasKids" name="chevron" :size="12" />
      </span>
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
      <span class="actions">
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
        @open="emit('open', $event)"
        @toggle="emit('toggle', $event)"
        @new-child="emit('newChild', $event)"
        @move="emit('move', $event)"
        @del="emit('del', $event)"
      />
    </template>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  align-items: center;
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
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
  display: none;
  flex-shrink: 0;
  gap: 2px;
}
.row:hover .actions { display: flex; }
.row:hover .indicators { display: none; } /* hover 时指示让位给操作 */
.actions button {
  border: none;
  background: transparent;
  color: var(--text-lo);
  font-size: 12px;
  padding: 2px 5px;
  border-radius: 4px;
  cursor: pointer;
}
.actions button:hover { background: var(--bg-panel); color: var(--text-hi); }
</style>
