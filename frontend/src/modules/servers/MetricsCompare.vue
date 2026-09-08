<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { api } from '../../api/client';
const props=defineProps<{nodeId:number;nodeName:string}>();
const emit=defineEmits<{close:[]}>();
interface Config {enabled:boolean;url:string|null;nodes:Record<string,{job:string;instance:string}>}
const config=ref<Config>({enabled:false,url:null,nodes:{}});
const url=ref(''),job=ref(''),instance=ref('');
const loading=ref(true),busy=ref(false),notice=ref(''),error=ref('');
const result=ref<any>(null);
const lifecycle=new AbortController();
onUnmounted(()=>lifecycle.abort());
const snapshot=computed(()=>result.value?.prometheus?.snapshot);
const legacy=computed(()=>result.value?.legacy?.latestSys);
const spacing=computed(()=>{
 const xs=(result.value?.prometheus?.sampleSpacing?.spacingSeconds||[]) as number[];
 if(!xs.length)return '暂无有效原始样本';
 const low=Math.min(...xs),high=Math.max(...xs);
 return Math.abs(high-low)<.05?`${low.toFixed(1).replace(/\.0$/,'')} 秒`:`${low.toFixed(1)}–${high.toFixed(1)} 秒`;
});
const rootDisk=computed(()=>snapshot.value?.filesystems?.find((f:any)=>f.mountpoint==='/')?.usedPct?.value);
const percent=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)?`${v.toFixed(1)}%`:'无样本';
const time=(ts:unknown)=>typeof ts==='number'?new Date(ts*1000).toLocaleString('zh-CN'):'无采样时间';
function detail(e:any){return typeof e?.detail==='string'?e.detail:e?.message||'请求失败';}
onMounted(async()=>{
 try{config.value=await api<Config>('/config/prometheus',{signal:lifecycle.signal});url.value=config.value.url||'';const t=config.value.nodes[String(props.nodeId)];job.value=t?.job||'';instance.value=t?.instance||'';}
 catch(e){if(!lifecycle.signal.aborted)error.value=detail(e);}
 finally{if(!lifecycle.signal.aborted)loading.value=false;}
});
async function save(){
 if(busy.value)return;busy.value=true;error.value='';notice.value='';
 try{
  const body={enabled:true,url:url.value.trim(),nodes:{...config.value.nodes,[String(props.nodeId)]:{job:job.value.trim(),instance:instance.value.trim()}}};
  config.value=await api<Config>('/config/prometheus',{method:'PUT',body:JSON.stringify(body),signal:lifecycle.signal});
  notice.value='对账配置已保存喵~';result.value=null;
 }catch(e){if(!lifecycle.signal.aborted)error.value=detail(e);}
 finally{if(!lifecycle.signal.aborted)busy.value=false;}
}
async function compare(){
 if(busy.value)return;busy.value=true;error.value='';notice.value='';
 try{result.value=await api(`/nodes/${props.nodeId}/metrics-comparison`,{signal:AbortSignal.any([lifecycle.signal,AbortSignal.timeout(60000)])});}
 catch(e){if(!lifecycle.signal.aborted)error.value=detail(e);}
 finally{if(!lifecycle.signal.aborted)busy.value=false;}
}
</script>
<template>
 <Teleport to="body">
  <div class="mc-mask" @click.self="emit('close')">
   <section class="mc-panel" role="dialog" aria-modal="true" aria-label="指标对账">
    <header><h2>指标对账 · {{ nodeName }}</h2><button @click="emit('close')">关闭</button></header>
    <p>只读比较 agent 与 Prometheus；保存配置不会切换图表或停止旧采集。</p>
    <p v-if="loading" role="status">读取配置中…</p>
    <template v-else>
     <div class="mc-fields">
      <label class="mc-url">Prometheus 地址<input v-model="url" type="url" placeholder="https://monitor.example:9090" /></label>
      <label>Job<input v-model="job" placeholder="node-exporter job" /></label>
      <label>Instance<input v-model="instance" placeholder="服务器:9100" /></label>
     </div>
     <div class="mc-actions"><button :disabled="busy||!url||!job||!instance" @click="save">保存对账配置</button><button :disabled="busy||!config.enabled||!config.nodes[String(nodeId)]" @click="compare">{{busy?'处理中…':'开始对账'}}</button></div>
    </template>
    <p v-if="notice" role="status">{{notice}}</p><p v-if="error" class="mc-error" role="alert">{{error}}</p>
    <template v-if="result">
     <p class="mc-warning">{{result.equivalence?.status==='not_equivalent'?'尚未对齐，不能替换现有数据源':'对账结果待确认'}} · 抓取状态：{{snapshot?.freshness}}</p>
     <div class="mc-cadence">Prometheus 实际抓取：{{spacing}}；现有网卡采样：{{result.legacy.trafficIntervalSeconds}} 秒；系统采样：{{result.legacy.expectedSysIntervalSeconds}} 秒</div>
     <table><thead><tr><th>指标</th><th>现有 agent</th><th>Prometheus</th></tr></thead><tbody>
      <tr><td>CPU</td><td>{{percent(legacy?.cpuPct)}}</td><td>{{percent(snapshot?.cpuPct?.value)}}</td></tr>
      <tr><td>内存</td><td>{{percent(legacy?.memoryPct)}}</td><td>{{percent(snapshot?.memoryPct?.value)}}</td></tr>
      <tr><td>根文件系统已用</td><td>{{percent(legacy?.diskPct)}}</td><td>{{percent(rootDisk)}}</td></tr>
      <tr><td>采样时间</td><td>{{time(legacy?.timestamp)}}</td><td>{{time(snapshot?.scrapeUp?.sampleTimestamp)}}</td></tr>
     </tbody></table>
     <p>时间窗不同会产生数值差异；Prometheus 速率采用 1 分钟窗口，5 秒查询步长不代表 5 秒原始采样。</p>
     <details v-if="snapshot?.networks?.length"><summary>网卡指标（{{snapshot.networks.length}}）</summary><table><thead><tr><th>设备</th><th>接收 B/s</th><th>发送 B/s</th></tr></thead><tbody><tr v-for="n in snapshot.networks" :key="n.device"><td>{{n.device}}</td><td>{{n.receiveBytesPerSecond?.value ?? '无样本'}}</td><td>{{n.transmitBytesPerSecond?.value ?? '无样本'}}</td></tr></tbody></table></details>
    </template>
   </section>
  </div>
 </Teleport>
