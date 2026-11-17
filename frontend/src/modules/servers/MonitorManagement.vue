<script setup lang="ts">
import {computed,ref,watch,nextTick,onBeforeUnmount,inject} from 'vue';
import {matchedRouteKey,onBeforeRouteLeave,onBeforeRouteUpdate} from 'vue-router';
import Dropdown from '../../shell/Dropdown.vue';
import MonitorActionMenu from './MonitorActionMenu.vue';
import MonitorItemEditor from './MonitorItemEditor.vue';
import MonitorGroupDelete from './MonitorGroupDelete.vue';
import MonitorBulkDelete from './MonitorBulkDelete.vue';
import {auth} from '../home/auth';
import {listMonitors,listMonitorGroups,updateMonitor,saveMonitorGroup,listMonitorChecks} from '../../api/servers';
import type {Monitor,MonitorGroup,MonitorCheck,Node} from '../../api/servers';
const props=withDefaults(defineProps<{open:boolean;monitors?:Monitor[];groups?:MonitorGroup[];nodes?:Node[]}>(),{monitors:()=>[],groups:()=>[],nodes:()=>[]});
const emit=defineEmits<{close:[];changed:[];'edit-monitor':[id:number];'edit-group':[id:number];add:[]}>();
const tab=ref<'groups'|'items'>('groups');
function edit(kind:'monitor'|'group',id:number){if(locked.value)return;if(kind==='monitor')emit('edit-monitor',id);else emit('edit-group',id);}
const items=ref<Monitor[]>([]),groups=ref<MonitorGroup[]>([]),loading=ref(false),busy=ref(false),error=ref('');
const deleting=ref<Monitor|null>(null),deleteEditor=ref<InstanceType<typeof MonitorItemEditor>|null>(null);
const deletingGroup=ref<number|null>(null),groupDelete=ref<InstanceType<typeof MonitorGroupDelete>|null>(null);
const selected=ref<number[]>([]),bulk=ref<Monitor[]|null>(null),bulkDelete=ref<InstanceType<typeof MonitorBulkDelete>|null>(null);
const selectable=computed(()=>standalone.value.filter(m=>m.management!=='entry_icmp'));
function selectAll(){if(locked.value)return;selected.value=selected.value.length===selectable.value.length?[]:selectable.value.map(m=>m.id);}
function requestBulk(){if(!locked.value&&selected.value.length)bulk.value=selectable.value.filter(m=>selected.value.includes(m.id));}
function closeBulk(){if(bulkDelete.value?.beforeLeave()!==false)bulk.value=null;}
function bulkChanged(ids:number[]){items.value=items.value.filter(m=>!ids.includes(m.id));selected.value=selected.value.filter(id=>!ids.includes(id));emit('changed');}
function beforeLeave(){return bulkDelete.value?.beforeLeave()!==false&&deleteEditor.value?.beforeLeave()!==false&&groupDelete.value?.beforeLeave()!==false&&!busy.value&&!pending.value;}
if(inject(matchedRouteKey,undefined)){onBeforeRouteLeave(beforeLeave);onBeforeRouteUpdate(beforeLeave);}
defineExpose({beforeLeave});
function requestGroupDelete(g:MonitorGroup){if(!locked.value&&!g.automatic)deletingGroup.value=g.id;}
function closeGroupDelete(){if(groupDelete.value?.beforeLeave()!==false){const id=deletingGroup.value;deletingGroup.value=null;void nextTick(()=>dialog.value?.querySelector<HTMLButtonElement>(`[data-group-id="${id}"] [aria-haspopup="menu"]`)?.focus());}}
async function groupDeleted(){deletingGroup.value=null;emit('changed');await reload();}
function requestDelete(m:Monitor){if(!locked.value&&m.management!=='entry_icmp')deleting.value=m;}
function closeDelete(){if(deleteEditor.value?.beforeLeave()!==false)deleting.value=null;}
async function deleted(){items.value=items.value.filter(m=>m.id!==deleting.value?.id);deleting.value=null;emit('changed');await reload();}
const pending=ref<{kind:'monitor'|'group';id:number;field:'visible'|'enabled';value:boolean}|null>(null);
const search=ref(''),historyId=ref<number|null>(null),checks=ref<MonitorCheck[]>([]),historyError=ref(''),historyLoading=ref(false),historyFilter=ref('all');
let historyGeneration=0,generation=0,request:AbortController|undefined;
const dialog=ref<HTMLDialogElement|null>(null),historyDialog=ref<HTMLDialogElement|null>(null);
let historyFocus:HTMLElement|null=null;
function closeHistory(){historyGeneration++;clearHistory();historyDialog.value?.close();void nextTick(()=>historyFocus?.isConnected&&historyFocus.focus());}
const active=computed(()=>props.open&&!!auth.me&&!auth.suspended&&!auth.sessionClosing);
let owner=auth.me?.id,returnFocus:HTMLElement|null=null;
const historyOptions=[{value:'all',label:'全部'},{value:'up',label:'正常'},{value:'down',label:'异常'}];
const locked=computed(()=>!active.value||loading.value||busy.value||!!pending.value||!!deleting.value||deletingGroup.value!==null||!!bulk.value);
function invalidate(){generation++;historyGeneration++;request?.abort();request=undefined;loading.value=false;busy.value=false;historyLoading.value=false;}
function clearHistory(){historyId.value=null;checks.value=[];historyError.value='';historyFilter.value='all';}
function close(){if(locked.value)return;emit('close');}
function trapTab(event:KeyboardEvent){
 if(event.key!=='Tab'||(event.target as Element|null)?.closest('dialog')!==dialog.value)return;
 const controls=Array.from(dialog.value?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),[tabindex="0"]')??[]).filter(el=>el.getClientRects().length);
 const first=controls[0],last=controls.at(-1);
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
 else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
}
const matching=(m:{name:string;target?:string})=>`${m.name} ${m.target??''}`.toLowerCase().includes(search.value.trim().toLowerCase());
const membership=computed(()=>new Set(groups.value.flatMap(g=>g.child_ids)));
const standalone=computed(()=>items.value.filter(m=>!membership.value.has(m.id)&&matching(m)));
watch(()=>[search.value,tab.value],()=>{selected.value=[];});
const shownGroups=computed(()=>groups.value.filter(g=>matching(g)||items.value.some(m=>g.child_ids.includes(m.id)&&matching(m))));
const filteredChecks=computed(()=>checks.value.filter(c=>historyFilter.value==='all'||c.success===(historyFilter.value==='up')));

