<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue';
import {auth} from '../home/auth';
import {getDetachedSource,saveDetachedSource,type DetachedSourceBody} from '../../api/detachedSources';
import ProjectSourceEditor from './ProjectSourceEditor.vue';
const props=defineProps<{fileId:string;active:boolean}>();
const emit=defineEmits<{directory:[];saved:[]}>();
const source=ref<DetachedSourceBody|null>(null),body=ref(''),baseline=ref(''),error=ref(''),busy=ref(false),conflict=ref(false),remoteText=ref(''),backup=ref(false),confirmRemote=ref(false);
const owner=auth.me?.id,session=auth.sessionGeneration;
let disposed=false,revoked=false,generation=0,timer:ReturnType<typeof setTimeout>|undefined,promise:Promise<boolean>|null=null;
let attempt:{content:string;version:string;base:string}|null=null;
const dirty=computed(()=>body.value!==baseline.value);
const authorized=()=>!disposed&&!revoked&&props.active&&!auth.suspended&&!auth.sessionClosing&&auth.me?.id===owner&&auth.sessionGeneration===session;
function fence(){++generation;clearTimeout(timer);promise=null;busy.value=false;}
watch(()=>[auth.me?.id,auth.sessionGeneration,auth.requestEpoch,auth.suspended,auth.sessionClosing,props.active],()=>{
 fence();
 if(auth.me?.id!==owner||auth.sessionGeneration!==session){revoked=true;source.value=null;body.value='';baseline.value='';attempt=null;error.value='';backup.value=false;remoteText.value='';confirmRemote.value=false;}
},{flush:'sync'});
function changed(text:string){if(!authorized())return;body.value=text;clearTimeout(timer);timer=setTimeout(()=>void flush(),600);}
async function load(){
 if(!authorized()||source.value)return;
 const gen=generation;
 try{const result=await getDetachedSource(props.fileId);if(gen!==generation||!authorized())return;if(result.id!==props.fileId||result.kind!=='detached-source')throw Error('源码身份不匹配');source.value=result;body.value=result.content;baseline.value=result.content;error.value='';}
 catch(e){if(gen===generation&&authorized())error.value=e instanceof Error?e.message:'源码读取失败';}
}
watch(()=>[props.active,auth.requestEpoch,auth.suspended,auth.sessionClosing],()=>{if(authorized()){if(!source.value)void load();else if(dirty.value||attempt)timer=setTimeout(()=>void flush(),600);}},{immediate:true});
async function flush():Promise<boolean>{
 clearTimeout(timer);if(!authorized()||!source.value)return false;if(promise)return promise;if(conflict.value)return false;if(!dirty.value&&!attempt)return true;
 const gen=generation,current=source.value;const valid=()=>gen===generation&&authorized()&&source.value===current;
 busy.value=true;
 promise=(async()=>{try{
  if(attempt){
   const pending=attempt,remote=await getDetachedSource(props.fileId);if(!valid())return false;
   if(remote.content===pending.content){current.updated_at=remote.updated_at;baseline.value=pending.content;attempt=null;}
   else if(remote.updated_at===pending.version&&remote.content===pending.base){attempt=null;}
   else{conflict.value=true;remoteText.value=remote.content;error.value='源码冲突，本地草稿仍保留。请复制核对后选择服务端版本。';return false;}
  }
  while(dirty.value&&valid()){
   const content=body.value;attempt={content,version:current.updated_at,base:baseline.value};
   const result=await saveDetachedSource(props.fileId,current.updated_at,content);if(!valid())return false;
   if(result.id!==props.fileId||result.kind!=='detached-source'||result.content!==content)throw Error('源码保存回执不匹配，请重试核对');
   current.updated_at=result.updated_at;baseline.value=content;attempt=null;
  }
  if(!valid())return false;error.value='';emit('saved');return !dirty.value;
 }catch(e){if(valid())error.value=e instanceof Error?e.message:'源码保存失败';return false;}
 finally{if(valid()){busy.value=false;promise=null;}}})();return promise;
}
async function useRemote(){
 if(!authorized()||!confirmRemote.value||busy.value)return;
 const gen=generation,text=body.value;busy.value=true;
 try{const result=await getDetachedSource(props.fileId);if(gen!==generation||!authorized())return;if(text!==body.value)throw Error('确认期间草稿再次变化，未丢弃');source.value=result;body.value=result.content;baseline.value=result.content;attempt=null;conflict.value=false;confirmRemote.value=false;backup.value=false;remoteText.value='';error.value='';}
 catch(e){if(gen===generation&&authorized())error.value=e instanceof Error?e.message:'读取失败';}
 finally{if(gen===generation)busy.value=false;}
}
function beforeUnload(event:BeforeUnloadEvent){if(dirty.value||attempt||busy.value){event.preventDefault();event.returnValue='';}}
onMounted(()=>window.addEventListener('beforeunload',beforeUnload));
onBeforeUnmount(()=>{disposed=true;fence();window.removeEventListener('beforeunload',beforeUnload);});
async function prepareDeletion(){
 // A confirmed clean file may already be frozen by the deletion dialog.
 // Never send a new write while frozen, or bypass a retained unknown attempt.
 if(disposed||revoked||auth.suspended||auth.sessionClosing||auth.me?.id!==owner||auth.sessionGeneration!==session||!source.value)return false;
 return !dirty.value&&!attempt&&!busy.value ? true : flush();
}
defineExpose({prepareNavigation:flush,prepareDeletion});
</script>
<template><section class="detached-source-pane"><header><button aria-label="笔记目录" @click="emit('directory')">目录</button><strong>独立源码 · {{source?.title}}</strong><span role="status">{{busy?'保存中':dirty?'源码待保存':'私有源码文件'}}</span><button :disabled="!authorized()||busy" @click="source?flush():load()">{{error?'重试':'保存源码'}}</button></header>
<p class="help">已移出网页项目，原项目不再读取此文件；相对引用不会自动修复。可在目录中移动、删除及恢复，仍按源码编辑，不转换为普通笔记。暂不支持移入网页项目。</p>
<p v-if="error&&authorized()" role="alert">{{error}}</p>
<div v-if="authorized()&&source" class="recovery"><button @click="backup=!backup">查看/复制本地草稿</button><button v-if="conflict||error" @click="confirmRemote=true">使用服务端版本</button><textarea v-if="backup" aria-label="本地草稿备份" readonly :value="body" /><details v-if="conflict"><summary>服务端冲突快照</summary><pre>{{remoteText}}</pre></details></div>
<div v-if="confirmRemote&&authorized()" role="alertdialog" aria-label="使用服务端版本"><p>确认放弃本地未保存草稿？请先复制备份。</p><button :disabled="busy" @click="confirmRemote=false">取消</button><button :disabled="busy" @click="useRemote">确认放弃本地草稿</button></div>
<ProjectSourceEditor v-if="source&&authorized()" :model-value="body" :filename="source.title" :readonly="!authorized()" @update:model-value="changed" /></section></template>
<style scoped>.detached-source-pane{flex:1;min-width:0;display:flex;flex-direction:column;overflow:hidden;background:var(--bg-panel);color:var(--text-hi)}header{display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:12px;border-bottom:1px solid #ffffff12}header strong{flex:1}button{padding:7px 10px;color:var(--text-hi);background:var(--bg-raised);border:1px solid #ffffff20;border-radius:7px;cursor:pointer}.help,.recovery,[role=alertdialog]{padding:8px 12px;font-size:12px;color:var(--text-lo)}[role=alert]{color:var(--danger);padding:10px}.project-code{flex:1;min-height:0}.recovery textarea{display:block;box-sizing:border-box;width:100%;height:120px;font-family:var(--font-mono)}pre{white-space:pre-wrap;max-height:160px;overflow:auto}</style>
