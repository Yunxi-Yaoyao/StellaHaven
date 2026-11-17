<script setup lang="ts">
import {ref,watch,onBeforeUnmount} from 'vue';
import {RouterLink} from 'vue-router';
import {listIncidents,fullTime,duration,incidentStatus,type IncidentPage} from '../../api/alerts';
import AlertIncidentDetail from './AlertIncidentDetail.vue';
import {notifications} from '../../stores/notifications';
const props=withDefaults(defineProps<{mode:'current'|'history'|'recent';nodes?:{id:number;name:string}[];revision?:number}>(),{nodes:()=>[],revision:0});
const page=ref<IncidentPage>(),loading=ref(true),error=ref(''),selected=ref<number>();
const status=ref(''),kind=ref(''),node=ref(''),since=ref(''),until=ref(''),offset=ref(0);
let controller:AbortController|undefined;
async function load(){
 controller?.abort();const c=new AbortController();controller=c;loading.value=true;error.value='';
 const q=new URLSearchParams({limit:props.mode==='history'?'30':'5',offset:String(offset.value)});
 if(props.mode==='current')q.set('status','unresolved');else if(status.value)q.set('status',status.value);
 if(props.mode==='history'){
  if(kind.value)q.set('kind',kind.value);if(node.value)q.set('node_id',node.value);
  if(since.value)q.set('since',new Date(since.value).toISOString());if(until.value)q.set('until',new Date(until.value).toISOString());
 }
 try{const p=await listIncidents(q,c.signal);if(!c.signal.aborted)page.value=p;}catch{if(!c.signal.aborted)error.value='告警加载失败，保留上次内容。请重试。';}finally{if(!c.signal.aborted)loading.value=false;}
}
function filter(){offset.value=0;void load();}
watch(()=>[props.mode,props.revision,notifications.items[0]?.id],()=>void load(),{immediate:true});
onBeforeUnmount(()=>controller?.abort());
</script>
<template><section class="incident-list" :aria-label="mode==='current'?'当前告警':mode==='recent'?'最近历史摘要':'告警记录'" data-alert-incidents>
<header><h3>{{mode==='current'?'当前告警':mode==='recent'?'最近历史摘要':'告警记录'}}</h3><button :disabled="loading" @click="load">{{loading?'读取中…':'刷新'}}</button></header>
<form v-if="mode==='history'" class="filters" @submit.prevent="filter"><label>节点<select v-model="node"><option value="">全部节点</option><option v-for="n in nodes" :key="n.id" :value="n.id">{{n.name}}</option></select></label><label>类型<select v-model="kind"><option value="">全部类型</option><option value="node_offline">节点上报中断</option><option value="monitor_down">监控异常</option><option value="wg_link">WG 链路</option><option value="node_metric">系统 / 流量指标</option></select></label><label>状态<select v-model="status"><option value="">全部状态</option><option value="unresolved">未恢复</option><option value="resolved">已恢复</option><option value="incomplete">记录不完整</option></select></label><label>开始时间 · 从<input v-model="since" type="datetime-local" /></label><label>至（不含）<input v-model="until" type="datetime-local" /></label><button>筛选</button></form>
<p v-if="error" role="alert" class="error">{{error}} <button @click="load">重试</button></p><p v-else-if="loading&&!page" role="status" class="hint">正在读取告警…</p><p v-else-if="!page?.total&&!page?.untracked?.length" class="empty">{{mode==='current'?'当前一切正常喵~':mode==='history'?'此筛选下没有告警记录':'暂无历史告警'}}</p>
<article v-for="gap in page?.untracked" :key="'gap-'+gap.rule_id"><div><strong>{{gap.label||'历史告警'}}</strong><p>{{gap.message}}</p><p class="hint">不根据当前槽位补造开始或恢复时间。</p></div></article>
<article v-for="i in page?.items" :key="i.id" :class="i.status"><div class="main"><button class="record-title" @click="selected=i.id">{{i.label||'历史告警'}}</button><span class="badge">{{incidentStatus(i)}}</span><span class="severity">{{i.severity==='critical'?'严重':'普通'}}</span><p>{{i.message}}</p><p class="hint">开始 {{i.started_at?fullTime(i.started_at):'起始记录缺失'}} · {{i.resolved_at?'恢复 '+fullTime(i.resolved_at):'未确认恢复'}} · 持续 {{duration(i.duration_seconds)}}</p><p v-if="i.status==='unresolved'&&i.observation==='unknown'" class="hint">最新观测未知 / 已过期 · 最后评估 {{fullTime(i.evaluated_at)}}</p></div><button @click="selected=i.id">详情</button></article>
<footer v-if="page&&page.total>0"><span>共 {{page.total}} 次告警</span><template v-if="mode==='history'"><button :disabled="offset===0||loading" @click="offset=Math.max(0,offset-30);load()">上一页</button><span>{{Math.floor(offset/30)+1}}</span><button :disabled="offset+30>=page.total||loading" @click="offset+=30;load()">下一页</button></template><RouterLink v-else :to="{path:'/status',query:{view:'alerts',alertTab:'history'}}">查看全部记录</RouterLink></footer>
<AlertIncidentDetail v-if="selected" :id="selected" @close="selected=undefined" />
</section></template>
<style scoped>
.incident-list{min-width:0;margin:0 0 24px;font-size:14px;color:var(--text-hi,#ede8e1)}header,footer{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}h3{font-size:17px;font-weight:550;margin:0}button,select,input{font:inherit;min-height:40px;max-width:100%;box-sizing:border-box;padding:7px 11px;border-radius:7px;border:1px solid #ffffff25;background:var(--bg-panel,#252321);color:inherit}button{cursor:pointer}button:disabled{opacity:.5;cursor:default}button:hover:not(:disabled){border-color:#9bcbb680}button:focus-visible,select:focus-visible,input:focus-visible,a:focus-visible{outline:2px solid #9bcbb6;outline-offset:2px}.empty{padding:18px 0;color:#a9d2bf}.hint,footer{font-size:13px;color:var(--text-lo,#bdb6ac);line-height:1.7}article{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:16px;margin-top:10px;background:var(--bg-panel,#252321);border:1px solid #ffffff14;border-left:3px solid #d4a169;border-radius:10px}article.resolved{border-left-color:#8cbba4}.main{min-width:0;overflow-wrap:anywhere}.record-title{padding:0;background:none;border:none;min-height:36px;text-align:left;font-size:15px;font-weight:550;color:var(--text-hi,#ede8e1)}.badge{margin:0 10px;color:#e6ba8a;font-size:12px}.resolved .badge{color:#a9d2bf}.severity{color:var(--text-lo,#bdb6ac);font-size:12px}p{margin:4px 0}.error{color:#ffb8a7}.filters{display:flex;flex-wrap:wrap;align-items:end;gap:12px;margin:16px 0}.filters label{display:grid;gap:5px;min-width:0;flex:1 1 150px;font-size:13px}.filters input,.filters select{width:100%;min-width:0}footer{justify-content:flex-end;margin-top:12px}footer>span:first-child{margin-right:auto}a{color:#b2dfce}@media(max-width:600px){article{padding:12px;align-items:start;flex-wrap:wrap}button,input,select{min-height:44px}.filters label{flex-basis:100%}}
</style>
