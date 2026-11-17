<script setup lang="ts">
import {ref,computed,watch,onUnmounted,nextTick} from 'vue';
import {api} from '../../api/client';
import {auth} from '../home/auth';
import ReportChannelManager from './ReportChannelManager.vue';
import Dropdown from '../../shell/Dropdown.vue';
import HelpHint from '../settings/HelpHint.vue';
import {readAgentSource,type AgentSource} from '../../api/agentSource';
export interface ManagedAgent {id:number;name:string;status:string;agent_version?:string|null;last_seen_at?:string|null}
const props=defineProps<{open:boolean;nodes:ManagedAgent[]}>();
const emit=defineEmits<{close:[]}>();
const dialog=ref<HTMLDialogElement>();
const tab=ref<'overview'|'source'|'channels'>('overview');
const channelsVisited=ref(false);
watch(tab,value=>{if(value==='channels')channelsVisited.value=true;});
const release=ref<{version:string;sha256?:string;size?:number}>();
const releaseLoading=ref(false),releaseError=ref('');
interface AgentRelease {source_version:string;source_sha256:string;source_size:number;announcement_version:string;rollout_policy:'pinned'|'source'}
const releaseDetails=ref<AgentRelease>(),detailsError=ref('');
const selected=ref<number>();
watch(()=>props.nodes.map(n=>n.id),ids=>{if(selected.value==null||!ids.includes(selected.value))selected.value=ids[0];},{immediate:true});
const node=computed(()=>props.nodes.find(n=>n.id===selected.value)??props.nodes[0]);
const blocked=computed(()=>auth.suspended||auth.sessionClosing);
let controller:AbortController|undefined,returnFocus:HTMLElement|null=null;
let sourceController:AbortController|undefined;
const source=ref<AgentSource>(),sourceLoading=ref(false),sourceError=ref(''),sourceUrl=ref(''),copyNotice=ref('');
const sourceMatches=computed(()=>!!releaseDetails.value&&source.value?.sha256===releaseDetails.value.source_sha256&&source.value?.size===releaseDetails.value.source_size&&source.value?.version===releaseDetails.value.source_version);
async function loadSource(){
 if(sourceLoading.value||blocked.value||!props.open)return;
 const request=new AbortController();sourceController=request;sourceLoading.value=true;sourceError.value='';copyNotice.value='';
 const timeout=setTimeout(()=>request.abort(),15000);
 try{
  const value=await readAgentSource(request.signal);if(request.signal.aborted)return;
  if(sourceUrl.value)URL.revokeObjectURL(sourceUrl.value);
  sourceUrl.value=URL.createObjectURL(new Blob([value.bytes],{type:'text/x-python;charset=utf-8'}));source.value=value;
 }catch(e){if(sourceController===request&&props.open&&!blocked.value)sourceError.value=request.signal.aborted?'源码读取超时，请重试。':e instanceof Error&&!e.message.startsWith('API ')?e.message:'源码读取失败，请重试。';}
 finally{clearTimeout(timeout);if(sourceController===request){sourceController=undefined;sourceLoading.value=false;}}
}
async function copySource(){
 if(!source.value)return;
 try{await navigator.clipboard.writeText(source.value.text);copyNotice.value='已复制源码';}
 catch{copyNotice.value='复制失败，请在下方选中源码手动复制。';}
}
async function copyHash(){
 if(!source.value)return;
 try{await navigator.clipboard.writeText(source.value.sha256);copyNotice.value='已复制校验值';}
 catch{copyNotice.value='复制失败，请展开并选中完整校验值。';}
}
async function readRelease(){
 if(releaseLoading.value||blocked.value||!props.open)return;
 const request=new AbortController();controller=request;releaseLoading.value=true;releaseError.value='';
 const timeout=setTimeout(()=>request.abort(),15000);
 try{
  const [announcement,details]=await Promise.allSettled([api<{version:string;sha256?:string;size?:number}>('/agent/version',{signal:request.signal,cache:'no-store'}),api<AgentRelease>('/agent/release',{signal:request.signal,cache:'no-store'})]);
  if(request.signal.aborted)throw new DOMException('aborted','AbortError');
  if(announcement.status==='rejected')throw announcement.reason;
  const metadata=details.status==='fulfilled'?details.value:undefined;
  const validMetadata=metadata&&typeof metadata.source_version==='string'&&/^[a-f0-9]{64}$/.test(metadata.source_sha256)&&Number.isSafeInteger(metadata.source_size)&&metadata.source_size>0&&metadata.announcement_version===announcement.value.version&&['pinned','source'].includes(metadata.rollout_policy);
  release.value=announcement.value;releaseDetails.value=validMetadata?metadata:undefined;detailsError.value=validMetadata?'':'下载源码信息暂不可用；请刷新重试。';
 }
 catch{if(controller===request&&props.open&&!blocked.value)releaseError.value=request.signal.aborted?'发行版本读取超时，请重试。':'发行版本读取失败，请重试。';}
 finally{clearTimeout(timeout);if(controller===request){controller=undefined;releaseLoading.value=false;}}
}
watch(()=>[props.open,blocked.value] as const,async([open,suspended],previous)=>{
 if(open&&!previous?.[0])returnFocus=document.activeElement as HTMLElement;
 await nextTick();
 if(open&&!suspended){
  if(!dialog.value?.open)dialog.value?.showModal();
  if(!release.value&&!releaseError.value)void readRelease();
 }else{
  dialog.value?.close();controller?.abort();controller=undefined;releaseLoading.value=false;
  sourceController?.abort();sourceController=undefined;sourceLoading.value=false;
  if(!open&&returnFocus?.isConnected)returnFocus.focus();
 }
},{immediate:true,flush:'post'});
watch(tab,value=>{if(value!=='source'){sourceController?.abort();sourceController=undefined;sourceLoading.value=false;}});
onUnmounted(()=>{controller?.abort();sourceController?.abort();if(sourceUrl.value)URL.revokeObjectURL(sourceUrl.value);dialog.value?.close();});
</script>
<template>
 <dialog ref="dialog" class="agent-dialog" aria-labelledby="agent-manager-title" @cancel.prevent="emit('close')" @click="e=>{if(e.target===dialog)emit('close')}">
  <div class="manager-head"><header><h2 id="agent-manager-title">Agent 管理</h2><button class="close" aria-label="关闭 Agent 管理" @click="emit('close')">×</button></header>
  <nav aria-label="Agent 管理栏目"><button :aria-pressed="tab==='overview'" @click="tab='overview'">总览</button><button :aria-pressed="tab==='source'" @click="tab='source'">源码</button><button :aria-pressed="tab==='channels'" @click="tab='channels'">上报通道</button></nav></div>
  <section v-show="tab==='overview'" aria-label="版本与运行状态">
   <div class="section-heading"><h3>源码与更新策略</h3><button :disabled="releaseLoading" @click="readRelease">{{ releaseError?'重试':'刷新发行' }}</button></div>
   <p v-if="releaseLoading" role="status">正在读取发行版本…</p><p v-if="releaseError" role="alert" class="error">{{ releaseError }}</p>
   <dl v-if="release"><dt>下载源码版本</dt><dd class="version">{{ releaseDetails?.source_version??'暂未读取' }}</dd><dt>自动更新公告版本</dt><dd>{{ release.version }}</dd><dt>更新策略</dt><dd>{{ releaseDetails?.rollout_policy==='pinned'?'已锁定自动更新公告；下载源码不代表允许节点升级。':releaseDetails?'公告跟随下载源码；本页仅查看，不执行升级。':'更新策略暂未读取；本页不执行升级。' }}</dd></dl>
   <p v-if="detailsError" role="status" class="error">{{detailsError}}</p>
   <details v-if="releaseDetails" class="source-hash"><summary>下载源码指纹与大小</summary><p class="hash">SHA-256 {{releaseDetails.source_sha256}}</p><p>{{releaseDetails.source_size.toLocaleString()}} bytes</p></details>
   <h3>节点运行</h3>
   <div v-if="nodes.length" class="node-picker"><span>节点</span><Dropdown :model-value="selected??null" :options="nodes.map(n=>({value:n.id,label:n.name}))" @update:model-value="value=>{if(typeof value==='number')selected=value;}" /></div>
   <dl v-if="node"><dt>节点</dt><dd>{{ node.name }}</dd><dt>状态</dt><dd>{{ ({online:'在线',offline:'离线',pending:'待报到',removed:'已移除'} as Record<string,string>)[node.status]??'未知' }}</dd><dt>实际运行版本</dt><dd>{{ node.agent_version??'尚未上报' }}<span v-if="releaseDetails&&node.agent_version" class="comparison">{{ node.agent_version===releaseDetails.source_version?'版本号与下载源码相同（未核节点指纹）':'版本号与下载源码不同' }}</span></dd><dt>最近心跳</dt><dd>{{ node.last_seen_at?new Date(node.last_seen_at).toLocaleString():'尚无心跳' }}</dd></dl>
   <p v-else class="muted">还没有纳管节点。安装和卸载仍在对应节点的 Agent 入口操作。</p>
  </section>
  <section v-show="tab==='source'" aria-label="Agent 源码">
   <div class="section-heading"><div class="section-title"><h3>Agent 源码</h3><HelpHint label="查看源码说明" :portal-target="dialog">读取中心当前提供的 stella_agent.py，不含节点 token。仅查看，不执行。</HelpHint></div><button :disabled="sourceLoading" @click="loadSource">{{ sourceLoading?'读取中…':sourceError?'重试读取':source?'重新读取':'查看源码' }}</button></div>
   <p v-if="sourceError" role="alert" class="error">{{ sourceError }}</p>
   <template v-if="source">
    <dl class="source-meta"><div><dt>源码版本</dt><dd>{{ source.version }}</dd></div><div><dt>实际大小</dt><dd>{{ source.size.toLocaleString() }} bytes</dd></div></dl>
    <details class="source-hash"><summary>SHA-256 <span class="hash">{{ source.sha256.slice(0,12) }}…{{ source.sha256.slice(-8) }}</span><span class="hash-disclosure">完整值</span></summary><div><code class="hash">{{ source.sha256 }}</code><button @click="copyHash">复制校验值</button></div></details>
    <p class="source-check" :class="{error:releaseDetails&&!sourceMatches}">{{ !releaseDetails?'未读取下载源码信息；以上为本次实际读取的源码，未核对发布指纹。':sourceMatches?'与下载源码信息一致；不代表节点运行文件已校验。':'与下载源码信息不一致，请刷新核对。' }}</p>
    <div class="source-actions"><button @click="copySource">复制源码</button><a :href="sourceUrl" download="stella_agent.py">下载源码</a><span role="status">{{ copyNotice }}</span></div>
    <pre tabindex="0" aria-label="只读 Agent 源码"><code>{{ source.text }}</code></pre>
   </template>
  </section>
  <ReportChannelManager v-if="channelsVisited" v-show="tab==='channels'" embedded :active="open&&!blocked&&tab==='channels'" />
 </dialog>
