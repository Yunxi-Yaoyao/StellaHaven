<script setup lang="ts">
import {computed,ref,watch,nextTick,onBeforeUnmount} from 'vue';
import {auth} from '../home/auth';
import Dropdown from '../../shell/Dropdown.vue';

import {updateMonitor,listMonitors,removeMonitor,listMonitorChecks,type Monitor,type MonitorCheck} from '../../api/servers';
import {monitorTarget,monitorTargetError,monitorWriteError} from './monitorTarget';
import {splitMonitorTarget,joinMonitorTarget} from './monitorBatchDraft';
const props=defineProps<{monitor:Monitor;nodes?:{id:number;name:string}[];nodeName:string;groupName?:string;deleteOnly?:boolean}>();
const emit=defineEmits<{close:[];saved:[]}>();
const dialog=ref<HTMLDialogElement|null>(null),historyDialog=ref<HTMLDialogElement|null>(null),confirmDialog=ref<HTMLDialogElement|null>(null);
const name=ref(props.monitor.name),type=ref(props.monitor.type),target=ref(props.monitor.target),node=ref(props.monitor.node_id),interval=ref(props.monitor.interval),timeout=ref(props.monitor.timeout);
const originalParts=splitMonitorTarget(props.monitor.type,props.monitor.target),host=ref(originalParts.host),port=ref(originalParts.port),suffix=ref(originalParts.suffix);
const splitError=ref('');
watch([host,port,suffix,type],()=>{splitError.value='';if(originalParts.legacy)return;try{if(suffix.value&&type.value!=='http'&&type.value!=='https')throw Error('旧 URL 含路径或查询；请先明确清空路径后再切换类型');target.value=joinMonitorTarget(type.value,host.value,port.value,suffix.value);}catch(e){splitError.value=(e as Error).message;}});
const busy=ref(false),error=ref(''),pending=ref<{fields:Parameters<typeof updateMonitor>[1]}|{delete:true}|null>(null);
const active=computed(()=>!!auth.me&&!auth.suspended&&!auth.sessionClosing),automatic=computed(()=>props.monitor.management==='entry_icmp');
const nodeOptions=computed(()=>(props.nodes?.length?props.nodes:[{id:props.monitor.node_id,name:props.nodeName}]).map(n=>({value:n.id,label:n.name})));
const options=[{value:'tcp',label:'TCP'},{value:'udp',label:'UDP'},{value:'ping',label:'Ping'},{value:'http',label:'HTTP'},{value:'https',label:'HTTPS'}];
const previousFocus=document.activeElement as HTMLElement;let historyGeneration=0;let generation=0,owner=auth.me?.id;
const checks=ref<MonitorCheck[]>([]),historyOpen=ref(false),historyLoading=ref(false),historyError=ref(''),filter=ref<string|number|boolean>('all');
const filtered=computed(()=>checks.value.filter(c=>filter.value==='all'||c.success===(filter.value==='up')));
function beforeLeave(){return !busy.value&&!pending.value;}
defineExpose({beforeLeave});
function close(){if(beforeLeave())emit('close');}
function escape(event:KeyboardEvent){if(event.isComposing){event.preventDefault();return;}close();}
async function confirmRead(){
 const current=generation;if(!active.value||busy.value||!pending.value)return;busy.value=true;error.value='';
 try{const stored=(await listMonitors()).find(m=>m.id===props.monitor.id);if(current!==generation||!active.value)return;const p=pending.value;if(!p)return;if('delete' in p?!!stored:!stored||Object.entries(p.fields).some(([k,v])=>stored[k as keyof Monitor]!==v))throw new Error('readback');pending.value=null;emit('saved');}
 catch{if(current===generation)error.value=pending.value&&'delete' in pending.value?'删除尚未确认，仅重新读取核对，不重复提交。':'保存尚未确认，仅重新读取核对，不重复提交。';}finally{if(current===generation)busy.value=false;}
}
async function save(){
 if(!active.value||busy.value)return;if(pending.value){await confirmRead();return;}
 if(!name.value.trim()){error.value='名称不能为空';return;}if(splitError.value){error.value=splitError.value;return;}
 const fields:Parameters<typeof updateMonitor>[1]={name:name.value.trim()};
 if(!automatic.value){const changed=type.value!==props.monitor.type||target.value!==props.monitor.target;if(changed&&monitorTargetError(type.value,target.value)){error.value=monitorTargetError(type.value,target.value);return;}if(!Number.isInteger(interval.value)||interval.value<10||interval.value>86400||!Number.isInteger(timeout.value)||timeout.value<1||timeout.value>120){error.value='请填写有效的检测间隔和超时';return;}Object.assign(fields,{node_id:node.value,interval:interval.value,timeout:timeout.value});if(changed)Object.assign(fields,{type:type.value,target:monitorTarget(type.value,target.value)});}
 const current=generation;pending.value={fields};busy.value=true;error.value='';
 try{await updateMonitor(props.monitor.id,fields);}catch(e:any){if(current!==generation||!active.value)return;if(e?.status>=400&&e?.status<500){pending.value=null;error.value=monitorWriteError(e,'保存被拒绝');}else error.value='保存尚未确认，仅重新读取核对，不重复提交。';busy.value=false;return;}
 if(current!==generation||!active.value)return;busy.value=false;await confirmRead();
}
async function remove(){
 if(!active.value||automatic.value||busy.value||pending.value)return;const current=generation;pending.value={delete:true};busy.value=true;error.value='';confirmDialog.value?.close();
 try{await removeMonitor(props.monitor.id);}catch(e:any){if(current!==generation||!active.value)return;if(e?.status>=400&&e?.status<500){pending.value=null;error.value='删除被拒绝';}else error.value='删除尚未确认，仅重新读取核对，不重复提交。';busy.value=false;return;}
 if(current!==generation||!active.value)return;busy.value=false;await confirmRead();
}
async function history(){
 if(!active.value)return;historyOpen.value=true;await nextTick();if(!historyDialog.value?.open)historyDialog.value?.showModal();const current=generation,request=++historyGeneration;historyLoading.value=true;historyError.value='';
 try{const rows=await listMonitorChecks(props.monitor.id);if(current===generation&&request===historyGeneration&&active.value&&historyOpen.value)checks.value=rows;}catch{if(current===generation)historyError.value='历史读取失败，请重试';}finally{if(current===generation)historyLoading.value=false;}
}
function closeHistory(){historyGeneration++;historyOpen.value=false;historyDialog.value?.close();}
function beforeUnload(e:BeforeUnloadEvent){if(!beforeLeave()){e.preventDefault();e.returnValue='';}}
watch(()=>[auth.me?.id,auth.suspended,auth.sessionClosing,auth.requestEpoch,auth.sessionGeneration],async()=>{generation++;busy.value=false;historyDialog.value?.close();confirmDialog.value?.close();historyOpen.value=false;checks.value=[];if(owner!==auth.me?.id){pending.value=null;name.value='';target.value='';host.value='';port.value='';suffix.value='';owner=auth.me?.id;dialog.value?.close();emit('close');return;}if(!active.value){dialog.value?.close();return;}await nextTick();if(active.value&&!dialog.value?.open){dialog.value?.showModal();dialog.value?.querySelector<HTMLInputElement>('input')?.focus();}},{immediate:true,flush:'sync'});
window.addEventListener('beforeunload',beforeUnload);
onBeforeUnmount(()=>{generation++;window.removeEventListener('beforeunload',beforeUnload);dialog.value?.close();historyDialog.value?.close();confirmDialog.value?.close();if(active.value)void nextTick(()=>previousFocus?.isConnected&&previousFocus.focus());});
</script>
<template>
<dialog ref="dialog" class="item-window" :aria-label="deleteOnly?'确认删除监控项':'编辑监控项'" @cancel.prevent="escape($event as KeyboardEvent)" @click.self="close">
 <template v-if="active&&deleteOnly"><h3>删除「{{monitor.name}}」？</h3><p>此监控项及其探测历史将永久删除，不能恢复。</p><p v-if="groupName">所属组「{{groupName}}」将不再包含此项；不会变为独立监控。删除最后一个成员后保留空组，可继续添加监控项。</p><p v-if="automatic">系统自动监控项不可手动删除，请管理节点或站点入口设置。</p><p v-if="error" role="alert">{{error}}</p><footer><button type="button" :disabled="!beforeLeave()" @click="close">取消</button><button v-if="pending" type="button" :disabled="busy" @click="confirmRead">重新读取确认</button><button v-else-if="!automatic" type="button" :disabled="busy" @click="remove">确认删除</button></footer></template>
 <template v-else-if="active"><header><h3>编辑监控项</h3><span :class="monitor.status==='up'?'up':'down'">{{monitor.enabled===false?'已停用':monitor.status==='up'?'正常':'异常'}}</span><button v-if="!automatic" type="button" class="text down" :disabled="busy||!!pending" @click="confirmDialog?.showModal()">删除监控项</button><button type="button" aria-label="关闭编辑监控项" :disabled="!beforeLeave()" @click="close">×</button></header>
 <form @submit.prevent="save()" @keydown.enter="($event.isComposing||$event.keyCode===229)&&$event.preventDefault()"><fieldset :disabled="busy||!!pending"><label>名称<input v-model="name" aria-label="名称" maxlength="64" required/></label><div class="split"><label>类型<span v-if="automatic" class="readonly">Ping · 自动入口</span><Dropdown v-else v-model="type" :options="options"/></label><label>探测节点<span v-if="automatic" class="readonly">{{nodeName}}</span><Dropdown v-else v-model="node" :options="nodeOptions"/></label></div><template v-if="automatic||originalParts.legacy"><label>{{automatic?'目标':'原始目标（兼容保留）'}}<input v-model="target" aria-label="目标" :readonly="automatic" required/></label><p v-if="originalParts.legacy">此旧目标无法安全拆分；保留原文，不会自动转换或删除 URL 路径。</p></template><template v-else><label>目标 · IP 或域名<input v-model="host" aria-label="目标" required/></label><label v-if="type!=='ping'">端口<input v-model="port" aria-label="端口" inputmode="numeric" required/></label><label v-if="suffix">原 URL 路径、查询与片段（保留）<input v-model="suffix" aria-label="URL 路径、查询与片段"/></label><p v-if="splitError" role="alert">{{splitError}}</p></template><div class="split"><label>检测间隔（秒）<input v-model.number="interval" aria-label="检测间隔（秒）" type="number" min="10" max="86400" :readonly="automatic"/></label><label>超时（秒）<input v-model.number="timeout" aria-label="超时（秒）" type="number" min="1" max="120" :readonly="automatic"/></label></div></fieldset><p v-if="groupName" class="membership">所属组 <strong>{{groupName}}</strong></p><p v-if="error" role="alert">{{error}}</p><footer><button type="button" class="text" @click="history">查看历史</button><span/><button type="button" :disabled="!beforeLeave()" @click="close">{{groupName?'返回监控组':'取消'}}</button><button class="primary" :disabled="busy">{{busy?'正在确认…':pending?'重新读取确认':'保存'}}</button></footer></form>
 </template>
 <dialog ref="historyDialog" class="secondary-window" aria-label="监控项历史" @cancel.prevent="closeHistory"><header><h3>{{monitor.name}} · 状态历史</h3><button @click="closeHistory">关闭历史</button></header><div class="split"><Dropdown v-model="filter" :options="[{value:'all',label:'全部'},{value:'up',label:'正常'},{value:'down',label:'异常'}]"/><button @click="history">重新读取历史</button></div><p v-if="historyError" role="alert">{{historyError}}</p><p v-if="historyLoading">正在读取…</p><ul v-else><li v-for="c in filtered" :key="c.id">{{new Date(c.ts).toLocaleString()}} · {{c.success?'正常':'异常'}} · {{c.latency_ms===null?'—':`${c.latency_ms} ms`}}</li><li v-if="!filtered.length">暂无匹配记录</li></ul></dialog>
 <dialog v-if="!automatic" ref="confirmDialog" class="secondary-window" aria-label="确认删除监控项" @cancel.prevent="confirmDialog?.close()"><h3>删除「{{monitor.name}}」？</h3><p>此监控项及其历史将删除，不能恢复。</p><footer><button @click="confirmDialog?.close()">取消</button><button @click="remove">确认删除</button></footer></dialog>
