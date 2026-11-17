<script setup lang="ts">
import HelpHint from "../settings/HelpHint.vue";
import {computed,ref,watch,onMounted,onBeforeUnmount} from 'vue';
import {auth} from '../home/auth';
import {getProjectSource,saveProjectSource,launchProject,renewProject,getProjectState,saveProjectState,resetProjectState,type WebProject,type RuntimeLaunch,type RuntimeState,type ProjectFile} from '../../api/webProjects';
import ProjectSourceEditor from './ProjectSourceEditor.vue';
import ProjectFiles from './ProjectFiles.vue';
import ProjectFileRename from './ProjectFileRename.vue';
const renameRef=ref<InstanceType<typeof ProjectFileRename>|null>(null),renameEditing=ref(false);
function renamed(project:FileProject,file:ProjectFile){if(source.value?.id===file.id){source.value.path=file.path;source.value.updated_at=file.updated_at;}emit('updated',project);emit('saved');}
import type {FileProject} from '../../api/projectFiles';
const filesRef=ref<InstanceType<typeof ProjectFiles>|null>(null);
const projectFilesOpen=ref(false);
async function toggleProjectFiles(){
 if(!authorized())return;
 const gen=generation,epoch=auth.requestEpoch;
 if(projectFilesOpen.value&&filesRef.value&&!await filesRef.value.prepareNavigation())return;
 if(gen!==generation||epoch!==auth.requestEpoch||!authorized())return;
 projectFilesOpen.value=!projectFilesOpen.value;
}
const props=defineProps<{project:WebProject;fileId:string;active:boolean}>();
const emit=defineEmits<{open:[id:string];directory:[];saved:[];updated:[project:FileProject]}>();
const frame=ref<HTMLIFrameElement|null>(null),grant=ref<RuntimeLaunch|null>(null),error=ref(''),status=ref(''),source=ref<(ProjectFile&{content:string|null;url:string|null})|null>(null),body=ref(''),savedBody=ref(''),sourceBusy=ref(false),runtimeBusy=ref(false);
const isRoot=computed(()=>props.fileId===props.project.id),dirty=computed(()=>!!source.value&&body.value!==savedBody.value);
const resetOpen=ref(false),resetBusy=ref(false);
let resetFlight:symbol|null=null;
let generation=0,disposed=false,revoked=false,timer:ReturnType<typeof setTimeout>|undefined,sourcePromise:Promise<boolean>|null=null,runtimePromise:Promise<boolean>|null=null;
let latest:Record<string,string>|null=null,retry:{id:string;data:Record<string,string>;base:RuntimeState}|null=null;
// The message identity/URL belongs to the rendered document, not its write grant.
const rendered=ref<RuntimeLaunch|null>(null),runtimeConflict=ref(false),renewalDenied=ref(false);
let expiresAt=0,renewTimer:ReturnType<typeof setTimeout>|undefined,needsReconcile=false;
let sourceAttempt:{text:string;version:string;base:string}|null=null;
const sourceConflict=ref(false);
const discardOpen=ref(false),discardBusy=ref(false),backup=ref<string|null>(null),remoteConflict=ref('');
function inspectLocal(){backup.value=isRoot.value?JSON.stringify({pending:retry,latest,base:grant.value?.state},null,2):body.value;}
function conflict(remote:RuntimeState){runtimeConflict.value=true;remoteConflict.value=JSON.stringify(remote,null,2);error.value='网页进度冲突：服务端已更新或重置，无法自动合并。本地待保存进度仍保留。';}
const sameData=(a:Record<string,string>,b:Record<string,string>)=>Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>Object.hasOwn(b,k)&&a[k]===b[k]);
const sameState=(a:RuntimeState,b:RuntimeState)=>a.epoch===b.epoch&&a.revision===b.revision&&sameData(a.data,b.data);
function validateLaunch(result:RuntimeLaunch){if(result.source_origin!==location.origin||new URL(result.url).origin!==result.target_origin)throw Error('网页运行入口不匹配');}
// Renewal extends the SAME resource grant; launch remains an explicit render action.
function scheduleAttempt(delay:number){clearTimeout(renewTimer);renewTimer=setTimeout(()=>{if(!authorized()||runtimeConflict.value||renewalDenied.value)return;if(runtimePromise){scheduleAttempt(1000);return;}void flushRuntime(true);},Math.max(1000,delay));}
function scheduleRenew(result:RuntimeLaunch,issuedAt=Date.now(),after=result.expires_in-60){expiresAt=issuedAt+result.expires_in*1000;scheduleAttempt(issuedAt+after*1000-Date.now());}
async function reauthorize(gen:number,epoch:number):Promise<boolean>{
 const base=retry?.base||grant.value?.state;
 const current=grant.value!;needsReconcile=true;const issuedAt=Date.now();
 let renewed;
 try{renewed=await renewProject(props.project.id,current.capability,current.state.epoch);}
 catch(e){
  if(gen!==generation||epoch!==auth.requestEpoch||!authorized())return false;
  if([403,409].includes((e as {status?:number}).status||0)){
   const remote=await getProjectState(props.project.id);if(gen!==generation||epoch!==auth.requestEpoch||!authorized())return false;
   if(base&&!sameState(base,remote)){conflict(remote);return false;}
   renewalDenied.value=true;clearTimeout(renewTimer);remoteConflict.value=JSON.stringify(remote,null,2);
   throw Error('网页续期授权已失效。本地待保存进度仍保留；请先备份，再确认使用服务端版本重新打开。');
  }throw e;
 }
 if(gen!==generation||epoch!==auth.requestEpoch||!authorized())return false;
 if(renewed.capability!==current.capability||renewed.epoch!==current.state.epoch)throw Error('网页续期授权不匹配');
 const result={...current,expires_in:renewed.expires_in};
 const remote=await getProjectState(props.project.id);if(gen!==generation||epoch!==auth.requestEpoch||!authorized())return false;
 // A reset between renewal and readback invalidates the retained capability.
 if(!base||renewed.epoch!==remote.epoch){conflict(remote);return false;}
 if(sameState(base,remote)){
  result.state=remote;
 }else if(retry&&remote.epoch===retry.base.epoch&&remote.revision===retry.base.revision+1&&sameData(remote.data,retry.data)){
  // Unknown commit is durable, proved by exact next revision + full data readback.
  result.state=remote;retry=null;
 }else{conflict(remote);return false;}
 grant.value=result;needsReconcile=false;scheduleRenew(result,issuedAt,renewed.renew_after);return true;
}
const owner=auth.me?.id,session=auth.sessionGeneration;
const authorized=()=>!disposed&&!revoked&&props.active&&auth.me?.id===owner&&auth.sessionGeneration===session&&!auth.suspended&&!auth.sessionClosing;
function fence(){++generation;clearTimeout(timer);clearTimeout(renewTimer);sourcePromise=null;runtimePromise=null;sourceBusy.value=false;runtimeBusy.value=false;resetFlight=null;resetBusy.value=false;discardBusy.value=false;}
watch(()=>[auth.me?.id,auth.sessionGeneration,auth.requestEpoch,auth.suspended,auth.sessionClosing,props.active],()=>{
 fence();
 if(auth.me?.id!==owner||auth.sessionGeneration!==session){revoked=true;grant.value=null;rendered.value=null;source.value=null;body.value='';savedBody.value='';latest=null;retry=null;sourceAttempt=null;resetOpen.value=false;error.value='';status.value='';runtimeConflict.value=false;renewalDenied.value=false;sourceConflict.value=false;backup.value=null;remoteConflict.value='';discardOpen.value=false;}
 else{if(!authorized())rendered.value=null;if(grant.value)needsReconcile=true;}
},{flush:'sync'});
function changed(value:string){if(!authorized())return;body.value=value;clearTimeout(timer);if(dirty.value||sourceAttempt){status.value='源码待保存';timer=setTimeout(()=>void flushSource(),600);}}
async function flushSource():Promise<boolean>{
 clearTimeout(timer);if(sourcePromise)return sourcePromise;if(sourceConflict.value)return false;if(!dirty.value&&!sourceAttempt)return true;if(!authorized()||!source.value)return false;
 const current=source.value,root=props.project.id,gen=generation,epoch=auth.requestEpoch;sourceBusy.value=true;
 const valid=()=>gen===generation&&epoch===auth.requestEpoch&&authorized()&&source.value===current;
 sourcePromise=(async()=>{try{
  if(sourceAttempt){
   const attempt=sourceAttempt,remote=await getProjectSource(root,current.id);if(!valid())return false;
   if(remote.content===attempt.text){current.updated_at=remote.updated_at;savedBody.value=attempt.text;sourceAttempt=null;}
   else if(remote.updated_at===attempt.version&&remote.content===attempt.base){sourceAttempt=null;}
   else{sourceConflict.value=true;remoteConflict.value=remote.content||'';error.value='源码冲突：服务端内容已变化，无法自动合并。本地草稿仍保留。';return false;}
  }
  while(dirty.value&&valid()){
   const text=body.value;sourceAttempt={text,version:current.updated_at,base:savedBody.value};
   const result=await saveProjectSource(root,current.id,current.updated_at,text);if(!valid())return false;
   current.updated_at=result.updated_at;savedBody.value=text;sourceAttempt=null;status.value=dirty.value?'源码待保存':'源码已保存';
  }
  if(!valid())return false;emit('saved');status.value='源码已保存';error.value='';return !dirty.value;
 }catch(e){if(valid())error.value=e instanceof Error?e.message:'源码保存失败';return false;}finally{if(valid()){sourceBusy.value=false;sourcePromise=null;}}})();return sourcePromise;
}
async function flushRuntime(renew=false):Promise<boolean>{
 if(runtimePromise)return runtimePromise;if(runtimeConflict.value||renewalDenied.value)return false;if(!latest&&!retry&&!renew&&!needsReconcile)return true;
 if(!grant.value||!authorized())return false;const root=props.project.id,gen=generation,epoch=auth.requestEpoch;runtimeBusy.value=true;
 const valid=()=>gen===generation&&epoch===auth.requestEpoch&&authorized();
 runtimePromise=(async()=>{try{
  let recovered=false;
  if(renew||needsReconcile||Date.now()>=expiresAt){if(!await reauthorize(gen,epoch))return false;recovered=true;}
  while((latest||retry)&&valid()){
   const current=grant.value!;
   if(!retry){retry={id:crypto.randomUUID(),data:latest!,base:current.state};latest=null;}
   try{
    const result=await saveProjectState(root,{...current,state:retry.base},retry.id,retry.data);if(!valid())return false;
    current.state=result;retry=null;status.value=latest?'进度同步中':'网页进度已保存到 Stella';
   }catch(e){
    if(!valid())return false;needsReconcile=true;
    if(!recovered&&[403,409].includes((e as {status?:number}).status||0)){if(!await reauthorize(gen,epoch))return false;recovered=true;continue;}
    throw e;
   }
  }if(!valid())return false;status.value='网页进度已保存到 Stella';error.value='';return !latest&&!retry;
 }catch(e){if(valid()){error.value=e instanceof Error?e.message:'进度尚未保存，请重试';const code=(e as {status?:number}).status||0;if(!renewalDenied.value&&!runtimeConflict.value&&(code===0||code>=500))scheduleAttempt(15000);}return false;}finally{if(valid()){runtimeBusy.value=false;runtimePromise=null;}}})();return runtimePromise;
}
async function prepareNavigation(){const gen=generation,epoch=auth.requestEpoch;return authorized()&&await flushSource()&&gen===generation&&epoch===auth.requestEpoch&&authorized()&&await flushRuntime()&&gen===generation&&epoch===auth.requestEpoch&&authorized();}
async function preparePaneNavigation(){
 if(renameRef.value&&!await renameRef.value.prepareNavigation())return false;
 const files=filesRef.value,gen=generation,epoch=auth.requestEpoch;
 const current=()=>gen===generation&&epoch===auth.requestEpoch&&authorized()&&filesRef.value===files;
 if(!current()||(files&&!await files.prepareNavigation())||!current()||!await prepareNavigation()||!current())return false;
 // Entry or rename may have started while the runtime/source save was awaited.
 // Keep beforeChange bound to prepareNavigation (this wrapper would self-lock).
 return (!files||await files.prepareNavigation())&&current()&&(!renameRef.value||await renameRef.value.prepareNavigation())&&current();
}
async function openFile(id:string){if(await preparePaneNavigation())emit('open',id);}
async function useRemote(){
 if(!discardOpen.value||discardBusy.value||!authorized())return;
 const gen=generation,epoch=auth.requestEpoch,text=body.value;discardBusy.value=true;
 const valid=()=>gen===generation&&epoch===auth.requestEpoch&&authorized();
 try{
  if(isRoot.value){
   const result=await launchProject(props.project.id);if(!valid())return;validateLaunch(result);
   const remote=await getProjectState(props.project.id);if(!valid())return;
   if(remote.epoch!==result.state.epoch)throw Error('运行数据再次变化，请重新确认');
   result.state=remote;latest=null;retry=null;needsReconcile=false;runtimeConflict.value=false;renewalDenied.value=false;grant.value=result;rendered.value=result;scheduleRenew(result);
  }else{
   const remote=await getProjectSource(props.project.id,props.fileId);if(!valid())return;
   if(body.value!==text)throw Error('确认期间草稿又有修改，已保留，请重新确认');
   source.value=remote;body.value=remote.content||'';savedBody.value=body.value;sourceAttempt=null;sourceConflict.value=false;
  }
  backup.value=null;remoteConflict.value='';discardOpen.value=false;error.value='';status.value='已使用服务端版本';
 }catch(e){if(valid())error.value=e instanceof Error?e.message:'读取服务端版本失败，本地草稿仍保留';}
 finally{if(valid())discardBusy.value=false;}
}
async function resetRuntime(){
 if(!resetOpen.value||!authorized()||resetBusy.value||runtimeBusy.value)return;
 resetBusy.value=true;const gen=generation,flight=Symbol('reset');resetFlight=flight;
 try{await resetProjectState(props.project.id);if(gen!==generation||!authorized())return;latest=null;retry=null;grant.value=null;rendered.value=null;runtimeConflict.value=false;renewalDenied.value=false;needsReconcile=false;backup.value=null;remoteConflict.value='';resetOpen.value=false;await refresh();}
 catch(e){if(gen===generation&&authorized())error.value=e instanceof Error?e.message:'运行数据清空结果未确认，请重试喵~';}
 finally{if(resetFlight===flight){resetFlight=null;resetBusy.value=false;}}
}
async function refresh(){if(!authorized()||!await prepareNavigation())return;const gen=++generation,epoch=auth.requestEpoch;grant.value=null;rendered.value=null;error.value='';status.value='正在打开网页';try{const result=await launchProject(props.project.id);if(gen!==generation||epoch!==auth.requestEpoch||!authorized())return;validateLaunch(result);grant.value=result;rendered.value=result;scheduleRenew(result);status.value='网页数据已恢复';}catch(e){if(gen===generation&&epoch===auth.requestEpoch)error.value=e instanceof Error?e.message:'网页打开失败';}}
function message(event:MessageEvent){const current=rendered.value,m=event.data;if(!authorized()||!current||event.origin!=='null'||event.source!==frame.value?.contentWindow||!m||m.capability!==current.capability||m.type!=='stella-project-storage')return;
 if(!m.data||typeof m.data!=='object'||Array.isArray(m.data)||Object.keys(m.data).length>1000||Object.values(m.data).some(v=>typeof v!=='string')||new TextEncoder().encode(JSON.stringify(m.data)).length>1048576){error.value='网页运行数据超过限制，未保存';return;}
 latest={...m.data};status.value='进度同步中';void flushRuntime();
}
watch(()=>[props.fileId,props.active,auth.requestEpoch,auth.suspended,auth.sessionClosing],async()=>{
 if(!authorized())return;const gen=++generation,epoch=auth.requestEpoch;
 if(isRoot.value){
  if(grant.value){const ok=await flushRuntime(true);if(ok&&gen===generation&&epoch===auth.requestEpoch&&authorized()&&!rendered.value)status.value='登录已恢复，进度已对账；点击刷新网页继续';}
  else await refresh();return;
 }
 if(source.value?.id===props.fileId){if(dirty.value||sourceAttempt)timer=setTimeout(()=>void flushSource(),600);return;}
 source.value=null;body.value='';savedBody.value='';error.value='';grant.value=null;rendered.value=null;clearTimeout(renewTimer);
 try{const result=await getProjectSource(props.project.id,props.fileId);if(gen!==generation||epoch!==auth.requestEpoch||!authorized())return;source.value=result;body.value=result.content||'';savedBody.value=body.value;status.value=result.kind==='text'?'源码 · 自动保存':'项目资源';}catch(e){if(gen===generation&&epoch===auth.requestEpoch)error.value=e instanceof Error?e.message:'文件读取失败';}
},{immediate:true});
function reconnect(){if(isRoot.value&&grant.value&&authorized())void flushRuntime(true);}
function visible(){if(document.visibilityState==='visible'&&(needsReconcile||Date.now()>=expiresAt-60000))reconnect();}
function beforeUnload(event:BeforeUnloadEvent){if(dirty.value||sourceAttempt||runtimeBusy.value||latest||retry){event.preventDefault();event.returnValue='';}}
onMounted(()=>{window.addEventListener('message',message);window.addEventListener('beforeunload',beforeUnload);window.addEventListener('online',reconnect);document.addEventListener('visibilitychange',visible);});
onBeforeUnmount(()=>{disposed=true;++generation;clearTimeout(timer);clearTimeout(renewTimer);window.removeEventListener('message',message);window.removeEventListener('beforeunload',beforeUnload);window.removeEventListener('online',reconnect);document.removeEventListener('visibilitychange',visible);});
defineExpose({prepareNavigation:preparePaneNavigation,prepareDeletion:preparePaneNavigation});
</script>
<template><section class="web-project-pane"><header><button aria-label="笔记目录" @click="emit('directory')">目录</button><strong><span class="project-badge">网页项目</span> {{project.title}}</strong><span role="status">{{status}}</span><button v-if="isRoot&&authorized()" :aria-expanded="projectFilesOpen" @click="toggleProjectFiles">项目文件</button><ProjectFileRename v-if="!isRoot&&source&&authorized()" ref="renameRef" :project-id="project.id" :file="source" :active="authorized()" :before-change="prepareNavigation" @editing="renameEditing=$event" @renamed="renamed" /><button v-if="!isRoot" @click="openFile(project.id)">网页视图</button><button v-if="isRoot" :disabled="runtimeBusy||resetBusy||!authorized()" @click="refresh">刷新网页</button><button v-if="isRoot" :disabled="runtimeBusy||resetBusy||!authorized()" @click="resetOpen=true">清空运行数据</button></header>
<div v-if="authorized()&&(runtimeConflict||sourceConflict||renewalDenied)" class="runtime-help" role="alert">
 <p>{{renewalDenied?'续期授权已失效，不能接管或复活旧运行实例。':'无法自动合并。'}}请先复制本地草稿，与服务端版本人工核对；不会自动覆盖或丢弃。</p>
 <button @click="inspectLocal">查看/复制本地草稿</button> <button @click="discardOpen=true">使用服务端版本</button>
 <details><summary>服务端冲突快照</summary><pre>{{remoteConflict}}</pre></details>
