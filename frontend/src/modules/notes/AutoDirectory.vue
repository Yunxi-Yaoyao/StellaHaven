<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue';
import type { Doc } from '../../api/notes';
import Icon from '../../shell/Icon.vue';

const props = defineProps<{
  docs: Doc[];
  docId: string;
  workspaceId: string;
  userId: string;
  hasBody: boolean;
}>();
const emit = defineEmits<{ open: [id: string]; createChild: [] }>();
const listId = useId();
const scope = computed(() => JSON.stringify([props.userId, props.workspaceId, props.docId]));
const storageKey = computed(() => `stella:auto-directory:v1:${scope.value}`);
const preference = ref<boolean | null>(null);
const mobile = ref(typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches);
const expandedIds = ref(new Set<string>());
// Component-local memory: account/workspace switches never share row state.
const expansionMemory = new Map<string, Set<string>>();
const foldMemory = new Map<string, boolean>();
let media: MediaQueryList | undefined;
function updateMobile() { mobile.value = media?.matches ?? false; }
onMounted(() => {
  media = window.matchMedia('(max-width: 768px)');
  updateMobile();
  media.addEventListener('change', updateMobile);
});
onBeforeUnmount(() => media?.removeEventListener('change', updateMobile));
watch(scope, (key, previous) => {
  if (previous) expansionMemory.set(previous, new Set(expandedIds.value));
  expandedIds.value = new Set(expansionMemory.get(key));
  preference.value = foldMemory.get(key) ?? null;
  try {
    const saved = localStorage.getItem(storageKey.value);
    if (saved === 'expanded' || saved === 'collapsed') preference.value = saved === 'expanded';
  } catch { /* Storage may be unavailable; the explicit in-memory choice still works. */ }
}, { immediate: true, flush: 'sync' });
const expanded = computed(() => preference.value ?? (!mobile.value || !props.hasBody));
function toggleRoot() {
  preference.value = !expanded.value;
  foldMemory.set(scope.value, preference.value);
  try { localStorage.setItem(storageKey.value, preference.value ? 'expanded' : 'collapsed'); }
  catch { /* Private/restricted storage must not prevent navigation. */ }
}
function toggleRow(id: string) {
  const next = new Set(expandedIds.value);
  if (next.has(id)) next.delete(id); else next.add(id);
  expandedIds.value = next;
}

// ID-only adjacency index with the same title order as the sidebar; never mutate metadata.
// Ignore duplicate IDs, self-links and the active root as a descendant.
const childrenById = computed(() => {
  const result = new Map<string, Doc[]>();
  const seen = new Set<string>();
  for (const doc of props.docs) {
    if (doc.workspace_id !== props.workspaceId || seen.has(doc.id)) continue;
    seen.add(doc.id);
    if (!doc.parent_id || doc.id === doc.parent_id || doc.id === props.docId) continue;
    const siblings = result.get(doc.parent_id) ?? [];
    siblings.push(doc);
    result.set(doc.parent_id, siblings);
  }
  const collator = new Intl.Collator('zh-Hans-CN', { numeric: true });
  const rank = (title: string) => /^\d/.test(title.trim()) ? 0 : /^[a-zA-Z]/.test(title.trim()) ? 1 : 2;
  for (const siblings of result.values()) siblings.sort((a,b) => rank(a.title)-rank(b.title) || collator.compare(a.title,b.title) || a.id.localeCompare(b.id));
  return result;
});
const directChildren = computed(() => childrenById.value.get(props.docId) ?? []);
// Iterative traversal avoids recursion limits; only expanded levels are materialized.
const rows = computed(() => {
  const result: { doc: Doc; depth: number; childCount: number }[] = [];
  const seen = new Set([props.docId]);
  const stack = directChildren.value.map(doc => ({ doc, depth: 0 })).reverse();
  while (stack.length) {
    const row = stack.pop()!;
    if (seen.has(row.doc.id)) continue;
    seen.add(row.doc.id);
    const children = (childrenById.value.get(row.doc.id) ?? []).filter(doc => !seen.has(doc.id));
    result.push({ ...row, childCount: children.length });
    if (expandedIds.value.has(row.doc.id)) {
      for (let i = children.length - 1; i >= 0; i--) stack.push({ doc: children[i]!, depth: row.depth + 1 });
    }
  }
  return result;
});
</script>

