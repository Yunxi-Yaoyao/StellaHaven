<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import TemplatePicker from './TemplatePicker.vue';
import { useNotesStore } from '../../stores/notes';
import { getDoc, listTemplates, createFromTemplate, type TemplateCatalog } from '../../api/notes';
import { importTreeRows } from './import-helpers';
const props = defineProps<{ parentId: string | null; parentTitle: string }>();
const emit = defineEmits<{ close: []; created: [id: string] }>();
const store = useNotesStore();
const owner = store.userId, workspace = store.workspaceId;
const title = ref(''), selected = ref(''), templateBody = ref('');
const catalog = ref<TemplateCatalog>({root_id:null,items:[],recent_ids:[]});
const busy = ref(false), loading = ref(true), previewFailed = ref(false), error = ref('');
let sequence = 0, mounted = true;
let catalogSequence = 0;
async function refreshCatalog() {
  if (!belongsHere()) return;
  const seq = ++catalogSequence;
  try {
    const result = await listTemplates(workspace);
    if (!belongsHere() || seq !== catalogSequence) return;
    catalog.value = result;
    if (selected.value && !result.items.some(t => t.id === selected.value && !t.is_folder)) {
      ++sequence; selected.value = ''; templateBody.value = ''; previewFailed.value = true; loading.value = false;
      error.value = '原模板已移出目录或删除，请选择其他模板或空白文章。';
    }
  } catch { if (belongsHere()) error.value = '模板列表更新失败，请重新打开后选择。'; }
}
watch(() => store.docs, () => { void refreshCatalog(); }, {deep:true});
onBeforeUnmount(() => { mounted = false; ++sequence; });
const belongsHere = () => mounted && store.userId === owner && store.workspaceId === workspace;
const heading = computed(() => props.parentId ? '新建子页面' : '新建笔记');
const items = computed(() => importTreeRows(catalog.value.items));
const recent = computed(() => catalog.value.recent_ids.slice(0,2).flatMap(id => catalog.value.items.filter(t => t.id === id && !t.is_folder)));
onMounted(async () => {
  try { const result = await listTemplates(workspace, true); if (belongsHere()) catalog.value = result; await store.refreshList(); }
  catch { error.value = '模板目录读取失败，请关闭后重试。仍可创建空白文章。'; }
  finally { loading.value = false; }
});
async function choose(id: string) {
  if (busy.value) return;
  const seq = ++sequence;
  selected.value = id;
  error.value = ''; previewFailed.value = false; templateBody.value = ''; loading.value = true;
  try {
    if (id) {
      const latest = await listTemplates(workspace);
      if (!belongsHere() || seq !== sequence) return;
      catalog.value = latest;
      if (!latest.items.some(t => t.id === id && !t.is_folder)) throw new Error('模板已移出目录或删除，请重新选择');
      const doc = await getDoc(id);
      if (!belongsHere() || seq !== sequence) return;
      templateBody.value = doc.content ?? '';
    }
  } catch (e) { if (seq === sequence) { previewFailed.value = true; error.value = e instanceof Error ? e.message : '模板读取失败'; } }
  finally { if (seq === sequence) loading.value = false; }
}
async function create() {
  if (busy.value || loading.value || previewFailed.value) return;
  error.value = ''; busy.value = true;
  try {
    if (!belongsHere()) throw new Error('账号或工作区已变更，请重新打开');
    const name = title.value.trim() || '未命名笔记';
    // Server revalidates membership and copies the latest body/attachments under lock.
    const doc = selected.value
      ? await createFromTemplate(workspace, selected.value, props.parentId, name)
      : await store.createNew(props.parentId ?? undefined, {title:name, content:''});
    if (belongsHere()) { void store.refreshList(); emit('created', doc.id); }
  } catch (e) { error.value = e instanceof Error ? e.message : '创建失败，请重试'; }
  finally { busy.value = false; }
}
</script>
<template>
 <Teleport to="body"><div class="new-child-mask" @click.self="!busy && emit('close')" @keydown.esc="!busy && emit('close')">
  <form class="new-child-panel" role="dialog" aria-modal="true" :aria-label="heading" @submit.prevent="create">
   <h2>{{ heading }}</h2><p>创建到：{{ parentTitle }}</p>
   <label>标题<input v-model="title" placeholder="未命名笔记" :disabled="busy" /></label>
   <section class="template-library" aria-label="模板库">
    <div class="template-options" role="group" aria-label="正文模板">
     <button type="button" :disabled="busy" :aria-pressed="!selected" @click="choose('')">空白文章</button>
     <button v-for="t in recent" :key="t.id" type="button" :disabled="busy" :aria-pressed="selected===t.id" @click="choose(t.id)">{{t.title}}</button>
    </div>
    <div class="template-field"><span>完整模板目录</span><TemplatePicker :model-value="selected" :options="items" :disabled="busy || loading" @update:model-value="choose" /></div>
    <p v-if="loading" role="status">读取模板中…</p>
    <pre v-else-if="templateBody" class="template-preview" aria-label="模板正文预览">{{ templateBody }}</pre>
   </section>
   <p v-if="error" role="alert">{{ error }}</p><footer><button type="button" :disabled="busy" @click="emit('close')">取消</button><button type="submit" :disabled="busy || loading || previewFailed">{{ busy ? '创建中…' : '创建' }}</button></footer>
  </form>
 </div></Teleport>
</template>
<style scoped>
.template-field{display:grid;gap:7px;font-size:13px;margin-top:12px}
.new-child-mask{position:fixed;inset:0;z-index:200;display:grid;place-items:center;background:#0008;padding:16px}.new-child-panel{width:min(580px,100%);max-height:90dvh;overflow:auto;box-sizing:border-box;background:var(--bg-panel);color:var(--text-hi);padding:20px;border:1px solid var(--accent-dim);border-radius:var(--radius)}h2{font-size:20px;margin:0 0 12px}p{font-size:12px;color:var(--text-lo);line-height:1.7}label{display:grid;gap:7px;font-size:13px;margin-top:12px}input,select{min-width:0;padding:8px;background:var(--bg-base);color:var(--text-hi);border:1px solid var(--accent-dim);border-radius:5px;font:inherit}.template-options,footer{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}footer{justify-content:flex-end}button{font:inherit;font-size:13px;padding:7px 12px;border-radius:5px;border:1px solid var(--accent-dim);background:transparent;color:var(--text-lo);cursor:pointer;max-width:100%;overflow-wrap:anywhere}button[aria-pressed=true]{background:var(--bg-raised);color:var(--accent)}button:disabled{opacity:.5;cursor:default}[role=alert]{color:var(--pink)}.template-preview{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto;background:var(--bg-base);padding:12px;border-radius:5px;line-height:1.65}.template-library{min-width:0}
</style>
