<script setup lang="ts">
import {ref,computed,watch,onMounted,onUnmounted} from 'vue';
import {auth} from '../home/auth';
import Dropdown from '../../shell/Dropdown.vue';
import {getReportChannels,putReportChannels,type ReportChannels,type ChannelNode,type ChannelMode} from '../../api/reportChannels';
import {ApiError} from '../../api/client';
const props=withDefaults(defineProps<{embedded?:boolean;active?:boolean}>(),{embedded:false,active:true});
const emit=defineEmits<{close:[]}>();
const dialog=ref<HTMLDialogElement>();
const data=ref<ReportChannels>();
const selected=ref<number[]>([]), choice=ref('default'),showInfo=ref(false),expanded=ref<number|null>(null);
const loading=ref(false),busy=ref(false),error=ref(''),notice=ref('');
const savedDraft=ref(''),readbackPending=ref(false);
const registryUnavailable=ref(false);
function draftKey(){return JSON.stringify({nodes:[...selected.value].sort((a,b)=>a-b),choice:choice.value});}
const dirty=computed(()=>draftKey()!==savedDraft.value||selected.value.some(id=>{
 const n=data.value?.nodes.find(n=>n.node_id===id);
 return !n||(n.mode==='fixed'?n.entry_id!==choice.value:n.mode!==choice.value);
}));
const controller=new AbortController();let timer:ReturnType<typeof setInterval>|undefined;
let returnFocus:HTMLElement|null=null;
const options=computed(()=>[
 {value:'default',label:'默认入口'},
 ...(data.value?.entries.filter(e=>e.entry_id!=='public').map(e=>({value:e.entry_id,label:'固定入口 · '+e.origin.replace('https://','')}))??[]),
 ...(data.value && data.value.entries.length>1?[{value:'auto',label:'自动选择'}]:[]),
]);
function label(n:ChannelNode){return n.mode==='default'?'默认入口':n.mode==='auto'?'自动选择':'固定入口';}
function validChoice(value:string){return options.value.some(o=>o.value===value);}
function state(n:ChannelNode){return n.state==='applied'?(n.online?'Agent 已确认':'已确认 · 当前离线'):n.state==='failed'?'应用失败 · 检测未通过':n.online?'待 Agent 确认':'离线 · 待应用';}
function toggle(id:number){selected.value=selected.value.includes(id)?selected.value.filter(n=>n!==id):[...selected.value,id];}
const bulkMode=ref(false),editing=ref<number|null>(null);
type RowDraft={choice:string;saved:string;notice:string;error:string;pending:boolean};
const drafts=ref<Record<number,RowDraft>>({});
function policy(n:ChannelNode){return n.mode==='fixed'?n.entry_id??'':n.mode;}
function edit(n:ChannelNode){
 editing.value=n.node_id;bulkMode.value=false;
 drafts.value[n.node_id]??={choice:policy(n),saved:policy(n),notice:'',error:'',pending:false};
}
function rowDirty(n:ChannelNode){const d=drafts.value[n.node_id];return !!d&&(d.choice!==d.saved||d.choice!==policy(n));}
function cancelRow(id:number){delete drafts.value[id];editing.value=null;}
async function applyRow(n:ChannelNode){
 const d=drafts.value[n.node_id];
 if(!d||busy.value||loading.value||!data.value||authBlocked.value||!props.active||!validChoice(d.choice))return;
 if(!rowDirty(n)){if(d.pending)await read();return;}
 busy.value=true;d.error='';d.notice='';
 const submitted=d.choice,mode:ChannelMode=submitted==='auto'?'auto':submitted==='default'?'default':'fixed';
 try{
  data.value=await putReportChannels({revision:data.value.revision,node_ids:[n.node_id],mode,entry_id:mode==='fixed'?submitted as 'public'|'private':null},controller.signal);
  d.saved=submitted;d.pending=true;d.notice='策略已保存；等待 Agent 确认。';readbackPending.value=true;
 }catch(e){if(!controller.signal.aborted)d.error=e instanceof ApiError&&e.status===409?'配置已变化，请刷新后重新应用。':'保存失败，草稿已保留，请重试。';return;}
 finally{busy.value=false;}
 await read();
}
async function read(silent=false){
 if(loading.value || busy.value || !props.active || authBlocked.value)return;
 loading.value=true;
 try{data.value=await getReportChannels(controller.signal);if(!silent||readbackPending.value)error.value='';registryUnavailable.value=false;readbackPending.value=false;for(const d of Object.values(drafts.value))d.pending=false;}
 catch(e){if(!controller.signal.aborted){registryUnavailable.value=e instanceof ApiError&&e.status===503&&e.detail==='上报通道需要已登记的精确 HTTPS 入口';error.value=readbackPending.value?'策略已保存，状态读取失败，请刷新。':registryUnavailable.value?'上报通道需要已登记的精确 HTTPS 入口':'读取失败，保留已选节点和上次结果。';}}
 finally{loading.value=false;}
}
async function apply(){
 if(busy.value||loading.value||!data.value||!selected.value.length||!props.active||authBlocked.value||!validChoice(choice.value))return;
 if(!dirty.value){if(readbackPending.value)await read();return;}
 busy.value=true;error.value='';notice.value='';
 const submitted=draftKey();
 const mode:ChannelMode=choice.value==='auto'?'auto':choice.value==='default'?'default':'fixed';
 try{
  data.value=await putReportChannels({revision:data.value.revision,node_ids:[...selected.value],mode,entry_id:mode==='fixed'?choice.value as 'private':null},controller.signal);
  // Retain the committed assignment even if the independent readback fails.
  savedDraft.value=submitted;readbackPending.value=true;
  notice.value='策略已保存；应用状态等待 Agent 确认。';
 }catch(e){if(!controller.signal.aborted)error.value=e instanceof ApiError&&e.status===409?'配置已变化，请刷新后重新应用。':'保存失败，所选节点与策略已保留，请重试。';return;}
 finally{busy.value=false;}
 await read();
}
function close(){if(!busy.value)emit('close');}
const authBlocked=computed(()=>auth.suspended||auth.sessionClosing);
// Yield the native top layer to login, retaining the committed receipt/draft.
watch(authBlocked,blocked=>{if(props.embedded)return;if(blocked)dialog.value?.close();else if(!dialog.value?.open)dialog.value?.showModal();},{flush:'post'});
watch(()=>props.active,active=>{if(active&&(!data.value||readbackPending.value)&&!error.value)void read();});
onMounted(()=>{returnFocus=document.activeElement as HTMLElement;if(!props.embedded&&!authBlocked.value)dialog.value?.showModal();if(props.active)void read();timer=setInterval(()=>{if(!document.hidden&&!authBlocked.value&&props.active&&!error.value)void read(true);},5000);});
onUnmounted(()=>{controller.abort();if(timer)clearInterval(timer);queueMicrotask(()=>{if(returnFocus?.isConnected)returnFocus.focus();});});
</script>

