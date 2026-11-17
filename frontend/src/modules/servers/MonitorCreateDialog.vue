<script setup lang="ts">
import {computed,ref,watch,nextTick,onBeforeUnmount} from 'vue';
import {auth} from '../home/auth';
import Dropdown from '../../shell/Dropdown.vue';
import {createMonitorBatch,getMonitorBatchReceipt,createMonitorGroup,getMonitorGroupReceipt,getMonitorGroupDeletionState,listMonitors,listMonitorGroups,type MonitorBatchReceipt} from '../../api/servers';
import {monitorWriteError} from './monitorTarget';
import {monitorTypes,portTypes,defaultPorts,batchTargets} from './monitorBatchDraft';
const props=defineProps<{nodes:{id:number;name:string}[];groupId?:number;groupName?:string}>();
const emit=defineEmits<{close:[];saved:[]}>();
const dialog=ref<HTMLDialogElement|null>(null),name=ref(''),host=ref(''),types=ref<string[]>(['tcp']),ports=ref('80'),portDrafts=ref({...defaultPorts});
const mode=ref<'solo'|'group'>('solo'),groupName=ref(''),node=ref(props.nodes[0]?.id??0),interval=ref(60),timeout=ref(5);
const snapshot=()=>({name:name.value,host:host.value,types:[...types.value],ports:ports.value,portDrafts:{...portDrafts.value},node:node.value,interval:interval.value,timeout:timeout.value});
const modeDrafts={solo:snapshot(),group:snapshot()};
function setMode(value:'solo'|'group'){if(locked.value||value===mode.value)return;modeDrafts[mode.value]=snapshot();const d=modeDrafts[value];name.value=d.name;host.value=d.host;types.value=[...d.types];ports.value=d.ports;portDrafts.value={...d.portDrafts};node.value=d.node;interval.value=d.interval;timeout.value=d.timeout;mode.value=value;error.value='';}
const active=computed(()=>!!auth.me&&!auth.suspended&&!auth.sessionClosing);
const portOrder=computed(()=>portTypes(types.value));
function editPorts(event:Event){ports.value=(event.target as HTMLInputElement).value;const values=ports.value.split('/');for(const [i,type] of portOrder.value.entries())portDrafts.value[type]=values[i]??'';}
function toggle(type:string){types.value=types.value.includes(type)?types.value.filter(t=>t!==type):[...types.value,type];ports.value=portOrder.value.map(t=>portDrafts.value[t]??defaultPorts[t]).join('/');}
const preview=computed(()=>{try{return {items:batchTargets(types.value,host.value,ports.value),error:''};}catch(e){return {items:[],error:(e as Error).message};}});
const valid=computed(()=>name.value.trim()&&name.value.trim().length<=56&&preview.value.items.length&&props.nodes.some(n=>n.id===node.value)&&Number.isInteger(interval.value)&&interval.value>=10&&interval.value<=86400&&Number.isInteger(timeout.value)&&timeout.value>=1&&timeout.value<=120&&(mode.value==='solo'||groupName.value.trim()));
const previousFocus=document.activeElement as HTMLElement;
type CreationOperation={key:string;kind:'batch'|'group';receipt:MonitorBatchReceipt|null;count:number};
const busy=ref(false),error=ref(''),pending=ref<CreationOperation|null>(null);
let generation=0,owner=auth.me?.id;
const locked=computed(()=>busy.value||!!pending.value);
function beforeLeave(){return !locked.value;}
async function save(){
 if(!active.value||busy.value||(!pending.value&&!valid.value))return;
 const current=generation,owned=()=>current===generation&&active.value;
 busy.value=true;error.value='';
 try{
  if(!pending.value){
   const items=preview.value.items.map(item=>({...item,name:name.value.trim()+(preview.value.items.length>1?' · '+item.type.toUpperCase():''),node_id:node.value,interval:interval.value,timeout:timeout.value}));
   let uuid:string|null=null;
   if(props.groupId!==undefined){const state=await getMonitorGroupDeletionState(props.groupId);if(!owned())return;if(!state.group_exists||state.protected||!state.stable_uuid)throw Error('监控组不可添加，请重新读取');if(state.children.length+items.length>12)throw Error('监控组最多 12 个监控项');uuid=state.stable_uuid;}
   if(!owned())return;
   const operation:CreationOperation={key:crypto.randomUUID(),kind:mode.value==='group'?'group':'batch',receipt:null,count:items.length};
   pending.value=operation;
   try{
    if(operation.kind==='group'){const created=await createMonitorGroup({name:groupName.value.trim(),items,request_key:operation.key,failure_policy:'any',rotation_seconds:0},owned);if(!owned())return;operation.receipt={group_id:created.id,monitor_ids:created.child_ids};}
    else{const receipt=await createMonitorBatch({items,request_key:operation.key,group_id:props.groupId??null,expected_group_uuid:uuid},owned);if(!owned())return;operation.receipt=receipt;}
   }catch(e:any){if(!owned())return;if([400,401,403,409,421,422].includes(e?.status))pending.value=null;throw e;}
  }else if(!pending.value.receipt){
   const operation=pending.value;const receipt=operation.kind==='group'?await getMonitorGroupReceipt(operation.key):await getMonitorBatchReceipt(operation.key);if(!owned())return;operation.receipt=receipt;
  }
  const operation=pending.value,receipt=operation?.receipt;if(!receipt||receipt.monitor_ids.length!==operation.count||new Set(receipt.monitor_ids).size!==operation.count)throw Error('回执范围不匹配');
  const [monitors,groups]=await Promise.all([listMonitors(),listMonitorGroups(undefined,true)]);if(!owned())return;
  if(!receipt.monitor_ids.every(id=>monitors.some(m=>m.id===id))||receipt.group_id!==null&&!receipt.monitor_ids.every(id=>groups.find(g=>g.id===receipt.group_id)?.child_ids.includes(id)))throw Error('创建范围尚未确认');
  pending.value=null;emit('saved');
 }catch(e){if(owned())error.value=pending.value?'创建尚未确认，仅重新读取回执与列表，不会重复提交；请保留此任务。':monitorWriteError(e,'创建失败，请重试');}
 finally{if(owned())busy.value=false;}
}
defineExpose({beforeLeave});
function close(){if(beforeLeave())emit('close');}
watch(()=>[active.value,auth.me?.id,auth.requestEpoch,auth.sessionGeneration],async()=>{const current=++generation;busy.value=false;if(owner!==auth.me?.id){owner=auth.me?.id;name.value='';host.value='';groupName.value='';ports.value='80';portDrafts.value={...defaultPorts};types.value=['tcp'];modeDrafts.solo=snapshot();modeDrafts.group=snapshot();pending.value=null;error.value='';dialog.value?.close();emit('close');return;}if(!active.value){dialog.value?.close();return;}await nextTick();if(current===generation&&active.value&&!dialog.value?.open){dialog.value?.showModal();dialog.value?.querySelector<HTMLInputElement>('input')?.focus();}},{immediate:true,flush:'sync'});
function beforeUnload(e:BeforeUnloadEvent){if(!beforeLeave()){e.preventDefault();e.returnValue='';}}
window.addEventListener('beforeunload',beforeUnload);
onBeforeUnmount(()=>{generation++;window.removeEventListener('beforeunload',beforeUnload);dialog.value?.close();if(active.value)void nextTick(()=>previousFocus?.isConnected&&previousFocus.focus());});
</script>
<template>
<dialog ref="dialog" class="create-window" aria-label="新建监控项" @cancel.prevent="close" @click.self="close">
 <form v-if="active" @submit.prevent="save"><header><h3>新建监控项</h3><button type="button" aria-label="关闭新建监控项" :disabled="locked" @click="close">×</button></header>
 <fieldset class="draft-fields" :disabled="locked">
 <div v-if="groupId===undefined" class="mode" role="group" aria-label="添加类型"><button type="button" :aria-pressed="mode==='solo'" @click="setMode('solo')">独立监控项</button><button type="button" :aria-pressed="mode==='group'" @click="setMode('group')">监控组</button></div>
 <p v-else>创建并加入「{{props.groupName}}」；不会修改组名与聚合规则。</p>
 <label v-if="mode==='group'">监控组名称<input v-model="groupName" aria-label="监控组名称" maxlength="64" required></label>
 <label>监控项名称<input v-model="name" aria-label="监控项名称" maxlength="56" required></label>
 <fieldset class="types"><legend>监控类型（可多选）</legend><label v-for="type in monitorTypes" :key="type"><input type="checkbox" :value="type" :checked="types.includes(type)" @change="toggle(type)">{{type==='ping'?'Ping':type.toUpperCase()}}</label></fieldset>
 <label>目标 · IP 或域名<input v-model="host" aria-label="目标" placeholder="example.com 或 2001:db8::1" required></label>
 <label v-if="portOrder.length">端口 · {{portOrder.map(t=>t.toUpperCase()).join(' / ')}}<input :value="ports" aria-label="端口" @input="editPorts"><small>按上方类型顺序，用 / 分隔；Ping 不占端口。</small></label>
 <label>探测节点<Dropdown v-model="node" :options="nodes.map(n=>({value:n.id,label:n.name}))"/></label>
 <details><summary>采样设置</summary><div class="sampling"><label>探测间隔（秒）<input v-model.number="interval" type="number" min="10" max="86400"></label><label>超时（秒）<input v-model.number="timeout" type="number" min="1" max="120"></label></div></details>
 <section aria-label="待建监控预览"><strong>将创建 {{preview.items.length}} 个监控项</strong><ul><li v-for="item in preview.items" :key="item.type">{{name||'未命名'}}{{preview.items.length>1?' · '+item.type.toUpperCase():''}} — {{item.target}}</li></ul><p v-if="host&&preview.error" role="alert">{{preview.error}}</p></section>
 </fieldset><p v-if="error" role="alert">{{error}}</p>
 <footer><button type="button" :disabled="locked" @click="close">取消</button><button type="submit" :disabled="busy||(!pending&&!valid)">{{busy?'正在确认…':pending?'重新读取确认':'创建监控'}}</button></footer></form>
