<script setup lang="ts">
import {ref,watch,onBeforeUnmount,nextTick} from 'vue';
import {getWebsite,deleteWebsite,rollbackInjection,websiteError,type Website} from '../../api/integrations';
import {checkWebsiteDraft,saveWebsiteDraft,type WebsiteDraft,type WebsiteCheck} from '../../api/websiteSettings';
import {websiteSaveKey} from '../../api/websiteSaveKey';
import Icon from '../../shell/Icon.vue';
import IconPicker from './IconPicker.vue';
import {loadNavigation,navigationRows} from '../../stores/navigation';
const props=defineProps<{id?:string}>();
const emit=defineEmits<{dirty:[value:boolean];cancel:[];saved:[];busy:[value:boolean]}>();
const fresh=():WebsiteDraft=>({address:'',name:'',icon:'globe',visible:true,keep_alive:false,open_behavior:'embedded',custom:{enabled:false,css:'',js:'',timing:'dom_ready'}});
const input=ref(fresh()),original=ref(JSON.stringify(input.value)),selected=ref<Website|null>(null);
const result=ref<WebsiteCheck|null>(null),stale=ref(false),busy=ref(false),checking=ref(false),message=ref(''),loadFailed=ref(false);
let generation=0,alive=true,controller:AbortController|undefined;
const nameEdited=ref(false);
const key=websiteSaveKey();
const pending=ref<{id:string;payload:WebsiteDraft}|null>(null);
const uncertain=ref<(WebsiteDraft & {idempotency_key:string})|null>(null);
const rollbackPending=ref<string|null>(null),deleting=ref(false),deletePending=ref(false);
watch(()=>busy.value||!!pending.value||!!uncertain.value||!!rollbackPending.value||deletePending.value,value=>emit('busy',value),{flush:'sync'});
async function commit(payload:WebsiteDraft & {idempotency_key:string}){
 try{const item=await saveWebsiteDraft(props.id,payload);if(!alive)return;uncertain.value=null;selected.value=item;pending.value={id:item.id,payload};await reconcile();}
 catch(e){const status=(e as {status?:number}).status;if(!status||status>=500||status===408){uncertain.value=payload;message.value='保存结果不确定；请用同一幂等请求确认结果，不要重新创建。';return;}throw e;}
}
async function confirmSave(){if(!uncertain.value||busy.value)return;busy.value=true;try{await commit(uncertain.value);}catch(e){message.value=websiteError(e);}finally{if(alive)busy.value=false;}}
async function reconcile(){
 if(!pending.value)return;busy.value=true;
 try{const {id,payload}=pending.value;const readback=await getWebsite(id);if(!alive)return;
  if(readback.browser_url!==payload.address||readback.name!==(payload.name||readback.name)||readback.icon!==payload.icon||(readback.keep_alive===true)!==payload.keep_alive||(readback.mode==='link')!==(payload.open_behavior==='external'))throw new Error('保存内容回读不一致');
  if(payload.custom){const draft=readback.injection?.draft;if(!draft||(['enabled','css','js','timing'] as const).some(field=>draft[field]!==payload.custom![field]))throw new Error('代码草稿回读不一致');}
  if(!await loadNavigation())throw new Error('导航回读失败');if(!alive)return;
  const row=navigationRows.value.find(x=>x.id===id);if(!row||row.label!==readback.name||row.icon!==payload.icon||row.visible!==payload.visible)throw new Error('导航显示回读不一致');
  pending.value=null;emit('dirty',false);emit('saved');
 }catch{if(alive)message.value='网站已保存，回读尚未确认；保留草稿，请重试回读，不要重复创建。';}
 finally{if(alive)busy.value=false;}
}
watch(input,()=>emit('dirty',JSON.stringify(input.value)!==original.value),{deep:true,flush:'sync'});