<template>
 <component :is="embedded?'section':'dialog'" ref="dialog" class="channel-dialog" :class="{embedded}" aria-labelledby="channel-title" @cancel.prevent="close" @click="(e:MouseEvent)=>{if(!embedded&&e.target===dialog)close();}">
  <header><div><h2 id="channel-title">上报通道</h2><p>在节点行内设置，确认后应用</p></div><div class="header-buttons"><button type="button" aria-label="查看通道说明" :aria-expanded="showInfo" @click="showInfo=!showInfo">i</button><button v-if="!embedded" type="button" aria-label="关闭上报通道" :disabled="busy" @click="close">×</button></div></header>
  <p v-if="showInfo" class="info">默认入口和固定入口不会自动切换。自动选择需手动开启，仅使用已登记的同中心 HTTPS 入口。离线节点恢复连接后才能接收配置；旧 Agent 升级并确认后才应用。</p>
  <p v-if="data" class="default-origin">默认入口 <strong>{{ data.entries.find(e=>e.entry_id===data?.default_entry_id)?.origin }}</strong></p>
  <div class="channel-tools">
   <button :disabled="busy" :aria-expanded="bulkMode" @click="bulkMode=!bulkMode;editing=null">{{ bulkMode?'退出批量':'批量设置' }}</button>
   <button :disabled="busy||loading" @click="read()">刷新</button>
  </div>
  <p v-if="data && data.entries.length<2" class="hint">当前仅登记默认入口，暂无其他固定入口或自动选择。请在<a href="/settings?section=services" target="_blank" rel="noopener noreferrer">站点设置</a>中检查入口登记。</p>
  <div v-if="bulkMode" class="channel-tools bulk-tools">
   <label class="check"><input type="checkbox" aria-label="选择全部节点" :checked="!!data?.nodes.length && selected.length===data.nodes.length" :disabled="busy" @change="selected=selected.length===data?.nodes.length?[]:data?.nodes.map(n=>n.node_id)??[]"> 全选</label>
   <span class="count">已选 {{ selected.length }} 台</span>
   <div class="selector" :inert="busy || !data"><Dropdown v-model="choice" :options="options" /></div>
   <button class="apply" :disabled="busy||loading||!data||!selected.length||!validChoice(choice)||(!dirty&&!readbackPending)" @click="apply">{{ busy?'保存中…':!dirty&&readbackPending?'重读状态':'应用到所选' }}</button>
   <button v-if="selected.length" class="cancel-selection" :disabled="busy" @click="selected=[];choice='default';notice=''">取消选择</button>
  </div>
  <p v-if="bulkMode&&choice==='auto'" class="hint">仅为所选节点开启自动选择。</p>
  <p v-if="error" class="error" role="alert">{{ error }}<span v-if="registryUnavailable"> 请在<a href="/settings?section=services" target="_blank" rel="noopener noreferrer">站点设置</a>中核对同中心 HTTPS 入口登记及主站信任。</span></p><p v-if="notice" class="notice" role="status">{{ notice }}</p>
  <p v-if="!data && loading" class="empty">正在读取通道…</p>
  <section v-if="data" class="channel-list" aria-label="节点通道">
   <div class="column-head"><span>节点 / 策略</span><span>实际入口</span><span>最近 HTTP 耗时</span><span>应用状态</span><span></span></div>
   <article v-for="n in data.nodes" :key="n.node_id" class="channel-row">
    <div class="node-choice"><label v-show="bulkMode" class="node-check"><input type="checkbox" :aria-label="'选择 '+n.name" :checked="selected.includes(n.node_id)" :disabled="busy" @change="toggle(n.node_id)"></label><span><button class="name-button node-name" :title="n.name" :aria-label="'查看 '+n.name+' 完整名称和入口'" :aria-expanded="expanded===n.node_id" @click="expanded=expanded===n.node_id?null:n.node_id">{{ n.name }}</button><small>{{ label(n) }}</small></span></div>
    <div class="origin"><span class="mobile-label">实际入口</span><button class="name-button" :title="n.actual_origin??''" :aria-label="'查看 '+n.name+' 实际入口'" @click="expanded=expanded===n.node_id?null:n.node_id">{{ n.actual_origin?.replace('https://','')??'尚未确认' }}</button></div>
    <div class="timing"><span class="mobile-label">最近 HTTP</span><span :title="[n.http_origin,n.sampled_at].filter(Boolean).join(' · ')">{{ n.http_status==='error'?'失败 · ':'' }}{{ n.http_ms==null?'尚无样本':n.http_ms.toFixed(1)+' ms' }}<small v-if="n.sampled_at">{{ new Date(n.sampled_at).toLocaleTimeString() }} · 上一笔报告</small></span></div>
    <span class="state" :class="n.state">{{ state(n) }}</span>
    <button class="row-edit" :aria-label="'设置 '+n.name+' 上报通道'" :aria-expanded="editing===n.node_id" :disabled="busy" @click="edit(n)">设置</button>
    <div v-if="editing===n.node_id&&drafts[n.node_id]" class="row-editor" role="region" :aria-label="n.name+' 上报通道设置'">
     <p>当前策略：{{ label(n) }}<span v-if="n.mode==='fixed'"> · {{ data.entries.find(e=>e.entry_id===n.entry_id)?.origin??'入口已不在登记列表' }}</span></p>
     <div class="edit-controls"><div class="selector" :inert="busy"><Dropdown v-model="drafts[n.node_id]!.choice" :options="options" /></div>
      <button class="apply" :disabled="busy||loading||!validChoice(drafts[n.node_id]!.choice)||(!rowDirty(n)&&!drafts[n.node_id]!.pending)" @click="applyRow(n)">{{ busy?'保存中…':!rowDirty(n)&&drafts[n.node_id]!.pending?'重读状态':'应用此节点' }}</button>
      <button :disabled="busy" @click="cancelRow(n.node_id)">取消</button></div>
     <p v-if="!validChoice(drafts[n.node_id]!.choice)" class="error" role="alert">草稿入口已不可用，请从已登记入口中重新选择。</p>
     <p v-if="drafts[n.node_id]!.error" class="error" role="alert">{{ drafts[n.node_id]!.error }}</p>
     <p v-if="drafts[n.node_id]!.notice" class="notice" role="status">策略已保存；{{ n.state==='pending'?'等待 Agent 确认。':state(n)+'。' }}</p>
    </div>
    <div v-if="expanded===n.node_id" class="row-detail" role="region" :aria-label="n.name+' 通道详情'"><strong>{{ n.name }}</strong><p>已选入口：{{ n.mode==='auto'?'自动选择':data.entries.find(e=>e.entry_id===(n.entry_id??'public'))?.origin }}</p><p>当前实际入口：{{ n.actual_origin??'尚未确认' }}</p><p v-if="n.http_origin">上一笔 HTTP 入口：{{ n.http_origin }}</p></div>
   </article>
   <p v-if="!data.nodes.length" class="empty">还没有纳管节点。</p>
  </section>
 </component>
