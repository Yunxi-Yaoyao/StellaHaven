<script setup lang="ts">
import {computed,nextTick,onMounted,onBeforeUnmount,ref,watch,type Ref} from 'vue';
import {DIRECTIONS,METRICS,REASONS,listMetricRules,previewMetric,saveMetric,type Metric,type Direction,type MetricCondition,type MetricIntent,type MetricRule,type MetricPreview} from '../../api/alertMetrics';
import {deleteRule} from '../../api/alerts';
import {toBase,fromBase} from './alertMetricUnits';
import {browserZone,localTime,localCandidates,resolveLocal,sameLocal,utcInstant,validWindow,type OriginalEndpoint} from './alertMetricTime';
const props=defineProps<{nodes:{id:number;name:string;interfaces?:Record<string,unknown>|null}[];embedded?:boolean}>();
const emit=defineEmits<{changed:[]}>();
type ListedMetricRule=Omit<MetricRule,'condition'|'node_id'|'severity'> & {condition:MetricCondition|null;node_id:number|null;severity:MetricRule['severity']|null;projection?:{state:'incomplete';invalid_fields:string[]}};
const rules=ref<ListedMetricRule[]>([]),editing=ref(false),busy=ref(false),error=ref(''),notice=ref('');
const id=ref<number>(),revision=ref<number>();
const nodeId=ref(0),metric=ref<Metric>('network.rate'),direction=ref<Direction>('out'),iface=ref('');
const label=ref(''),threshold=ref('80000000'),unit=ref('Mbps'),amount=ref('80');
const mode=ref<'independent'|'shared'>('independent'),cin=ref(''),cout=ref(''),shared=ref('');
const start=ref(''),end=ref(''),zone=ref(browserZone());
const originalStart=ref<OriginalEndpoint>(),originalEnd=ref<OriginalEndpoint>();
const startChoice=ref(''),endChoice=ref('');
const zones=computed(()=>[...new Set([browserZone(),zone.value,'UTC',...Intl.supportedValuesOf('timeZone')])]);
function candidates(local:string){try{return localCandidates(local,zone.value);}catch{return [];}}
const startCandidates=computed(()=>candidates(start.value)),endCandidates=computed(()=>candidates(end.value));
function endpoint(which:'start'|'end',displayZone=zone.value){return which==='start'?resolveLocal(start.value,displayZone,originalStart.value,startChoice.value):resolveLocal(end.value,displayZone,originalEnd.value,endChoice.value);}
const windowResult=computed(()=>{
 try{
  const s=endpoint('start'),e=endpoint('end');
  if(!validWindow(s,e))throw new Error('实际日期范围需大于零且不超过31天喵~');
  return {start:s,end:e,error:''};
 }catch(e){return {start:'',end:'',error:message(e)};}
});
function zoneChanged(event:Event){
 const selected=(event.target as HTMLSelectElement).value;
 try{
  const s=start.value?endpoint('start'):null,e=end.value?endpoint('end'):null;
  zone.value=selected;
  if(s){start.value=localTime(s,selected);originalStart.value={local:start.value,zone:selected,instant:s};}
  if(e){end.value=localTime(e,selected);originalEnd.value={local:end.value,zone:selected,instant:e};}
  startChoice.value='';endChoice.value='';error.value='';
 }catch(e){(event.target as HTMLSelectElement).value=zone.value;error.value=message(e)+'；请先处理日期，再切换显示时区。';}
}
const debounce=ref(2),repeat=ref(0),email=ref(false),enabled=ref(true),severity=ref<'warning'|'critical'>('warning');
const preview=ref<MetricPreview|null>(null),previewing=ref(false);
const now=ref(Date.now()),previewEvaluated=ref<string|null>(null);
let clock:ReturnType<typeof setInterval>|undefined;
const confirmDelete=ref<number|null>(null);
const editor=ref<HTMLFormElement>();
let returnFocus:HTMLElement|null=null,draftKey='new';
const draftFields:Record<string,Ref<unknown>>={id,revision,nodeId,metric,direction,iface,label,threshold,unit,amount,mode,cin,cout,shared,start,end,zone,originalStart,originalEnd,startChoice,endChoice,debounce,repeat,email,enabled,severity};
const snapshot=()=>Object.fromEntries(Object.entries(draftFields).map(([key,field])=>[key,field.value]));
const defaults=snapshot();
const drafts=new Map<string,{values:Record<string,unknown>;error:string}>();
function restore(values:Record<string,unknown>){for(const [key,field] of Object.entries(draftFields))field.value=values[key];}
function closeEditor(){
 if(busy.value)return;
 drafts.set(draftKey,{values:snapshot(),error:error.value});cancelPreview();editing.value=false;error.value='';notice.value='草稿暂存于本页；重新编辑可继续，离开本页后不保留喵~';
 void nextTick(()=>returnFocus?.focus());
}
function editorKeys(event:KeyboardEvent){
 if(event.isComposing)return;
 if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeEditor();return;}
 if(event.key!=='Tab')return;
 const controls=[...editor.value?.querySelectorAll<HTMLElement>('input:not(:disabled),select:not(:disabled),button:not(:disabled),summary')||[]].filter(el=>!el.closest('details:not([open])')||el.tagName==='SUMMARY');
 const first=controls[0],last=controls.at(-1);
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
 else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
}
let generation=0,controller:AbortController|undefined;
const network=computed(()=>metric.value.startsWith('network.'));
const ifaces=computed(()=>Object.keys(props.nodes.find(n=>n.id===nodeId.value)?.interfaces||{}));
const units=computed(()=>metric.value==='network.volume'?['GB','GiB','TB','TiB','byte']:metric.value==='network.rate'?['Mbps','bit/s']:['%']);
function message(e:unknown){const d=(e as {detail?:unknown})?.detail;if(Array.isArray(d))return d.map(item=>String(item.msg||'字段无效')).join('；');return typeof d==='string'?d:e instanceof Error?e.message:'请求失败，请重试';}
function cancelPreview(){generation++;controller?.abort();preview.value=null;previewing.value=false;}
watch([nodeId,metric,direction,iface,amount,mode,cin,cout,shared,start,end,zone,startChoice,endChoice],cancelPreview);
onMounted(()=>{clock=setInterval(()=>{now.value=Date.now();},1000);});
onBeforeUnmount(()=>{generation++;controller?.abort();clearInterval(clock);});
function metricChanged(){unit.value=metric.value==='network.volume'?'GB':metric.value==='network.rate'?'Mbps':'%';amount.value=metric.value==='network.volume'?'100':'80';threshold.value=toBase(amount.value,unit.value);}
function unitChanged(){try{amount.value=fromBase(threshold.value,unit.value);error.value='';}catch(e){error.value=message(e);}}
function amountChanged(){try{threshold.value=toBase(amount.value,unit.value);error.value='';}catch(e){error.value=message(e);}}
function condition():MetricCondition {
 const c:MetricCondition={metric:metric.value,threshold:toBase(amount.value,unit.value)};
 if(network.value){c.interface=iface.value;c.direction=direction.value;}
 if(metric.value==='network.utilization')c.capacity=mode.value==='shared'?{mode:'shared',shared_bps:Number(shared.value)*1e6}:{mode:'independent',in_bps:cin.value?Number(cin.value)*1e6:null,out_bps:cout.value?Number(cout.value)*1e6:null};
 if(metric.value==='network.volume'){
  if(windowResult.value.error)throw new Error(windowResult.value.error);
  c.window={kind:'fixed',start:windowResult.value.start,end:windowResult.value.end,timezone:zone.value};
 }
 return c;
}
const meaning=computed(()=>`${props.nodes.find(n=>n.id===nodeId.value)?.name||'选择节点'} · ${METRICS[metric.value]}${network.value?' / '+(iface.value||'选择接口')+' / '+DIRECTIONS[direction.value]:''} ≥ ${amount.value} ${unit.value}；连续 ${debounce.value} 个新有效样本触发。`);
const invalidTotal=computed(()=>metric.value==='network.utilization'&&mode.value==='independent'&&direction.value==='total');
async function reload(){rules.value=await listMetricRules();}
onMounted(()=>reload().catch(e=>error.value=message(e)));
function begin(rule?:MetricRule,initialMetric?:Metric){
 if(editing.value||busy.value)return;
 returnFocus=document.activeElement as HTMLElement;draftKey=rule?String(rule.id):initialMetric?'new:'+initialMetric:'new';
 const draft=drafts.get(draftKey);
 if(draft){restore(draft.values);error.value=draft.error;notice.value='已恢复本页草稿喵~';editing.value=true;void nextTick(()=>editor.value?.querySelector<HTMLElement>('select:not(:disabled)')?.focus());return;}
 restore(defaults);
 cancelPreview();error.value='';notice.value='';id.value=rule?.id;revision.value=rule?.revision;
 if(!rule&&initialMetric){metric.value=initialMetric;metricChanged();}
 if(rule){
  const c=rule.condition;nodeId.value=rule.node_id;label.value=rule.label;metric.value=c.metric;direction.value=c.direction||'out';iface.value=c.interface||'';
  unit.value=c.metric==='network.volume'?'GB':c.metric==='network.rate'?'Mbps':'%';threshold.value=c.threshold;amount.value=fromBase(c.threshold,unit.value);
  mode.value=c.capacity?.mode||'independent';cin.value=c.capacity?.in_bps?String(c.capacity.in_bps/1e6):'';cout.value=c.capacity?.out_bps?String(c.capacity.out_bps/1e6):'';shared.value=c.capacity?.shared_bps?String(c.capacity.shared_bps/1e6):'';
  if(c.window?.kind==='fixed'){
   zone.value=c.window.timezone;start.value=localTime(c.window.start,zone.value);end.value=localTime(c.window.end,zone.value);
   originalStart.value={local:start.value,zone:zone.value,instant:c.window.start};originalEnd.value={local:end.value,zone:zone.value,instant:c.window.end};
  }
  debounce.value=rule.debounce;repeat.value=rule.repeat_minutes;email.value=rule.email;enabled.value=rule.enabled;severity.value=rule.severity;
 }
 editing.value=true;
 void nextTick(()=>editor.value?.querySelector<HTMLElement>('select:not(:disabled)')?.focus());
}
async function check(){
 const focus=document.activeElement as HTMLElement;editor.value?.focus();
 cancelPreview();const token=generation;controller=new AbortController();previewing.value=true;error.value='';
 const requestedAt=new Date().toISOString();
 try{const p=await previewMetric(nodeId.value,condition(),controller.signal);if(token===generation){preview.value=p;previewEvaluated.value=requestedAt;now.value=Date.now();}}
 catch(e){if(token===generation)error.value=message(e);}
 finally{if(token===generation){previewing.value=false;await nextTick();if(document.activeElement===editor.value&&focus.isConnected)focus.focus();}}
}
async function save(){
 const focus=document.activeElement as HTMLElement;
 if(busy.value)return;busy.value=true;error.value='';
 editor.value?.focus();
 try{
  const data:MetricIntent={node_id:nodeId.value,label:label.value,condition:condition(),severity:severity.value,debounce:debounce.value,repeat_minutes:repeat.value,email:email.value,enabled:enabled.value};
  const receipt=await saveMetric(data,id.value,revision.value);
  // Remember committed identity even if the following readback fails.
  id.value=receipt.id;revision.value=receipt.revision;
  await reload();if(!rules.value.some(r=>r.id===receipt.id&&r.revision===receipt.revision))throw new Error('保存回读不匹配，草稿已保留');
  drafts.delete(draftKey);cancelPreview();editing.value=false;emit('changed');notice.value='已保存并回读规则喵~';void nextTick(()=>returnFocus?.focus());
 }catch(e){error.value=message(e)+'；草稿已保留。若响应中断，请先检查规则列表，勿重复创建。';}
 finally{busy.value=false;await nextTick();if(editing.value&&document.activeElement===editor.value&&focus.isConnected)focus.focus();}
}
async function remove(rule:Pick<MetricRule,'id'>){
 if(confirmDelete.value!==rule.id){confirmDelete.value=rule.id;return;}
 try{await deleteRule(rule.id);await reload();confirmDelete.value=null;emit('changed');}catch(e){error.value=message(e);}
}
function observation(c:MetricCondition,p:MetricPreview|null,evaluated:string|null){
 if(c.window?.kind==='fixed'){
  if(now.value<Date.parse(c.window.start))return '等待开始日期';
  if(now.value>=Date.parse(c.window.end))return '已结束';
 }
 const sample=p?.watermark?Date.parse(p.watermark):NaN,evaluation=evaluated?Date.parse(evaluated):NaN;
 if(sample>now.value+5000||evaluation>now.value+5000)return '时钟异常 · 当前状态未知';
 if(!p||!Number.isFinite(sample)||!Number.isFinite(evaluation))return REASONS[p?.reason||'']||'等待新有效样本';
 // Latest metrics mirror the evaluator. Fixed totals are evaluated at most
 // once/minute; 120s is a conservative UI freshness limit, not a new alert rule.
 const maxAge=c.metric==='network.volume'?120000:c.metric.startsWith('network.')?45000:180000;
 if(now.value-sample>maxAge||now.value-evaluation>maxAge)return '数据已过期 · 当前状态未知';
 if(p.quality!=='valid')return REASONS[p.reason]||'数据不完整 · 当前状态未知';
 if(p.bad===null||p.value===null)return '当前状态未知';
 return p.bad?'最新观测已达阈值':'当前未超限';
}
function editable(r:ListedMetricRule):r is MetricRule{return !!r.condition&&r.node_id!==null&&r.severity!==null;}
function status(r:ListedMetricRule){
 if(!r.condition||r.projection?.state==='incomplete')return `${r.condition?'规则数据不完整':'规则数据无效'} · ${r.enabled?'仍启用':'已停用'}${r.state==='firing'?' · 告警未确认恢复':''}`;
 if(!r.enabled)return '已停用';
 const current=observation(r.condition,r.preview,r.evaluated_at);
 if(current==='已结束')return r.state==='firing'?'已结束 · 曾超限':'已结束';
 if(r.state==='firing')return current==='最新观测已达阈值'?'正在告警':current+' · 告警未确认恢复';
 return current;
}
const previewStatus=computed(()=>{try{return observation(condition(),preview.value,previewEvaluated.value);}catch{return '当前状态未知';}});
function beginNew(m:Metric){if(busy.value)return;if(editing.value)closeEditor();begin(undefined,m);}
defineExpose({beginNew,closeEditor});
</script>
<template>
<section v-show="!embedded||editing||rules.length||error||notice" class="metrics-panel" :class="{embedded}" aria-label="指标告警">
 <header v-if="!embedded"><div><h2>指标告警</h2><p>明确计量口与阈值。新数据到达时评估，不额外巡检或测速。</p></div><button data-add-metric :disabled="editing" @click="begin()">添加指标规则</button></header>
 <form v-if="editing" ref="editor" role="dialog" tabindex="-1" aria-label="编辑指标规则" @submit.prevent="save" @keydown="editorKeys">
  <div class="fields">
   <label>资源<select v-model="nodeId" :disabled="!!id||busy"><option :value="0" disabled>选择节点</option><option v-for="n in nodes" :key="n.id" :value="n.id">{{n.name}}</option></select></label>
   <label>指标<select v-model="metric" :disabled="busy" @change="metricChanged"><option v-for="(name,key) in METRICS" :key="key" :value="key">{{name}}</option></select></label>
   <label v-if="network">方向<select v-model="direction" :disabled="busy"><option v-for="(name,key) in DIRECTIONS" v-show="key!=='any'||metric==='network.utilization'" :key="key" :value="key">{{name}}</option></select></label>
   <label v-if="network">单一计量接口<select v-model="iface" :disabled="busy"><option value="" disabled>明确选择，不默认所有网卡</option><option v-for="name in ifaces" :key="name" :value="name">{{name}}</option></select></label>
   <label>{{metric==='network.volume'?'累计流量达到':'触发阈值 ≥'}}<input v-model="amount" inputmode="decimal" :disabled="busy" required @input="amountChanged" /></label>
   <label>单位<select v-model="unit" :disabled="busy" @change="unitChanged"><option v-for="u in units" :key="u">{{u}}</option></select></label>
  </div>
  <p v-if="network" class="hint">入站＝节点接收，出站＝节点发送。只选一个观察口，避免物理口与隧道重复；不代表运营商账单。</p>
  <fieldset v-if="metric==='network.utilization'"><legend>用户明确配置的线路带宽</legend><div class="fields">
   <label>容量口径<select v-model="mode" :disabled="busy"><option value="independent">独立双向</option><option value="shared">明确共享收发容量</option></select></label>
   <template v-if="mode==='independent'"><label>入站容量（Mbps）<input v-model="cin" inputmode="decimal" :disabled="busy" /></label><label>出站容量（Mbps）<input v-model="cout" inputmode="decimal" :disabled="busy" /></label></template>
   <label v-else>共享容量（Mbps）<input v-model="shared" inputmode="decimal" :disabled="busy" required /></label>
  </div><p class="hint">填写合同/线路容量，不使用网卡协商速度或测速值。容量随此规则版本保存；只计算最新样本，不回算历史利用率。</p><p v-if="invalidTotal" role="alert" class="error">独立双向没有合计饱和度。请选择入站、出站或任一方向（取较高）。</p></fieldset>
  <fieldset v-if="metric==='network.volume'"><legend>固定日期窗口 [开始, 结束)</legend><div class="fields dates">
   <label>开始时刻（含）<input v-model="start" type="datetime-local" step="0.001" :disabled="busy" required @input="startChoice=''" aria-describedby="window-help window-error" /></label>
   <label>结束时刻（不含）<input v-model="end" type="datetime-local" step="0.001" :disabled="busy" required @input="endChoice=''" aria-describedby="window-help window-error" /></label>
   <label v-if="startCandidates.length>1&&!(originalStart&&sameLocal(originalStart.local,start))">开始时间重复，请选择<select v-model="startChoice" data-fold="start" :disabled="busy"><option value="" disabled>明确选择一次</option><option v-for="(instant,index) in startCandidates" :key="instant" :value="instant">第{{index+1}}次 · {{instant}}</option></select></label>
   <label v-if="endCandidates.length>1&&!(originalEnd&&sameLocal(originalEnd.local,end))">结束时间重复，请选择<select v-model="endChoice" data-fold="end" :disabled="busy"><option value="" disabled>明确选择一次</option><option v-for="(instant,index) in endCandidates" :key="instant" :value="instant">第{{index+1}}次 · {{instant}}</option></select></label>
   <label>显示时区<select data-zone :value="zone" :disabled="busy" @change="zoneChanged"><option v-for="z in zones" :key="z" :value="z">{{z}}</option></select></label>
  </div><p id="window-help" class="hint">日期时间按 {{zone}} 显示；切换时区不移动实际时刻。单次固定日期累计，不自动重置；新周期需另设窗口。最多31天，包含开始、不包含结束 [start,end)。未来窗口等待开始，已结束日期只能停用保存。缺历史不按0计算。保留未修改端点的原始精度喵~</p><p v-if="windowResult.error" id="window-error" class="error" role="status">{{windowResult.error}}</p><p v-else class="actual-window">实际 UTC 时段（以端点偏移为准）：<br>{{utcInstant(windowResult.start)}} → {{utcInstant(windowResult.end)}}</p></fieldset>
  <details><summary>通知与规则选项</summary><div class="fields">
   <label>名称<input v-model="label" maxlength="128" :disabled="busy" /></label><label>连续新样本数<input v-model.number="debounce" type="number" min="1" max="10" :disabled="busy" /></label>
   <label>重复提醒（分钟，0关闭）<input v-model.number="repeat" type="number" min="0" max="1440" :disabled="busy" /></label>
   <label>级别<select v-model="severity" :disabled="busy"><option value="warning">普通</option><option value="critical">严重</option></select></label>
   <label class="check"><input v-model="email" type="checkbox" :disabled="busy" />邮件通知</label><label class="check"><input v-model="enabled" type="checkbox" :disabled="busy" />启用规则</label>
  </div><p class="hint">站内通知始终开启；一个新有效样本低于阈值时恢复。未知数据不恢复；全部采集器停止时无法保证准点告警。</p></details>
  <p class="meaning">{{meaning}}</p>
  <div v-if="preview" class="preview" aria-live="polite"><strong>{{previewStatus}}</strong><span>上次观测：{{preview.value===null?'无可确认值':`${preview.value} ${preview.unit}`}}</span><span v-if="preview.lower!=null">当次已确认下界 {{preview.lower}} {{preview.unit}}；上界 {{preview.upper??'未知'}}</span><span>{{preview.watermark?'样本 '+preview.watermark:'尚无有效样本'}}</span><span>预览请求时间 {{previewEvaluated}} · 不自动刷新数据</span></div>
  <p v-if="error" class="error" role="alert">{{error}}</p>
  <footer><button type="button" :disabled="previewing||busy||!nodeId||invalidTotal||(metric==='network.volume'&&!!windowResult.error)" @click="check">{{previewing?'计算中…':'只读预览'}}</button><button type="button" :disabled="busy" @click="closeEditor">取消</button><button class="primary" :disabled="busy||!nodeId||invalidTotal||(metric==='network.volume'&&!!windowResult.error)">{{busy?'保存并核对…':'保存规则'}}</button></footer>
 </form>
 <p v-if="error&&!editing" class="error" role="alert">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
 <p v-if="!embedded&&!rules.length&&!editing" class="hint">尚无指标规则。可添加系统使用率、带宽或日期累计流量。</p>
 <article v-for="r in rules" :key="r.id"><div><strong>{{r.label||(r.condition?METRICS[r.condition.metric]:'无效规则')}}</strong><p v-if="r.condition">{{nodes.find(n=>n.id===r.node_id)?.name||r.node_id}} · {{METRICS[r.condition.metric]}} {{r.condition.direction?DIRECTIONS[r.condition.direction]:''}} <span v-if="r.condition.interface">/ {{r.condition.interface}}</span> ≥ {{r.condition.threshold}} {{r.condition.metric==='network.volume'?'字节':r.condition.metric==='network.rate'?'bit/s':'%'}}</p><p class="current-status">{{status(r)}}</p><div v-if="r.preview" class="last-observation"><span>上次观测：{{r.preview.value===null?'无可确认值':`${r.preview.value} ${r.preview.unit}`}}</span><span v-if="r.preview.lower!=null">当次下界 {{r.preview.lower}} {{r.preview.unit}}；上界 {{r.preview.upper??'未知'}}</span><small>{{r.preview.watermark?'样本 '+r.preview.watermark:'无样本时间'}} · {{r.evaluated_at?'最后评估 '+r.evaluated_at:'尚未评估'}}</small></div><small v-else>{{r.projection?'存储数据无效，未修改规则或告警状态':'尚未评估'}}</small></div><div class="ops"><button :disabled="!editable(r)" @click="editable(r)&&begin(r)">编辑</button><button @click="remove(r)">{{confirmDelete===r.id?'确认删除此规则？':'删除'}}</button><button v-if="confirmDelete===r.id" @click="confirmDelete=null">取消</button></div></article>
