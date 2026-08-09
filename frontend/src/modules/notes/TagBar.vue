<script setup lang="ts">
import { ref, computed } from "vue";
import { useNotesStore } from "../../stores/notes";

const props = defineProps<{ docId: string }>();
const store = useNotesStore();

const input = ref("");
const focused = ref(false);

const myTags = computed(() => store.tagsOf(props.docId));

// 已有标签建议：匹配输入 + 当前文档还没挂的
const suggestions = computed(() => {
  const q = input.value.trim().toLowerCase();
  const mine = new Set(myTags.value.map((t) => t.id));
  return store.tags
    .filter((t) => !mine.has(t.id) && (!q || t.name.toLowerCase().includes(q)))
    .slice(0, 6);
});

async function add(name?: string) {
  const n = (name ?? input.value).trim();
  if (!n) return;
  await store.tagDoc(props.docId, n);
  input.value = "";
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Enter") {
    e.preventDefault();
    add();
  }
}

function onBlur() {
  setTimeout(() => (focused.value = false), 150);
}
</script>

<template>
  <div class="tag-bar">
    <span v-for="t in myTags" :key="t.id" class="tag-chip">
      {{ t.name }}
      <button class="x" title="移除标签" @click="store.untagDoc(props.docId, t.id)">×</button>
    </span>
    <div class="add-box">
      <input
        v-model="input"
        class="tag-input"
        placeholder="+ 标签"
        @focus="focused = true"
        @blur="onBlur"
        @keydown="onKey"
      />
      <div v-if="focused && suggestions.length" class="sug-list">
        <div
          v-for="s in suggestions"
          :key="s.id"
          class="sug"
          @mousedown.prevent="add(s.name)"
        >{{ s.name }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tag-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 6px 16px;
}
.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--bg-raised);
  border: 1px solid var(--accent-dim);
  font-size: 11.5px;
  color: var(--accent);
}
.tag-chip .x {
  border: none;
  background: none;
  color: var(--text-faint);
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}
.tag-chip .x:hover { color: var(--pink); }
.add-box { position: relative; }
.tag-input {
  width: 72px;
  padding: 3px 10px;
  border: 1px dashed var(--text-faint);
  border-radius: 999px;
  background: transparent;
  color: var(--text-hi);
  font-size: 11.5px;
  outline: none;
  transition: all var(--transition);
}
.tag-input:focus { border-color: var(--accent-dim); width: 110px; }
.sug-list {
  position: absolute;
  top: 28px;
  left: 0;
  min-width: 140px;
  background: var(--bg-raised);
  border: 1px solid var(--accent-dim);
  border-radius: var(--radius-sm);
  overflow: hidden;
  z-index: 25;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}
.sug { padding: 7px 12px; font-size: 12.5px; color: var(--text-lo); cursor: pointer; }
.sug:hover { background: var(--bg-panel); color: var(--accent); }
</style>