watch(()=>[input.value.address,input.value.open_behavior,JSON.stringify(input.value.custom)],()=>{generation++;controller?.abort();checking.value=false;if(result.value)stale.value=true;},{flush:'sync'});
async function read(){
 if(!props.id)return;
 busy.value=true;loadFailed.value=false;
 try{const item=await getWebsite(props.id);if(!alive)return;selected.value=item;
  const custom=item.injection?.draft||item.injection?.active;
  input.value={address:item.browser_url,name:navigationRows.value.find(x=>x.id===item.id)?.label||item.name,icon:navigationRows.value.find(x=>x.id===item.id)?.icon||item.icon,visible:navigationRows.value.find(x=>x.id===item.id)?.visible??true,keep_alive:item.keep_alive===true,open_behavior:item.mode==='link'?'external':'embedded',custom:item.adapter==='generic'?{enabled:custom?.enabled??false,css:custom?.css||'',js:custom?.js||'',timing:custom?.timing||'dom_ready'}:undefined};
  original.value=JSON.stringify(input.value);nameEdited.value=true;emit('dirty',false);
  await nextTick();(document.querySelector('.inline-editor input') as HTMLInputElement|null)?.focus();
 }catch(e){if(alive){loadFailed.value=true;message.value=websiteError(e);}}finally{if(alive)busy.value=false;}
}
watch(()=>input.value.address,address=>{if(!selected.value||!input.value.custom)return;try{const url=new URL(address.includes('://')?address:'https://'+address);if(url.origin!==new URL(selected.value.browser_url).origin)input.value.custom.enabled=false;}catch{input.value.custom.enabled=false;}},{flush:'sync'});
void read();
onBeforeUnmount(()=>{alive=false;generation++;controller?.abort();});
async function detect():Promise<WebsiteCheck|null>{
 if(!input.value.address.trim()) {message.value='请填写网站地址';return null;}
 controller?.abort();controller=new AbortController();const seq=++generation;
 checking.value=true;message.value='';
 try{const current=await checkWebsiteDraft({address:input.value.address,open_behavior:input.value.open_behavior,custom_enabled:input.value.custom?.enabled===true},controller.signal);
  if(!alive||seq!==generation)return null;
  // Rejected/invalid normalization must never erase the user's address draft.
  try{const normalized=new URL(current.normalized_url);if(['http:','https:'].includes(normalized.protocol)&&normalized.hostname)input.value.address=current.normalized_url;}catch{/* Keep the original address and show the structured check below. */}
  if(!nameEdited.value&&!input.value.name)input.value.name=current.name_suggestion;
  result.value=current;stale.value=false;return current;
 }catch(e){if(alive&&seq===generation)message.value=websiteError(e);return null;}
 finally{if(alive&&seq===generation)checking.value=false;}
}
async function remove(){if(!props.id||busy.value)return;busy.value=true;
 try{if(!deletePending.value){await deleteWebsite(props.id);deletePending.value=true;}
  try{await getWebsite(props.id);throw new Error('删除回读不一致');}catch(e){if((e as {status?:number}).status!==404)throw e;}
  if(!await loadNavigation())throw new Error('导航回读失败');if(!alive)return;deleting.value=false;emit('dirty',false);emit('saved');
 }catch{if(alive)message.value='删除结果尚未确认，请重试回读；不删除原网站数据。';}finally{if(alive)busy.value=false;}}