</dialog>
</template>
<style scoped>
.draft-fields{display:grid;gap:16px}
.create-window{position:fixed;inset:0;margin:auto;box-sizing:border-box;width:min(600px,calc(100% - 24px));max-height:calc(100dvh - 24px);overflow:auto;border:1px solid var(--accent-dim);border-radius:var(--radius);padding:22px;color:var(--text-hi);background:var(--bg-raised);font-size:14px}.create-window:not([open]){display:none}.create-window::backdrop{background:#0008}form{display:grid;gap:16px}header,footer,.mode,.sampling{display:flex;align-items:center;gap:10px}header h3{margin:0;flex:1;font-size:18px}label{display:grid;gap:6px;min-width:0}fieldset{border:0;padding:0;margin:0;min-width:0}.types{display:flex;gap:12px;flex-wrap:wrap}.types label{display:flex;align-items:center;gap:6px;min-height:36px}.types legend{margin-bottom:6px}input:not([type=checkbox]),button{box-sizing:border-box;font:inherit;padding:9px 10px;border:1px solid var(--accent-dim);border-radius:var(--radius-sm);background:var(--bg-panel);color:var(--text-hi);min-width:0}input:not([type=checkbox]){width:100%}button{cursor:pointer;min-height:38px}button:disabled{opacity:.45;cursor:default}.mode button{flex:1}.mode [aria-pressed=true]{border-color:var(--accent);color:var(--accent)}small,p,summary,legend{color:var(--text-lo);font-size:13px}p{margin:0}section{background:var(--bg-panel);padding:12px;border-radius:var(--radius-sm)}ul{padding-left:18px;margin-bottom:0}li{overflow-wrap:anywhere;font-size:13px;margin-top:8px}[role=alert]{color:#ed9299}footer{justify-content:flex-end}.sampling{margin-top:12px}.sampling>label{flex:1}input:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}.create-window :deep(.dd-btn){width:100%;min-width:0}@media(max-width:480px){.create-window{padding:16px}.types{gap:6px 12px}.sampling{flex-direction:column;align-items:stretch}}
</style>
