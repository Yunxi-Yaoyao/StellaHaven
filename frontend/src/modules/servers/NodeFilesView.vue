<script setup lang="ts">
import {computed, onBeforeUnmount, onMounted, ref, watch, nextTick} from 'vue'
import Dropdown from '../../shell/Dropdown.vue'
import Icon from '../../shell/Icon.vue'
const props = defineProps<{scopeKey: string}>()
type Root = {id:string;label:string;write:boolean;blocked:boolean}
type Node = {id:number;name:string;online:boolean;roots:Root[]}
type Entry = {name:string;kind:string;size:number;mtime:number;mode:string;uid:number;gid:number}
const nodes = ref<Node[]>([]), nodeId = ref(0), rootId = ref(''), path = ref('')
const entries = ref<Entry[]>([]), hidden = ref(false), sort = ref('name'), descending = ref(false)
const busy = ref(false), error = ref(''), preview = ref<{text:string;etag:string}|null>(null), selected = ref('')
let generation = 0, jobId = '', controller = new AbortController()
const uploadInput=ref<HTMLInputElement|null>(null), attemptKey=ref('')
const attemptStorage=computed(()=>`stella:node-files:${props.scopeKey}:${nodeId.value}:${rootId.value}`)
function rememberAttempt(key:string){sessionStorage.setItem(attemptStorage.value,key);attemptKey.value=key}
function forgetAttempt(){sessionStorage.removeItem(attemptStorage.value);attemptKey.value='';uncertain.value=false}
class ApiError extends Error{status:number;constructor(message:string,status:number){super(message);this.status=status}}
const action = ref<{op:string;source:string;destination:string}|null>(null), draft = ref(''), editing = ref(false), notice=ref(''), uncertain=ref(false)
const writable=computed(()=>!!roots.value.find(x=>x.id===rootId.value)?.write && !roots.value.find(x=>x.id===rootId.value)?.blocked && !uncertain.value && !!node.value?.online)
const node = computed(()=>nodes.value.find(x=>x.id === nodeId.value))
const roots = computed(()=>node.value?.roots ?? [])
const crumbs = computed(()=>path.value ? path.value.split('/') : [])
const errorText:Record<string,string> = {destination_exists:'目标已存在，未覆盖任何文件。',cas_conflict:'文件已被其他程序修改；草稿已保留，请先核对新内容。',read_only_root:'当前目录只读。',metadata_preservation_denied:'无法保持原文件权限或属主，未保存。',node_offline:'节点离线，请等待文件服务上线。',path_denied:'路径不可访问或包含符号链接。',permission_denied:'节点当前运行用户无权读取此文件或目录（EACCES/EPERM）；未提权。',preview_limit:'文件超过文本预览上限（256 KiB），请下载查看。',binary_or_encoding:'此文件不是 UTF-8 文本，请下载查看。',directory_limit:'目录条目超过上限（2000），请进入更小的目录。',request_busy_or_unknown:'还有未完成或结果不明的操作，请先核对。',inactive_request:'操作已取消或过期。'}
async function api(url:string, init:RequestInit = {}) {
  const r = await fetch(url, {...init, credentials:'same-origin', signal:AbortSignal.any([init.signal??controller.signal,AbortSignal.timeout(10000)])})
  if (!r.ok) { if(r.status===401){entries.value=[];clearPreview();nodes.value=[];path.value=''} const data = await r.json().catch(()=>({})); throw new ApiError(typeof data.detail === 'string' ? data.detail : `请求失败（${r.status}）`,r.status) }
  return r.json()
}
function clearPreview(){preview.value=null;selected.value='';editing.value=false;draft.value=''}
const discardDialog=ref<HTMLDialogElement|null>(null)
const confirmingDiscard=ref(false)
let resolveDiscard:((discard:boolean)=>void)|undefined
async function discardDraft():Promise<boolean>{
 if(!editing.value || draft.value===preview.value?.text)return true
 if(resolveDiscard)return false
 confirmingDiscard.value=true
 const answer=new Promise<boolean>(resolve=>{resolveDiscard=resolve})
 await nextTick();discardDialog.value?.showModal()
 return answer
}
function answerDiscard(discard:boolean){discardDialog.value?.close();confirmingDiscard.value=false;resolveDiscard?.(discard);resolveDiscard=undefined}
async function closePreview(){if(busy.value||!await discardDraft())return;clearPreview()}
async function cancelRequest(){if(await discardDraft())leave()}
function leave() {
  answerDiscard(false)
  generation++; controller.abort(); controller = new AbortController()
  const old = jobId; jobId = ''; busy.value = false; clearPreview(); action.value=null; notice.value='';uncertain.value=!!attemptKey.value
  const g=generation
  if (old) void fetch(`/node-files/requests/${old}/cancel`, {method:'POST', credentials:'same-origin'}).then(r=>r.ok?r.json():null).then(job=>{if(g===generation&&job&&job.request_key===attemptKey.value&&['done','failed','cancelled'].includes(job.state))forgetAttempt()}).catch(()=>{})
}
async function request(op:string, target=path.value, options:Record<string,unknown>={}, upload?:Blob) {
  const g = ++generation, ctl=controller, write=['upload','edit','create','mkdir','rename','copy','move'].includes(op), key=crypto.randomUUID(); let created=false, tracked=false
  busy.value = true; error.value = ''; notice.value=''
  const scoped=(url:string, init:RequestInit={})=>api(url,{...init,signal:ctl.signal})
  try {
    if(upload){
      if(upload.size>(op==='edit'?256*1024:32*1024*1024))throw new Error('文件超过传输上限。')
      const hash=await crypto.subtle.digest('SHA-256',await upload.arrayBuffer())
      if(g!==generation)return null
      options={...options,size:upload.size,sha256:Array.from(new Uint8Array(hash)).map(x=>x.toString(16).padStart(2,'0')).join('')}
    }
    if(write){rememberAttempt(key);tracked=true}
    let job = await scoped('/node-files/requests', {method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify({protocol:1,request_key:key,node_id:nodeId.value,root:rootId.value,op,path:target,hidden:hidden.value,sort:sort.value,descending:descending.value,...options})})
    if(g !== generation) return null
    jobId = job.id;created=true
    if(upload){
      for(let offset=0;offset<upload.size;offset+=65536){
        if(g!==generation)return null
        await scoped(`/node-files/requests/${job.id}/upload?offset=${offset}`,{method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:await upload.slice(offset,offset+65536).arrayBuffer()})
      }
      job=await scoped(`/node-files/requests/${job.id}/seal`,{method:'POST'})
    }
    const deadline=Date.now()+65000
    while(['uploading','pending','running','committing'].includes(job.state)) {
      if(g !== generation) return null
      if(Date.now()>deadline) throw new Error('操作超时，请刷新核对，不要重复写入。')
      await new Promise(resolve=>setTimeout(resolve,120))
      job=await scoped(`/node-files/requests/${job.id}`)
    }
    if(g !== generation) return null
    if(job.state==='unknown'){uncertain.value=true;throw new Error('操作结果不明，仅可刷新列表或预览核对，写入已锁定。')}
    if(job.state!=='done') {jobId='';if(write){forgetAttempt();tracked=false}throw new Error(job.error ?? job.state)}
    if(write){forgetAttempt();tracked=false}
    jobId=''
    return job
  } catch(e) {
    if(g===generation && tracked){
      if(!created && e instanceof ApiError && e.status<500){forgetAttempt();tracked=false}
      else {uncertain.value=true;error.value='回执未明，写入已锁定；请先核对回执与文件。';return null}
    }
    if(g === generation && !(e instanceof DOMException && e.name === 'AbortError')) {const message=e instanceof Error?e.message:String(e);error.value=errorText[message]??message}
    return null
  } finally { if(g === generation) busy.value=false }
}
async function refresh(){
 if(busy.value||!await discardDraft())return
 const g=++generation
 try{const data=await api('/node-files/nodes');if(g!==generation)return;nodes.value=data;if(!roots.value.some(x=>x.id===rootId.value)){leave();entries.value=[];rootId.value='';path.value='';return}await load()}catch(e){if(g===generation)error.value=e instanceof Error?e.message:String(e)}
}
async function load() {const job=await request('list');if(job) entries.value=job.result.entries}
async function open(entry:Entry) {
  if(busy.value||!['directory','file'].includes(entry.kind)||!await discardDraft())return
  const target=[path.value,entry.name].filter(Boolean).join('/')
  if(entry.kind==='directory') {leave();path.value=target;await load()}
  else {clearPreview();const job=await request('preview',target);if(job){selected.value=target;preview.value=job.result;draft.value=job.result.text}}
}
async function download(entry?:Entry) {
  const target=entry?[path.value,entry.name].filter(Boolean).join('/'):selected.value
  const job=await request('download',target)
  if(job){const a=document.createElement('a');a.href=`/node-files/requests/${job.id}/download`;a.download=target.split('/').at(-1)??'download';document.body.appendChild(a);a.click();a.remove()}
}
async function navigate(index:number){if(busy.value||!await discardDraft())return;leave();path.value=crumbs.value.slice(0,index).join('/');await load()}
async function switchNode(value:string|number|boolean=nodeId.value){if(typeof value!=='number'||busy.value||!await discardDraft())return;leave();nodeId.value=value;entries.value=[];path.value='';rootId.value=roots.value[0]?.id??'';restoreAttempt();if(rootId.value)await load()}
async function switchRoot(value:string|number|boolean=rootId.value){if(typeof value!=='string'||busy.value||!await discardDraft())return;leave();rootId.value=value;entries.value=[];path.value='';restoreAttempt();if(rootId.value)await load()}
async function initialize(){
 const g=generation
 try{const data=await api('/node-files/nodes');if(g!==generation)return;nodes.value=data;nodeId.value=data[0]?.id??0;await switchNode()}catch(e){if(g===generation)error.value=e instanceof Error?e.message:String(e)}
}
function restoreAttempt(){attemptKey.value=sessionStorage.getItem(attemptStorage.value)??'';uncertain.value=!!attemptKey.value}
async function reconcile(){
 const g=++generation;busy.value=true;error.value=''
 try{
  const job=await api(`/node-files/by-key/${attemptKey.value}`)
  if(g!==generation)return
  if(['done','failed','cancelled'].includes(job.state)){forgetAttempt();jobId='';notice.value=job.state==='done'?'回执已确认操作完成，请刷新核对文件。':'回执已确认未完成操作。'}
  else{uncertain.value=true;error.value='操作尚未确认，仅可刷新列表或预览核对。'}
 }catch(e){if(g===generation){uncertain.value=true;error.value='暂未取得回执，保持写入锁定，不会重放请求。'}}
 finally{if(g===generation)busy.value=false}
}
function begin(op:string, source='') {action.value={op,source,destination:''};error.value='';notice.value=''}
async function applyAction(){
 const value=action.value;if(!value||!writable.value)return
 const source=['create','mkdir'].includes(value.op)?[path.value,value.destination].filter(Boolean).join('/'):value.source
 const job=await request(value.op,source,['rename','copy','move'].includes(value.op)?{destination:value.destination}:{})
 if(job){action.value=null;await load();notice.value='操作已完成。'}
}
async function uploadFile(event:Event){
 const input=event.target as HTMLInputElement, file=input.files?.[0]
 if(!file||!writable.value)return
 const job=await request('upload',[path.value,file.name].filter(Boolean).join('/'),{},file)
 if(job){await load();notice.value='上传已完成。';input.value=''}
}
function startEditing(){draft.value=preview.value?.text??'';editing.value=true;notice.value=''}
async function saveText(){
 if(!preview.value||!editing.value||!selected.value||busy.value||!writable.value)return
 const job=await request('edit',selected.value,{etag:preview.value.etag},new Blob([draft.value],{type:'text/plain;charset=utf-8'}))
 if(job){const current=await request('preview',selected.value);if(current){preview.value=current.result;draft.value=current.result.text;editing.value=false;notice.value='文件已保存。'}}
}
function target(entry:Entry){return [path.value,entry.name].filter(Boolean).join('/')}
watch(()=>props.scopeKey,()=>{leave();nodes.value=[];entries.value=[];uncertain.value=false;void initialize()})
onMounted(initialize)
onBeforeUnmount(leave)
</script>