async function reload(){
 if(!active.value||busy.value)return;
 request?.abort();const controller=new AbortController();request=controller;const current=++generation;
 loading.value=true;error.value='';
 try{
  const [ms,gs]=await Promise.all([listMonitors(controller.signal),listMonitorGroups(controller.signal,true)]);
  if(current!==generation||!active.value)return;
  items.value=ms;groups.value=gs;
  if(pending.value){
   const p=pending.value,actual=(p.kind==='monitor'?ms:gs).find(x=>x.id===p.id);
   if(!actual||actual[p.field]!==p.value){error.value='操作尚未确认：服务器状态与预期不一致，请重新读取核对';return;}
   pending.value=null;emit('changed');
  }
 }catch{if(current===generation&&active.value)error.value=pending.value?'操作尚未确认：变更可能已保存，仅重新读取，不重复提交':'读取监控管理失败，请重试';}
 finally{if(current===generation)loading.value=false;}
}
async function toggle(kind:'monitor'|'group',item:Monitor|MonitorGroup,field:'visible'|'enabled'){
 if(locked.value)return;
 busy.value=true;error.value='';const current=generation;
 const value=item[field]===false;
 pending.value={kind,id:item.id,field,value};
 try{
  if(kind==='monitor')await updateMonitor(item.id,{[field]:value});
  else{const g=item as MonitorGroup;await saveMonitorGroup(g.id,{name:g.name,failure_policy:g.failure_policy,rotation_seconds:g.rotation_seconds,[field]:value});}
 }catch(e){
  if(current!==generation||!active.value)return;
  const status=(e as {status?:number})?.status;
  if(status&&status>=400&&status<500){pending.value=null;error.value='操作被拒绝，未确认保存，请刷新后重试';busy.value=false;return;}
  error.value='操作尚未确认：未收到完整回执，仅重新读取，不重复提交';busy.value=false;return;
 }
 if(current!==generation||!active.value)return;
 busy.value=false;await reload();
}
async function history(id:number){
 if(!active.value||locked.value)return;historyFocus=document.activeElement as HTMLElement;historyId.value=id;await nextTick();historyDialog.value?.showModal();historyError.value='';checks.value=[];historyLoading.value=true;
 const generation=++historyGeneration;
 try{const result=await listMonitorChecks(id);if(generation===historyGeneration)checks.value=result;}
 catch{if(generation===historyGeneration)historyError.value='历史读取失败，可重新点击历史重试';}
 finally{if(generation===historyGeneration)historyLoading.value=false;}
}
watch(()=>[props.open,auth.me?.id,auth.suspended,auth.sessionClosing,auth.sessionGeneration,auth.requestEpoch],async()=>{
 const previousOwner=owner;owner=auth.me?.id;
 invalidate();clearHistory();historyDialog.value?.close();
 if(owner!==previousOwner){items.value=[];groups.value=[];search.value='';tab.value='groups';error.value='';pending.value=null;deleting.value=null;deletingGroup.value=null;selected.value=[];bulk.value=null;returnFocus=null;}
 if(!active.value){
  dialog.value?.close();
  if(!props.open&&!auth.suspended&&!auth.sessionClosing&&owner===previousOwner){const target=returnFocus;void nextTick(()=>{if(target?.isConnected)target.focus();});}
  return;
 }
 const current=generation;
 if(!dialog.value?.open)returnFocus=document.activeElement as HTMLElement;
 await nextTick();if(current!==generation||!active.value)return;
 if(!dialog.value?.open)dialog.value?.showModal();
 dialog.value?.querySelector<HTMLInputElement>('input')?.focus();
 void reload();
},{immediate:true,flush:'sync'});
onBeforeUnmount(()=>{invalidate();dialog.value?.close();});
</script>