</section>
</template>
<style scoped>
.metrics-panel.embedded{background:transparent;border:0;padding:0;margin-bottom:16px}
.metrics-panel{color-scheme:dark;font-family:"Inter Variable","PingFang SC","Noto Sans SC","Noto Sans CJK SC","Microsoft YaHei","WenQuanYi Zen Hei",system-ui,sans-serif}
.actual-window{overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.last-observation{display:flex;flex-direction:column;border-left:2px solid var(--edge);padding-left:10px;margin-top:6px;color:var(--muted)}.current-status{font-weight:550}
.metrics-panel{--ink:#ede8e1;--muted:#bdb6ac;--edge:#49443e;color:var(--ink);background:#252321;border:1px solid var(--edge);border-radius:12px;padding:18px;margin-bottom:24px;font-size:14px;line-height:1.6}
header,footer,article,.ops{display:flex;gap:12px;align-items:center;justify-content:space-between}header{align-items:flex-start}h2{font-size:22px;margin:0;font-weight:550}p{margin:5px 0 12px}header p,.hint,small{color:var(--muted)}form{margin-top:18px}.fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.dates{grid-template-columns:repeat(2,minmax(0,1fr))}.dates label:last-child{grid-column:1/-1}label{display:flex;flex-direction:column;gap:5px}input,select,button{font:inherit;color:var(--ink);background:#302d29;border:1px solid #625b52;border-radius:7px;min-height:40px;box-sizing:border-box;max-width:100%;padding:7px 10px}input,select{width:100%;min-width:0}button{cursor:pointer;flex-shrink:0}button:hover{border-color:#8dc6af}button:disabled{opacity:.55;cursor:default}.primary{background:#9bcbb6;color:#192820;border-color:#9bcbb6}input:focus-visible,select:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid #d4b378;outline-offset:3px}fieldset{border:1px solid var(--edge);border-radius:8px;margin:16px 0;padding:12px;min-width:0}legend,summary{color:#d4b378}summary{cursor:pointer;padding:10px 0}details .fields{margin-top:8px}.check{flex-direction:row;align-items:center}.check input{width:20px;min-height:20px}.meaning{border-left:3px solid #8dc6af;padding-left:12px;margin:16px 0}.preview{display:flex;flex-direction:column;padding:12px;background:#302d29;border-radius:8px;overflow-wrap:anywhere;margin-bottom:12px}.error{color:#ffb8a7;overflow-wrap:anywhere}footer{justify-content:flex-end;flex-wrap:wrap}article{padding:14px 0;border-top:1px solid var(--edge);margin-top:14px}article>div:first-child{min-width:0;overflow-wrap:anywhere}article p{margin:3px 0}.ops{flex-wrap:wrap;justify-content:flex-end}small{font-size:12px}
@media(max-width:650px){.metrics-panel{padding:14px}.fields,.dates{grid-template-columns:repeat(2,minmax(0,1fr))}.fields>label{min-width:0}header,article{flex-wrap:wrap}.dates label{grid-column:1/-1}.ops{justify-content:flex-start}button{min-height:44px}.metrics-panel header>button{width:100%}}
@media(max-width:360px){.fields{grid-template-columns:minmax(0,1fr)}}
</style>