<template>
<section class="node-files" aria-label="节点文件管理">
  <header><div><h2>文件管理</h2><p>节点目录</p></div><button :disabled="busy" @click="refresh">刷新</button><button v-if="busy" @click="cancelRequest">取消</button></header>
  <div class="toolbar">
    <!-- Dropdown intentionally has no disabled prop. A native disabled fieldset
         disables its real trigger/options without modifying the shared component. -->
    <fieldset class="picker" :disabled="busy" aria-label="节点选择"><span>节点</span><Dropdown role="group" :model-value="nodeId" aria-label="节点" :options="nodes.map(n=>({value:n.id,label:n.name+(n.online?'':' · 离线')}))" @update:model-value="switchNode" /></fieldset>
    <fieldset class="picker" :disabled="busy" aria-label="允许根选择"><span>目录</span><Dropdown role="group" :model-value="rootId" aria-label="允许根" :options="roots.map(r=>({value:r.id,label:r.label}))" @update:model-value="switchRoot" /></fieldset>
    <label class="toggle"><input v-model="hidden" type="checkbox" :disabled="busy" @change="load">隐藏文件</label>
    <fieldset class="picker sort-picker" :disabled="busy" aria-label="排序选择"><span>排序</span><Dropdown role="group" v-model="sort" aria-label="排序" :options="[{value:'name',label:'名称'},{value:'size',label:'大小'},{value:'mtime',label:'修改时间'}]" @update:model-value="load" /></fieldset>
    <label class="toggle"><input v-model="descending" type="checkbox" :disabled="busy" @change="load">降序</label>
  </div>
  <div class="write-toolbar"><button :disabled="busy||!writable" @click="begin('create')">新建文件</button><button :disabled="busy||!writable" @click="begin('mkdir')">新建目录</button><button :disabled="busy||!writable" @click="uploadInput?.click()">上传文件</button><input ref="uploadInput" class="file-input" aria-label="上传文件" type="file" tabindex="-1" :disabled="busy||!writable" @change="uploadFile"><button v-if="attemptKey" :disabled="busy" @click="reconcile">核对回执</button><span v-if="!writable">{{uncertain||roots.find(x=>x.id===rootId)?.blocked?'结果不明 · 仅可核对':'只读'}}</span></div>
  <form v-if="action" class="action-form" @submit.prevent="applyAction"><h3>{{({create:'新建文件',mkdir:'新建目录',rename:'改名',copy:'复制',move:'移动'} as Record<string,string>)[action.op]}}</h3><p v-if="action.source">{{action.source}}</p><label>{{['create','mkdir'].includes(action.op)?'名称':'目标路径'}}<input v-model="action.destination" :aria-label="['create','mkdir'].includes(action.op)?'名称':'目标路径'" required :disabled="busy" :placeholder="['create','mkdir'].includes(action.op)?'文件或目录名':'同一允许根内的相对路径'"></label><button type="submit" :disabled="busy||!writable">{{['create','mkdir'].includes(action.op)?'确认创建':'确认操作'}}</button><button type="button" :disabled="busy" aria-label="取消表单" @click="action=null">取消</button></form>
  <p v-if="notice" class="notice" role="status">{{notice}}</p>
  <nav class="breadcrumbs" aria-label="路径"><button :disabled="busy" @click="navigate(0)">{{roots.find(x=>x.id===rootId)?.label??'允许根'}}</button><template v-for="(c,i) in crumbs" :key="i"><span>/</span><button :disabled="busy" @click="navigate(i+1)">{{c}}</button></template></nav>
  <p v-if="error" role="alert">{{error}}</p>
  <p v-if="busy" role="status">正在读取…</p>
  <p v-if="!nodes.length && !error">尚未授权节点目录。</p>
  <p v-else-if="!node?.online">节点文件服务离线。</p>
  <div class="table-wrap"><table v-if="rootId"><thead><tr><th>名称</th><th>大小</th><th>权限</th><th>UID / GID</th><th>修改时间</th><th>操作</th></tr></thead><tbody>
    <tr v-for="entry in entries" :key="entry.name"><td><button class="filename" :disabled="busy||!['file','directory'].includes(entry.kind)" @click="open(entry)"><Icon :name="entry.kind==='directory'?'folder':entry.kind==='file'?'note':'link'" :size="16" aria-hidden="true" /><span>{{entry.name}}</span></button><small class="mobile-meta">{{entry.size.toLocaleString()}} B · {{entry.mode}} · UID {{entry.uid}} / GID {{entry.gid}}</small><small v-if="['link','special'].includes(entry.kind)">不跟随链接或特殊文件</small></td><td>{{entry.kind==='directory'?'—':`${entry.size.toLocaleString()} B`}}</td><td><code>{{entry.mode}}</code></td><td>{{entry.uid}} / {{entry.gid}}</td><td>{{new Date(entry.mtime*1000).toLocaleString()}}</td><td class="actions"><button v-if="entry.kind==='file'" :disabled="busy" :aria-label="`下载 ${entry.name}`" @click="download(entry)">下载</button><template v-if="['file','directory'].includes(entry.kind)"><button :disabled="busy||!writable" :aria-label="`改名 ${entry.name}`" @click="begin('rename',target(entry))">改名</button><button v-if="entry.kind==='file'" :disabled="busy||!writable" :aria-label="`复制 ${entry.name}`" @click="begin('copy',target(entry))">复制</button><button :disabled="busy||!writable" :aria-label="`移动 ${entry.name}`" @click="begin('move',target(entry))">移动</button></template></td></tr>
  </tbody></table></div>
  <p v-if="rootId&&!busy&&!entries.length&&!error">此目录为空。</p>
  <section v-if="preview" class="preview" aria-label="文本预览"><header><h3>{{selected}}</h3><button :disabled="busy" @click="closePreview">关闭</button><button :disabled="busy" @click="download()">下载</button><button v-if="!editing" :disabled="busy||!writable" @click="startEditing">编辑文本</button><button v-else :disabled="busy||!writable" @click="saveText">保存文件</button></header><textarea v-if="editing" v-model="draft" aria-label="文件内容" :disabled="busy" spellcheck="false"></textarea><pre v-else>{{preview.text}}</pre></section>
  <dialog v-if="confirmingDiscard" ref="discardDialog" class="discard-dialog" aria-label="未保存的文件修改" @cancel.prevent="answerDiscard(false)"><h3>未保存的文件修改</h3><p>丢弃草稿并继续？</p><footer><button autofocus @click="answerDiscard(false)">保留草稿</button><button @click="answerDiscard(true)">丢弃并继续</button></footer></dialog>