</template>

<style scoped>
.row-editor{grid-column:1/-1;min-width:0;padding:14px;background:#ffffff06;border:1px solid #ffffff16;border-radius:8px;overflow-wrap:anywhere}.edit-controls{display:flex;align-items:flex-start;flex-wrap:wrap;gap:10px;margin-top:12px}.row-editor .selector{max-width:100%;min-width:0;flex:1 1 240px}.row-editor .notice,.row-editor .error{margin:12px 0 0}.channel-dialog :deep(.selector .dd-menu){position:relative;top:auto;left:auto;box-sizing:border-box;max-width:100%;min-width:0;width:100%;margin-top:4px;max-height:320px}.channel-dialog :deep(.selector .dd-btn){min-width:0}.row-editor :deep(.dd-label){white-space:normal;overflow-wrap:anywhere;text-align:left}.row-editor :deep(.dd-item){min-width:0}
.channel-dialog{box-sizing:border-box;width:min(1080px,calc(100vw - 40px));max-height:85dvh;margin:auto;border:1px solid #414044;border-radius:16px;padding:24px;background:var(--bg-panel,#222226);color:var(--text-hi,#eeeaf1);font-size:14px;overflow:auto;box-shadow:0 24px 90px #0008}
.channel-dialog::backdrop{background:#08080ca8;backdrop-filter:blur(5px)}
.channel-dialog.embedded{width:100%;max-height:none;padding:20px 0 0;margin:0;border:0;border-radius:0;background:transparent;box-shadow:none;overflow:visible;animation:none}.embedded h2{font-size:16px}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}h2{font-size:22px;font-weight:550;margin:0 0 8px}p{line-height:1.6;margin:0}header p,.hint,.default-origin{color:var(--text-lo,#c3bdc9)}header>button{font-size:23px;width:36px;padding:0}.default-origin{margin-top:18px;font-size:13px;overflow-wrap:anywhere}.default-origin strong{margin-left:12px;font-weight:500;color:var(--text-hi,#eeeaf1)}
button{border:1px solid #57515e;border-radius:7px;background:transparent;color:inherit;padding:8px 12px;min-height:36px;cursor:pointer;font:inherit;white-space:nowrap}button:disabled{opacity:.5;cursor:default}button:hover:not(:disabled){background:#ffffff0b}button:focus-visible,input:focus-visible{outline:2px solid #b4a2eb;outline-offset:3px}.channel-tools{display:flex;align-items:center;gap:12px;margin-top:20px;flex-wrap:wrap}.check{display:flex;align-items:center;gap:6px;white-space:nowrap}.count{font-size:13px;color:var(--text-lo,#c3bdc9)}input{accent-color:#b4a2eb;width:16px;height:16px;flex:none}.selector{min-width:180px;max-width:320px;flex:1}.selector :deep(.dd-btn){width:100%;max-width:100%;min-height:38px}.selector :deep(.dd-menu){min-width:100%;max-width:min(440px,80vw)}.selector :deep(.dd-item-label){white-space:normal;overflow-wrap:anywhere}.apply{border-color:#a292c6;background:#a292c621!important;color:#e3d7ff}.hint{font-size:13px;margin:14px 0 20px}.error,.notice{font-size:13px;padding:10px 12px;margin-bottom:16px;border-radius:8px}.error{color:#ffd0cb;background:#a9323026}.notice{color:#b7e4d3;background:#25846026}
.column-head,.channel-row{display:grid;grid-template-columns:minmax(150px,1.2fr) minmax(140px,1.2fr) minmax(140px,1fr) minmax(120px,.9fr) 64px;gap:16px;align-items:center}.column-head{color:var(--text-lo,#c3bdc9);font-size:12px;padding:0 10px 10px;border-bottom:1px solid #ffffff1c}.channel-row{padding:17px 10px;border-bottom:1px solid #ffffff12}.node-choice{display:flex;gap:8px;align-items:center;min-width:0}.node-check{display:inline-flex;align-items:center;justify-content:center;flex:none;width:32px;min-height:32px;cursor:pointer}.node-check input{margin:0}.node-check:focus-within{outline:2px solid #b4a2eb;outline-offset:1px;border-radius:6px}.node-choice>span{min-width:0}strong{font-weight:500;overflow-wrap:anywhere}small{display:block;color:var(--text-lo,#c3bdc9);font-size:12px;margin-top:5px;line-height:1.4}.origin{overflow-wrap:anywhere;font-size:13px}.timing{font-variant-numeric:tabular-nums;font-size:13px}.state{font-size:12px;color:#d4c9b4}.state.applied{color:#a6dac7}.state.failed{color:#ffc1b9}.mobile-label{display:none}.row-edit{font-size:12px}.empty{padding:28px 4px;color:var(--text-lo,#c3bdc9)}
@media(max-width:700px){.channel-dialog{width:calc(100vw - 20px);padding:18px 14px;max-height:92dvh;border-radius:12px}.channel-tools{gap:10px}.selector{order:3;flex:1 1 calc(100% - 130px);min-width:0;max-width:none}.apply{order:4}.channel-tools>button:last-child{margin-left:auto}.column-head{display:none}.channel-row{grid-template-columns:1fr auto;gap:12px;padding:18px 0}.node-choice{grid-column:1}.row-edit{grid-column:2;grid-row:1}.origin,.timing{grid-column:1/-1;display:flex;gap:10px}.state{grid-column:1/-1}.mobile-label{display:inline;color:var(--text-lo,#c3bdc9);flex:none;min-width:64px}.default-origin strong{display:block;margin-left:0;margin-top:3px}button{min-height:40px}}
@media(max-width:700px){.row-editor .selector{order:0;flex-basis:100%}.row-editor .apply{order:0}.edit-controls>button{flex:1}}
@media(prefers-reduced-motion:no-preference){.channel-dialog{animation:arrive .16s ease-out}@keyframes arrive{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}}
.header-buttons{display:flex;gap:8px}.header-buttons button{width:34px;min-height:34px;padding:0;font-size:18px}.header-buttons button:first-child{font-family:serif;font-size:16px}.info{font-size:13px;color:var(--text-lo,#c3bdc9);padding:12px 14px;background:#ffffff06;border-radius:8px;margin-top:14px}.channel-list{margin-top:22px}.name-button{display:block;min-width:0;max-width:100%;width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:0;border-radius:3px;background:transparent!important;padding:0;min-height:24px;font-size:13px;text-align:left}.node-choice>span{flex:1}.origin{min-width:0}.row-detail{grid-column:1/-1;padding:12px 14px;background:#ffffff06;border-radius:8px;font-size:13px;line-height:1.6;overflow-wrap:anywhere}.row-detail strong{display:block;margin-bottom:5px}.row-detail p{color:var(--text-lo,#c3bdc9)}.cancel-selection{font-size:13px;color:var(--text-lo,#c3bdc9)}
@media(max-width:700px){.node-check{width:44px;min-height:44px}.check{min-height:44px}.cancel-selection{order:5;min-height:44px;padding:4px 8px}.header-buttons{gap:5px}.header-buttons button{width:44px;min-height:44px}.name-button,.row-edit,button{min-height:44px}.selector :deep(.dd-btn),.selector :deep(.dd-item){min-height:44px}.origin{align-items:center}.origin .name-button{flex:1;max-width:calc(100% - 74px)}}
</style>
