<script setup lang="ts">
import { computed, onMounted, ref, toRaw } from 'vue';
import Dropdown from '../../shell/Dropdown.vue';
import ImportTargetTree from './ImportTargetTree.vue';
import ImportReadPreview from './ImportReadPreview.vue';
import ZipImportDialog from './ZipImportDialog.vue';
import HtmlConversionRow from './HtmlConversionRow.vue';
import WebProjectImportRow from './WebProjectImportRow.vue';
import { api } from '../../api/client';
import { useImportSession, isImportAbort, importErrorMessage } from './importSession';
import { listDocs, type Doc } from '../../api/notes';
import { useNotesStore } from '../../stores/notes';
import { isZipFilename, prepareImport, queueImports, runImportBatch, type ImportEncoding, type ImportSource, type ImportTarget, type ImportRow } from './import-helpers';

const props = defineProps<{ files: ImportSource[]; workspaceId: string; parentId: string | null }>();
const emit = defineEmits<{ close: []; busy: [value: boolean]; open: [id:string] }>();
const store = useNotesStore();
const session = useImportSession();
const zipFiles = ref<ImportSource[]>([]);
const htmlFiles = ref<ImportSource[]>([]);
const conversionFiles = ref<ImportSource[]>([]);
const sourceProblems = ref<{file:ImportSource;error:string}[]>([]);
const rows = ref<ImportRow[]>([]);
const activeTextId = ref('');
const activeText = computed(() => rows.value.find(row => row.id === activeTextId.value && row.content !== undefined) ?? rows.value.find(row => row.content !== undefined));
const importedResults = ref<{id:string;title?:string}[]>([]);
function recordResults(documents:{id:string;title?:string}[]) {
  for(const doc of documents) if(!importedResults.value.some(item => item.id === doc.id)) importedResults.value.push(doc);
}
const results = computed(() => [...rows.value.filter(row => row.status === 'success' && row.documentId).map(row => ({id:row.documentId!,title:row.title})),...importedResults.value]);
const htmlDone = ref(0);
const projectFiles = ref<ImportSource[]>([]);
const projectDone = ref(0);
function projectComplete(id:string,title:string) {projectDone.value++;recordResults([{id,title}]);}
const admissions=new WeakMap<object,{auto:()=>void;manual:()=>void}>();
function admitQueue(){session.capture()();}
function admission(file:ImportSource){return admissions.get(toRaw(file));}
function chooseHtml(index:number, mode:'project'|'markdown') {
  if(busy.value||preparing.value||loadingTargets.value||error.value)return;
  const check=session.capture();
  try{check();}catch(e){error.value=message(e);return;}
  const file=htmlFiles.value.splice(index,1)[0];
  if(file)admissions.set(toRaw(file),{auto:check,manual:()=>{session.capture()();}});
  if(file)(mode==='project'?projectFiles:conversionFiles).value.push(file);
}
// Dialog-owned, per-original-file, read-only receipts only; rows still unmount and cancel.
const previews = new WeakMap<object, Map<string, unknown>>();
function previewCache(file:ImportSource) { const key=toRaw(file); let cache=previews.get(key); if(!cache){cache=new Map();previews.set(key,cache);}return cache; }
const ids = new WeakMap<object,string>();
function fileId(file:ImportSource){let id=ids.get(file);if(!id){id=crypto.randomUUID();ids.set(file,id);}return id;}
const fileInput = ref<HTMLInputElement|null>(null);
const excluded = ref(new Set<string>());
async function prepareSources(files:ImportSource[]) {
  const texts = files.filter(file => (!isZipFilename(file.name) && !/\.html?$/i.test(file.name)) || file.isDirectory);
  const additions = queueImports([...rows.value.map(r=>r.file), ...texts]).slice(rows.value.length);
  const start = rows.value.length;
  rows.value.push(...additions);
  for(const file of files.filter(file=>!texts.includes(file))) {
    if(!isZipFilename(file.name)){htmlFiles.value.push(file);continue;}
    try {
      if(file.size>32*1024*1024)throw new Error('ZIP 文件超过32 MiB，未读取或上传。');
      const bytes=await file.arrayBuffer();
      if(bytes.byteLength>32*1024*1024)throw new Error('ZIP 文件超过32 MiB，未上传。');
      // Inspect member names only. Never extract, rename or rewrite the source ZIP.
      const {default:JSZip}=await import('jszip');
      const zip=await JSZip.loadAsync(bytes);
      (Object.values(zip.files).some(entry=>!entry.dir&&/\.html?$/i.test(entry.name))?htmlFiles:zipFiles).value.push(file);
    } catch(e) {sourceProblems.value.push({file,error:importErrorMessage(e,'无法读取 ZIP 文件')});}
  }
  // Decode through Vue proxies so the eligible count updates immediately.
  for(const row of rows.value.slice(start))await prepareImport(row);
}
async function append(files:ImportSource[]) {
  if(busy.value||preparing.value||frozen.value)return;
  preparing.value=true;
  try {await prepareSources(files);} finally {preparing.value=false;}
}
function picked(event:Event) { const input=event.target as HTMLInputElement; void append(Array.from(input.files??[])); input.value=''; }
function drop(event:DragEvent) { if(event.dataTransfer) void append(Array.from(event.dataTransfer.files)); }
function remove(id:string) { if(!busy.value&&!frozen.value&&!preparing.value) rows.value=rows.value.filter(r=>r.id!==id); }
function selectRow(id:string, checked:boolean) { const next=new Set(excluded.value); if(checked)next.delete(id);else next.add(id);excluded.value=next; }
const workspaceId = ref(props.workspaceId);
const parentId = ref(props.parentId ?? '');
const docs = ref<Doc[]>([]);
const busy = ref(false);
const zipCompleted = ref<Record<string, number>>({});
const zipDone = computed(() => Object.keys(zipCompleted.value).length);
const zipDocCount = computed(() => Object.values(zipCompleted.value).reduce((a,b) => a+b,0));
const preparing = ref(true);
const loadingTargets = ref(false);
const frozen = ref<ImportTarget | null>(null);
const error = ref('');
const finalizeError = ref('');
const refreshError = ref('');
async function refreshImportedList() {
  refreshError.value = '';
  try { await store.refreshList(); }
  catch (e) { refreshError.value = `列表刷新失败：${message(e)}`; }
}
async function retryRefresh() {
  if (busy.value) return;
  busy.value = true; emit('busy', true);
  try { await refreshImportedList(); }
  finally { busy.value = false; emit('busy', false); }
}
const synced = ref<number | null>(null);
const phase = ref('等待导入');
const completed = computed(() => rows.value.filter(row => row.status === 'success' || row.status === 'failed').length);
const actionable = computed(() => rows.value.filter(row => row.payload || ['ready', 'importing', 'failed', 'success'].includes(row.status)).length);
const readCount = computed(() => rows.value.filter(row => !['reading', 'pending'].includes(row.status)).length);
const currentFile = computed(() => rows.value.find(row => row.status === 'importing')?.file.name);

