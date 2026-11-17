<script setup lang="ts">
import {ref,computed,nextTick,watch,onBeforeUnmount,useId} from 'vue';
import {auth} from '../home/auth';
import {updateDoc} from '../../api/notes';
import {api,ApiError} from '../../api/client';
import type {ProjectFile} from '../../api/webProjects';
import type {FileProject} from '../../api/projectFiles';
const props=defineProps<{projectId:string;file:ProjectFile;active:boolean;beforeChange:()=>Promise<boolean>}>();
const emit=defineEmits<{renamed:[project:FileProject,file:ProjectFile];editing:[value:boolean]}>();
const owner=auth.me?.id,session=auth.sessionGeneration;
let disposed=false,sequence=0;
const allowed=computed(()=>!disposed&&props.active&&auth.me?.id===owner&&auth.sessionGeneration===session&&!auth.suspended&&!auth.sessionClosing);
const trigger=ref<HTMLButtonElement|null>(null),dialog=ref<HTMLDialogElement|null>(null),input=ref<HTMLInputElement|null>(null);
const opened=ref(false),busy=ref(false),name=ref(''),extension=ref(''),error=ref(''),status=ref('');
const description=useId(),errorId=useId();
const base=ref<ProjectFile|null>(null);
async function focusInput(){await nextTick();input.value?.focus();}
function dismiss(){dialog.value?.close();opened.value=false;emit('editing',false);void nextTick(()=>trigger.value?.focus());}
function close(){if(!busy.value)dismiss();}
function trapTab(event:KeyboardEvent){
 if(event.key!=='Tab')return;
 const controls=[...(dialog.value?.querySelectorAll<HTMLElement>('input:not(:disabled),button:not(:disabled)')??[])];
 const first=controls[0],last=controls.at(-1);
 if(!first){event.preventDefault();return;}
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
 else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
}
async function open(){
 if(!allowed.value||busy.value||opened.value)return;
 const seq=sequence,epoch=auth.requestEpoch,id=props.file.id;
 busy.value=true;
 try{
  if(!await props.beforeChange()||seq!==sequence||epoch!==auth.requestEpoch||!allowed.value||props.file.id!==id)return;
  base.value={...props.file};const filename=base.value.path.split('/').at(-1)!;const dot=filename.lastIndexOf('.');
  extension.value=dot>0?filename.slice(dot):'';name.value=dot>0?filename.slice(0,dot):filename;
  error.value='';opened.value=true;emit('editing',true);await nextTick();dialog.value?.showModal();busy.value=false;await focusInput();input.value?.select();
 }finally{if(seq===sequence)busy.value=false;}
}
async function rename(){
 if(!allowed.value||busy.value||!opened.value||!base.value)return;
 const title=name.value+extension.value;
 if(!name.value.trim()||name.value==='.'||name.value==='..'||/[\/\\\x00-\x1f\x7f]/.test(name.value)){
  error.value='文件名不能为空，也不能包含路径分隔符、控制字符或使用 . / ..。';await focusInput();return;
 }
 if(title===base.value.path.split('/').at(-1)){close();return;}
 const seq=sequence,epoch=auth.requestEpoch,current=base.value,root=props.projectId;
 const valid=()=>allowed.value&&seq===sequence&&epoch===auth.requestEpoch&&props.file.id===current.id&&props.projectId===root;
 busy.value=true;error.value='';
 try{
  const changed=await updateDoc(current.id,current.updated_at,{title});if(!valid())return;
  const project=await api<FileProject>(`/web-projects/${root}`);if(!valid())return;
  const file=project.files.find(f=>f.id===current.id),prefix=current.path.slice(0,current.path.lastIndexOf('/')+1);
  if(project.id!==root||!file||file.path!==prefix+title||file.updated_at!==changed.updated_at)throw Error('重命名结果未确认；请重新打开文件核对，当前输入仍保留。');
  emit('renamed',project,file);status.value='已重命名；请检查相对引用，并手动刷新网页。运行数据未清空。';dismiss();
 }catch(e){
  if(valid()){
   error.value=e instanceof ApiError?(e.status===409?'重命名冲突或路径不可用：'+(typeof e.detail==='string'?e.detail:'请核对重名、保留路径或文件版本')+'。输入已保留；版本冲突请取消后重新打开文件核对。':`重命名失败（${e.status}），输入已保留。`):(e instanceof Error?e.message:'重命名未确认，输入已保留。');
   busy.value=false;await focusInput();
  }
 }finally{if(valid())busy.value=false;}
}
watch(()=>[allowed.value,auth.requestEpoch,props.projectId,props.file.id],()=>{
 ++sequence;busy.value=false;if(opened.value)dismiss();
 if(auth.me?.id!==owner||auth.sessionGeneration!==session){name.value='';extension.value='';base.value=null;error.value='';status.value='';}
},{flush:'sync'});
defineExpose({prepareNavigation:async()=>!busy.value&&!opened.value});
onBeforeUnmount(()=>{disposed=true;++sequence;dialog.value?.close();});
</script>
<template>
 <span class="project-rename"><button v-if="allowed" ref="trigger" :disabled="busy" @click="open">重命名文件</button><span v-if="status&&allowed" role="status">{{status}}</span>
 <dialog v-if="opened&&allowed" ref="dialog" aria-label="重命名项目文件" :aria-describedby="description" @cancel.prevent="close" @keydown="trapTab">
  <form @submit.prevent="rename"><h2>重命名项目文件</h2><p class="path">{{base?.path}}</p>
   <p :id="description">路径改变后，现有 HTML/CSS/JS 相对引用不会自动修复，请自行检查（包括动态路径）。网页需手动刷新才使用新路径，不会清空运行数据。</p>
   <label>文件名 <span class="filename"><input ref="input" v-model="name" aria-label="文件名（不含扩展名）" :aria-invalid="!!error" :aria-describedby="error?errorId:description" :disabled="busy" autocomplete="off" @keydown.enter="$event.isComposing&&$event.preventDefault()" /><span>{{extension}}</span></span></label>
   <p v-if="error" :id="errorId" role="alert">{{error}}</p><footer><button type="button" :disabled="busy" @click="close">取消</button><button type="submit" :disabled="busy">{{busy?'正在重命名…':'确认重命名'}}</button></footer>
  </form>
 </dialog></span>
</template>
<style scoped>
.project-rename{display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap}.project-rename>[role=status]{font-size:12px;color:var(--text-lo)}button,input{font:inherit;color:var(--text-hi);background:var(--bg-raised);border:1px solid var(--text-faint);border-radius:7px;padding:8px 10px}button{cursor:pointer;font-size:12px;min-height:36px}button:disabled{opacity:.6;cursor:default}button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}dialog{position:fixed;inset:0;margin:auto;box-sizing:border-box;width:min(460px,calc(100vw - 32px));max-height:calc(100dvh - 32px);overflow:auto;border:1px solid var(--text-faint);border-radius:var(--radius);padding:20px;color:var(--text-hi);background:var(--bg-panel)}dialog::backdrop{background:#0009}h2{font-size:17px;margin:0 0 12px}p{font-size:13px;line-height:1.6;color:var(--text-lo)}.path{overflow-wrap:anywhere;color:var(--text-hi)}label{display:block;font-size:13px}.filename{display:flex;align-items:center;gap:8px;margin-top:8px}.filename input{width:100%;min-width:0}.filename>span{color:var(--text-lo)}footer{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}[role=alert]{color:var(--danger);margin-top:12px}
</style>