</template>
<style scoped>
.mc-mask{position:fixed;inset:0;background:#0009;z-index:160;display:grid;place-items:center;padding:20px}.mc-panel{width:min(760px,100%);max-height:90vh;overflow:auto;background:var(--bg-panel,#171b24);color:var(--text-hi,#eee);padding:20px;border:1px solid var(--accent-dim,#444);border-radius:var(--radius,10px)}header{display:flex;align-items:center;justify-content:space-between}h2{font-size:19px;margin:0}p,.mc-cadence{font-size:12px;line-height:1.7;color:var(--text-lo,#aab)}.mc-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}.mc-url{grid-column:1/-1}label{display:grid;gap:6px;font-size:12px}input{padding:8px;border:1px solid var(--accent-dim,#444);border-radius:5px;background:var(--bg-base,#151820);color:inherit;min-width:0}.mc-actions{display:flex;gap:10px;margin-top:14px}button{padding:6px 12px;color:var(--accent,#c9d4e8);background:var(--bg-raised,#262c38);border:1px solid var(--accent-dim,#444);border-radius:5px;cursor:pointer}button:disabled{opacity:.45;cursor:default}table{width:100%;border-collapse:collapse;font-size:12px;margin:12px 0}td,th{text-align:left;padding:8px;border-bottom:1px solid var(--bg-raised,#333)}.mc-warning{color:#e3b96b}.mc-error{color:var(--pink,#f99)}summary{cursor:pointer;font-size:12px}
</style>