</section>
</template>

<style scoped>
.discard-dialog { width:min(420px,90vw); padding:22px; border:1px solid var(--accent-dim); border-radius:var(--radius); color:var(--text-hi); background:var(--bg-panel); }
.discard-dialog::backdrop { background:rgba(10,12,18,.6); backdrop-filter:blur(3px); }
.discard-dialog p { margin:14px 0; }
.discard-dialog footer { display:flex; justify-content:flex-end; gap:10px; }
.node-files { min-width:0; min-height:70vh; padding:22px 26px; color:var(--text-hi); background:var(--bg-base); font-family:"Inter Variable",var(--font-ui); font-size:14px; line-height:1.6; }
header,.toolbar,.breadcrumbs,.write-toolbar { display:flex; align-items:center; flex-wrap:wrap; gap:10px; }
header { justify-content:space-between; margin-bottom:18px; }
header>div { margin-right:auto; }
h2,h3,p { margin:0; }
h2 { font-size:19px; font-weight:600; letter-spacing:1px; }
header p { color:var(--text-faint); font-size:12px; margin-top:2px; }
button { display:inline-flex; align-items:center; justify-content:center; gap:6px; min-height:38px; max-width:100%; padding:7px 12px; border:1px solid var(--accent-dim); border-radius:var(--radius-sm); background:var(--bg-panel); color:var(--text-hi); font:inherit; font-size:13px; cursor:pointer; white-space:nowrap; transition:background-color var(--transition),border-color var(--transition); }
button:hover:not(:disabled) { background:var(--bg-raised); border-color:var(--accent); }
button:focus-visible,input:focus-visible,textarea:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
button:disabled { opacity:.5; cursor:default; }
.toolbar { gap:12px 18px; padding-bottom:16px; border-bottom:1px solid var(--accent-dim); }
.picker { display:flex; align-items:center; gap:8px; padding:0; margin:0; border:0; min-width:0; }
.picker>span,.toggle { color:var(--text-lo); font-size:13px; }
.picker :deep(.dd) { min-width:0; }
.picker :deep(.dd-btn) { min-height:38px; max-width:100%; }
.picker :deep(.dd-menu) { max-width:min(360px,calc(100vw - 48px)); }
.picker :deep(.dd-item-label) { white-space:normal; overflow-wrap:anywhere; }
.picker :deep(.dd-btn:disabled) { opacity:.5; cursor:default; }
.toggle { display:flex; align-items:center; gap:8px; min-height:38px; white-space:nowrap; cursor:pointer; }
.toggle input { width:16px; height:16px; accent-color:var(--accent); }
.write-toolbar { padding:14px 0 4px; }
.write-toolbar>span { color:var(--text-faint); font-size:12px; }
.file-input { position:absolute; width:1px; height:1px; opacity:0; overflow:hidden; pointer-events:none; }
.action-form { display:flex; align-items:center; flex-wrap:wrap; gap:10px; padding:16px; margin-top:12px; border:1px solid var(--accent-dim); border-radius:var(--radius); background:var(--bg-panel); }
.action-form h3 { font-size:15px; font-weight:600; }
.action-form p { max-width:100%; overflow-wrap:anywhere; color:var(--text-lo); }
.action-form label { display:flex; align-items:center; gap:8px; flex:1; min-width:min(220px,100%); color:var(--text-lo); white-space:nowrap; }
.action-form input { width:100%; min-width:0; min-height:38px; padding:8px 10px; color:var(--text-hi); background:var(--bg-base); border:1px solid var(--accent-dim); border-radius:var(--radius-sm); font:inherit; }
.action-form input::placeholder { color:var(--text-faint); opacity:1; }
.breadcrumbs { gap:6px; padding:14px 0; color:var(--text-faint); }
.breadcrumbs button { border:0; background:transparent; color:var(--accent); white-space:normal; overflow-wrap:anywhere; text-align:left; }
.table-wrap { min-width:0; overflow:auto; border:1px solid var(--accent-dim); border-radius:var(--radius); background:var(--bg-panel); }
table { width:100%; border-collapse:collapse; text-align:left; font-size:13px; }
th { color:var(--text-lo); background:var(--bg-raised); font-size:12px; font-weight:500; }
th,td { padding:10px 12px; border-bottom:1px solid var(--accent-dim); }
tr:last-child td { border-bottom:0; }
td { white-space:nowrap; color:var(--text-lo); }
.filename { justify-content:flex-start; min-width:0; max-width:36vw; padding:4px 0; background:transparent; border:0; color:var(--text-hi); text-align:left; }
.filename span { min-width:0; overflow:hidden; text-overflow:ellipsis; }
.filename :deep(.icon) { color:var(--accent); }
.actions { white-space:nowrap; }
.actions button { padding:6px 8px; background:transparent; }
.actions button+button { margin-left:4px; }
small { display:block; color:var(--text-faint); font-size:12px; overflow-wrap:anywhere; }
.mobile-meta { display:none; }
code,pre,textarea { font-family:var(--font-mono); }
p[role=alert] { padding:12px; margin:12px 0; border:1px solid var(--danger); border-radius:var(--radius-sm); color:var(--danger); overflow-wrap:anywhere; background:var(--bg-panel); }
p[role=status] { color:var(--success); padding:8px 0; }
.preview { min-width:0; margin-top:20px; border:1px solid var(--accent-dim); border-radius:var(--radius); padding:16px; background:var(--bg-panel); }
.preview header { gap:8px; margin-bottom:14px; }
.preview h3 { min-width:0; margin-right:auto; font-size:15px; font-weight:600; overflow-wrap:anywhere; }
.preview pre { max-height:50vh; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; color:var(--text-hi); font-size:13px; }
.preview textarea { width:100%; min-height:260px; max-height:50vh; resize:vertical; color:var(--text-hi); background:var(--bg-base); border:1px solid var(--accent-dim); border-radius:var(--radius-sm); padding:12px; font-size:14px; line-height:1.6; }
@media(max-width:650px) {
  .node-files { padding:18px 14px; }
  header { gap:8px; }
  .toolbar { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:8px 12px; }
  .picker { grid-column:1/-1; display:grid; grid-template-columns:36px minmax(0,1fr); }
  .picker :deep(.dd-btn) { width:100%; min-width:0; min-height:44px; }
  .picker :deep(.dd-menu) { width:100%; min-width:0; max-width:100%; }
  .picker :deep(.dd-item) { min-height:44px; align-items:center; font-size:13px; }
  .sort-picker { grid-row:3; }
  .toggle { min-height:44px; }
  button { min-height:44px; }
  .write-toolbar { gap:8px; }
  .action-form { padding:12px; }
  .action-form h3,.action-form p,.action-form label { flex-basis:100%; }
  .action-form input { min-height:44px; }
  table,tbody,tr { display:block; width:100%; }
  thead { display:none; }
  tr { border-bottom:1px solid var(--accent-dim); }
  tr:last-child { border-bottom:0; }
  td { border:0; }
  td:nth-child(n+2):nth-child(-n+5) { display:none; }
  td:first-child { display:block; padding:10px 12px 0; }
  .filename { max-width:100%; }
  .mobile-meta { display:block; white-space:normal; }
  .actions { display:flex; flex-wrap:wrap; gap:4px; padding:4px 8px 10px; }
  .actions button+button { margin-left:0; }
  .preview { padding:12px; }
  .preview h3 { flex-basis:100%; }
}
@media(prefers-reduced-motion:reduce) { button { transition:none; } }
</style>
