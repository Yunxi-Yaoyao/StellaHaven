<script setup lang="ts">
import {ref,computed,watch,onActivated,onDeactivated,onBeforeUnmount} from 'vue';
import {auth,isAdmin} from '../home/auth';
import {listNodes,type Node} from '../../api/servers';
import {getEntryMonitoring,type ManagementEntry,type EntrySample} from '../../api/nodeMonitoringPolicy';
import HelpHint from './HelpHint.vue';
const entries=ref<ManagementEntry[]>([]),nodes=ref<Node[]>([]),busy=ref(false),message=ref('');
const active=ref(true),now=ref(Date.now());
const allowed=computed(()=>active.value&&isAdmin.value&&!auth.suspended&&!auth.sessionClosing);
let epoch=0;
const current=(ticket:number)=>allowed.value&&ticket===epoch;

async function load(){
 if(!allowed.value||busy.value)return;
 const ticket=++epoch;busy.value=true;
 try{const [definitions,items]=await Promise.all([getEntryMonitoring(),listNodes()]);if(current(ticket)){entries.value=definitions;nodes.value=items;message.value='';now.value=Date.now();}}
 catch(error){if(current(ticket)){const status=(error as {status?:number}).status;message.value=status===401?'登录已失效，请重新登录':status===403?'当前会话无权读取监控状态':'监控状态读取失败，请重试';}}
 finally{if(current(ticket))busy.value=false;}
}
function sample(node:Node,entry:ManagementEntry){return node.control_channel?.icmp.find(s=>s.entry_id===entry.entry_id&&s.version===entry.version);}
function stale(node:Node,ts:string,limit=180000){const age=now.value-Date.parse(ts);return node.status!=='online'||!Number.isFinite(age)||age>limit||age < -300000;}
const reasons:Record<EntrySample['status'],string>={complete:'已采样',dns_error:'域名暂不能解析',dns_timeout:'域名解析超时',outside_scope:'解析结果不在此节点批准的目标范围',too_many_ips:'解析地址超过本轮上限，未探测',budget_exceeded:'本周期预算已用完，结果不完整',unavailable:'ICMP 暂不可用，未改用 TCP'};
function pending(node:Node){if(node.status!=='online')return '节点离线，等待上线';const cap=node.components?.monitoring;return !cap||!cap.ready?'等待 Agent 提供监控能力':!cap.types?.includes('ping')?'Agent 当前不具 ICMP 能力':'等待首个样本';}
function ms(value:number|null|undefined){return value==null?'未测得':value.toFixed(2)+' ms';}
function label(id:string|null){return id==='public'?'默认入口':id==='private'?'其他入口':'未匹配已配置入口';}
const timer=setInterval(()=>{now.value=Date.now();if(allowed.value)void load();},15000);
onBeforeUnmount(()=>{clearInterval(timer);active.value=false;epoch++;});
onDeactivated(()=>{active.value=false;});
onActivated(()=>{active.value=true;});
watch([allowed,()=>auth.me?.id,()=>auth.sessionGeneration,()=>auth.requestEpoch],()=>{epoch++;busy.value=false;entries.value=[];nodes.value=[];if(allowed.value)void load();},{immediate:true,flush:'sync'});
</script>
<template><section class="node-monitoring" aria-label="节点到管理入口监控">
 <h2>节点到管理入口<HelpHint label="自动监控说明">由各节点 Agent 在自己的网络解析已部署的管理入口，固定每 60 秒进行有界 ICMP 探测。当前兼容默认和另一条入口，不改变汇报地址、不自动切换。域名指向 CDN 时，ICMP 测到的是解析出的边缘 IP，不代表宿主机延迟。</HelpHint></h2>
 <template v-if="allowed">
  <p>无需设置探测源或启用开关。ICMP 与正常汇报事务分别记录；未提供、不可用或过期均不算健康。</p>
  <p v-for="entry in entries" :key="entry.entry_id">{{label(entry.entry_id)}} · {{entry.origin}}</p>
  <article v-for="node in nodes" :key="node.id">
   <h3><RouterLink :to="{name:'status-node',params:{id:node.id}}">{{node.name}}</RouterLink></h3>
   <div v-for="entry in entries" :key="entry.entry_id" class="entry-result">
    <strong>ICMP · {{label(entry.entry_id)}} · {{entry.hostname}}</strong>
    <template v-if="sample(node,entry)">
     <p>{{reasons[sample(node,entry)!.status]}} · {{stale(node,sample(node,entry)!.sampled_at)?'已过期（不代表当前健康）':'最近采样'}} · {{sample(node,entry)!.sampled_at}}</p>
     <p v-for="ip in sample(node,entry)!.results" :key="ip.ip"><code>{{ip.ip}}</code> · IPv{{ip.family}} · {{ip.status==='up'?'收到响应':ip.status==='down'?'未收到响应':'未测得'}} · {{ms(ip.latency_ms)}} · 丢包 {{ip.loss_pct==null?'未知':ip.loss_pct+'%'}}</p>
    </template><p v-else>{{pending(node)}}</p>
   </div>
   <div class="report-result"><strong>正常汇报事务 · 上一笔完成请求</strong>
    <template v-if="node.control_channel?.report"><p>{{label(node.control_channel.report.entry_id)}} · {{node.control_channel.report.origin}} · {{ms(node.control_channel.report.duration_ms)}} · {{node.control_channel.report.status==='ok'?'成功':'失败'}}<template v-if="node.control_channel.report.http_status"> · HTTP {{node.control_channel.report.http_status}}</template><template v-if="node.control_channel.report.error"> · {{node.control_channel.report.error}}</template></p><p>{{stale(node,node.control_channel.report.sampled_at,120000)?'已过期（不代表当前健康）':'最近完成'}} · {{node.control_channel.report.sampled_at}}</p></template>
    <p v-else>Agent 尚未提供真实汇报耗时；不是 HTTP 健康探针。</p>
   </div>
  </article>
  <p v-if="!nodes.length&&!busy">暂无节点。</p><button class="st-button" :disabled="busy" @click="load">{{busy?'读取中…':'重新读取结果'}}</button>
  <p>手动监控与旧版节点可达性历史保留，未收编到此机制。<RouterLink to="/status">查看节点与监控历史</RouterLink></p>
 </template>
 <div v-else><p>请登录用户账号后查看监控状态。</p></div>
 <p v-if="message" role="alert">{{message}}</p>
</section></template>
<style scoped>
.node-monitoring{min-width:0;color:var(--text-hi)}h2{font-size:16px;display:flex;align-items:center;gap:4px}h3{font-size:15px;margin:0 0 12px}p{font-size:14px;line-height:1.7;color:var(--text-lo);overflow-wrap:anywhere;margin:8px 0}article{border:1px solid var(--control-border);border-radius:10px;padding:16px;margin:14px 0;min-width:0}strong{font-size:14px;font-weight:500;overflow-wrap:anywhere}.entry-result{margin-bottom:12px}.report-result{border-top:1px solid var(--control-border);padding-top:12px}a{color:var(--text-hi);text-decoration:underline;text-underline-offset:3px}code{overflow-wrap:anywhere}button{min-height:38px}@media(max-width:600px){article{padding:12px}button{min-height:44px}}
</style>
