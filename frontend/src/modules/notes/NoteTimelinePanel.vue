<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount,onDeactivated,watch} from 'vue';
import {api} from '../../api/client';
import {readNoteNode,setNoteNode,nodeTimeline,type Doc,type SearchItem} from '../../api/notes';
import {useRouter} from 'vue-router';
import './notesModal.css';
const props=defineProps<{doc:Doc}>();const emit=defineEmits<{close:[];history:[]}>();const router=useRouter();
const nodes=ref<{id:number;name:string;status:string}[]>([]),selected=ref(''),items=ref<SearchItem[]>([]),error=ref(''),busy=ref(false),loading=ref(true),more=ref(false),unknownHistory=ref(false);
// An unread association is not the known, explicit "不关联" choice.
const known=ref(false),readRetry=ref(false);
let controller=new AbortController();
function invalidate(){controller.abort();known.value=false;busy.value=false;items.value=[];more.value=false;unknownHistory.value=false;}
onBeforeUnmount(invalidate);onDeactivated(invalidate);
watch(()=>[props.doc.id,props.doc.workspace_id],()=>{invalidate();controller=new AbortController();void load();},{flush:'sync'});
async function refresh(signal:AbortSignal){
  items.value=[];more.value=false;unknownHistory.value=false;
  if(!selected.value)return;
  const r=await nodeTimeline(Number(selected.value),props.doc.workspace_id,signal);
  if(!signal.aborted){items.value=r.items;more.value=r.has_more;unknownHistory.value=!!r.unknown_notes_present;}
}
async function load(){
  if(controller.signal.aborted||busy.value)return;
  const signal=controller.signal;
  loading.value=true;known.value=false;error.value='';readRetry.value=false;
  try{
    const [n,association]=await Promise.all([api<typeof nodes.value>('/nodes/',{signal}),readNoteNode(props.doc.id,signal)]);
    if(signal.aborted)return;
    nodes.value=n;selected.value=association.node_id===null?'':String(association.node_id);
    await refresh(signal);
    if(!signal.aborted)known.value=true;
  }catch{if(!signal.aborted){error.value='关联时间线加载失败，请重试';readRetry.value=true;}}
  finally{if(!signal.aborted)loading.value=false;}
}
onMounted(load);
async function save(){
  if(busy.value||loading.value||!known.value||controller.signal.aborted)return;
  const signal=controller.signal;
  busy.value=true;error.value='';
  try{
    await setNoteNode(props.doc.id,selected.value?Number(selected.value):null,signal);
    if(signal.aborted)return;
  }catch{
    if(!signal.aborted){error.value='关联保存失败，未更新；请重试';busy.value=false;}
    return;
  }
  // The write is acknowledged. Any subsequent recovery is GET-only.
  busy.value=false;await load();
}
const labels:Record<string,string>={node_status:'节点状态事件',alert:'告警事件',mtr_task:'MTR 任务创建',iperf_task:'打流任务创建',component_task:'组件任务创建',command_task:'命令任务创建',net_task:'网络任务创建',note_updated:'笔记最近保存'};
function open(item:SearchItem){emit('close');void router.push(item.path);}
</script>
<template><Teleport to="body"><div class="notes-modal-mask" @click.self="!busy&&emit('close')"><section class="notes-modal timeline-modal" role="dialog" aria-modal="true" aria-label="关联时间线">
<header><h2>关联时间线</h2><button :disabled="busy" aria-label="关闭关联时间线" @click="emit('close')">×</button></header>
<p>选择节点将本笔记关联到已有状态、告警和任务记录。任务时间表示创建时间，状态是当前值；笔记仅展示最近保存，不虚构历史。</p>
<div class="association"><label>关联节点<select aria-label="关联节点" v-model="selected" :disabled="busy||loading||!known"><option value="">{{ known ? '不关联' : '关联尚未读取' }}</option><option v-for="n in nodes" :key="n.id" :value="String(n.id)">{{n.name}}</option></select></label><button :disabled="busy||loading||!known" @click="save">保存关联</button></div>
<p v-if="error" role="alert">{{error}} <button v-if="readRetry" :disabled="busy||loading" @click="load">重试读取关联</button></p><p v-if="loading">正在载入…</p><p v-else-if="known&&!items.length">暂无记录；不会创建探测或发送任务。</p>
<p v-if="unknownHistory">部分笔记的历史保存时间未知，未参与排序；可在当前工作区笔记列表或搜索中查看。<button @click="emit('history');emit('close')">查看笔记列表</button></p>
<ol><li v-for="item in items" :key="item.kind+item.id"><small>{{item.ts?new Date(item.ts).toLocaleString():''}} · {{labels[item.kind]||item.kind}}</small><button @click="open(item)">{{item.label}}</button><span v-if="item.state">{{item.state}}</span></li></ol><p v-if="more">只显示最近 100 条记录。</p>
</section></div></Teleport></template>
<style scoped>.association{display:flex;gap:12px;align-items:end;flex-wrap:wrap}.association label{display:grid;gap:6px;flex:1;font-size:13px}.association select{background:var(--bg-raised);color:var(--text-hi);border:1px solid var(--accent-dim);padding:8px;border-radius:var(--radius-sm)}.timeline-modal ol{list-style:none;padding:0}.timeline-modal li{padding:12px 0;border-bottom:1px solid var(--bg-raised);display:flex;gap:8px;align-items:center;flex-wrap:wrap}.timeline-modal small{color:var(--text-faint);width:100%}.timeline-modal li button{flex:1;text-align:left}.timeline-modal li span{font-size:12px;color:var(--text-lo)}</style>
