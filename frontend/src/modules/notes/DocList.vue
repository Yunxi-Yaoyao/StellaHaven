<script setup lang="ts">
import { ref, computed } from "vue";
import { storeToRefs } from "pinia";
import { useNotesStore, buildTree, type TreeNode } from "../../stores/notes";
import DocTreeNode from "./DocTreeNode.vue";

const emit = defineEmits<{
  open: [id: string];
  showTrash: [];
  newChild: [node: TreeNode | null];
  move: [node: TreeNode];
  del: [node: TreeNode];
}>();
const props = defineProps<{ currentId: string | null; trashOpen: boolean }>();

const store = useNotesStore();
const { docs, recent, searchQuery, searching } = storeToRefs(store);

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

let debounceTimer: ReturnType<typeof setTimeout> | null = null;
function onSearchInput() {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => store.refreshList(), 300);
}
</script>

<template>
  <div class="doc-list">
    <div class="search-box">
      <input
        v-model="searchQuery"
        placeholder="搜索标题和正文…"
        @input="onSearchInput"
      />
    </div>

    <button class="new-btn" @click="emit('newChild', null)">＋ 新建笔记</button>
    <div v-if="searching" class="search-hint">搜索「{{ searchQuery }}」的结果（平铺显示）</div>

    <div class="items">
      <!-- 搜索中：平铺结果 -->
      <template v-if="searching">
        <div
          v-for="doc in docs"
          :key="doc.id"
          class="flat-item"
          :class="{ active: doc.id === props.currentId }"
          @click="emit('open', doc.id)"
        >
          {{ doc.title }}
        </div>
      </template>

      <template v-else>
        <!-- ⭐ 星标区块 -->
        <div v-if="favorites.length" class="section">
          <div class="section-title">⭐ 星标</div>
          <div
            v-for="doc in favorites"
            :key="doc.id"
            class="flat-item fav"
            :class="{ active: doc.id === props.currentId }"
            @click="emit('open', doc.id)"
          >{{ doc.title }}</div>
        </div>

        <!-- 🕘 最近查看区块 -->
        <div v-if="recent.length" class="section">
          <div class="section-title">🕘 最近查看</div>
          <div
            v-for="doc in recent.slice(0, 5)"
            :key="doc.id"
            class="flat-item"
            :class="{ active: doc.id === props.currentId }"
            @click="emit('open', doc.id)"
          >{{ doc.title }}</div>
        </div>

        <!-- 目录树 -->
        <div class="section">
          <div class="section-title">📒 全部笔记</div>
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
          />
          <div v-if="tree.length === 0" class="empty">还没有笔记，点上面新建一篇吧</div>
        </div>
      </template>
    </div>

    <div class="trash-entry" :class="{ active: props.trashOpen }" @click="emit('showTrash')">
      🗑 回收站
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
.search-box { padding: 12px 12px 8px; }
.search-box input {
  width: 100%;
  padding: 8px 12px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--bg-raised);
  color: var(--text-hi);
  font-size: 13px;
  outline: none;
  transition: box-shadow var(--transition);
}
.search-box input:focus { box-shadow: 0 0 0 1.5px var(--accent-dim); }
.search-hint { padding: 0 14px 6px; font-size: 11px; color: var(--text-faint); }
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
  font-size: 11px;
  color: var(--text-faint);
  letter-spacing: 1px;
  padding: 6px 10px 4px;
}
.flat-item {
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
  color: var(--text-lo);
  transition: background var(--transition);
}
.flat-item:hover { background: var(--bg-raised); color: var(--text-hi); }
.flat-item.active { background: var(--bg-raised); color: var(--accent); box-shadow: inset 2px 0 0 var(--accent); }
.empty { padding: 24px 12px; text-align: center; color: var(--text-faint); font-size: 12px; }

.trash-entry {
  padding: 12px 16px;
  font-size: 12.5px;
  color: var(--text-lo);
  cursor: pointer;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  transition: all var(--transition);
}
.trash-entry:hover, .trash-entry.active { color: var(--text-hi); background: var(--bg-raised); }

@media (max-width: 768px) {
  .doc-list { width: 200px; }
}
</style>