<template>
  <section v-if="directChildren.length" class="auto-directory" aria-label="子页面目录">
    <header class="directory-header">
      <button type="button" class="directory-toggle" :aria-expanded="expanded" :aria-controls="listId" @click="toggleRoot">
        <Icon name="chevron" :size="14" :class="{ rotated: expanded }" aria-hidden="true" />
        <span>目录 · {{ directChildren.length }} 个子页面</span>
      </button>
      <button type="button" class="directory-create" @click="emit('createChild')">
        <Icon name="plus" :size="14" aria-hidden="true" />新建子页面
      </button>
    </header>
    <ul v-show="expanded" :id="listId" class="directory-list" aria-label="子页面">
      <li v-for="row in rows" :key="row.doc.id" class="directory-row" :style="{ paddingInlineStart: `${Math.min(row.depth, 6) * 12}px` }">
        <button v-if="row.childCount" type="button" class="directory-arrow" :aria-expanded="expandedIds.has(row.doc.id)" :aria-label="`${expandedIds.has(row.doc.id) ? '收起' : '展开'} ${row.doc.title} 的子页面`" @click="toggleRow(row.doc.id)">
          <Icon name="chevron" :size="13" :class="{ rotated: expandedIds.has(row.doc.id) }" aria-hidden="true" />
        </button>
        <span v-else class="directory-arrow-placeholder" aria-hidden="true" />
        <button type="button" class="directory-open" :aria-label="row.doc.title || '无标题'" :title="row.doc.title || '无标题'" @click="emit('open', row.doc.id)">
          <Icon :name="row.childCount ? 'folder' : 'note'" :size="15" aria-hidden="true" />
          <span class="directory-title">{{ row.doc.title || '无标题' }}</span>
          <span v-if="row.childCount" class="directory-count">{{ row.childCount }}</span>
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.auto-directory { flex-shrink: 0; min-width: 0; max-width: 100%; margin: 4px 16px 10px; padding: 6px 0; border-bottom: 1px solid var(--bg-raised); border-radius: var(--radius-sm); background: var(--bg-panel); color: var(--text-hi); }
.directory-header { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 12px; min-width: 0; }
button { border: 0; background: transparent; color: inherit; font: inherit; font-size: 13px; cursor: pointer; border-radius: var(--radius-sm); }
button:hover { background: var(--bg-raised); }
button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.directory-toggle, .directory-create { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 4px 8px; }
.directory-toggle { min-width: 0; text-align: start; }
.directory-create { margin-inline-start: auto; color: var(--text-lo); white-space: nowrap; }
.directory-list { list-style: none; margin: 4px 0 0; padding: 0; max-height: clamp(0px, 30vh, 24rem); overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain; }
.directory-row { display: flex; align-items: center; min-width: 0; max-width: 100%; }
.directory-arrow, .directory-arrow-placeholder { width: 32px; flex: 0 0 32px; }
.directory-arrow { display: grid; place-items: center; min-height: 36px; color: var(--text-lo); }
.directory-open { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; min-height: 36px; padding: 4px 8px; text-align: start; }
.directory-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.directory-count { margin-inline-start: auto; flex-shrink: 0; color: var(--text-faint); font-size: 12px; }
.rotated { transform: rotate(90deg); }
@media (max-width: 768px) {
  .directory-list { max-height: clamp(0px, 35vh, 24rem); }
  .directory-arrow, .directory-open, .directory-toggle, .directory-create { min-height: 44px; }
}
</style>
