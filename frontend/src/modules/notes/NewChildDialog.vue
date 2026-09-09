<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useNotesStore } from '../../stores/notes';
import { getDoc } from '../../api/notes';
import { builtinTemplates, TEMPLATE_TAG } from './noteTemplates';
const props = defineProps<{ parentId: string | null; parentTitle: string }>();
const emit = defineEmits<{ close: []; created: [id: string] }>();
const store = useNotesStore();
const owner = store.userId, workspace = store.workspaceId;
const title = ref(''), selected = ref('blank'), templateBody = ref('');
const busy = ref(false), loading = ref(false), previewFailed = ref(false), error = ref('');
let sequence = 0, mounted = true;
onBeforeUnmount(() => { mounted = false; ++sequence; });
onMounted(() => { void store.refreshTags().catch(() => { error.value = '模板列表读取失败，请关闭后重试喵~'; }); });
const belongsHere = () => mounted && store.userId === owner && store.workspaceId === workspace;
const heading = computed(() => props.parentId ? '新建子页面' : '新建笔记');
const custom = computed(() => {
  const tags = new Set(store.tags.filter(t => t.name === TEMPLATE_TAG).map(t => t.id));
  const ids = new Set(store.docTags.filter(t => tags.has(t.tag_id)).map(t => t.doc_id));
  return store.allDocs.filter(d => d.workspace_id === workspace && ids.has(d.id));
});
async function choose(id: string, source = false) {
  if (busy.value) return;
  const seq = ++sequence;
  selected.value = source ? `doc:${id}` : id;
  error.value = ''; previewFailed.value = false; templateBody.value = ''; loading.value = true;
  try {
    if (source) {
      const doc = await getDoc(id);
      if (!belongsHere() || seq !== sequence) return;
      if (doc.workspace_id !== workspace || doc.status === 'trashed') throw new Error('模板已移走或删除，请重新选择喵~');
      templateBody.value = doc.content ?? '';
    } else templateBody.value = builtinTemplates.find(t => t.id === id)?.content ?? '';
  } catch (e) { if (seq === sequence) { previewFailed.value = true; error.value = e instanceof Error ? e.message : '模板读取失败喵~'; } }
  finally { if (seq === sequence) loading.value = false; }
}
async function create() {
  if (busy.value || loading.value || previewFailed.value) return;
  error.value = '';
  busy.value = true;
  try {
    if (!belongsHere()) throw new Error('账号或工作区已变更，请重新打开喵~');
    if (props.parentId && !store.allDocs.some(d => d.id === props.parentId && d.workspace_id === workspace)) throw new Error('父页面已不存在，请重新选择喵~');
    // Copy only the previewed body; the source page and its descendants are untouched.
    const doc = await store.createNew(props.parentId ?? undefined, { title: title.value.trim() || '未命名笔记', content: templateBody.value });
    if (belongsHere()) emit('created', doc.id);
  } catch (e) { error.value = e instanceof Error ? e.message : '创建失败，请重试喵~'; }
  finally { busy.value = false; }
}
</script>
<template>
 <Teleport to="body"><div class="new-child-mask" @click.self="!busy && emit('close')" @keydown.esc="!busy && emit('close')">
  <form class="new-child-panel" role="dialog" aria-modal="true" :aria-label="heading" @submit.prevent="create">
   <h2>{{ heading }}</h2><p>创建到：{{ parentTitle }}。只新建正文，不修改原模板和已有页面。</p>
   <label>标题<input v-model="title" placeholder="未命名笔记" :disabled="busy" /></label>
   <section class="template-library" aria-label="模板库">
    <div class="template-options" role="group" aria-label="正文模板"><button v-for="t in builtinTemplates" :key="t.id" type="button" :disabled="busy" :aria-pressed="selected===t.id" :title="t.description" @click="choose(t.id)">{{ t.title }}</button></div>
    <div v-if="custom.length" class="template-options custom-templates" role="group" aria-label="我的模板"><button v-for="t in custom" :key="t.id" type="button" :disabled="busy" :aria-pressed="selected===`doc:${t.id}`" @click="choose(t.id,true)">{{ t.title }}</button></div>
    <p>在文章工具栏点“设为模板”，即可在此复用；编辑原文即可更新模板，移出模板库不会删除原文。模板按工作区保存，可跨设备使用。</p>
    <p v-if="selected.startsWith('doc:')">仅复制正文，不复制子页面或附件文件；正文中的链接仍指向原资源。</p>
    <p v-if="loading" role="status">读取模板中…</p>
    <pre v-else-if="templateBody" class="template-preview" aria-label="模板正文预览">{{ templateBody }}</pre>
   </section>
   <p v-if="error" role="alert">{{ error }}</p><footer><button type="button" :disabled="busy" @click="emit('close')">取消</button><button type="submit" :disabled="busy || loading || previewFailed">{{ busy ? '创建中…' : '创建' }}</button></footer>
  </form>
 </div></Teleport>
</template>
<style scoped>
.new-child-mask{position:fixed;inset:0;z-index:200;display:grid;place-items:center;background:#0008;padding:16px}.new-child-panel{width:min(580px,100%);max-height:90dvh;overflow:auto;box-sizing:border-box;background:var(--bg-panel);color:var(--text-hi);padding:20px;border:1px solid var(--accent-dim);border-radius:var(--radius)}h2{font-size:20px;margin:0 0 12px}p{font-size:12px;color:var(--text-lo);line-height:1.7}label{display:grid;gap:7px;font-size:13px}input{min-width:0;padding:8px;background:var(--bg-base);color:var(--text-hi);border:1px solid var(--accent-dim);border-radius:5px;font:inherit}.template-options,footer{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}footer{justify-content:flex-end}button{font:inherit;font-size:13px;padding:7px 12px;border-radius:5px;border:1px solid var(--accent-dim);background:transparent;color:var(--text-lo);cursor:pointer;max-width:100%;overflow-wrap:anywhere}button[aria-pressed=true]{background:var(--bg-raised);color:var(--accent)}button:disabled{opacity:.5;cursor:default}[role=alert]{color:var(--pink)}.template-preview{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto;background:var(--bg-base);padding:12px;border-radius:5px;line-height:1.65}.custom-templates{max-height:130px;overflow:auto}.template-library{min-width:0}
</style>
