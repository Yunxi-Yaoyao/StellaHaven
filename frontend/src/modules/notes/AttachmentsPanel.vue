<script setup lang="ts">
import { ref, onMounted } from "vue";
import { storeToRefs } from "pinia";
import { useNotesStore } from "../../stores/notes";
import { api } from "../../api/client";
import Icon from "../../shell/Icon.vue";

const emit = defineEmits<{ close: []; open: [id: string] }>();
const store = useNotesStore();
const { workspaceId } = storeToRefs(store);

interface AttachmentItem {
  id: string;
  url: string;
  filename: string;
  mime: string;
  size: number;
  created_at: string;
  doc_id: string;
  doc_title: string;
  doc_in_trash: boolean;
}

const items = ref<AttachmentItem[]>([]);

onMounted(async () => {
  items.value = await api<AttachmentItem[]>(`/attachments/?workspace_id=${workspaceId.value}`);
});

function fmtSize(bytes: number) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

function isImage(mime: string) {
  return mime.startsWith("image/");
}
</script>

<template>
  <div class="att-panel">
    <div class="head">
      <span><Icon name="image" :size="15" /> 附件</span>
      <span class="tip">{{ items.length }} 个文件 · 笔记里删掉引用会自动清理</span>
      <button class="back" @click="emit('close')">← 返回</button>
    </div>

    <div class="grid">
      <div
        v-for="a in items"
        :key="a.id"
        class="card"
        @click="emit('open', a.doc_id)"
        :title="'来自「' + a.doc_title + '」，点击打开这篇笔记'"
      >
        <div class="thumb">
          <img v-if="isImage(a.mime)" :src="a.url" :alt="a.filename" loading="lazy" />
          <Icon v-else name="note" :size="28" />
        </div>
        <div class="info">
          <div class="name">{{ a.filename }}</div>
          <div class="meta">
            {{ fmtSize(a.size) }} · 来自「{{ a.doc_title }}」
            <span v-if="a.doc_in_trash" class="in-trash">回收站中</span>
          </div>
        </div>
      </div>
      <div v-if="items.length === 0" class="empty">还没有附件——在笔记里粘贴或拖入图片/文件试试</div>
    </div>
  </div>
</template>

<style scoped>
.att-panel {
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
.grid {
  flex: 1;
  overflow-y: auto;
  padding: 14px 18px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
  align-content: start;
}
.card {
  background: var(--bg-raised);
  border-radius: var(--radius-sm);
  overflow: hidden;
  cursor: pointer;
  transition: all var(--transition);
}
.card:hover { transform: translateY(-2px); box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35); }
.thumb {
  height: 90px;
  display: grid;
  place-items: center;
  background: var(--bg-base);
  color: var(--text-faint);
  overflow: hidden;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.info { padding: 8px 10px; }
.name {
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.meta { font-size: 10.5px; color: var(--text-faint); margin-top: 2px; }
.in-trash { color: var(--pink); margin-left: 4px; }
.empty { grid-column: 1 / -1; text-align: center; color: var(--text-faint); padding: 40px; }
</style>