</dialog>
</template>
<style scoped>
.item-window,.secondary-window{position:fixed;inset:0;margin:auto;height:fit-content;box-sizing:border-box;width:min(560px,calc(100% - 24px));max-height:calc(100dvh - 24px);overflow:auto;border:1px solid var(--accent-dim);border-radius:12px;padding:22px;color:var(--text-hi);background:var(--bg-raised);font-size:14px}.item-window::backdrop,.secondary-window::backdrop{background:#0008}header,footer,.split{display:flex;gap:12px;align-items:center}header{margin-bottom:22px}h3{margin:0;flex:1;font-size:18px;font-weight:550}header>span{font-size:13px}.up{color:#86cbb1}.down,[role=alert]{color:#ed9299}fieldset{border:0;padding:0;margin:0;min-width:0;display:grid;gap:16px}label{display:flex;flex-direction:column;gap:7px;min-width:0;color:var(--text-lo);font-size:13px}.split{align-items:stretch}.split>label{flex:1;min-width:0}input,.readonly{box-sizing:border-box;width:100%;min-width:0;padding:10px;border-radius:6px;border:1px solid var(--accent-dim);background:var(--bg-panel);color:var(--text-hi);font:inherit}input[readonly],.readonly{color:var(--text-lo)}button{min-height:36px;border:1px solid var(--accent-dim);border-radius:6px;background:var(--bg-panel);color:var(--text-hi);padding:6px 12px;font:inherit;cursor:pointer;white-space:nowrap}button:disabled{opacity:.45;cursor:default}footer{margin-top:22px;border-top:1px solid var(--accent-dim);padding-top:16px;gap:8px}footer>span{flex:1}.primary{background:var(--accent);color:var(--bg-base)}.text{padding:0;border:0;background:none}.membership{font-size:13px;color:var(--text-lo);margin:18px 0 0}.membership strong{color:var(--text-hi);font-weight:400}.item-window :deep(.dd-btn){width:100%;min-width:0}.item-window :deep(.dd-menu){min-width:100%;box-sizing:border-box}.item-window :deep(.dd-item-label){white-space:normal}button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}li{padding:8px 0;font-size:13px;overflow-wrap:anywhere}ul{padding:0;list-style:none}@media(max-width:400px){.item-window,.secondary-window{padding:14px}header{gap:4px}h3{font-size:16px}footer{flex-wrap:wrap}.split{gap:8px}.item-window :deep(.dd-btn){padding:8px}.item-window :deep(.dd-label){font-size:12px}}
h3{min-width:0;overflow-wrap:anywhere}
</style>
