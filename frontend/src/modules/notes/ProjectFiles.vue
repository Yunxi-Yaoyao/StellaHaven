<script setup lang="ts">
import HelpHint from "../settings/HelpHint.vue";
import {computed,ref,watch,onBeforeUnmount,nextTick} from 'vue';
import {auth} from '../home/auth';
import {getProjectSource} from '../../api/webProjects';
import {setProjectEntry,type FileProject} from '../../api/projectFiles';
import {dragProjectAsset} from './projectAssetCopy';
const props=defineProps<{project:FileProject;fileId:string;active:boolean;beforeChange?:()=>Promise<boolean>}>();
const emit=defineEmits<{open:[id:string];directory:[];updated:[project:FileProject]}>();
const owner=auth.me?.id,session=auth.sessionGeneration;
let disposed=false,sequence=0;
const allowed=computed(()=>!disposed&&props.active&&auth.me?.id===owner&&auth.sessionGeneration===session&&!auth.suspended&&!auth.sessionClosing);
const directory=computed(()=>props.project.directories?.find(d=>d.id===props.fileId));
const file=computed(()=>props.project.files.find(f=>f.id===props.fileId));
const entries=computed(()=>props.project.files.filter(f=>f.kind==='text'&&/\.html?$/i.test(f.path)));
const currentEntry=computed(()=>props.project.entry_file_id??props.project.files.find(f=>f.path===props.project.entry)?.id??null);
const selectedEntry=ref(''),busy=ref(false),error=ref(''),status=ref('');
const pickerOpen=ref(false),picker=ref<HTMLElement|null>(null),trigger=ref<HTMLButtonElement|null>(null);
async function openPicker(){if(busy.value)return;pickerOpen.value=true;await nextTick();picker.value?.querySelector<HTMLButtonElement>('[role=option]')?.focus();}
function chooseEntry(id:string){selectedEntry.value=id;pickerOpen.value=false;trigger.value?.focus();}
function pickerKey(event:KeyboardEvent){const options=[...(picker.value?.querySelectorAll<HTMLButtonElement>('[role=option]')??[])];if(event.key==='Escape'){event.preventDefault();pickerOpen.value=false;trigger.value?.focus();}else if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();const i=options.indexOf(document.activeElement as HTMLButtonElement),step=event.key==='ArrowDown'?1:-1;options[(i+step+options.length)%options.length]?.focus();}}
const source=ref<Awaited<ReturnType<typeof getProjectSource>>|null>(null);
const children=computed(()=>{
 const path=directory.value?.path??'';
 return [...(props.project.directories??[]),...props.project.files].filter(f=>f.path.slice(0,f.path.lastIndexOf('/')<0?0:f.path.lastIndexOf('/'))===path);
});
watch(currentEntry,id=>selectedEntry.value=id??'',{immediate:true});
watch(()=>[props.project.id,props.fileId,allowed.value,auth.requestEpoch],async()=>{
 const seq=++sequence;source.value=null;error.value='';
 if(!allowed.value||file.value?.kind!=='binary')return;
 try{const value=await getProjectSource(props.project.id,props.fileId);if(seq===sequence&&allowed.value)source.value=value;}
 catch(e){if(seq===sequence&&allowed.value)error.value=e instanceof Error?e.message:'资源读取失败';}
},{immediate:true,flush:'sync'});
async function changeEntry(){
 if(!allowed.value||busy.value||!selectedEntry.value)return;
 const seq=sequence,epoch=auth.requestEpoch,root=props.project.id;
 const valid=()=>allowed.value&&seq===sequence&&epoch===auth.requestEpoch&&root===props.project.id;
 busy.value=true;error.value='';
 try{
  if(props.beforeChange&&!await props.beforeChange())return;
  if(!valid())return;
  const result=await setProjectEntry(root,selectedEntry.value,currentEntry.value);
  if(!valid())return;
  if(result.id!==root||result.entry_file_id!==selectedEntry.value)throw Error('入口修改结果未确认，请重新读取');
  emit('updated',result);status.value='入口已保存；手动刷新网页后生效，运行数据未清空。';
 }catch(e){if(valid())error.value=e instanceof Error?e.message:'入口修改失败，请重新读取后重试';}
 finally{busy.value=false;}
}
function drag(event:DragEvent,id:string){if(!allowed.value){event.preventDefault();return;}dragProjectAsset(event,props.project,id);}
const prepareNavigation=async()=>!busy.value;
defineExpose({prepareNavigation,prepareDeletion:prepareNavigation});
onBeforeUnmount(()=>{disposed=true;++sequence;});
</script>
<template>
<section class="project-files" aria-label="网页项目文件">
 <header><button @click="emit('directory')">笔记目录</button><strong>{{project.title}} · {{directory?.path || file?.path || '项目文件'}}</strong><HelpHint v-if="allowed" label="项目相对引用说明">项目内移动或重命名会改变相对引用，请同步检查 HTML/CSS/JS；不会自动修复动态路径。跨项目移入/移出暂不支持。</HelpHint><button v-if="fileId!==project.id" @click="emit('open',project.id)">网页视图</button></header>
 <template v-if="allowed">
  <div v-if="!file" class="entry-picker"><div ref="picker" class="entry-dropdown" @keydown="pickerKey" @focusout="!picker?.contains($event.relatedTarget as Node) && (pickerOpen=false)"><button ref="trigger" :disabled="busy" aria-label="网页入口" aria-haspopup="listbox" :aria-expanded="pickerOpen" @click="pickerOpen?pickerOpen=false:openPicker()">{{entries.find(e=>e.id===selectedEntry)?.path || '请选择 HTML 入口'}}</button><div v-if="pickerOpen" role="listbox" aria-label="HTML 入口"><button v-for="entry in entries" :key="entry.id" role="option" :aria-selected="entry.id===selectedEntry" @click="chooseEntry(entry.id)">{{entry.path}}</button></div></div><button data-set-entry :disabled="busy||!selectedEntry||selectedEntry===currentEntry" @click="changeEntry">设为入口</button><p v-if="!project.entry">当前入口已失效，请重新选择。</p></div>
  <p v-if="status" role="status">{{status}}</p><p v-if="error" role="alert">{{error}}</p>
  <nav v-if="!file" aria-label="项目目录内容"><button v-for="item in children" :key="item.id" :data-project-file="item.id" :draggable="item.kind!=='directory'&&item.mime.startsWith('image/')" @dragstart="drag($event,item.id)" @click="emit('open',item.id)">{{item.kind==='directory'?'📁 ':''}}{{item.path}} <small v-if="item.path===project.entry">入口</small></button><p v-if="!children.length">此目录暂无文件</p></nav>
  <div v-else class="file-detail"><dl><dt>MIME</dt><dd>{{file.mime}}</dd><dt>大小</dt><dd>{{file.size===undefined?'元信息未提供':`${file.size} 字节`}}</dd><dt>路径</dt><dd>{{file.path}}</dd></dl><img v-if="source?.url&&file.mime.startsWith('image/')" :src="source.url" :alt="file.path" draggable="true" @dragstart="drag($event,file.id)" /><a v-if="source?.url" :href="source.url" download>下载文件</a><p v-if="file.mime.startsWith('image/')">拖到普通笔记正文可建立独立附件；原项目图片保持不动。失败后请在正文重试，不会插入项目私有路径。</p></div>
 </template><p v-else>登录恢复后可查看项目文件。</p>