const workspaceOptions = computed(() => store.workspaces.map(w => ({ value: w.id, label: w.name })));
const target = computed(() => frozen.value ?? { workspaceId: workspaceId.value, parentId: parentId.value || null });
function lockTarget() { frozen.value ??= { ...target.value }; }
function zipBusy(value: boolean) { busy.value = value; emit('busy', value); }
const encodingOptions = [{ value: 'auto', label: '自动 / BOM' }, { value: 'utf-8', label: 'UTF-8' }, { value: 'gb18030', label: 'GB18030' }];
const eligible = computed(() => rows.value.filter(r => !excluded.value.has(r.id) && (r.status === 'ready' || r.status === 'failed')).length);
const successes = computed(() => rows.value.filter(r => r.status === 'success').length);
const labels: Record<ImportRow['status'], string> = { pending: '等待读取', reading: '读取中', ready: '待导入', 'encoding-error': '请指定编码', rejected: '已拒绝', importing: '导入中', success: '已导入', failed: '失败 · 可重试' };
async function loadTargets() {
  loadingTargets.value = true;
  error.value = '';
  try { docs.value = await listDocs(workspaceId.value); }
  catch (e) { error.value = `无法加载完整目标列表：${message(e)}`; }
  finally { loadingTargets.value = false; }
}
async function changeWorkspace(value: string | number | boolean) {
  if (frozen.value || busy.value) return;
  workspaceId.value = String(value); parentId.value = ''; docs.value = [];
  await loadTargets();
}
function message(e: unknown) { return importErrorMessage(e, String(e)); }
async function reDecode(row: ImportRow, value: string | number | boolean) {
  if (busy.value || row.payload) return;
  row.encoding = value as ImportEncoding;
  await prepareImport(row);
}
onMounted(async () => {
  const targets=loadTargets();
  if(props.files.length){try{await prepareSources(props.files);}finally{preparing.value=false;}}
  else {preparing.value=false;fileInput.value?.click();}
  await targets;
});
async function run() {
  if (busy.value || preparing.value || loadingTargets.value) return;
  const check = session.capture();
  phase.value = '正在检查目标位置…'; busy.value = true; emit('busy', true); error.value = ''; finalizeError.value = ''; synced.value = null;
  // Never follow the selected editor or a later workspace switch.
  const target = frozen.value ?? { workspaceId: workspaceId.value, parentId: parentId.value || null };
  frozen.value = { ...target };
  try {
    check();
    const all = await listDocs(target.workspaceId); // Full workspace, never filtered store.docs.
    check();
    if (target.parentId && !all.some(d => d.id === target.parentId)) throw new Error('目标笔记已不存在，请关闭后重新选择');
    phase.value = '正在导入文件…';
    await runImportBatch(rows.value.filter(r=>!excluded.value.has(r.id)), target, all.map(d => d.title), payload =>
      api<{ id: string }>('/documents/', { method: 'POST', signal: check.signal, headers: {'Content-Type':'application/json','X-Import-Key':payload.file_path}, body: JSON.stringify(payload) }), check);
    check();
    const ids = rows.value.filter(r => r.status === 'success' && r.documentId).map(r => r.documentId!);
    if (ids.length) {
      phase.value = '正在同步双链…';
      try {
        check();
        const result = await api<{ synced: number }>('/documents/import/finalize', {
          method: 'POST', signal: check.signal, body: JSON.stringify({ workspace_id: target.workspaceId, document_ids: ids }),
        });
        check();
        synced.value = result.synced;
      } catch (e) {
        finalizeError.value = `笔记已创建，但双链同步结果未确认：${message(e)}。可重试同步，不会重复创建成功笔记。`;
        check(); if (isImportAbort(e)) throw e;
      }
    }
  } catch (e) {
    if (session.alive()) {
      error.value = message(e);
      // Creation may have finished just before the finalization admission fence.
      if (synced.value === null && rows.value.some(row => row.status === 'success')) {
        finalizeError.value ||= '笔记已创建，双链同步尚未确认。请以原账号明确重试同步，不会重复创建。';
      }
    }
  }
  finally {
    try {
      check();
      phase.value = '正在刷新列表…';
      await refreshImportedList();
      check();
      phase.value = '本轮处理完成';
    } catch (e) { if (session.alive()) error.value = message(e); }
    busy.value = false; if (session.alive()) emit('busy', false);
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="import-mask" @click.self="!busy && emit('close')" @keydown.esc="!busy && emit('close')">
      <section class="import-dialog" role="dialog" aria-modal="true" aria-labelledby="import-title" tabindex="-1">
        <header><h2 id="import-title">导入笔记 / 网页</h2><button :disabled="busy" aria-label="关闭导入" @click="emit('close')"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg></button></header>
        <div class="import-body">
        <div class="file-drop" @dragover.prevent @drop.prevent.stop="drop"><button :disabled="busy || preparing || !!frozen" @click="fileInput?.click()">选择文件 / 继续添加</button><span>或拖放多个文件到此处</span><input ref="fileInput" type="file" accept=".md,.txt,.zip,.html,.htm" multiple hidden @change="picked" /><details class="format-limits"><summary>限制与原档</summary><p>Markdown / 文本各新建私有笔记，不覆盖旧笔记；最多 50 个文本文件，单个 5 MiB，每批 20 MiB。HTML 转换保留原档附件；ZIP 保留目录与附件；各格式独立导入。</p></details></div>

        <fieldset :disabled="busy || !!frozen || loadingTargets" class="targets">
          <label>工作区<Dropdown :model-value="workspaceId" :options="workspaceOptions" @update:model-value="changeWorkspace" /></label>
          <div class="target-pages"><span>导入到</span><ImportTargetTree v-model="parentId" :docs="docs" :disabled="busy || !!frozen || loadingTargets" /></div>
        </fieldset>
        <p v-if="frozen">失败重试仍导入原位置。</p>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <p v-if="finalizeError" class="warning" role="alert">{{ finalizeError }}</p>
        <div v-if="refreshError" class="warning" role="alert">{{ refreshError }} <button :disabled="busy" @click="retryRefresh">重试刷新列表</button></div>
        <div v-if="rows.length" class="import-progress" aria-live="polite">
          <template v-if="preparing"><span>正在读取文件 {{ readCount }} / {{ rows.length }}…</span><progress aria-label="文件读取进度" :value="readCount" :max="rows.length || 1" /></template>
          <template v-else><span>{{ currentFile ? `正在导入：${currentFile}` : busy ? phase : frozen ? '本轮处理完成' : `已读取 ${rows.length} 个文件` }}</span><progress v-if="busy || frozen" aria-label="文件导入进度" :value="completed" :max="actionable || 1" /><span v-if="busy || frozen">{{ completed }} / {{ actionable }} 已处理 · {{ successes }} 成功</span></template>
        </div>
        <div class="import-rows" aria-live="polite">
          <article v-for="(file,index) in htmlFiles" :key="fileId(file)" class="format-choice">
            <strong>{{file.name}}</strong>
            <p v-if="file.size>25*1024*1024" class="error" role="alert">文件超过25 MiB，未读取或上传。</p>
            <div class="choice-actions"><button :disabled="busy||preparing||loadingTargets||!!error||file.size>25*1024*1024" @click="chooseHtml(index,'project')">渲染HTML</button><button :disabled="busy||preparing||loadingTargets||!!error||file.size>25*1024*1024" @click="chooseHtml(index,'markdown')">转为MD笔记</button><button :disabled="busy||preparing" :aria-label="`移除 ${file.name}`" @click="htmlFiles.splice(index,1)">移除</button></div>
            <p>渲染HTML保留网页样式与交互；转为MD笔记后可编辑。两种方式都保留原文件。</p>
          </article>
          <WebProjectImportRow v-for="file in projectFiles" :key="fileId(file)" auto-start :admission="admission(file)" :preview-cache="previewCache(file)" :file="file" :target="target" :disabled="busy||preparing||loadingTargets||!!error" @busy="zipBusy" @lock="lockTarget" @complete="projectComplete($event,file.name)" />
          <HtmlConversionRow v-for="file in conversionFiles" :key="fileId(file)" auto-start :admission="admission(file)" :preview-cache="previewCache(file)" :file="file" :target="target" :disabled="busy||preparing||loadingTargets||!!error" @busy="zipBusy" @lock="lockTarget" @complete="htmlDone+=$event" @created="recordResults" />
          <ZipImportDialog v-for="file in zipFiles" :key="fileId(file)" :admission="admitQueue" :preview-cache="previewCache(file)" :file="file" :target="target" :disabled="busy||preparing||loadingTargets||!!error" @busy="zipBusy" @lock="lockTarget" @complete="zipCompleted[fileId(file)]=$event" @created="recordResults" />
          <article v-for="problem in sourceProblems" :key="fileId(problem.file)" class="import-row"><strong>{{problem.file.name}}</strong><p class="error" role="alert">{{problem.error}}</p></article>
          <article v-for="row in rows" :key="row.id" class="import-row" :data-status="row.status">
            <div class="row-heading"><label><input type="checkbox" :checked="!excluded.has(row.id)" :disabled="busy||!!frozen||preparing" :aria-label="`选择 ${row.file.name}`" @change="selectRow(row.id,($event.target as HTMLInputElement).checked)" /><strong>{{ row.file.name }}</strong></label><span>{{ labels[row.status] }}</span><button :disabled="busy||!!frozen||preparing" :aria-label="`移除 ${row.file.name}`" @click="remove(row.id)">移除</button></div>
            <button v-if="rows.length > 1 && row.content !== undefined" class="text-preview-choice" :aria-pressed="activeText?.id === row.id" @click="activeTextId=row.id">预览 {{row.file.name}}</button>
            <div v-if="row.title !== row.file.name.replace(/\.(md|txt)$/i, '')">新标题：{{ row.title }}</div>
            <p v-if="row.error" class="error">{{ row.error }}</p>
            <p v-if="row.warning" class="warning">{{ row.warning }} 可将正文与图片一起打包为 ZIP 导入。</p>
            <fieldset v-if="row.status === 'encoding-error'" :disabled="busy"><legend>重试解码</legend><Dropdown :model-value="row.encoding" :options="encodingOptions" @update:model-value="reDecode(row, $event)" /></fieldset>
          </article>
          <details v-if="activeText"><summary>查看正文</summary><ImportReadPreview :markdown="activeText.content!" /></details>
        </div>
        <div v-if="results.length" class="import-results" aria-label="导入结果"><button v-for="doc in results" :key="doc.id" :disabled="busy" @click="emit('open',doc.id)">打开 {{doc.title || '导入的笔记'}}</button></div>
        </div>
        <footer><span>{{ preparing ? '正在读取文件…' : results.length ? `已创建 ${results.length} 项` : '尚未导入' }}<span v-if="zipFiles.length"> ZIP {{ zipDone }} / {{ zipFiles.length }} · {{ zipDocCount }} 个页面已导入</span><template v-if="synced !== null"> · 双链已同步 {{ synced }} 篇</template></span>
          <button v-if="results.length" :disabled="busy" @click="emit('open',results[0]!.id)">打开首篇</button>
          <button :disabled="busy" @click="emit('close')">{{ successes || zipDone || htmlDone || projectDone ? '完成' : '取消' }}</button>
          <button v-if="rows.length && (eligible || finalizeError || successes < rows.length)" class="primary" :disabled="busy || preparing || loadingTargets || (!eligible && !finalizeError)" @click="run">{{ busy ? '导入中…' : eligible ? (rows.some(r => r.payload) ? '重试未成功文件' : `导入 ${eligible} 篇`) : finalizeError ? '重试双链同步' : '暂无可导入文本' }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.format-choice{display:grid;gap:10px;padding:14px 0;border-bottom:1px solid var(--accent-dim)}.choice-actions{display:flex;flex-wrap:wrap;gap:8px}.format-choice strong{font-size:14px}.choice-actions button:first-child{color:var(--accent)}
.import-progress { display: grid; gap: 6px; font-size: 12px; color: var(--text-lo); }
.import-progress progress { width: 100%; height: 7px; accent-color: var(--accent); border: none; border-radius: 4px; overflow: hidden; }
.import-progress progress::-webkit-progress-bar { background: var(--bg-raised); }
.import-progress progress::-webkit-progress-value { background: var(--accent); transition: width .15s; }

.import-mask { position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,.62); display: grid; place-items: center; padding: 16px; }
.import-dialog { overflow: hidden; font-family: Inter, sans-serif; width: min(1040px, 100%); max-height: calc(100dvh - 32px); display: flex; flex-direction: column; gap: 14px; padding: 22px; box-sizing: border-box; background: var(--bg-panel); color: var(--text-hi); border: 1px solid var(--accent-dim); border-radius: var(--radius); box-shadow: 0 20px 60px #0006; }
header, footer, .row-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2 { font-size: 18px; margin: 0; } p { margin: 0; font-size: 12px; line-height: 1.6; color: var(--text-lo); }
fieldset { border: 0; margin: 0; padding: 0; min-width: 0; } .targets { display: flex; gap: 18px; flex-shrink: 0; } .target-pages { flex: 1; } label { display: grid; gap: 6px; font-size: 12px; min-width: 0; }
fieldset:disabled { opacity: .6; pointer-events: none; } .import-rows { min-height: 70px; }
.import-body { overflow-y:auto; min-height:0; overscroll-behavior:contain; display:flex;flex-direction:column;gap:10px; padding-right:4px; }
.import-body>*{flex-shrink:0}.file-modes{margin:5px 0}.file-modes summary{font-size:12px;color:var(--text-lo);cursor:pointer;padding:6px 0}.file-modes button{margin:3px 6px 3px 0}
header,footer { flex-shrink:0; } footer { border-top:1px solid var(--accent-dim); padding-top:12px; }
.file-drop { display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--text-lo); } .format-limits summary{font-size:12px;cursor:pointer;color:var(--text-lo);padding:6px 0;}
.target-pages{display:block}.target-pages>span{display:block;margin-bottom:6px}.row-heading>label{display:flex;align-items:center;gap:8px;flex:1}.row-heading>label input{flex-shrink:0}.text-preview-choice{width:fit-content;max-width:100%;overflow-wrap:anywhere}.text-preview-choice[aria-pressed=true]{color:var(--accent)}.import-results{display:flex;flex-wrap:wrap;gap:8px}.import-results button{max-width:100%;overflow-wrap:anywhere}
.import-row { padding: 12px 0; border-bottom: 1px solid var(--bg-raised); font-size: 12px; display: grid; gap: 6px; } strong { overflow-wrap: anywhere; } .row-heading span { flex-shrink: 0; color: var(--text-lo); }
.error { color: var(--pink, #f99); } .warning { color: #e3b96b; } [data-status=success] .row-heading span { color: var(--accent); }
button { border: 1px solid var(--accent-dim); background: transparent; color: var(--text-hi); padding: 7px 12px; border-radius: var(--radius-sm); cursor: pointer; } button:disabled { opacity: .45; cursor: default; } .primary { color: var(--accent); } footer { flex-wrap: wrap; font-size: 12px; } footer span { margin-right: auto; }
@media(max-width: 520px) { .import-mask{padding:8px}.targets { gap:10px;align-items:start; }.targets>label{width:108px;flex-shrink:0}.targets :deep(.dd){min-width:0;width:100%}.targets :deep(.dd-btn){min-width:0;width:100%;height:41px;box-sizing:border-box}.file-drop>span{display:none}.target-pages{min-width:0} .import-dialog { padding: 14px; max-height:calc(100dvh - 16px); } footer{gap:8px}footer>span{flex-basis:100%}.row-heading{gap:6px}.row-heading span{font-size:11px}.row-heading button{padding:6px} }
</style>
