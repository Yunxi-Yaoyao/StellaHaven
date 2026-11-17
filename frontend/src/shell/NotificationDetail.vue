<script setup lang="ts">
import {ref,watch,onBeforeUnmount} from 'vue';
import {RouterLink} from 'vue-router';
import DetailDialog from './DetailDialog.vue';
import type {NotificationOrigin} from './notificationMotion';
import AlertIncidentDetail from '../modules/servers/AlertIncidentDetail.vue';
import {getNotification,fullTime,type NotificationDetail as Detail} from '../api/alerts';
import {notificationActions} from '../stores/notifications';
const props=defineProps<{id:number;origin?:NotificationOrigin}>();defineEmits<{close:[]}>();
const note=ref<Detail>(),error=ref(''),readError=ref(''),loading=ref(true),incident=ref<number>();
let controller:AbortController|undefined;
async function read(id=props.id,owner=controller){try{await notificationActions.readOne(id);if(owner===controller&&!owner?.signal.aborted)readError.value='';}catch{if(owner===controller&&!owner?.signal.aborted)readError.value='标记已读失败，内容仍可查看。';}}
async function load(){controller?.abort();const c=new AbortController(),id=props.id;controller=c;loading.value=true;error.value='';readError.value='';note.value=undefined;incident.value=undefined;try{const n=await getNotification(id,c.signal);if(c.signal.aborted)return;note.value=n;void read(id,c);}catch{if(!c.signal.aborted)error.value='通知详情加载失败，请重试';}finally{if(!c.signal.aborted)loading.value=false;}}
watch(()=>props.id,load,{immediate:true});onBeforeUnmount(()=>controller?.abort());
const kinds:Record<string,string>={alert:'告警通知',alert_resolved:'告警恢复',backup_result:'备份结果',manual_test_result:'手动测试结果',import_result:'导入结果',export_result:'导出结果'};
</script>
<template>
 <DetailDialog title="通知详情" :origin="origin" @close="$emit('close')">
  <div data-notification-detail :aria-busy="loading">
   <div v-if="loading" class="phase" role="status"><span class="loading-mark" aria-hidden="true" />正在读取通知…</div>
   <div v-else-if="error" class="phase error" role="alert"><p>{{error}}</p><button @click="load">重试</button></div>
   <template v-else-if="note">
    <div class="meta"><span>{{kinds[note.kind]||'Stella 通知'}}</span><span class="severity" :data-level="note.severity">{{note.severity==='critical'?'严重':note.severity==='warning'?'需关注':'信息'}}</span></div>
    <h3>{{note.title}}</h3>
    <p class="sent">发送时间 <time :datetime="note.ts">{{fullTime(note.ts)}}</time></p>
    <p class="body"><template v-for="entity in note.entities" :key="entity.id"><RouterLink v-if="entity.available" class="entity" :to="`/status/${entity.id}`">{{entity.label}}</RouterLink><span v-else class="entity missing" title="节点已移除或不可用">{{entity.label}}（不可用）</span> </template>{{note.body}}</p>
    <p v-if="note.context?.incident_id" class="foot"><button class="inline" @click="incident=note.context!.incident_id!">查看对应告警详情</button></p>
    <p v-if="note.kind.startsWith('alert')" class="hint">发送时的通知快照 · 已读不代表告警恢复，当前状态请查看告警详情。</p>
    <p v-if="readError" class="read-error" role="alert">{{readError}} <button @click="read()">重试标记</button></p>
   </template>
  </div>
  <AlertIncidentDetail v-if="incident" :id="incident" @close="incident=undefined" />
 </DetailDialog>
</template>
<style scoped>
h3{font-size:21px;line-height:1.5;font-weight:550;margin:10px 0 6px;color:var(--text-hi,#ede8e1)}.meta{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--text-lo,#bdb6ac)}.severity{font-size:12px;line-height:1.5;padding:2px 7px;border-radius:5px;background:#ffffff09;border:1px solid #ffffff14}.severity[data-level=warning]{color:#edc585;background:#d9a03f12;border-color:#d9a03f30}.severity[data-level=critical]{color:#f3aaa5;background:#e5605c12;border-color:#e5605c30}.sent{display:flex;gap:8px;flex-wrap:wrap;color:var(--text-lo,#bdb6ac);font-size:12px;margin:0}.sent time{font-variant-numeric:tabular-nums}.body{white-space:pre-wrap;font-size:15px;line-height:1.85;margin:18px 0;color:var(--text-hi,#ede8e1)}.entity{display:inline;padding:2px 6px;border-radius:5px;color:#b2dfce;background:#9bcbb61a;text-decoration:none;box-decoration-break:clone}.entity:hover{text-decoration:underline}.missing{color:#c1bbb2;background:#ffffff0a}.foot{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:14px 0}.hint{border-top:1px solid #ffffff14;padding-top:12px;margin:16px 0 0;color:var(--text-lo,#bdb6ac);font-size:12px;line-height:1.7}.phase{padding:16px 0;display:flex;align-items:center;gap:10px;color:var(--text-lo,#bdb6ac)}.error{display:block}.error p{margin:0 0 10px}.loading-mark{width:12px;height:12px;border:2px solid #ffffff25;border-top-color:#9bcbb6;border-radius:50%;animation:spin .8s linear infinite}.read-error{font-size:13px;color:#edc585}a{color:#b2dfce}button{font:inherit;color:inherit;border:1px solid #ffffff30;background:#ffffff08;padding:7px 11px;border-radius:7px;min-height:40px;cursor:pointer}.inline{color:#b2dfce}a:focus-visible,button:focus-visible{outline:2px solid #9bcbb6;outline-offset:3px}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:600px){h3{font-size:20px}button{min-height:44px}}@media(prefers-reduced-motion:reduce){.loading-mark{animation:none}}
</style>
