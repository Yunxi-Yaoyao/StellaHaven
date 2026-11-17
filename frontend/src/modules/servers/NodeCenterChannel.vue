<script setup lang="ts">
import {computed} from 'vue';
import type {Node} from '../../api/servers';
const props=defineProps<{node:Node;now:number}>();
const report=computed(()=>props.node.control_channel?.report);
const reasons:Record<string,string>={complete:'已采样',dns_error:'域名暂不能解析',dns_timeout:'域名解析超时',outside_scope:'解析结果不在此节点批准的目标范围',too_many_ips:'解析地址超过本轮上限，未探测',budget_exceeded:'本周期预算已用完，结果不完整',unavailable:'ICMP 暂不可用，未改用 TCP'};
function stale(ts:string){const age=props.now-Date.parse(ts);return props.node.status!=='online'||!Number.isFinite(age)||age>180000||age< -300000;}
const pending=computed(()=>props.node.status!=='online'?'节点离线，等待上线':!props.node.components?.monitoring?.ready?'等待 Agent 提供 ICMP 能力':'等待首个合法 ICMP 样本');
</script>
<template>
 <details id="node-center-channel" class="center-channel">
  <summary>中心连接 <span v-if="report">· 汇报事务 {{report.duration_ms==null?'未测得':report.duration_ms.toFixed(2)+' ms'}}{{stale(report.sampled_at)?' · 已过期':''}}</span><span v-else>· 尚无汇报耗时</span></summary>
  <p v-if="report">上一笔完成的汇报事务 · {{report.origin}} · {{report.status==='ok'?'成功':'失败'}}<template v-if="report.http_status"> · HTTP {{report.http_status}}</template><template v-if="report.error"> · {{report.error}}</template> · {{report.sampled_at}}</p>
  <p v-else>Agent 尚未提供真实汇报耗时。</p>
  <p>汇报事务耗时不作为 ICMP 延迟或父监控健康；ICMP 结果见服务监控子项。</p>
  <p v-for="sample in node.control_channel?.icmp??[]" :key="sample.entry_id">ICMP · {{sample.entry_id==='public'?'默认入口':'其他入口'}} · {{reasons[sample.status]??'未知'}} · {{stale(sample.sampled_at)?'已过期':'最近上报'}} · {{sample.sampled_at}}</p>
  <p v-if="!node.control_channel?.icmp?.length">{{pending}}</p>
 </details>
</template>
<style scoped>
.center-channel{min-width:0;border-bottom:1px solid var(--control-border);padding:10px 0;margin-bottom:16px;color:var(--text-hi);font-size:14px}summary{cursor:pointer;min-height:28px;line-height:1.8}summary span,p{color:var(--text-lo)}p{line-height:1.7;overflow-wrap:anywhere;margin:8px 0}summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
</style>
