<script setup lang="ts">
import { onMounted } from "vue";
import { storeToRefs } from "pinia";
import { useNotesStore } from "../../stores/notes";

const emit = defineEmits<{ close: [] }>();
const store = useNotesStore();
const { trash } = storeToRefs(store);

onMounted(() => store.refreshTrash());

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
</script>

<template>
  <div class="trash-panel">
    <div class="head">
      <span>🗑 回收站</span>
      <span class="tip">超过 30 天的会被自动清理</span>
      <button class="back" @click="emit('close')">← 返回</button>
    </div>

    <div class="items">
      <div v-for="doc in trash" :key="doc.id" class="item">
        <div class="info">
          <div class="title">{{ doc.title }}</div>
          <div class="meta">删于 {{ fmtTime((doc as any).deleted_at || doc.updated_at) }}</div>
        </div>
        <button class="restore" @click="store.restore(doc.id)">还原</button>
        <button class="purge" @click="store.purge(doc.id)">彻底删除</button>
      </div>
      <div v-if="trash.length === 0" class="empty">回收站是空的 ✨</div>
    </div>
  </div>
</template>

<style scoped>
.trash-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-radius: 0 var(--radius) var(--radius) 0;
  overflow: hidden;
}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  font-size: 15px;
  font-weight: 600;
}
.tip { flex: 1; font-size: 11px; color: var(--text-faint); font-weight: 400; }
.back {
  padding: 5px 14px;
  border: 1px solid var(--accent-dim);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--accent);
  font-size: 12px;
  cursor: pointer;
}
.items { flex: 1; overflow-y: auto; padding: 12px 18px; }
.item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--bg-raised);
  margin-bottom: 8px;
}
.info { flex: 1; min-width: 0; }
.title { font-size: 13.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta { font-size: 11px; color: var(--text-faint); margin-top: 2px; }
.restore, .purge {
  padding: 5px 14px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
}
.restore { border: 1px solid var(--accent-dim); background: transparent; color: var(--accent); }
.purge { border: 1px solid transparent; background: transparent; color: var(--text-faint); }
.purge:hover { border-color: var(--pink); color: var(--pink); }
.empty { text-align: center; color: var(--text-faint); padding: 40px; }
</style>
