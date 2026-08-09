<script setup lang="ts">
import { ref, onMounted } from "vue";
import { storeToRefs } from "pinia";
import { useNotesStore } from "../../stores/notes";
import { toast } from "../../composables/useToast";
import type { Doc } from "../../api/notes";

const emit = defineEmits<{ close: [] }>();
const store = useNotesStore();
const { trash } = storeToRefs(store);

// 有下挂的还原前要先选：确认中的条目 id
const confirming = ref<string | null>(null);
// 一键清空的二次确认弹窗
const emptyConfirm = ref(false);

async function onEmptyAll() {
  const n = await store.emptyAllTrash();
  emptyConfirm.value = false;
  toast(n > 0 ? `已永久删除 ${n} 篇` : "回收站已经是空的");
}

onMounted(() => store.refreshTrash());

function trashedChildren(doc: Doc): Doc[] {
  return trash.value.filter((d) => d.parent_id === doc.id);
}

function onRestore(doc: Doc) {
  if (trashedChildren(doc).length > 0) {
    confirming.value = doc.id; // 有下挂 → 先选
  } else {
    store.restore(doc.id, false);
  }
}

function confirmRestore(doc: Doc, cascade: boolean) {
  confirming.value = null;
  store.restore(doc.id, cascade);
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
</script>

<template>
  <div class="trash-panel">
    <div class="head">
      <span>🗑 回收站</span>
      <span class="tip">超过 30 天的会被自动清理</span>
      <button v-if="trash.length" class="empty-btn" @click="emptyConfirm = true">清空回收站</button>
      <button class="back" @click="emit('close')">← 返回</button>
    </div>

    <div class="items">
      <div v-for="doc in trash" :key="doc.id" class="item">
        <div class="info">
          <div class="title">{{ doc.title }}</div>
          <div class="meta">删于 {{ fmtTime((doc as any).deleted_at || doc.updated_at) }}</div>
        </div>

        <!-- 有下挂：先选范围 -->
        <template v-if="confirming === doc.id">
          <button class="restore" @click="confirmRestore(doc, true)">全部还原（含 {{ trashedChildren(doc).length }} 篇下挂）</button>
          <button class="restore" @click="confirmRestore(doc, false)">仅此篇</button>
          <button class="purge" @click="confirming = null">取消</button>
        </template>
        <template v-else>
          <button class="restore" @click="onRestore(doc)">还原</button>
          <button class="purge" @click="store.purge(doc.id)">彻底删除</button>
        </template>
      </div>
      <div v-if="trash.length === 0" class="empty">回收站是空的 ✨</div>
    </div>

    <!-- 一键清空：二次确认 -->
    <div v-if="emptyConfirm" class="mask" @click.self="emptyConfirm = false">
      <div class="dialog">
        <div class="head danger-text">清空回收站？</div>
        <div class="body">回收站里 {{ trash.length }} 篇笔记将被<strong>永久删除，不可恢复</strong>。</div>
        <div class="btns">
          <button class="danger" @click="onEmptyAll">永久清空（{{ trash.length }} 篇）</button>
          <button class="cancel" @click="emptyConfirm = false">取消</button>
        </div>
      </div>
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
  flex-wrap: wrap;
}
.info { flex: 1; min-width: 120px; }
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
.empty-btn {
  padding: 5px 14px;
  border: 1px solid var(--text-faint);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-lo);
  font-size: 12px;
  cursor: pointer;
}
.empty-btn:hover { border-color: var(--pink); color: var(--pink); }

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
</style>