<template>
 <dialog ref="dialog" class="management-mask" aria-label="监控管理" @cancel.prevent="close" @click.self="close" @keydown="trapTab">
  <section v-if="active" class="management-panel">
   <header><h2>监控管理</h2><span/><button type="button" :disabled="locked" @click="emit('add')">添加监控</button><button type="button" aria-label="关闭监控管理" :disabled="locked" @click="close">×</button></header>
   <div class="toolbar"><div role="tablist" aria-label="监控类别"><button role="tab" :aria-selected="tab==='groups'" @click="tab='groups'">监控组 {{groups.length}}</button><button role="tab" :aria-selected="tab==='items'" @click="tab='items'">独立监控 {{items.filter(m=>!membership.has(m.id)).length}}</button></div><input v-model="search" aria-label="搜索监控" placeholder="搜索名称或目标"><button type="button" :disabled="loading||busy" @click="reload">重新读取</button></div>
   <p v-if="error" role="alert">{{error}}</p><p v-if="loading" role="status">正在读取…</p>
   <div v-if="tab==='items'" class="bulk-toolbar"><label><input type="checkbox" aria-label="全选当前列表" :disabled="locked||!selectable.length" :checked="!!selectable.length&&selected.length===selectable.length" @change="selectAll">全选当前列表</label><button type="button" :disabled="locked||!selected.length" @click="requestBulk">批量删除 ({{selected.length}})</button><small>仅当前可见独立项，不含系统自动项</small></div>
   <div class="management-list" role="tabpanel">
    <div class="table-head"><span>{{tab==='groups'?'监控组':'名称 / 类型与目标'}}</span><span>{{tab==='groups'?'正常 / 异常':'状态'}}</span><span>总览显示</span><span>启用</span><span/><span/></div>
    <template v-if="tab==='groups'"><div v-for="g in shownGroups" :key="g.id" :data-group-id="g.id" class="row group-row">
     <div class="identity"><button class="name" :disabled="locked" @click="edit('group',g.id)">{{g.name}}</button><small>{{g.child_ids.length}} 个监控项</small></div>
     <div class="health"><span v-if="g.enabled===false">已停用</span><span v-else-if="!g.child_ids.length&&g.automatic">{{g.availability_reason==='entry_not_configured'?'未配置其他入口':'暂无接入节点'}}</span><span v-else-if="!g.eligible_child_ids?.length">无参与项</span><template v-else><span class="up">{{g.up_count||0}} 正常</span><span :class="{down:g.down_count>0}">{{g.down_count}} 异常</span></template></div>
     <button class="switch" role="switch" :aria-label="`总览显示 ${g.name}`" :aria-checked="g.visible!==false" :disabled="locked" @click="toggle('group',g,'visible')"><i/></button><button class="switch" role="switch" :aria-label="`启用 ${g.name}`" :aria-checked="g.enabled!==false" :disabled="locked" @click="toggle('group',g,'enabled')"><i/></button>
     <span/><div class="row-actions"><MonitorActionMenu :label="`更多组操作 ${g.name}`" :disabled="locked" :options="[{value:'edit',label:g.automatic?'系统组设置':'编辑监控组'},...(!g.automatic?[{value:'delete',label:'删除监控组'}]:[])]" @select="$event==='delete'?requestGroupDelete(g):edit('group',g.id)"/></div>
    </div></template>
    <template v-else><div v-for="m in standalone" :key="m.id" class="row item-row">
     <div class="identity"><input v-if="m.management!=='entry_icmp'" v-model="selected" class="item-selection" type="checkbox" :value="m.id" :aria-label="`选择监控项 ${m.name}`" :disabled="locked"><button class="name" :disabled="locked" @click="edit('monitor',m.id)">{{m.name}}</button><small :title="`${m.type.toUpperCase()} · ${m.target}`">{{m.type.toUpperCase()}} · {{m.target}}</small></div>
     <span class="health" :class="{up:m.enabled!==false&&m.effective_enabled!==false&&m.status==='up',down:m.enabled!==false&&m.effective_enabled!==false&&m.status!=='up'}">{{m.enabled===false?'已停用':m.effective_enabled===false?'组已停用':m.status==='up'?'正常':'异常'}}</span>
     <button class="switch" role="switch" :aria-label="`总览显示 ${m.name}`" :aria-checked="m.visible!==false" :disabled="locked" @click="toggle('monitor',m,'visible')"><i/></button><button class="switch" role="switch" :aria-label="`启用 ${m.name}`" :aria-checked="m.enabled!==false" :disabled="locked" @click="toggle('monitor',m,'enabled')"><i/></button>
     <button class="edit" :disabled="locked" @click="edit('monitor',m.id)">编辑</button><div class="row-actions"><button v-if="m.management!=='entry_icmp'" class="edit delete-action" :aria-label="`删除监控项 ${m.name}`" :disabled="locked" @click="requestDelete(m)">删除</button><MonitorActionMenu :label="`更多监控操作 ${m.name}`" :disabled="locked" :options="[{value:'history',label:'查看历史'}]" @select="history(m.id)"/></div>
    </div></template>
    <p v-if="!loading&&!(tab==='groups'?shownGroups.length:standalone.length)">没有匹配的监控项</p>
   </div><footer>{{tab==='groups'?shownGroups.length:standalone.length}} 个{{tab==='groups'?'监控组':'独立监控'}}</footer>
  </section>
  <dialog ref="historyDialog" class="history-window" aria-label="监控历史" @cancel.prevent="closeHistory" @click.self="closeHistory">
   <section v-if="historyId!==null" class="history"><header><h3>{{items.find(m=>m.id===historyId)?.name}} · 状态历史</h3><button aria-label="关闭历史" @click="closeHistory">×</button></header><div class="history-filter"><span>结果筛选</span><Dropdown v-model="historyFilter" :options="historyOptions"/><button @click="history(historyId)">重新读取历史</button></div><p v-if="historyError" role="alert">{{historyError}}</p><p v-else-if="historyLoading">正在读取历史…</p><ul v-else><li v-for="c in filteredChecks" :key="c.id"><time>{{new Date(c.ts).toLocaleString()}}</time><span>{{c.success?'正常':'异常'}}</span><span>{{c.latency_ms===null?'—':`${c.latency_ms} ms`}}</span></li><li v-if="!filteredChecks.length">暂无匹配记录</li></ul></section>
  </dialog>
  <MonitorItemEditor v-if="deleting" ref="deleteEditor" :monitor="deleting" :delete-only="true" :node-name="nodes.find(n=>n.id===deleting?.node_id)?.name??''" @close="closeDelete" @saved="deleted"/>
  <MonitorGroupDelete v-if="deletingGroup!==null" ref="groupDelete" :group-id="deletingGroup" :open="open" @close="closeGroupDelete" @deleted="groupDeleted"/>
  <MonitorBulkDelete v-if="bulk" ref="bulkDelete" :monitors="bulk" @close="closeBulk" @changed="bulkChanged"/>
 </dialog>
