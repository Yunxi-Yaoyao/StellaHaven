<script setup lang="ts">
import {zipLimitsText} from './importLimits';
import { computed, onBeforeUnmount, ref, watch, toRaw } from 'vue';
import ImportReadPreview from './ImportReadPreview.vue';
import type JSZipType from 'jszip';
import { importRequestId } from './importRequestId';
import { api, ApiError } from '../../api/client';
import {useImportSession, importErrorMessage, type ImportCheck} from './importSession';
import { useNotesStore } from '../../stores/notes';
import { decodeImport, importTreeRows, type ImportSource, type ImportTarget, type ImportEncoding } from './import-helpers';
interface Preview { entries: {path: string; title: string; kind: 'directory' | 'document' | 'attachment'; parent_path: string | null}[]; warnings: string[]; counts: { documents: number; attachments: number } }
interface Result { documents: {id: string; title: string; path: string; parent_id: string | null}[]; attachments: number; warnings: string[]; reused: boolean }
const props = defineProps<{ file: ImportSource; target: ImportTarget; disabled: boolean; admission?:()=>void; previewCache?: Map<string, unknown> }>();
const emit = defineEmits<{ busy: [value: boolean]; lock: []; complete: [count: number]; created: [documents: {id:string;title?:string}[]] }>();
const store = useNotesStore();
const session = useImportSession();
const encoding = ref<ImportEncoding>('auto');
const preview = ref<Preview | null>(null), result = ref<Result | null>(null);
const status = ref<'pending' | 'previewing' | 'ready' | 'importing' | 'failed' | 'success'>('pending');
const error = ref('');
const refreshError = ref('');
const snapshot = ref<{target: ImportTarget; encoding: ImportEncoding; importId: string} | null>(null);
let original:ImportSource|null=null, bytes:Promise<ArrayBuffer>|null=null;
const bodyPath = ref(''), bodyMarkdown = ref<string|null>(null), bodyNotice = ref('');
let bodySequence = 0, disposed = false;
onBeforeUnmount(() => { disposed = true; ++bodySequence; });
// Only read a server-approved member, never resources or arbitrary archive paths.
// Stream output is capped independently of untrusted ZIP size metadata.
async function readBody(path:string) {
  if(status.value === 'importing')return;
  const seq = ++bodySequence, check = session.capture();
  bodyPath.value=path; bodyMarkdown.value=null; bodyNotice.value='正在读取本地正文…';
  try {
    if(props.file.size > 25*1024*1024) throw new Error('文件过大，仅提供结构预检；正文请导入后查看。');
    const {default:JSZip}=await import('jszip');
    const zip = await JSZip.loadAsync(await props.file.arrayBuffer()); check(); if(disposed||seq!==bodySequence)return;
    const entry=zip.file(path); if(!entry) throw new Error('此目录没有可直接预览的正文；完整结果请导入后查看。');
    const cap=256*1024;
    const {bytes,truncated} = await new Promise<{bytes:Uint8Array;truncated:boolean}>((resolve,reject)=>{
      const chunks:Uint8Array[]=[];let size=0,finished=false;
      // JSZip exposes this browser stream at runtime; its bundled object DTO omits the signature.
      const member=entry as typeof entry & {internalStream(type:'uint8array'):JSZipType.JSZipStreamHelper<Uint8Array>};
      if(typeof member.internalStream!=='function')throw new Error('当前环境无法提供有界正文预览；请导入后查看。');
      const stream=member.internalStream('uint8array');
      function finish(truncated:boolean) { if(finished)return;finished=true;stream.pause();const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}resolve({bytes,truncated}); }
      stream.on('data',(chunk:Uint8Array)=>{if(finished)return;if(disposed||seq!==bodySequence){finished=true;stream.pause();reject(new Error('预览已取消'));return;}const part=chunk.subarray(0,cap-size);chunks.push(part);size+=part.length;if(size>=cap)finish(true);}).on('error',reject).on('end',()=>finish(false)).resume();
    });
    check(); if(disposed||seq!==bodySequence)return;
    bodyMarkdown.value=decodeImport(bytes,path,encoding.value).content;
    bodyNotice.value=truncated ? '本地正文摘要已截断至前 256 KiB；图片与相对链接未绑定，完整结果请导入后查看。' : '本地正文阅读预览；图片与相对链接未绑定。README 合并及目录标题以服务端导入结果为准。';
    savePreview();
  } catch(e) { if(!disposed&&seq===bodySequence){bodyNotice.value=message(e);savePreview();} }
}
const tree = computed(() => importTreeRows((preview.value?.entries ?? []).map(e => ({ ...e, id: e.path, parent_id: e.parent_path }))));
const locked = computed(() => props.disabled || status.value === 'previewing' || status.value === 'importing');
function message(e: unknown) { return e instanceof ApiError && typeof e.detail === 'string' ? e.detail : importErrorMessage(e, String(e)); }
function binding() { return JSON.stringify([props.target.workspaceId,props.target.parentId,encoding.value]); }
interface CachedPreview {file:ImportSource; key:string; encoding:ImportEncoding; preview:Preview; path:string; markdown:string|null; notice:string}
function savePreview() { if(preview.value)props.previewCache?.set('zip',{file:toRaw(props.file),key:binding(),encoding:encoding.value,preview:preview.value,path:bodyPath.value,markdown:bodyMarkdown.value,notice:bodyNotice.value} satisfies CachedPreview); }
const initial=props.previewCache?.get('zip') as CachedPreview|undefined;
if(initial?.file===toRaw(props.file))encoding.value=initial.encoding;
watch(() => [props.file,props.target.workspaceId, props.target.parentId], () => {
  if (!snapshot.value) {
    const cached=props.previewCache?.get('zip') as CachedPreview|undefined;
    const valid=cached?.file===toRaw(props.file)&&cached.key===binding();
    preview.value=valid?cached.preview:null;error.value='';status.value=valid?'ready':'pending';++bodySequence;
    bodyMarkdown.value=valid?cached.markdown:null;bodyPath.value=valid?cached.path:'';bodyNotice.value=valid?cached.notice:'';
  }
}, {immediate:true});
async function form(target: ImportTarget, codec: ImportEncoding, check: ImportCheck) {
  check();
  const file=original??props.file;
  if(file.size>32*1024*1024)throw new Error('文件超过32 MiB，未读取或上传。');
  const data=await(bytes??=file.arrayBuffer().catch(e=>{bytes=null;throw e;}));check();
  if(data.byteLength>32*1024*1024)throw new Error('文件超过32 MiB，未上传。');
  const body = new FormData();
  body.append('file', new Blob([data]), file.name);
  check();
  body.append('workspace_id', target.workspaceId);
  if (target.parentId) body.append('parent_id', target.parentId);
  body.append('encoding', codec);
  return body;
}
async function readPreview(codec = encoding.value) {
  if (locked.value || snapshot.value) return;
  try{props.admission?.();}catch(e){error.value=message(e);return;}
  const check = session.capture(), target={...props.target}, file=props.file;
  ++bodySequence;bodyPath.value='';bodyMarkdown.value=null;bodyNotice.value='';
  encoding.value = codec; preview.value = null; error.value = ''; status.value = 'previewing'; emit('busy', true);
  try {
    // Explicit empty headers suppress the JSON wrapper default; browser sets multipart boundary.
    const body = await form(target, codec, check);
    check();
    const data = await api<Preview>('/documents/import/zip/preview', { method: 'POST', signal: check.signal, headers: {}, body });
    check();
    if(file!==props.file||target.workspaceId!==props.target.workspaceId||target.parentId!==props.target.parentId)return;
    preview.value = data;
    status.value = 'ready';savePreview();

  } catch (e) { error.value = message(e); status.value = 'pending'; }
  finally { if (session.alive()) emit('busy', false); }
}
async function commit() {
  if (locked.value || result.value || props.file.size>32*1024*1024) return;
  try{props.admission?.();}catch(e){error.value=message(e);return;}
  const check = session.capture();
  original??=props.file;
  snapshot.value ??= { target: { ...props.target }, encoding: encoding.value, importId: importRequestId() };
  emit('lock'); emit('busy', true); status.value = 'importing'; error.value = ''; refreshError.value = '';
  try {
    const frozen = snapshot.value;
    if(!preview.value){
      const validation=await form(frozen.target,frozen.encoding,check);check();
      const data=await api<Preview>('/documents/import/zip/preview',{method:'POST',signal:check.signal,headers:{},body:validation});check();
      preview.value=data;
    }
    const body = await form(frozen.target, frozen.encoding, check);
    check(); body.append('import_id', frozen.importId);
    const data = await api<Result>('/documents/import/zip', { method: 'POST', signal: check.signal, headers: {}, body });
    check();
    result.value = data;
    status.value = 'success'; emit('complete', result.value.documents.length); emit('created', result.value.documents);
  } catch (e) { status.value = 'failed'; error.value = message(e); }
  finally {
    try { check(); await store.refreshList(); check(); } catch (e) { if (session.alive()) refreshError.value = message(e); }
    if (session.alive()) emit('busy', false);
  }
}
</script>
<template>
  <article class="zip-import" :data-status="status" aria-live="polite">
    <div class="zip-heading"><strong>{{ file.name }}</strong><span>{{ status === 'success' ? '已导入' : status === 'importing' ? '正在导入…' : status === 'previewing' ? '正在预览…' : status === 'failed' ? '失败 · 可重试' : '结构化 ZIP' }}</span></div>
    <p>保留目录与附件；新建私有笔记，同名自动加后缀，不覆盖已有页面。</p>
  <details><summary>ZIP 格式限制</summary><p class="import-limits">{{zipLimitsText}}</p></details>
    <p v-if="file.size>32*1024*1024" role="alert">文件超过32 MiB，未读取或上传。</p>
    <button v-if="!result" class="primary" :disabled="locked||file.size>32*1024*1024" @click="commit">{{ status === 'failed' ? '重试此 ZIP' : '导入此 ZIP' }}</button>
    <details v-if="!snapshot"><summary>正文编码</summary><div class="zip-actions">
      <span>正文编码</span>
      <button v-for="codec in (['auto', 'utf-8', 'gb18030'] as const)" :key="codec" :aria-pressed="encoding === codec" :disabled="locked" @click="readPreview(codec)">{{ codec === 'auto' ? '自动' : codec.toUpperCase() }}</button>

    </div></details>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="refreshError" class="error" role="alert">{{ refreshError }}</p>
    <progress v-if="status === 'previewing' || status === 'importing'" :aria-label="status === 'previewing' ? 'ZIP 预览进度' : 'ZIP 导入进度'" />
    <details v-if="preview"><summary>目录与附件详情</summary>
      <p>结构计划：{{ preview.counts.documents }} 个页面（含目录） · {{ preview.counts.attachments }} 个附件</p>
      <details class="zip-structure"><summary>目录与附件 · 更换预览篇目</summary><ul class="zip-tree" aria-label="ZIP 只读预览">
        <li v-for="entry in tree" :key="entry.path" :style="{ paddingLeft: `${8 + Math.min(entry.depth, 8) * 16}px` }" :title="entry.path"><span class="kind">{{ entry.kind === 'directory' ? '目录' : entry.kind === 'document' ? '笔记' : '附件' }}</span><button v-if="entry.kind==='document' && /\.(md|txt)$/i.test(entry.path)" :aria-pressed="bodyPath===entry.path" :disabled="locked" @click="readBody(entry.path)">{{entry.title}} · 阅读预览</button><span v-else>{{entry.title}}</span></li>
      </ul></details>
      <ImportReadPreview v-if="bodyMarkdown !== null" :markdown="bodyMarkdown" :summary="bodyNotice" />
      <p v-else-if="bodyNotice" role="status">{{bodyNotice}}</p>

      <p v-for="(warning, i) in preview.warnings" :key="i" class="warning">{{ warning }}</p>
    </details>
    <template v-if="result">
      <p class="success">已导入 {{ result.documents.length }} 个页面（含目录）、{{ result.attachments }} 个附件{{ result.reused ? ' · 已复用上次结果，未重复创建' : '' }}</p>
      <details><summary>已创建的页面</summary><ul class="zip-tree" aria-label="ZIP 导入结果"><li v-for="doc in result.documents" :key="doc.id">{{ doc.title }}</li></ul></details>
      <p v-for="(warning, i) in result.warnings" :key="i" class="warning">{{ warning }}</p>
    </template>
  </article>