</div>
<div v-if="authorized()&&backup!==null" class="runtime-help"><textarea aria-label="本地草稿备份" readonly :value="backup" /><p>此备份仅保留在当前页面，请复制到安全位置后再离开。</p><button @click="backup=null">关闭备份</button></div>
<div v-if="authorized()&&discardOpen" role="alertdialog" aria-label="使用服务端版本" class="runtime-help"><p>确认放弃本地未保存草稿，使用服务端最新版本？网页会重新打开，不会删除服务端运行数据。</p><button :disabled="discardBusy" @click="discardOpen=false">取消</button><button :disabled="discardBusy" @click="useRemote">确认放弃本地草稿</button></div>
<div v-if="resetOpen&&authorized()" role="alertdialog" aria-label="清空运行数据" class="runtime-help"><p>只清空此项目保存在 Stella 的运行进度，不删除源码或图片；尚未同步的进度也将丢弃喵~</p><button :disabled="resetBusy" @click="resetOpen=false">取消</button><button :disabled="resetBusy||runtimeBusy" @click="resetRuntime">确认清空</button></div><p v-if="error" role="alert">{{error}} <button @click="isRoot?(grant?flushRuntime(true):refresh()):flushSource()">重试</button></p><div v-if="isRoot" class="project-content"><nav v-if="projectFilesOpen" aria-label="网页项目文件"><ProjectFiles ref="filesRef" :project="project" :file-id="project.id" :active="authorized()" :before-change="prepareNavigation" @open="openFile" @directory="emit('directory')" @updated="emit('updated',$event)" /></nav><div class="project-view"><HelpHint label="网页运行进度说明">网页与主站隔离。常用 localStorage 数据同步到 Stella；浏览器数据库等其他存储能力尚不支持自动恢复。</HelpHint><iframe v-if="rendered&&authorized()" ref="frame" :src="rendered.url" sandbox="allow-scripts" referrerpolicy="no-referrer" :title="project.title+' 网页视图'" /></div></div><ProjectSourceEditor v-else-if="authorized()&&source?.kind==='text'" :model-value="body" :filename="source.path" :readonly="!active||auth.suspended||auth.sessionClosing||renameEditing" @update:model-value="changed" /><ProjectFiles v-else-if="source&&authorized()" ref="filesRef" :project="project" :file-id="fileId" :active="authorized()" @open="openFile" @directory="emit('directory')" /></section></template>
<style scoped>.web-project-pane{flex:1;min-width:0;display:flex;flex-direction:column;background:var(--bg-panel);color:var(--text-hi);overflow:hidden}header{display:flex;align-items:center;gap:10px;padding:12px;border-bottom:1px solid #ffffff12;flex-wrap:wrap}header strong{flex:1;font-size:15px}header [role=status]{font-size:12px;color:var(--text-lo)}button,a{font:inherit;font-size:12px;padding:7px 10px;color:var(--text-hi);background:var(--bg-raised);border:1px solid #ffffff20;border-radius:7px;cursor:pointer}.project-badge{font-size:11px;color:var(--accent);border:1px solid var(--selected-border);border-radius:5px;padding:3px 5px}.project-content{display:flex;flex:1;min-height:0;min-width:0}nav{width:200px;flex-shrink:0;border-right:1px solid #ffffff12;padding:10px;overflow:auto}nav button{display:block;width:100%;text-align:left;margin:5px 0;overflow-wrap:anywhere}nav small{color:var(--warm)}.project-view{min-width:0;flex:1;display:flex;flex-direction:column}iframe{border:0;flex:1;width:100%;background:#fff}.runtime-help{font-size:12px;color:var(--text-lo);padding:8px 12px}.binary{padding:20px;overflow:auto}.binary img{max-width:100%;max-height:60vh;display:block;margin-bottom:16px}[role=alert]{color:var(--danger);padding:10px;font-size:13px}.project-code{flex:1;min-height:0}@media(max-width:600px){.project-content{flex-direction:column}nav{width:100%;max-height:140px;flex-shrink:0;border-right:0;border-bottom:1px solid #ffffff12}header strong{flex-basis:65%}}</style>
