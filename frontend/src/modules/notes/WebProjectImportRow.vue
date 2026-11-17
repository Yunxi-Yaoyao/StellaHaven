<script setup lang="ts">
import {projectLimitsText} from './importLimits';
import {onBeforeUnmount,onMounted,ref,watch,toRaw} from 'vue';
import {api} from '../../api/client';
import {useImportSession, importErrorMessage, type ImportCheck} from './importSession';
import {useNotesStore} from '../../stores/notes';
import type {ImportSource,ImportTarget} from './import-helpers';
const props=defineProps<{file:ImportSource;target:ImportTarget;disabled?:boolean;autoStart?:boolean;admission?:{auto:()=>void;manual:()=>void};previewCache?:Map<string,unknown>}>();
const emit=defineEmits<{busy:[value:boolean];lock:[];complete:[id:string]}>();
const store=useNotesStore();
const session=useImportSession();
interface Preview {files:{path:string;size:number;kind:string}[];entries:string[];suggested_entry:string|null;warnings:string[]}
const report=ref<Preview|null>(null),entry=ref(''),busy=ref(false),done=ref(false),error=ref('');
let importId='',frozen:ImportTarget|null=null,frozenEntry='',disposed=false,sequence=0;
let bytes:Promise<ArrayBuffer>|null=null,original:ImportSource|null=null;
const MAX_BYTES=25*1024*1024;
function binding(){return JSON.stringify([props.target.workspaceId,props.target.parentId]);}
watch(()=>[props.file,props.target.workspaceId,props.target.parentId],()=>{if(!importId){
 ++sequence;bytes=null;
 const cached=props.previewCache?.get('project') as {file:ImportSource;key:string;report:Preview}|undefined;
 report.value=cached?.file===toRaw(props.file)&&cached.key===binding()?cached.report:null;entry.value=report.value?.suggested_entry??'';error.value='';
}},{immediate:true});
onBeforeUnmount(()=>{disposed=true;++sequence;});
async function form(target:ImportTarget,check:ImportCheck) {
 check();
 const file=original??props.file;
 if(file.size>MAX_BYTES)throw Error('文件超过25 MiB，未读取或上传喵~');
 const data=await (bytes??=file.arrayBuffer().catch(e=>{bytes=null;throw e;}));
 check();
 if(data.byteLength>MAX_BYTES)throw Error('文件超过25 MiB，未上传喵~');
 const body=new FormData();body.append('file',new Blob([data]),file.name);body.append('workspace_id',target.workspaceId);
 if(target.parentId)body.append('parent_id',target.parentId);
 if(importId){body.append('import_id',importId);body.append('entry',frozenEntry);}
 return body;
}
async function commit(automatic=false){
 if(busy.value||props.disabled||disposed||done.value||props.file.size>MAX_BYTES)return;
 try{props.admission?.[automatic?'auto':'manual']();}catch(e){error.value=importErrorMessage(e);return;}
 const check=session.capture();
 frozen??={...props.target};original??=props.file;importId ||= crypto.randomUUID();
 busy.value=true;emit('busy',true);emit('lock');error.value='';
 try{
  if(!report.value){const body=await form(frozen,check);check();const data=await api<Preview>('/web-projects/import/preview',{method:'POST',signal:check.signal,body});check();if(disposed)return;report.value=data;}
  if(!frozenEntry){
   const entries=report.value.entries;
   frozenEntry=(report.value.suggested_entry&&entries.includes(report.value.suggested_entry)?report.value.suggested_entry:null)??entries.find(path=>/(^|\/)index\.html?$/i.test(path))??entries[0]??'';
   if(!frozenEntry)throw Error('文件中没有可打开的 HTML 页面。');
   entry.value=frozenEntry;
  }
  const body=await form(frozen,check);check();const result=await api<{id:string;reused:boolean}>('/web-projects/import',{method:'POST',signal:check.signal,body});
  check();
  if(disposed)return;done.value=true;emit('complete',result.id);
  try{check();await store.refreshList();check();}catch{if(!disposed)error.value='项目已导入，目录刷新失败。请重新打开目录，不要重复导入喵~';}
 }catch(e){if(!disposed)error.value=importErrorMessage(e,'导入结果未确认，请用同一批次重试喵~');}
 finally{busy.value=false;if(!disposed)emit('busy',false);}
}
onMounted(()=>{if(props.autoStart)void commit(true);});
</script>
<template>
 <section class="project-import">
  <header><strong>{{file.name}}</strong><span>原版网页项目</span></header>
  <p>保留 HTML、CSS、JavaScript 和相对资源。网页在隔离入口运行；localStorage 数据同步到 Stella，其他浏览器存储暂不自动恢复。原文件同时保留。</p>
  <details><summary>网页项目格式限制</summary><p class="import-limits">{{projectLimitsText}}</p></details>
  <p v-if="file.size>MAX_BYTES" role="alert">文件超过25 MiB，未读取或上传喵~</p>
  <button class="primary" :disabled="busy||disabled||done||file.size>MAX_BYTES" @click="commit()">{{done?'网页项目已导入':busy?'正在导入…':importId||error?'重试确认导入结果':'渲染HTML'}}</button>
  <details v-if="report"><summary>项目文件（{{report.files.length}}）</summary><p>入口：{{entry}}</p><ul><li v-for="file in report.files" :key="file.path">{{file.path}} · {{file.size}} 字节</li></ul><p v-for="warning in report.warnings" :key="warning">{{warning}}</p></details>
  <p v-if="error" role="alert">{{error}}</p><p v-if="busy" role="status">正在处理网页项目…</p>
 </section>
</template>
<style scoped>
.project-import{border-top:1px solid #ffffff18;padding:14px 0;color:var(--text-hi)}header{display:flex;gap:12px;justify-content:space-between;flex-wrap:wrap}strong,label,li{overflow-wrap:anywhere}header span,p,li{font-size:12px;color:var(--text-lo);line-height:1.7}fieldset{border:0;margin:12px 0;padding:0}legend{font-size:13px;margin-bottom:8px}label{display:flex;gap:8px;align-items:center;font-size:13px;padding:5px 0}button{font:inherit;font-size:13px;padding:8px 12px;color:var(--text-hi);background:var(--bg-raised);border:1px solid var(--accent-dim);border-radius:7px;cursor:pointer}button:disabled{opacity:.5;cursor:default}summary{font-size:13px;cursor:pointer;padding:8px 0}ul{max-height:180px;overflow:auto;padding-left:20px}[role=alert]{color:var(--pink)}
.primary{position:sticky;bottom:0;z-index:2;margin-left:auto;display:block;background:var(--bg-panel);box-shadow:0 -5px 14px var(--bg-panel);min-height:38px;color:var(--accent)}summary{cursor:pointer;font-size:12px;color:var(--text-lo);padding:5px 0}</style>
