<script setup lang="ts">
import { onMounted, ref, watch, toRaw } from 'vue';
import { api } from '../../api/client';
import { useNotesStore } from '../../stores/notes';
import type { ImportSource, ImportTarget } from './import-helpers';
import { useImportSession, importErrorMessage, type ImportCheck } from './importSession';
import { htmlLimitsText } from './importLimits';

const props = defineProps<{ file: ImportSource; target: ImportTarget; disabled?: boolean; autoStart?: boolean; admission?: {auto:()=>void;manual:()=>void}; previewCache?: Map<string, unknown> }>();
const emit = defineEmits<{ busy: [value: boolean]; lock: []; complete: [count: number]; created: [documents: {id:string;title?:string}[]] }>();
const store = useNotesStore();
const session = useImportSession();
interface Report {
  converted_count: number;
  documents: { source: string; target: string; markdown: string; losses: string[] }[];
  warnings: string[];
}
const report = ref<Report | null>(null);
const error = ref(''), busy = ref(false), done = ref(false), requestId = ref('');
let frozen: ImportTarget | null = null, original: ImportSource | null = null;
let bytes: Promise<ArrayBuffer> | null = null;
function binding() { return JSON.stringify([props.target.workspaceId,props.target.parentId,'auto']); }
watch(() => [props.file, props.target.workspaceId, props.target.parentId], () => {
  if (!requestId.value) {
    const cached=props.previewCache?.get('html') as {file:ImportSource; key:string; report:Report}|undefined;
    report.value=cached?.file===toRaw(props.file)&&cached.key===binding()?cached.report:null; error.value='';
  }
}, {immediate:true});
async function form(target: ImportTarget, check: ImportCheck) {
  check();
  const file = original ?? props.file;
  if (file.size > 25*1024*1024) throw new Error('文件超过25 MiB，未读取或上传。');
  const data = await (bytes ??= file.arrayBuffer().catch(e => { bytes=null; throw e; }));
  check();
  if (data.byteLength > 25*1024*1024) throw new Error('文件超过25 MiB，未上传。');
  const body = new FormData();
  body.append('file', new Blob([data]), file.name);
  body.append('workspace_id', target.workspaceId);
  if (target.parentId) body.append('parent_id', target.parentId);
  body.append('encoding', 'auto');
  if (requestId.value) body.append('import_id', requestId.value);
  return body;
}
async function commit(automatic=false) {
  if (busy.value || props.disabled || done.value || props.file.size > 25*1024*1024) return;
  try{props.admission?.[automatic?'auto':'manual']();}catch(e){error.value=importErrorMessage(e);return;}
  const check = session.capture();
  busy.value = true; emit('busy', true); error.value = '';
  frozen ??= { ...props.target };
  original ??= props.file;
  requestId.value ||= crypto.randomUUID();
  emit('lock');
  try {
    if (!report.value) {
      const validation = await form(frozen, check);
      check();
      report.value = await api<Report>('/documents/import/html/preview', {method:'POST',signal:check.signal,body:validation});
      check();
    }
    const body = await form(frozen, check);
    check();
    const result = await api<{ documents: { id: string; title?: string; path?: string }[] }>('/documents/import/html', { method: 'POST', signal: check.signal, body });
    check();
    // ZIP receipts include directories before articles. Open the converted article,
    // retaining every returned result and its original path/order within each group.
    const convertedPaths = new Set(report.value?.documents.map(doc => doc.target));
    const converted = result.documents.filter(doc => doc.path !== undefined && convertedPaths.has(doc.path));
    const others = result.documents.filter(doc => doc.path === undefined || !convertedPaths.has(doc.path));
    done.value = true; emit('complete', result.documents.length); emit('created', [...converted, ...others]);
    try { check(); await store.refreshList(); check(); }
    catch { if (session.alive()) error.value = '笔记已导入，目录刷新失败。请重新打开目录，不要重复导入。'; }
  } catch (e) {
    if (session.alive()) error.value = importErrorMessage(e, '导入结果未确认，请重试同一批次');
  } finally {
    busy.value = false; if (session.alive()) emit('busy', false);
  }
}
onMounted(() => { if (props.autoStart) void commit(true); });
const lossNames: Record<string, string> = { script: '脚本交互', style: '样式', layout: '页面布局', iframe: '嵌入页面', canvas: '画布', form: '表单', 'event-handler': '事件交互', 'table-layout': '表格布局', 'external-layout': '外部样式', 'responsive-image': '响应式图片规则', 'merged-table-cells': '合并单元格转换后数据归属可能改变', 'list-numbering': '列表转换后编号可能改变' };
const altered = new Set(['layout','table-layout','external-layout','responsive-image','merged-table-cells','list-numbering']);
function lossSummary(losses:string[]) {
  const removed=losses.filter(x=>!altered.has(x)).map(x=>lossNames[x]||'其他不支持的内容');
  const changed=losses.filter(x=>altered.has(x)).map(x=>lossNames[x]||'其他结构');
  return [removed.length?`不保留：${removed.join('、')}`:'',changed.length?`可能改变：${changed.join('、')}`:''].filter(Boolean).join('；');
}
</script>
<template>
  <section class="html-conversion">
    <header><strong>{{file.name}}</strong><span>转为MD笔记</span></header>
    <p>保留原文件附件；转换后可编辑。</p>
    <p v-if="file.size>25*1024*1024" role="alert">文件超过25 MiB，未读取或上传。</p>
    <button class="primary" :disabled="busy||disabled||done||file.size>25*1024*1024" @click="commit()">{{done?'已导入':busy?'正在导入…':requestId||error?'重试确认导入结果':'转为MD笔记'}}</button>
    <details><summary>格式与转换详情</summary><p>{{htmlLimitsText}}</p><template v-if="report"><p v-for="doc in report.documents" :key="doc.source">{{doc.source}} → {{doc.target}}<span v-if="doc.losses.length"> · {{lossSummary(doc.losses)}}</span></p><p v-for="warning in report.warnings" :key="warning">{{warning}}</p></template></details>
    <p v-if="error" role="alert">{{error}}</p>
    <p v-if="busy" role="status">正在导入…</p>
  </section>
</template>
<style scoped>.html-conversion{border-top:1px solid #ffffff18;padding:14px 0}header{display:flex;flex-wrap:wrap;gap:8px;justify-content:space-between}header span,p{font-size:12px;color:var(--text-lo);line-height:1.7}strong{font-size:14px;overflow-wrap:anywhere}button{font:inherit;font-size:13px;padding:8px 12px;border:1px solid var(--accent-dim);background:var(--bg-raised);color:var(--text-hi);border-radius:7px;cursor:pointer}button:disabled{opacity:.5;cursor:default}pre{max-height:200px;overflow:auto;white-space:pre-wrap;font-size:12px;background:var(--bg-base);padding:12px}summary{cursor:pointer;font-size:13px;padding:9px 0}[role=alert]{color:var(--danger,var(--pink))}.primary{position:sticky;bottom:0;z-index:2;margin-left:auto;display:block;background:var(--bg-panel);box-shadow:0 -5px 14px var(--bg-panel);min-height:38px;color:var(--accent)}summary{cursor:pointer;font-size:12px;color:var(--text-lo);padding:5px 0}</style>