async function rollbackRead(){if(!props.id||!rollbackPending.value)return;busy.value=true;try{const item=await getWebsite(props.id);if(!alive)return;if(rollbackPending.value!=='unknown'&&item.injection?.active?.version!==rollbackPending.value)throw new Error('版本回读不一致');selected.value=item;const custom=item.injection?.draft||item.injection?.active;if(custom)input.value.custom={enabled:custom.enabled,css:custom.css,js:custom.js,timing:custom.timing};original.value=JSON.stringify(input.value);rollbackPending.value=null;emit('dirty',false);message.value='已回退并回读活动版本；已打开的网站请手动重载。';}catch{if(alive)message.value='回退结果未确认，请刷新活动版本，不要重复回退。';}finally{if(alive)busy.value=false;}}
async function rollback(){if(!props.id||busy.value||JSON.stringify(input.value)!==original.value)return;busy.value=true;try{const state=await rollbackInjection(props.id) as {active?:{version?:string}};rollbackPending.value=state.active?.version||'unknown';await rollbackRead();}catch(e){if(!(e as {status?:number}).status)rollbackPending.value='unknown';message.value=websiteError(e);}finally{if(alive)busy.value=false;}}
async function enableSaved(){if(!selected.value||JSON.stringify(input.value)!==original.value||!input.value.custom||stale.value||result.value?.injection.status!=='supported')return;input.value.custom.enabled=true;await save();}
async function save(){
 if(busy.value||checking.value||loadFailed.value||pending.value||uncertain.value)return;busy.value=true;
 try{const check=await detect();if(!check)return;
  if(!check.can_save){message.value='当前设置不能保存；请按检测结果处理或显式选择新窗口后重试。';return;}
  await commit({...JSON.parse(JSON.stringify(input.value)),name:input.value.name?.trim()||undefined,idempotency_key:key});
 }catch(e){if(!alive)return;const detail=(e as {detail?:{code?:string;check?:WebsiteCheck}}).detail;
  if(detail?.code==='website_check_failed'&&detail.check){result.value=detail.check;stale.value=false;message.value='保存时重新检测未通过，修改已保留。';}
  else message.value=e instanceof Error&&!(e as {status?:number}).status?e.message:websiteError(e);
 }finally{if(alive)busy.value=false;}
}
</script>
<template><form class="inline-editor" @submit.prevent="save"><header class="editor-head"><h3>{{id?'编辑网站':'添加网站'}}</h3><button type="button" aria-label="收起编辑" :disabled="busy||!!pending||!!uncertain||!!rollbackPending" @click="emit('cancel')"><Icon name="x" :size="16"/></button></header><fieldset :disabled="busy||loadFailed||!!pending||!!uncertain||!!rollbackPending"><div class="address-row"><label>网站地址<input v-model="input.address" aria-label="网站地址" required placeholder="输入域名或完整网址" /></label><button type="button" :disabled="checking" @click="detect">检测</button></div>
<p v-if="stale" role="status">需重新检测</p><section v-if="result&&!stale" class="check-result" aria-label="检测结果"><strong>{{result.embedding.reason}}</strong><p>服务端：{{result.access.status==='reachable'?'可访问':result.access.status==='login_required'?'返回认证响应':result.access.status==='blocked'?'拒绝访问':'尚未确认'}} · 浏览器内容尚未确认，响应头检测不保证登录与实际页面可用。</p><p>{{result.injection.reason}}</p><p v-for="issue in result.issues" :key="issue">{{issue}}</p><details v-if="result.help" open><summary>{{result.help.title}}</summary><code v-if="result.help.location">{{result.help.location}}</code><p v-for="line in result.help.instructions" :key="line">{{line}}</p></details></section>
<label class="name-field">显示名称<input v-model="input.name" aria-label="显示名称" maxlength="80" @input="nameEdited=true" /></label>
<IconPicker v-model="input.icon" :name="input.name||''"/><label>打开方式<select v-model="input.open_behavior" aria-label="打开方式"><option value="embedded">在 Stella 内打开</option><option value="external">新窗口打开</option></select></label><label class="check"><input v-model="input.keep_alive" type="checkbox"/>切页保留现场（最多 3 个网站）</label>
<details v-if="(!selected||selected.adapter==='generic')&&input.custom" class="custom"><summary>自定义外观与脚本（可选）</summary><p>尚未保存的草稿不会执行；不在 Stella 页面运行代码。请勿填入密码或 Token。保存时服务端校验语法；不支持注入仍可保留停用草稿。</p><p v-if="result&&!stale">{{result.injection.reason}}</p><section v-if="selected?.injection?.active" aria-label="活动版本内容"><p>活动版本：{{selected.injection.active.version||'无'}}（{{selected.injection.active.enabled?'启用':'停用'}}，只读）</p><label>活动版本 CSS<textarea :value="selected.injection.active.css" aria-label="活动版本 CSS" readonly spellcheck="false" /></label><label>活动版本 JavaScript<textarea :value="selected.injection.active.js" aria-label="活动版本 JavaScript" readonly spellcheck="false" /></label></section><p>{{selected?.injection?.draft?'编辑内容：已保存草稿（与活动版本分开）':selected?.injection?.active?'编辑内容：活动版本的副本（修改后保存为草稿）':'编辑内容：新草稿'}}</p><label class="check"><input v-model="input.custom.enabled" type="checkbox"/>保存时启用自定义（会在目标网站执行，需检测支持）</label><label>自定义 CSS<textarea v-model="input.custom.css" aria-label="自定义 CSS" spellcheck="false" /></label><label>自定义 JavaScript<textarea v-model="input.custom.js" aria-label="自定义 JavaScript" spellcheck="false" /></label><p>当前生效：{{selected?.injection?.active?.version||'无'}} · 上一版本：{{selected?.injection?.previous?.version||'无'}}</p><button type="button" :disabled="!selected||JSON.stringify(input)!==original||stale||result?.injection.status!=='supported'" @click="enableSaved">应用保存的版本</button><button v-if="selected?.injection?.previous" type="button" :disabled="JSON.stringify(input)!==original||!!rollbackPending" @click="rollback">回退上一版本</button></details><p v-if="selected&&selected.adapter!=='generic'"><RouterLink :to="{path:'/settings',query:{section:'navigation',module:selected.adapter==='openlist'?'drive':'gallery'}}">前往内置服务唯一连接与注入设置</RouterLink></p>
<div class="actions"><button v-if="id" type="button" @click="deleting=true">删除网站入口</button><button type="button" @click="emit('cancel')">取消</button><button type="submit">保存</button></div></fieldset><p v-if="message" role="alert">{{message}}</p><button v-if="rollbackPending" type="button" :disabled="busy" @click="rollbackRead">回退结果回读</button><button v-if="uncertain" type="button" :disabled="busy" @click="confirmSave">确认保存结果</button><button v-if="pending" type="button" :disabled="busy" @click="reconcile">重试回读</button><button v-if="loadFailed" type="button" @click="read">重试读取</button><Teleport to="body"><div v-if="deleting" class="mask"><section role="dialog" aria-modal="true" aria-label="删除网站入口" class="dialog"><h3>删除网站入口？</h3><p>仅删除 Stella 入口与配置，不删除原网站数据、不卸载服务。</p><button type="button" :disabled="busy||deletePending" @click="deleting=false">取消删除</button><button type="button" :disabled="busy" @click="remove">{{deletePending?'重试删除回读':'确认删除入口'}}</button></section></div></Teleport></form></template>
<style scoped>.inline-editor{padding:18px;margin-bottom:14px;background:var(--bg-base);border:1px solid #7085a94d;border-radius:10px;min-width:0}fieldset{border:0;padding:0;margin:0;min-width:0}.editor-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}.editor-head h3{font-size:14px;margin:0}.editor-head button{display:flex;align-items:center;padding:7px}label{display:block;font-size:12px;color:var(--text-lo);margin:12px 0}input:not([type=checkbox]),select{display:block;box-sizing:border-box;width:100%;padding:8px 10px;border:1px solid #ffffff20;border-radius:7px;background:var(--bg-base);color:var(--text-hi);min-width:0;margin-top:5px}button{font:inherit;white-space:nowrap;padding:7px 11px;background:var(--bg-raised);border:1px solid #ffffff20;border-radius:7px;color:var(--text-hi);cursor:pointer}button:disabled{opacity:.45}.address-row{display:flex;gap:10px;align-items:end}.address-row label{flex:1;min-width:0;margin:0}.address-row button{flex-shrink:0}.name-field{width:220px;max-width:100%}.check{display:flex;gap:8px;align-items:center}.actions{display:flex;gap:10px;justify-content:flex-end;margin-top:18px}p{font-size:12px;line-height:1.7;color:var(--text-lo)}.check-result{margin:14px 0;padding:14px;border:1px solid #ffffff20;border-radius:8px;overflow-wrap:anywhere}textarea{display:block;width:100%;box-sizing:border-box;min-width:0;height:130px;margin-top:6px;padding:10px;background:var(--bg-base);color:var(--text-hi);border:1px solid #ffffff20;border-radius:7px;font-family:monospace}summary{cursor:pointer}code{white-space:normal;overflow-wrap:anywhere}.mask{position:fixed;inset:0;z-index:1000;background:#080c16b8;display:grid;place-items:center;padding:18px}.dialog{background:var(--bg-panel);padding:24px;border:1px solid #ffffff20;border-radius:14px;width:min(460px,100%)}.dialog button{margin-right:8px}</style>