</template>
<style scoped>
.zip-import { display: grid; gap: 9px; padding: 14px 0; border-bottom: 1px solid var(--accent-dim); font-size: 12px; min-width: 0; }
.zip-heading, .zip-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; } .zip-heading { justify-content: space-between; } strong { overflow-wrap: anywhere; } p { margin: 0; color: var(--text-lo); line-height: 1.6; } .zip-tree { list-style: none; padding: 4px; margin: 0; max-height: 180px; overflow: auto; background: var(--bg-raised); border-radius: var(--radius-sm); } li { padding: 5px 8px; overflow-wrap: anywhere; } .kind { color: var(--text-lo); margin-right: 8px; font-size: 10px; } button { width: fit-content; background: transparent; color: var(--text-hi); border: 1px solid var(--accent-dim); border-radius: var(--radius-sm); padding: 8px 10px; cursor: pointer; font: inherit; } button:disabled { opacity: .45; cursor: default; } button[aria-pressed=true], .primary, .success { color: var(--accent); } .error { color: var(--pink, #f99); } .warning { color: #e3b96b; } progress { width: 100%; accent-color: var(--accent); }
.primary{position:sticky;bottom:0;z-index:2;margin-left:auto;display:block;background:var(--bg-panel);box-shadow:0 -5px 14px var(--bg-panel);min-height:38px;color:var(--accent)}summary{cursor:pointer;font-size:12px;color:var(--text-lo);padding:5px 0}</style>
