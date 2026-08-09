<script setup lang="ts">
import { storeToRefs } from "pinia";
import { useNotesStore } from "../../stores/notes";

const emit = defineEmits<{ open: [id: string]; showTrash: [] }>();
const props = defineProps<{ currentId: string | null; trashOpen: boolean }>();

const store = useNotesStore();
const { docs, searchQuery, searching } = storeToRefs(store);

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

    <button class="new-btn" @click="emit('open', '__new__')">＋ 新建笔记</button>

    <div v-if="searching" class="search-hint">搜索「{{ searchQuery }}」的结果</div>

    <div class="items">
      <div
        v-for="doc in docs"
        :key="doc.id"
        class="item"
        :class="{ active: doc.id === props.currentId }"
        @click="emit('open', doc.id)"
      >
        <div class="title">
          <span class="text">{{ doc.title }}</span>
          <span class="indicators">
            <span v-if="doc.is_favorite" class="star" title="星标">⭐</span>
            <span v-if="doc.has_draft" class="draft-dot" title="有未保存草稿">●</span>
          </span>
        </div>
      </div>
      <div v-if="docs.length === 0" class="empty">
        {{ searching ? "没有命中" : "还没有笔记，点上面新建一篇吧" }}
      </div>
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
.search-box input:focus {
  box-shadow: 0 0 0 1.5px var(--accent-dim);
}
.search-hint {
  padding: 0 14px 6px;
  font-size: 11px;
  color: var(--text-faint);
}
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
.item {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--transition);
}
.item:hover { background: var(--bg-raised); }
.item.active {
  background: var(--bg-raised);
  box-shadow: inset 2px 0 0 var(--accent);
}
.title {
  display: flex;
  align-items: center;
  font-size: 13.5px;
}
.title .text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.indicators {
  margin-left: auto;
  padding-left: 8px;
  flex-shrink: 0;
  display: flex;
  gap: 5px;
  align-items: center;
}
.star { font-size: 11px; }
.draft-dot { color: var(--pink); font-size: 10px; }
.empty {
  padding: 24px 12px;
  text-align: center;
  color: var(--text-faint);
  font-size: 12px;
}

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
