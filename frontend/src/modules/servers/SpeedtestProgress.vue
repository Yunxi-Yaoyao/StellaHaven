<script lang="ts">
// A read-only UI guard, not a substitute for result admission on the server.
// Keep historical speedtest-go/Ookla and normalized/native iperf shapes readable.
export function throughputResultError(task: {status: string; mode: string; result_json?: unknown}): string {
  if (!['done', 'failed'].includes(task.status)) return '';
  const object = (value: unknown): Record<string, any> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {};
  const r = object(task.result_json);
  if (r.error) return typeof r.error === 'string' ? r.error : '测试结果包含错误，请重测';
  if (task.status === 'failed') return '测试失败，请重试';
  if (r.suspicious) return '数据异常（iperf3 统计虚高，请重测）';
  const number = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value >= 0;
  let rates: unknown[], optional: unknown[];
  if (task.mode === 'speedtest') {
    const srv = object(Array.isArray(r.servers) ? r.servers[0] : null);
    const download = object(r.download), upload = object(r.upload), ping = object(r.ping);
    rates = [srv.dl_speed, srv.ul_speed, download.bandwidth, upload.bandwidth];
    optional = [srv.latency, srv.jitter, ping.latency, ping.jitter];
  } else {
    const end = object(r.end);
    rates = [r.avg_bitrate, r.send_avg_bitrate, object(end.sum_received).bits_per_second, object(end.sum_sent).bits_per_second, object(r.sum_sent).bits_per_second];
    optional = [r.peak_bitrate, r.total_bytes, r.lost_pct, r.jitter_ms, r.retransmits];
  }
  if (!rates.some(number) || [...rates, ...optional].some(value => value != null && !number(value))) return '结果无效或缺少当前测速模式的有效速率，请重测';
  return '';
}
</script>
<script setup lang="ts">
import {computed} from 'vue';
import type {IperfTask} from '../../api/servers';
const props=defineProps<{task:IperfTask;points:NonNullable<IperfTask['progress_json']>;metrics:{label:string;value:string}[]}>();
const note=computed(()=>[...props.points].reverse().find(p=>p.note)?.note);
const running=computed(()=>['pending','running'].includes(props.task.status));
const rates=computed(()=>props.metrics.filter(m=>['下载','上传'].includes(m.label)).map(m=>({...m,rate:Number.parseFloat(m.value)})).filter(m=>Number.isFinite(m.rate)));
const maximum=computed(()=>Math.max(1,...rates.value.map(m=>m.rate)));
const resultError=computed(()=>throughputResultError(props.task));
</script>
<template>
  <div class="speedtest-progress">
    <template v-if="running">
      <div class="st-stage" role="status">{{ task.status === 'pending' ? '等待所选节点领取任务喵~' : note || '测速运行中，等待 CLI 返回结果喵~' }}</div>
      <div class="st-running" role="progressbar" aria-label="测速执行中，完成时间未知"><span /></div>
      <p class="st-explain">当前工具仅返回最终速率，不绘制虚构的实时曲线喵~</p>
    </template>
    <p v-else-if="resultError" class="st-explain" role="alert">{{ resultError }}喵~</p>
    <template v-else-if="task.status === 'done'">
      <div class="st-rates" aria-label="最终下载与上传速率对比">
        <div v-for="r in rates" :key="r.label" class="st-rate"><span>{{ r.label }}</span><div class="st-track"><span :class="{upload:r.label==='上传'}" :style="{width:`${r.rate / maximum * 100}%`}" /></div><b>{{ r.value }}</b></div>
      </div>
      <dl class="st-results"><div v-for="m in metrics.filter(m=>!['下载','上传'].includes(m.label))" :key="m.label"><dt>{{ m.label }}</dt><dd>{{ m.value }}</dd></div></dl>
      <p v-if="!metrics.length" class="st-explain">任务已结束，但没有可显示的有效结果；请重测喵~</p>
      <p v-if="task.result_json?.via_proxy" class="st-explain">本次结果经代理通道，非节点直连带宽喵~</p>
    </template>
  </div>
</template>
<style scoped>
.speedtest-progress{padding:12px 0 4px;min-width:0}.st-stage{font-size:14px;color:var(--text-hi);line-height:1.6;overflow-wrap:anywhere}.st-explain{font-size:13px;color:var(--text-lo);margin:12px 0 4px;line-height:1.6}.st-running{height:3px;margin-top:14px;border-radius:3px;overflow:hidden;background:var(--bg-panel)}.st-running span{display:block;height:100%;width:28%;background:var(--accent);animation:st-sweep 1.8s ease-in-out infinite alternate}@keyframes st-sweep{to{transform:translateX(250%)}}.st-rates{display:grid;gap:12px;margin:4px 0 18px}.st-rate{display:grid;grid-template-columns:32px minmax(20px,1fr) 110px;align-items:center;gap:12px;font-size:14px}.st-rate b{text-align:right;font-variant-numeric:tabular-nums;font-weight:500}.st-track{height:8px;background:var(--bg-panel);border-radius:4px;overflow:hidden}.st-track span{display:block;height:100%;background:var(--pink);border-radius:4px}.st-track .upload{background:#8cccd5}.st-results{display:flex;flex-wrap:wrap;gap:12px 30px;margin:0}.st-results div{min-width:90px;max-width:100%}.st-results dt{font-size:12px;color:var(--text-lo);margin-bottom:5px}.st-results dd{font-size:15px;font-weight:500;color:var(--text-hi);margin:0;overflow-wrap:anywhere}@media(prefers-reduced-motion:reduce){.st-running span{animation:none;width:100%;opacity:.6}}@media(max-width:600px){.st-rate{gap:8px;grid-template-columns:30px minmax(20px,1fr) 100px}.st-results{gap:14px 20px}}
</style>
