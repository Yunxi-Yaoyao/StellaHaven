<script setup lang="ts">
import {ref,computed,watch,nextTick,onMounted,onBeforeUnmount,inject} from 'vue';
import {matchedRouteKey,onBeforeRouteLeave,onBeforeRouteUpdate} from 'vue-router';
import {listMonitorGroups,listMonitors,updateMonitor,saveMonitorGroup,dissolveMonitorGroup,type Monitor,type MonitorGroup,type MonitorGroupWrite} from '../../api/servers';
import Dropdown from '../../shell/Dropdown.vue';
import MonitorItemEditor from './MonitorItemEditor.vue';
import MonitorCreateDialog from './MonitorCreateDialog.vue';
import MonitorGroupDelete from './MonitorGroupDelete.vue';
import MonitorBulkDelete from './MonitorBulkDelete.vue';
import MonitorActionMenu from './MonitorActionMenu.vue';
import {auth} from '../home/auth';
import {monitorStatusLabel} from './monitorStatusLabel';
import {monitorWriteError} from './monitorTarget';
const props=defineProps<{monitors:Monitor[];groups:MonitorGroup[];nodeName:(id:number)=>string;initialGroupId?:number|null;initialMonitorId?:number|null;nodes?:{id:number;name:string}[]}>();
const emit=defineEmits<{close:[];saved:[];changed:[]}>();
const dialog=ref<HTMLDialogElement|null>(null),rulesDialog=ref<HTMLDialogElement|null>(null),confirmDialog=ref<HTMLDialogElement|null>(null);
const localMonitors=ref([...props.monitors]),localGroups=ref([...props.groups]);
const id=ref(props.initialGroupId??null),name=ref(''),childIds=ref<number[]>([]),policy=ref<'any'|'all'>('any'),rotation=ref<0|8|15|30>(0),groupVisible=ref(true),groupEnabled=ref(true);
const active=computed(()=>!!auth.me&&!auth.suspended&&!auth.sessionClosing),selectedGroup=computed(()=>localGroups.value.find(g=>g.id===id.value)),systemGroup=computed(()=>selectedGroup.value?.automatic===true);
const isNew=computed(()=>id.value===null&&!props.initialMonitorId),members=computed(()=>localMonitors.value.filter(m=>childIds.value.includes(m.id)));
const busy=ref(false),error=ref(''),refreshFailed=ref(false),editing=ref<Monitor|null>(props.initialMonitorId?props.monitors.find(m=>m.id===props.initialMonitorId)??null:null),deletingOnly=ref(false),adding=ref(false),deletingGroup=ref(false);
const itemEditor=ref<InstanceType<typeof MonitorItemEditor>|null>(null),createDialog=ref<InstanceType<typeof MonitorCreateDialog>|null>(null),groupDelete=ref<InstanceType<typeof MonitorGroupDelete>|null>(null);
const selected=ref<number[]>([]),bulk=ref<Monitor[]|null>(null),bulkDelete=ref<InstanceType<typeof MonitorBulkDelete>|null>(null);
const selectable=computed(()=>systemGroup.value?[]:members.value.filter(m=>m.management!=='entry_icmp'));
function selectAll(){selected.value=selected.value.length===selectable.value.length?[]:selectable.value.map(m=>m.id);}
function requestBulk(){if(active.value&&!busy.value&&!pending.value&&selected.value.length)bulk.value=selectable.value.filter(m=>selected.value.includes(m.id));}
function closeBulk(){if(bulkDelete.value?.beforeLeave()!==false)bulk.value=null;}
function bulkChanged(ids:number[]){localMonitors.value=localMonitors.value.filter(m=>!ids.includes(m.id));childIds.value=childIds.value.filter(id=>!ids.includes(id));selected.value=selected.value.filter(id=>!ids.includes(id));emit('changed');}
type Managed={visible?:boolean;enabled?:boolean};
function flag(item:Managed,key:'visible'|'enabled'){return item[key]??true;}
type Receipt={kind:'member';id:number;key:'visible'|'enabled';value:boolean}|{kind:'group';id:number;data:MonitorGroupWrite&Managed}|{kind:'dissolve';id:number};
const operationReceipt=ref<Receipt|null>(null),pending=computed(()=>!!operationReceipt.value);
let owner=auth.me?.id,generation=0,memberReturnLabel:string|null=null;
const previousFocus=document.activeElement as HTMLElement|null;
function choose(){const g=selectedGroup.value;name.value=g?.name??'';childIds.value=[...(g?.child_ids??[])];policy.value=g?.failure_policy??'any';rotation.value=g?.rotation_seconds??0;groupVisible.value=flag(g??{},'visible');groupEnabled.value=flag(g??{},'enabled');}
choose();
watch(()=>props.monitors,value=>{if(!busy.value)localMonitors.value=[...value];});
watch(()=>props.groups,value=>{if(!busy.value)localGroups.value=[...value];});
function beforeLeave(){if((editing.value&&itemEditor.value?.beforeLeave()===false)||((adding.value||isNew.value)&&createDialog.value?.beforeLeave()===false)||(deletingGroup.value&&groupDelete.value?.beforeLeave()===false)||(bulk.value&&bulkDelete.value?.beforeLeave()===false))return false;return !busy.value&&!pending.value;}
defineExpose({beforeLeave});
function close(){if(beforeLeave())emit('close');}
function closeItem(){if(itemEditor.value?.beforeLeave()===false)return;if(props.initialMonitorId)emit('close');else editing.value=null;}
function closeCreate(){if(createDialog.value?.beforeLeave()===false)return;if(isNew.value)emit('close');else adding.value=false;}
function closeGroupDelete(){if(groupDelete.value?.beforeLeave()!==false)deletingGroup.value=false;}
function openCreate(){if(active.value&&!busy.value&&!pending.value){memberReturnLabel='新建监控项';adding.value=true;}}
function editMember(m:Monitor,remove=false){if(busy.value||pending.value||!active.value||remove&&(systemGroup.value||m.management==='entry_icmp'))return;memberReturnLabel=`${remove?'删除':'编辑'}监控项 ${m.name}`;deletingOnly.value=remove;editing.value=m;}
async function readback(){const current=generation;if(!active.value)throw Error('inactive');const [groups,monitors]=await Promise.all([listMonitorGroups(undefined,true),listMonitors()]);if(current!==generation||!active.value)throw Error('stale');localGroups.value=groups;localMonitors.value=monitors;return {groups,monitors};}
async function confirmOperation(){
 if(!active.value||busy.value||!operationReceipt.value)return;const current=generation,receipt=operationReceipt.value;busy.value=true;error.value='';
 try{const stored=await readback();if(current!==generation||operationReceipt.value!==receipt)return;
 if(receipt.kind==='member'){const actual=stored.monitors.find(m=>m.id===receipt.id);if(!actual||flag(actual,receipt.key)!==receipt.value)throw Error('readback');operationReceipt.value=null;emit('changed');}
 else if(receipt.kind==='dissolve'){if(stored.groups.some(g=>g.id===receipt.id))throw Error('readback');operationReceipt.value=null;emit('saved');}
 else{const actual=stored.groups.find(g=>g.id===receipt.id);if(!actual||Object.entries(receipt.data).some(([k,v])=>k==='child_ids'?actual.child_ids.join(',')!==(v as number[]).join(','):actual[k as keyof MonitorGroup]!==v))throw Error('readback');operationReceipt.value=null;emit('saved');}
 }catch{if(current===generation)error.value='操作未确认，仅重新读取核对，不重复提交。';}finally{if(current===generation)busy.value=false;}
}
async function toggleMember(m:Monitor,key:'visible'|'enabled'){
 if(!active.value||busy.value||pending.value)return;const current=generation,value=!flag(m,key);operationReceipt.value={kind:'member',id:m.id,key,value};busy.value=true;error.value='';
 try{await updateMonitor(m.id,{[key]:value});}catch(e:any){if(current!==generation||!active.value)return;if(e?.status>=400&&e?.status<500&&e.status!==408)operationReceipt.value=null;error.value='开关状态未确认，请重新读取核对';busy.value=false;return;}
 if(current!==generation||!active.value)return;busy.value=false;await confirmOperation();
}
async function refreshMembers(){
 if(!active.value||busy.value||pending.value)return;const current=generation;busy.value=true;error.value='';
 try{const stored=await readback();childIds.value=[...(stored.groups.find(g=>g.id===id.value)?.child_ids??[])];refreshFailed.value=false;emit('changed');}
 catch{if(current===generation){refreshFailed.value=true;error.value='监控项刷新失败，请重新读取；已确认的删除不会重复提交。';}}
 finally{if(current===generation)busy.value=false;}
}
async function edited(){if(props.initialMonitorId){emit('saved');return;}const deleted=deletingOnly.value?editing.value?.id:null;if(deleted){localMonitors.value=localMonitors.value.filter(m=>m.id!==deleted);childIds.value=childIds.value.filter(mid=>mid!==deleted);}editing.value=null;await refreshMembers();}
async function created(){if(isNew.value){emit('saved');return;}adding.value=false;await refreshMembers();}
async function save(){
 if(!active.value||busy.value)return;if(operationReceipt.value){await confirmOperation();return;}if(isNew.value)return;
 const current=generation,data:MonitorGroupWrite&Managed={name:name.value,failure_policy:policy.value,rotation_seconds:rotation.value,visible:groupVisible.value,enabled:groupEnabled.value};
 operationReceipt.value={kind:'group',id:id.value!,data};busy.value=true;error.value='';
 try{await saveMonitorGroup(id.value,data);}catch(e:any){if(current!==generation||!active.value)return;if(e?.status>=400&&e?.status<500&&e.status!==408)operationReceipt.value=null;error.value=monitorWriteError(e,'保存未确认，请重新读取核对。');busy.value=false;return;}
 if(current!==generation||!active.value)return;busy.value=false;await confirmOperation();
}
async function dissolve(){
 if(systemGroup.value||!active.value||id.value===null||busy.value||pending.value)return;const current=generation;operationReceipt.value={kind:'dissolve',id:id.value};busy.value=true;error.value='';
 try{await dissolveMonitorGroup(id.value);}catch(e:any){if(current!==generation||!active.value)return;if(e?.status>=400&&e?.status<500&&e.status!==408)operationReceipt.value=null;error.value='解散未确认，请重新读取核对。';busy.value=false;return;}
 if(current!==generation||!active.value)return;busy.value=false;await confirmOperation();
}
function groupAction(action:string|number|boolean){if(!active.value||busy.value||pending.value)return;if(action==='visible')groupVisible.value=!groupVisible.value;else if(action==='enabled')groupEnabled.value=!groupEnabled.value;else if(action==='delete'&&!systemGroup.value)deletingGroup.value=true;else if(action==='dissolve'&&!systemGroup.value)confirmDialog.value?.showModal();}
async function syncDialog(){await nextTick();if(!active.value||editing.value||adding.value||isNew.value||deletingGroup.value||bulk.value){dialog.value?.close();rulesDialog.value?.close();confirmDialog.value?.close();return;}if(!dialog.value?.open){dialog.value?.showModal();const target=[...dialog.value?.querySelectorAll<HTMLButtonElement>('.child-actions button')??[]].find(b=>b.getAttribute('aria-label')===memberReturnLabel);if(target)target.focus();else if(memberReturnLabel==='新建监控项')dialog.value?.querySelector<HTMLButtonElement>('[data-create]')?.focus();else dialog.value?.querySelector<HTMLInputElement>('input')?.focus();}}
watch(()=>[active.value,auth.me?.id,auth.requestEpoch,auth.sessionGeneration],()=>{generation++;busy.value=false;if(owner!==auth.me?.id){owner=auth.me?.id;memberReturnLabel=null;editing.value=null;name.value='';childIds.value=[];localMonitors.value=[];localGroups.value=[];operationReceipt.value=null;emit('close');}void syncDialog();},{flush:'sync'});
watch(()=>[editing.value,adding.value,deletingGroup.value,bulk.value],syncDialog,{flush:'post'});
onMounted(syncDialog);
function beforeUnload(e:BeforeUnloadEvent){if(!beforeLeave()){e.preventDefault();e.returnValue='';}}
window.addEventListener('beforeunload',beforeUnload);
if(inject(matchedRouteKey,undefined)){onBeforeRouteLeave(beforeLeave);onBeforeRouteUpdate(beforeLeave);}
onBeforeUnmount(()=>{generation++;window.removeEventListener('beforeunload',beforeUnload);dialog.value?.close();if(active.value&&previousFocus?.isConnected)previousFocus.focus();});
</script>
<template>
<div>
 <MonitorCreateDialog v-if="isNew||adding" ref="createDialog" :nodes="nodes??[]" :group-id="isNew?undefined:id??undefined" :group-name="name" @close="closeCreate" @saved="created"/>
 <dialog ref="dialog" class="group-dialog" aria-labelledby="group-title" @cancel.prevent="close" @click.self="close">
 <div v-if="active&&!editing&&!adding&&!isNew&&!deletingGroup&&!bulk">
 <header><h3 id="group-title">监控组设置</h3><button aria-label="关闭监控组设置" :disabled="busy||pending" @click="close">×</button></header>
 <form @submit.prevent="save" @keydown.enter="($event.isComposing||$event.keyCode===229)&&$event.preventDefault()">
 <label>监控组名称<input v-model="name" aria-label="监控组名称" required maxlength="64" :disabled="busy||pending"></label>
 <p v-if="systemGroup" class="hint">目标：{{selectedGroup?.target_origin||'未配置其他入口'}} · 由<a href="/settings?section=services#site-addresses">站点与服务</a>统一设置</p>
 <div class="member-list-head"><span>监控项 · {{members.length}}</span><button v-if="!systemGroup" type="button" data-create :disabled="busy||pending||childIds.length>=12" @click="openCreate">新建监控项</button></div>
 <div v-if="!systemGroup" class="bulk-toolbar"><label><input type="checkbox" aria-label="全选当前列表" :checked="!!selectable.length&&selected.length===selectable.length" :disabled="busy||pending||!selectable.length" @change="selectAll">全选当前列表</label><button type="button" :disabled="busy||pending||!selected.length" @click="requestBulk">批量删除 ({{selected.length}})</button></div>
 <fieldset :disabled="busy||pending" aria-label="监控项列表"><div v-for="m in members" :key="m.id" class="child-row">
 <div class="child-choice"><input v-if="!systemGroup&&m.management!=='entry_icmp'" v-model="selected" type="checkbox" :value="m.id" :aria-label="`选择监控项 ${m.name}`"><strong>{{m.name}}</strong><small class="child-target" :title="m.target">{{m.type.toUpperCase()}} · {{m.target}}</small></div><span class="child-status">{{m.enabled===false?'已停用':monitorStatusLabel(m)}}</span>
 <div class="child-actions"><button type="button" :aria-label="`编辑监控项 ${m.name}`" @click="editMember(m)">编辑</button><button v-if="!systemGroup&&m.management!=='entry_icmp'" type="button" class="delete-action" :aria-label="`删除监控项 ${m.name}`" @click="editMember(m,true)">删除</button><MonitorActionMenu :label="`成员操作 ${m.name}`" :disabled="busy||pending" :options="[{value:'visible',label:flag(m,'visible')?'隐藏于总览':'显示于总览'},{value:'enabled',label:flag(m,'enabled')?'停用监控':'启用监控'}]" @select="toggleMember(m,$event as 'visible'|'enabled')"/></div>
 </div><p v-if="!members.length" class="hint">{{systemGroup?(selectedGroup?.availability_reason==='entry_not_configured'?'未配置其他入口':'暂无接入节点'):'没有监控项，此组不会出现在总览。'}}</p></fieldset>
 <p v-if="error" role="alert">{{error}}</p><button v-if="refreshFailed" type="button" :disabled="busy||pending" @click="refreshMembers">重新读取监控项</button><button v-if="pending" type="button" :disabled="busy" @click="confirmOperation">重新读取确认</button>
 <footer><button type="button" class="text-action" :disabled="busy||pending" @click="rulesDialog?.showModal()">聚合与轮播设置 ›</button><MonitorActionMenu label="监控组操作" :disabled="busy||pending" :options="[{value:'visible',label:groupVisible?'隐藏监控组':'显示监控组'},{value:'enabled',label:groupEnabled?'停用监控组':'启用监控组'},...(!systemGroup?[{value:'delete',label:'删除监控组'},{value:'dissolve',label:'解散监控组…'}]:[])]" @select="groupAction"/><span/><button type="button" :disabled="busy||pending" @click="close">取消</button><button type="submit" :disabled="busy">{{busy?'正在确认…':'保存设置'}}</button></footer>
 </form></div>
 <dialog ref="rulesDialog" class="small-dialog" aria-label="聚合与轮播设置" @cancel.prevent="rulesDialog?.close()"><h3>聚合与轮播设置</h3><div class="group-fields"><label>异常规则<Dropdown v-model="policy" :options="[{value:'any',label:'任一监控项失败'},{value:'all',label:'全部监控项失败'}]"/></label><label>监控项轮转<Dropdown v-model="rotation" :options="[{value:0,label:'关闭 · 手动切换'},{value:8,label:'每 8 秒'},{value:15,label:'每 15 秒'},{value:30,label:'每 30 秒'}]"/></label></div><footer><button @click="rulesDialog?.close()">完成</button></footer></dialog>
 <dialog v-if="!systemGroup" ref="confirmDialog" class="small-dialog" aria-label="确认解散监控组" @cancel.prevent="confirmDialog?.close()"><h3>解散「{{name}}」？</h3><p>仅解除组合关系，所有监控项与历史保留；自动监控组不会重建。</p><footer><button :disabled="busy" @click="confirmDialog?.close()">取消</button><button :disabled="busy" @click="dissolve">确认解散</button></footer></dialog>
 </dialog>
 <MonitorItemEditor v-if="editing" ref="itemEditor" :monitor="editing" :delete-only="deletingOnly" :nodes="nodes" :node-name="nodeName(editing.node_id)" :group-name="initialMonitorId?undefined:name" @close="closeItem" @saved="edited"/>
 <MonitorGroupDelete v-if="deletingGroup&&id!==null" ref="groupDelete" :group-id="id" :open="true" @close="closeGroupDelete" @deleted="emit('saved')"/>
 <MonitorBulkDelete v-if="bulk" ref="bulkDelete" :monitors="bulk" :group-name="name" @close="closeBulk" @changed="bulkChanged"/>
