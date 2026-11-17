<script setup lang="ts">
import {computed,ref,watch,nextTick,onBeforeUnmount} from 'vue';
import {auth} from '../home/auth';
import {getMonitorGroupDeletionState,deleteMonitorGroup,type MonitorGroupDeletionState} from '../../api/servers';
const props=defineProps<{groupId:number;open:boolean}>();
const emit=defineEmits<{close:[];deleted:[]}>();
const dialog=ref<HTMLDialogElement|null>(null),scope=ref<(MonitorGroupDeletionState&{groupId:number})|null>(null),busy=ref(false),pending=ref(false),error=ref('');
const active=computed(()=>props.open&&!!auth.me&&!auth.suspended&&!auth.sessionClosing);
let generation=0,owner=auth.me?.id,request:AbortController|undefined;

function beforeLeave(){return !pending.value;}
defineExpose({beforeLeave});
function close(){if(beforeLeave())emit('close');}
async function readScope(){
 if(!active.value||busy.value||pending.value)return;
 const current=generation,groupId=props.groupId;request?.abort();request=new AbortController();busy.value=true;error.value='';scope.value=null;
 try{const state=await getMonitorGroupDeletionState(groupId,[],request.signal);if(current!==generation||!active.value)return;if(state.group_exists&&!state.stable_uuid)throw new Error('missing identity');scope.value={...state,children:state.children.map(m=>({...m})),groupId};if(!state.group_exists)error.value='监控组已不存在，请取消并刷新列表';else if(state.protected)error.value='系统入口监控组或 entry_icmp 监控项不可手动删除';}
 catch{if(current===generation&&active.value)error.value='读取删除范围失败，请重新读取范围';}
 finally{if(current===generation)busy.value=false;}
}
async function readBack(){
 if(!active.value||busy.value||!pending.value||!scope.value)return;
 const current=generation,confirmed=scope.value;busy.value=true;error.value='';request?.abort();request=new AbortController();
 try{const state=await getMonitorGroupDeletionState(confirmed.groupId,confirmed.children.map(m=>m.id),request.signal,confirmed.stable_uuid!);if(current!==generation||!active.value)return;if(state.identity_matches!==false){error.value='删除尚未确认：原确认监控组仍存在或身份尚未核对。仅重新读取，不重复提交。';return;}if(state.remaining_child_ids.length){error.value=`删除尚未确认：原确认监控组已消失，但仍有 ${state.remaining_child_ids.length} 个确认成员存在，不能确认整批已删除。仅重新读取，不重复提交。`;return;}pending.value=false;emit('deleted');}
 catch{if(current===generation&&active.value)error.value='删除尚未确认：需核对监控组及确认成员均已消失。仅重新读取，不重复提交。';}
 finally{if(current===generation)busy.value=false;}
}
async function remove(){
 if(!active.value||busy.value||pending.value||!scope.value?.group_exists||!scope.value.stable_uuid||scope.value.protected)return;
 const current=generation,confirmed=scope.value;pending.value=true;busy.value=true;error.value='';
 try{await deleteMonitorGroup(confirmed.groupId,confirmed.children.map(m=>m.id),confirmed.stable_uuid!);}
 catch(e:any){if(current!==generation||!active.value)return;busy.value=false;if(e?.status>=400&&e?.status<500){pending.value=false;scope.value=null;error.value=e.status===409?'组身份或成员范围已变化，未删除。请重新读取范围后再次确认。':'删除被拒绝。请重新读取范围后核对。';}else error.value='删除尚未确认：未收到完整回执。仅重新读取，不重复提交。';return;}
 if(current!==generation||!active.value)return;busy.value=false;await readBack();
}
watch(()=>[props.open,props.groupId,auth.me?.id,auth.suspended,auth.sessionClosing,auth.requestEpoch,auth.sessionGeneration],async()=>{
 const current=++generation;request?.abort();busy.value=false;dialog.value?.close();
 if(owner!==auth.me?.id){owner=auth.me?.id;scope.value=null;pending.value=false;error.value='';emit('close');return;}
 if(!active.value)return;
 await nextTick();if(current!==generation||!active.value)return;dialog.value?.showModal();
 if(!pending.value)void readScope();
},{immediate:true,flush:'sync'});
function beforeUnload(e:BeforeUnloadEvent){if(!beforeLeave()){e.preventDefault();e.returnValue='';}}
window.addEventListener('beforeunload',beforeUnload);
onBeforeUnmount(()=>{generation++;request?.abort();window.removeEventListener('beforeunload',beforeUnload);dialog.value?.close();});
</script>
<template>
 <dialog ref="dialog" class="group-delete-window" aria-label="确认删除监控组" @cancel.prevent="close" @click.self="close">
  <template v-if="active">
   <h3>删除整组「{{scope?.name??'监控组'}}」？</h3>
   <p>监控组及以下 {{scope?.children.length??0}} 个监控项、各自的探测历史将永久删除，不能恢复。不是解散，不会保留为独立监控。MTR 历史保留并解除监控项关联。</p>
   <ul v-if="scope"><li v-for="m in scope.children" :key="m.id"><strong>{{m.name}}</strong><small>{{m.type.toUpperCase()}} · {{m.target}}</small></li><li v-if="!scope.children.length">空组：只删除此监控组。</li></ul>
   <p v-if="busy" role="status">正在读取或确认…</p><p v-if="error" role="alert">{{error}}</p>
   <footer><button type="button" :disabled="!beforeLeave()" @click="close">取消</button><button v-if="pending" type="button" :disabled="busy" @click="readBack">重新读取确认</button><button v-else-if="!scope||scope.protected||!scope.group_exists" type="button" :disabled="busy" @click="readScope">重新读取范围</button><button v-else type="button" class="danger" :disabled="busy" @click="remove">确认删除整组</button></footer>
  </template>
 </dialog>
</template>
<style scoped>
.group-delete-window{position:fixed;inset:0;margin:auto;height:fit-content;box-sizing:border-box;width:min(560px,calc(100% - 24px));max-height:calc(100dvh - 24px);overflow:auto;border:1px solid var(--accent-dim);border-radius:var(--radius);padding:22px;color:var(--text-hi);background:var(--bg-raised);font-size:14px}.group-delete-window::backdrop{background:#0008}h3{font-size:18px;font-weight:550;margin:0;min-width:0;overflow-wrap:anywhere}p,li{overflow-wrap:anywhere;line-height:1.6}p,small{color:var(--text-lo)}ul{list-style:none;padding:0;max-height:40dvh;overflow:auto}li{padding:8px 0;border-bottom:1px solid var(--accent-dim)}strong{font-weight:500}small{display:block;font-size:13px}footer{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px;border-top:1px solid var(--accent-dim);padding-top:16px;margin-top:18px}button{font:inherit;min-height:36px;border:1px solid var(--accent-dim);border-radius:var(--radius-sm);padding:6px 12px;background:var(--bg-panel);color:var(--text-hi);cursor:pointer}button:disabled{opacity:.45;cursor:default}.danger,[role=alert]{color:#ed9299}button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(max-width:400px){.group-delete-window{padding:16px}}
</style>