</template>
<style scoped>
input[type=checkbox]{width:16px;height:16px;min-height:0;padding:0;margin:0 8px 0 0;vertical-align:middle;accent-color:var(--accent)}.bulk-toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:12px 0}.bulk-toolbar label{display:flex;align-items:center;font-size:13px}.bulk-toolbar small{font-size:13px}
.management-mask{position:fixed;inset:0;width:100%;height:100%;max-width:none;max-height:none;box-sizing:border-box;border:0;margin:0;background:transparent;padding:18px;color:var(--text-hi);font-size:14px}.management-mask:not([open]){display:none}.management-mask[open]{display:flex;align-items:center;justify-content:center}.management-mask::backdrop,.history-window::backdrop{background:#0008}
.management-panel{background:var(--bg-raised);border:1px solid var(--accent-dim);border-radius:12px;width:min(900px,100%);max-height:92dvh;overflow:auto;padding:22px;box-sizing:border-box;box-shadow:0 16px 60px #0005}header,.toolbar,.history-filter{display:flex;gap:12px;align-items:center}header>span{flex:1}h2{margin:0;font-size:18px;font-weight:550}h3{margin:0;font-size:16px}p,small,footer{color:var(--text-lo);font-size:12px}.toolbar{margin:22px 0 12px;flex-wrap:wrap}.toolbar input{margin-left:auto;min-width:100px;width:180px}.toolbar [role=tablist]{display:flex;gap:16px}.toolbar [role=tab]{border:0;border-radius:0;background:none;padding:8px 0;color:var(--text-lo);white-space:nowrap}.toolbar [aria-selected=true]{color:var(--text-hi);border-bottom:2px solid var(--accent)}
.row,.table-head{display:grid;grid-template-columns:minmax(0,1fr) 110px 70px 52px 46px 36px;align-items:center;gap:10px}.table-head{font-size:12px;color:var(--text-lo);padding:10px 0}.row{min-height:74px;border-top:1px solid var(--accent-dim)}.identity{min-width:0}.identity small{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:5px}.identity .name{text-align:left;border:0;background:none;padding:0;max-width:100%;white-space:normal;overflow-wrap:anywhere;font-size:14px;min-height:24px}.health{display:flex;gap:8px;color:var(--text-lo);font-size:12px;flex-wrap:wrap}.up{color:#86cbb1}.down{color:#ed9299}.edit{border:0;background:none;padding:0;white-space:nowrap}button,input{font:inherit;background:var(--bg-panel);color:var(--text-hi);border:1px solid var(--accent-dim);border-radius:6px;padding:7px 10px;min-height:36px;box-sizing:border-box}button{cursor:pointer}button:disabled{opacity:.45;cursor:default}button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}.switch{justify-self:center;width:42px;min-height:36px;display:grid;place-items:center;background:none;border:0;padding:0}.switch i{width:28px;height:16px;border-radius:12px;background:#424b59;position:relative}.switch i:after{content:'';position:absolute;top:3px;left:3px;width:10px;height:10px;border-radius:50%;background:#9ba6b5}.switch[aria-checked=true] i{background:#94a9cc}.switch[aria-checked=true] i:after{left:15px;background:#e4eaf4}footer{border-top:1px solid var(--accent-dim);padding-top:14px;margin-top:8px}[role=alert]{color:#ed9299}.history-window{width:min(650px,calc(100% - 32px));max-height:80dvh;box-sizing:border-box;color:var(--text-hi);background:var(--bg-raised);border:1px solid var(--accent-dim);border-radius:12px;padding:20px}.history header{justify-content:space-between;margin-bottom:20px}.history-filter{flex-wrap:wrap}.history ul{list-style:none;padding:0}.history li{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:10px 0;border-bottom:1px solid var(--accent-dim);font-size:13px}
@media(max-width:600px){.management-mask{padding:8px}.management-panel{padding:14px;max-height:96dvh}.toolbar{gap:8px}.toolbar input{width:100%;margin:0}.row,.table-head{grid-template-columns:minmax(0,1fr) 54px 44px 44px 32px 28px;gap:4px}.table-head{font-size:10px}.health{font-size:11px;gap:2px}.identity .name{font-size:13px}.identity small{font-size:11px}.edit{font-size:12px}.switch{width:36px}.management-panel header{gap:8px}.management-panel header>button{white-space:nowrap}.management-panel header h2{font-size:16px}.management-panel header button{padding:6px 8px}.row{padding:8px 0}}
.row,.table-head{grid-template-columns:minmax(0,1fr) 110px 70px 52px 46px 76px}
.row-actions{display:flex;align-items:center;justify-content:flex-end;gap:4px;min-width:0}
.row-actions>.delete-action{color:#ed9299;font-size:14px}
@media(max-width:600px){.row,.table-head{grid-template-columns:minmax(0,1fr) 40px 36px 36px 28px 72px}.row-actions{gap:2px}}
</style>
