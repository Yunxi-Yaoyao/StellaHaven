<script setup lang="ts">
import { computed } from 'vue';
import { importTreeRows } from './import-helpers';
const props = defineProps<{ docs: { id: string; title: string; parent_id: string | null }[]; modelValue: string; disabled?: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const rows = computed(() => importTreeRows(props.docs));
</script>
<template>
  <div class="target-tree" role="tree" aria-label="导入目标页面层级">
    <button role="treeitem" aria-label="工作区根目录" :aria-selected="!modelValue" :aria-level="1" :disabled="disabled" @click="emit('update:modelValue', '')">工作区根目录</button>
    <button v-for="row in rows" :key="row.id" role="treeitem" :aria-label="row.title" :aria-level="row.depth + 2" :aria-selected="modelValue === row.id" :disabled="disabled" :style="{ paddingLeft: `${16 + Math.min(row.depth + 1, 8) * 16}px` }" @click="emit('update:modelValue', row.id)">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6"/></svg><span>{{ row.title || '未命名笔记' }}</span>
    </button>
  </div>
</template>
<style scoped>
.target-tree { max-height: 175px; overflow: auto; border: 1px solid var(--accent-dim); border-radius: var(--radius-sm); min-width: 0; }
button { width: 100%; border: 0; background: transparent; color: var(--text-lo); text-align: left; padding: 9px 12px; display: flex; gap: 7px; align-items: center; font: inherit; cursor: pointer; }
button[aria-selected=true] { background: var(--bg-raised); color: var(--accent); } button:hover { background: var(--bg-raised); } button:disabled { cursor: default; } span { overflow-wrap: anywhere; min-width: 0; } svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.5; flex-shrink: 0; }
</style>