</div>
</template>
<style scoped>
input[type=checkbox]{width:16px;height:16px;min-height:0;margin:0 8px 0 0;vertical-align:middle;accent-color:var(--accent)}.bulk-toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.bulk-toolbar label{display:flex;align-items:center;font-size:13px}
.group-dialog,.small-dialog{position:fixed;inset:0;margin:auto;height:fit-content;box-sizing:border-box;width:min(680px,calc(100% - 24px));max-height:calc(100dvh - 24px);overflow:auto;border:1px solid var(--accent-dim);border-radius:var(--radius);padding:20px;color:var(--text-hi);background:var(--bg-raised);font-size:14px}.group-dialog:not([open]),.small-dialog:not([open]){display:none}.group-dialog::backdrop,.small-dialog::backdrop{background:#0008}header,footer,.group-fields,.member-list-head{display:flex;gap:10px;align-items:center}header{justify-content:space-between}h3{margin:0;font-size:18px}form{display:grid;gap:16px;margin-top:18px}label{display:grid;gap:6px;min-width:0}input,button{font:inherit;box-sizing:border-box;border:1px solid var(--accent-dim);border-radius:var(--radius-sm);background:var(--bg-panel);color:var(--text-hi);padding:8px 10px;min-height:36px}input{width:100%;min-width:0}button{cursor:pointer}button:disabled{opacity:.45;cursor:default}fieldset{border:0;padding:0;margin:0;min-width:0}.member-list-head{justify-content:space-between}.member-list-head button,.child-actions>button,.text-action{border:0;background:none}.child-row{display:grid;grid-template-columns:minmax(0,1fr) 44px 132px;align-items:center;gap:8px;padding:12px 0;border-bottom:1px solid var(--accent-dim)}.child-choice{min-width:0}.child-choice strong{font-weight:500;overflow-wrap:anywhere}.child-target{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-lo);font-size:13px;margin-top:5px}.child-actions{display:flex;align-items:center;gap:2px;justify-content:flex-end}.child-actions>button{padding:4px 6px;white-space:nowrap}.child-status,.hint{font-size:13px;color:var(--text-lo)}.delete-action,[role=alert]{color:#ed9299}footer{justify-content:flex-end;flex-wrap:wrap}footer>span{flex:1}.group-fields>label{flex:1}.small-dialog{width:min(460px,calc(100% - 24px))}.small-dialog .group-fields{margin-top:20px}.small-dialog footer{margin-top:20px}button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(max-width:480px){.group-dialog{padding:14px}.child-row{grid-template-columns:minmax(0,1fr) 36px 124px;gap:4px}footer{gap:6px}footer>.text-action{width:100%;text-align:left}.group-fields{display:grid}}
</style>
