<script setup lang="ts">
import {ref,computed,watch,nextTick,onBeforeUnmount} from 'vue';
import {auth} from '../home/auth';
import {removeMonitor,listMonitors,type Monitor} from '../../api/servers';
const props=defineProps<{monitors:Monitor[];groupName?:string}>();
const emit=defineEmits<{close:[];changed:[ids:number[]]}>();
// Freeze only the displayed user selection. Never expand to groups or hidden results.
const rows=ref([...new Map(props.monitors.filter(m=>m.management!=='entry_icmp').map(m=>[m.id,{id:m.id,name:m.name,type:m.type,target:m.target,status:'ready' as 'ready'|'unknown'|'deleted'|'failed'}])).values()]);
const dialog=ref<HTMLDialogElement|null>(null),busy=ref(false),error=ref(''),started=ref(false),previousFocus=document.activeElement as HTMLElement;
const active=computed(()=>!!auth.me&&!auth.suspended&&!auth.sessionClosing),unknown=computed(()=>rows.value.some(r=>r.status==='unknown')),complete=computed(()=>rows.value.every(r=>r.status==='deleted'));
let owner=auth.me?.id,generation=0;
function beforeLeave(){return !busy.value&&!unknown.value;}
defineExpose({beforeLeave});
function close(){if(beforeLeave())emit('close');}
function trapTab(event:KeyboardEvent){
 if(event.key!=='Tab')return;
 const controls=[...dialog.value?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')??[]].filter(el=>el.getClientRects().length),first=controls[0],last=controls.at(-1);
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();event.stopPropagation();last?.focus();}
 else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();event.stopPropagation();first?.focus();}
}
async function read(current=generation){
 const stored=await listMonitors();if(current!==generation||!active.value)return;
 const removed:number[]=[];for(const row of rows.value){if(row.status==='deleted'||row.status==='ready')continue;if(!stored.some(m=>m.id===row.id)){row.status='deleted';removed.push(row.id);}else if(row.status!=='unknown')row.status='failed';}
 if(removed.length)emit('changed',removed);
 error.value=unknown.value?'部分删除尚未确认：仍存在的项仅可重新读取，不重复提交。':rows.value.some(r=>r.status==='failed')?'部分项目删除被拒绝；保留失败项，可明确确认后重试。':'';
}
async function reconcile(){if(!active.value||busy.value)return;const current=generation;busy.value=true;error.value='';try{await read(current);}catch{if(current===generation)error.value='删除尚未确认，读取失败；仅重新读取，不重复提交。';}finally{if(current===generation)busy.value=false;}}
async function remove(){
 if(!active.value||busy.value||unknown.value)return;const current=generation,owned=()=>current===generation&&active.value;busy.value=true;started.value=true;error.value='';
 try{
  for(const row of rows.value){
   if(!owned())return;if(row.status!=='ready'&&row.status!=='failed')continue;
   row.status='unknown';
   try{await removeMonitor(row.id,owned);}catch(e:any){if(!owned())return;if(e?.status>=400&&e?.status<500&&e.status!==408&&e.status!==404)row.status='failed';if(e?.status===401||e?.status===403)break;}
   if(!owned())return;
  }
  await read(current);
 }catch{if(owned())error.value='删除尚未确认，读取失败；仅重新读取，不重复提交。';}
 finally{if(owned())busy.value=false;}
}
watch(()=>[active.value,auth.me?.id,auth.requestEpoch,auth.sessionGeneration],async()=>{const current=++generation;busy.value=false;if(owner!==auth.me?.id){owner=auth.me?.id;rows.value=[];error.value='';dialog.value?.close();emit('close');return;}if(!active.value){dialog.value?.close();return;}await nextTick();if(current===generation&&active.value&&!dialog.value?.open){dialog.value?.showModal();dialog.value?.querySelector<HTMLButtonElement>('button')?.focus();}},{immediate:true,flush:'sync'});
function beforeUnload(e:BeforeUnloadEvent){if(!beforeLeave()){e.preventDefault();e.returnValue='';}}
window.addEventListener('beforeunload',beforeUnload);
onBeforeUnmount(()=>{generation++;window.removeEventListener('beforeunload',beforeUnload);dialog.value?.close();if(active.value)void nextTick(()=>previousFocus?.isConnected&&previousFocus.focus());});
</script>
<template>
<dialog ref="dialog" class="bulk-window" aria-label="批量删除监控项" @cancel.prevent="close" @click.self="close" @keydown="trapTab"><template v-if="active"><h3>删除所选 {{rows.length}} 个监控项？</h3><p>仅删除下列明确勾选的监控项及其探测历史，不能恢复。不会删除监控组，空组保留；成员不会变为独立监控。系统自动项不在范围内。</p><p v-if="groupName">所属组：{{groupName}}</p>
 <ul><li v-for="row in rows" :key="row.id"><strong>{{row.name}}</strong><small>#{{row.id}} · {{row.type.toUpperCase()}} · {{row.target}}</small><span>{{row.status==='deleted'?'已删除':row.status==='failed'?'失败，已保留':row.status==='unknown'?'尚未确认 / 仍存在':'待删除'}}</span></li></ul><p v-if="error" role="alert">{{error}}</p>
 <footer><button type="button" :disabled="!beforeLeave()" @click="close">{{complete?'完成':started?'关闭':'取消'}}</button><button v-if="unknown" type="button" :disabled="busy" @click="reconcile">重新读取确认</button><button v-else-if="!complete" type="button" class="danger" :disabled="busy||!rows.length" @click="remove">{{busy?'正在删除…':started?'确认重试失败项':'确认批量删除'}}</button></footer></template></dialog>
</template>
<style scoped>
.bulk-window{position:fixed;inset:0;margin:auto;box-sizing:border-box;width:min(580px,calc(100% - 24px));max-height:calc(100dvh - 24px);overflow:auto;border:1px solid var(--accent-dim);border-radius:var(--radius);padding:22px;color:var(--text-hi);background:var(--bg-raised);font-size:14px}.bulk-window:not([open]){display:none}.bulk-window::backdrop{background:#0008}h3{margin:0;font-size:18px;overflow-wrap:anywhere}p,small{font-size:13px;color:var(--text-lo);line-height:1.6}ul{list-style:none;padding:0;margin:16px 0}li{border-top:1px solid var(--accent-dim);padding:12px 0;display:grid;gap:5px;overflow-wrap:anywhere}strong{font-weight:500}li span{font-size:13px}footer{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}button{font:inherit;min-height:38px;padding:8px 12px;background:var(--bg-panel);color:var(--text-hi);border:1px solid var(--accent-dim);border-radius:var(--radius-sm);cursor:pointer}button:disabled{opacity:.45;cursor:default}.danger,[role=alert]{color:#ed9299}button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(max-width:480px){.bulk-window{padding:16px}}
</style>