</section>
</template>
<style scoped>
.project-files{flex:1;min-width:0;overflow:auto;padding:12px;color:var(--text-hi);background:var(--bg-panel)}header,.entry-picker{display:flex;gap:8px;align-items:center;flex-wrap:wrap}header strong{flex:1;overflow-wrap:anywhere}button,select,a{font:inherit;color:var(--text-hi);background:var(--bg-raised);border:1px solid var(--accent-dim);border-radius:6px;padding:7px;cursor:pointer}button:disabled{opacity:.5;cursor:default}.reference-warning,.file-detail p{font-size:12px;color:var(--text-lo)}nav{display:flex;flex-direction:column;gap:6px;margin-top:12px}nav button{text-align:left;overflow-wrap:anywhere}.file-detail img{display:block;max-width:100%;max-height:55vh;margin-bottom:12px}dl{display:grid;grid-template-columns:auto 1fr;gap:8px}dd{margin:0;overflow-wrap:anywhere}[role=alert]{color:var(--danger)}select{max-width:100%}
.entry-dropdown{position:relative;min-width:0;max-width:100%}.entry-dropdown>button{max-width:100%;overflow-wrap:anywhere;text-align:left}.entry-dropdown [role=listbox]{display:flex;flex-direction:column;gap:4px;max-height:220px;overflow:auto;background:var(--bg-raised);padding:6px;border:1px solid var(--accent-dim);border-radius:6px}.entry-dropdown [role=option]{text-align:left;overflow-wrap:anywhere}
</style>