</template>
<style scoped>
.agent-dialog{box-sizing:border-box;width:min(1080px,calc(100vw - 40px));max-width:calc(100vw - 20px);max-height:85dvh;margin:auto;padding:24px;border:1px solid #49454e;border-radius:16px;background:var(--bg-panel,#222226);color:var(--text-hi,#eeeaf1);overflow:auto;font-size:14px;box-shadow:0 24px 90px #0008}
.agent-dialog::backdrop{background:#08080ca8;backdrop-filter:blur(5px)}header,.section-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}h2{font-size:22px;font-weight:550;margin:0}h3{font-size:16px;font-weight:550;margin:24px 0 14px}header button.close{width:38px;padding:0;font-size:24px}button{font:inherit;min-height:38px;color:inherit;border:1px solid #615a6b;border-radius:7px;background:transparent;padding:8px 12px;cursor:pointer}button:disabled{opacity:.55;cursor:default}button:hover:not(:disabled){background:#ffffff0b}button:focus-visible,pre:focus-visible{outline:2px solid #b4a2eb;outline-offset:3px}nav{display:flex;gap:8px;padding:20px 0 16px;border-bottom:1px solid #ffffff1c}nav button{border-color:transparent}nav button[aria-pressed=true]{background:#a292c621;border-color:#a292c6;color:#e3d7ff}dl{display:grid;grid-template-columns:110px minmax(0,1fr);gap:14px 20px;margin:0;padding:18px;background:#ffffff04;border:1px solid #ffffff10;border-radius:10px;line-height:1.6}dt,.muted{color:var(--text-lo,#c3bdc9)}dd{margin:0;overflow-wrap:anywhere;min-width:0}.hash{font-family:var(--font-mono,monospace);font-size:13px}.version{font-size:18px}.comparison{margin-left:14px;color:var(--text-lo,#c3bdc9);font-size:13px}.node-picker{display:flex;gap:16px;align-items:center;margin-bottom:14px}.error{color:#ffd0cb;line-height:1.6}.section-heading h3{margin-top:20px}
.manager-head{position:sticky;top:-24px;z-index:3;margin:-24px -24px 0;padding:24px 24px 0;background:var(--bg-panel,#222226)}
@media(max-width:700px){.agent-dialog{width:calc(100vw - 20px);padding:18px 14px;max-height:92dvh;border-radius:12px}button{min-height:44px}dl{grid-template-columns:1fr;gap:5px;padding:14px}dd{margin-bottom:10px}.comparison{display:block;margin-left:0}.node-picker{gap:10px}nav{gap:4px}nav button{flex:1;padding-inline:8px}}
.section-title{display:flex;align-items:center;gap:4px;min-width:0}.section-title h3{white-space:nowrap}.section-title :deep(.help-hint){padding:0;border:0;min-height:36px}.node-picker :deep(.dd){flex:1;min-width:0}.node-picker :deep(.dd-btn){width:100%;max-width:100%;min-width:0;min-height:38px}.node-picker :deep(.dd-menu){box-sizing:border-box;width:100%;min-width:0;max-height:240px}.node-picker :deep(.dd-item-label){white-space:normal;overflow-wrap:anywhere;text-align:left}
.source-meta{display:flex;flex-wrap:wrap;gap:8px 24px;margin-top:12px;padding:10px 12px}.source-meta>div{display:flex;gap:10px;align-items:baseline}.source-meta dd{margin:0}.source-hash{margin:8px 0;color:var(--text-lo,#c3bdc9);font-size:12px}.source-hash summary{cursor:pointer;min-height:36px;align-content:center;overflow-wrap:anywhere}.source-hash summary:focus-visible{outline:2px solid #b4a2eb;outline-offset:2px}.source-hash summary .hash{font-size:12px;color:var(--text-hi,#eeeaf1)}.hash-disclosure{margin-left:8px}.source-hash>div{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:8px 12px;border:1px solid #ffffff1c;border-radius:8px}.source-hash code{min-width:0;overflow-wrap:anywhere;flex:1 1 260px;color:var(--text-hi,#eeeaf1)}.source-hash button{font-size:12px}.source-check{margin:8px 0;line-height:1.6;color:#b7e4d3}.source-check.error{color:#ffd0cb}.source-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:14px 0}.source-actions a{display:inline-flex;align-items:center;min-height:38px;padding:0 12px;border:1px solid #615a6b;border-radius:7px;color:inherit;text-decoration:none}.source-actions span{font-size:13px;color:var(--text-lo,#c3bdc9)}pre{box-sizing:border-box;width:100%;max-width:100%;max-height:45dvh;min-height:160px;overflow:auto;white-space:pre;background:#151519;border:1px solid #49454e;border-radius:8px;padding:16px;margin:0;color:#e2ddea;font:13px/1.65 var(--font-mono,monospace);tab-size:4}a:focus-visible{outline:2px solid #b4a2eb;outline-offset:3px}
@media(max-width:700px){.manager-head{top:-18px;margin:-18px -14px 0;padding:18px 14px 0}.source-actions a{min-height:44px}.node-picker :deep(.dd-btn),.node-picker :deep(.dd-item){min-height:44px}.section-title :deep(.help-hint){width:44px;min-height:44px}.source-hash summary{min-height:44px}.source-meta{gap:4px 16px}.source-meta>div{gap:8px}}
</style>
