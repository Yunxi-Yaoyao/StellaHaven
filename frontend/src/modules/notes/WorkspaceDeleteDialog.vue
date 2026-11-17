<script setup lang="ts">
import {computed, onMounted, onBeforeUnmount, onDeactivated, ref, watch, nextTick} from 'vue';
import {useNotesStore} from '../../stores/notes';
import {listDocs, listTrash} from '../../api/notes';
import {workspaceDeletionContext} from './workspaceDeletion';
import './notesModal.css';

const props = defineProps<{targets:{id:string;name:string}[]; beforeDelete?:()=>Promise<boolean>}>();
const emit = defineEmits<{close:[]; changed:[]}>();
const store = useNotesStore();
const targets = props.targets.map(target=>({...target}));
const current = workspaceDeletionContext(store);
let alive = true;
let invalidated = false, deleting = false;
const valid = () => alive && !invalidated && current();
const ownerCurrent = workspaceDeletionContext({get userId(){return store.userId;},workspaceId:store.workspaceId});
watch(ownerCurrent, value => { if(!value) emit('close'); }, {flush:'sync'});
watch(current, value => {
  if(!value) { invalidated=true; if(!deleting || !ownerCurrent()) emit('close'); }
}, {flush:'sync'});
const loading = ref(true), busy = ref(false), error = ref('');
const counts = ref<{id:string;name:string;active:number;trash:number}[]>([]);
const result = ref<Awaited<ReturnType<typeof store.deleteWorkspaceBatch>>|null>(null);
const total = computed(()=>counts.value.reduce((n,row)=>n+row.active+row.trash,0));
const dialog = ref<HTMLElement|null>(null), cancelButton = ref<HTMLButtonElement|null>(null);
function onKeydown(event:KeyboardEvent) {
  if(event.key==='Escape') { event.stopPropagation(); if(!busy.value) emit('close'); }
  if(event.key!=='Tab') return;
  const buttons=[...dialog.value!.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];
  const first=buttons[0], last=buttons.at(-1);
  if(!first) {event.preventDefault();return;}
  if(event.shiftKey && document.activeElement===first) {event.preventDefault();last!.focus();}
  else if(!event.shiftKey && document.activeElement===last) {event.preventDefault();first.focus();}
}
async function preview() {
  loading.value = true; error.value = '';
  try {
    const rows = await Promise.all(targets.map(async target=>{
      const [active,trash] = await Promise.all([listDocs(target.id),listTrash(target.id)]);
      if(!Array.isArray(active) || !Array.isArray(trash) || [...active,...trash].some(doc=>doc.workspace_id!==target.id) || new Set([...active,...trash].map(doc=>doc.id)).size!==active.length+trash.length) throw new Error('Incomplete workspace inventory');
      return {...target,active:active.length,trash:trash.length};
    }));
    if(valid()) counts.value = rows;
  } catch { if(valid()) error.value = '工作区数量读取失败，请重试。'; }
  finally { if(valid()) loading.value = false; }
}
async function confirmDelete() {
  if(!valid() || loading.value || busy.value || result.value || error.value) return;
  busy.value = true;
  try {
    if(props.beforeDelete && !(await props.beforeDelete())) return;
    if(!valid()) return;
    deleting = true;
    const response = await store.deleteWorkspaceBatch(targets.map(w=>w.id),valid);
    if(!alive || !ownerCurrent()) return;
    result.value = response;
    if(response.results.some(r=>r.status==='deleted')) emit('changed');
  } finally { if(alive) busy.value = false; }
}
const statusText = {deleted:'已删除',failed:'删除失败',unknown:'结果尚未确认，请刷新核对；不要重复删除',skipped:'未执行'};
async function refreshInventory() {
  if(busy.value || !valid() || !result.value) return;
  busy.value = true;
  const verified = await store.reconcileWorkspaceDeletions(result.value.results.filter(r=>r.status==='deleted').map(r=>r.id),valid);
  if(alive && ownerCurrent()) {result.value.refreshFailed=!verified;busy.value=false;if(verified) emit('changed');}
}
onMounted(async()=>{void preview();await nextTick();cancelButton.value?.focus();});
onBeforeUnmount(()=>{alive=false;});
onDeactivated(()=>{invalidated=true;emit('close');});
</script>

<template>
  <Teleport to="body">
    <div class="notes-modal-mask" @click.self="!busy && emit('close')">
      <section ref="dialog" class="notes-modal workspace-delete-modal" role="dialog" aria-modal="true" aria-labelledby="workspace-delete-title" @keydown="onKeydown">
        <header><h2 id="workspace-delete-title">删除 {{ targets.length }} 个工作区</h2></header>
        <p v-if="loading" role="status">正在读取正常笔记和回收站数量…</p>
        <template v-else>
          <ul class="workspace-impact">
            <li v-for="row in counts" :key="row.id"><strong>{{ row.name }}</strong><span>正常 {{ row.active }} 篇 · 回收站 {{ row.trash }} 篇</span></li>
          </ul>
          <p v-if="!error">共 {{ total }} 篇笔记。工作区及其中所有正常笔记、回收站内容将一起<strong class="danger-text">永久删除，不可恢复</strong>。</p>
        </template>
        <p v-if="error" role="alert">{{ error }}</p>
        <template v-if="result">
          <ul class="workspace-results" aria-live="polite"><li v-for="row in result.results" :key="row.id">{{ targets.find(w=>w.id===row.id)?.name }}：{{ row.status==='deleted' && result.refreshFailed ? '删除请求成功，待核对' : statusText[row.status] }}</li></ul>
          <p v-if="result.refreshFailed" role="alert">删除请求已处理，但工作区列表刷新失败；请刷新核对，不要重复删除。</p>
        </template>
        <footer>
          <button v-if="!result" class="danger" :disabled="loading || busy || !!error" @click="confirmDelete">{{ busy ? '正在删除…' : '确认永久删除' }}</button>
          <button v-if="error" @click="preview">重新读取数量</button>
          <button v-if="result?.refreshFailed" :disabled="busy || invalidated" @click="refreshInventory">刷新工作区列表</button>
          <button ref="cancelButton" :disabled="busy" @click="emit('close')">{{ result ? '关闭' : '取消' }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.workspace-delete-modal{width:min(520px,100%)}
.workspace-impact,.workspace-results{padding:0;list-style:none;font-size:14px;line-height:1.6}
.workspace-impact li{padding:10px 0;border-bottom:1px solid var(--bg-raised);display:flex;flex-wrap:wrap;gap:4px 16px;justify-content:space-between}
.workspace-impact strong{overflow-wrap:anywhere}.workspace-impact span{color:var(--text-lo)}
.danger-text{color:var(--pink)}
footer{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end;margin-top:16px}
</style>
