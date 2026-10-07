<script setup lang="ts">
import {ref,watch,onBeforeUnmount,nextTick,computed} from 'vue';
import {getWebsite,deleteWebsite,rollbackInjection,websiteError,type Website} from '../../api/integrations';
import {checkWebsiteDraft,saveWebsiteDraft,getWebsiteTemplates,type WebsiteTemplate,type ConnectionDraft,type WebsiteDraft,type WebsiteCheck} from '../../api/websiteSettings';
import {websiteSaveKey} from '../../api/websiteSaveKey';
import Icon from '../../shell/Icon.vue';
import Dropdown from '../../shell/Dropdown.vue';
import IconPicker from './IconPicker.vue';
import {loadNavigation,navigationRows} from '../../stores/navigation';
import {effectiveWebsiteBackground,confirmWebsiteBackground} from '../../stores/websiteBackground';
const props=defineProps<{id?:string}>();
const emit=defineEmits<{dirty:[value:boolean];cancel:[];saved:[];busy:[value:boolean]}>();
const fresh=():WebsiteDraft=>({address:'',name:'',icon:'globe',visible:true,keep_alive:false,open_behavior:'embedded',custom:{enabled:false,css:'',js:'',timing:'dom_ready'},template_id:null,connection:{transport:'auto',auth_mode:'original',header_name:'Authorization',token:null,clear_token:false,injection_delivery:'proxy'},background:'solid'});
const input=ref(fresh()),original=ref(JSON.stringify(input.value)),selected=ref<Website|null>(null);
const backgroundTouched=ref(false);
const legacyBackground=computed(()=>effectiveWebsiteBackground(selected.value).legacy);
function chooseBackground(value:string|number|boolean){if(value==='home'||value==='solid'){input.value.background=value;backgroundTouched.value=true;}}
const result=ref<WebsiteCheck|null>(null),stale=ref(false),busy=ref(false),checking=ref(false),message=ref(''),loadFailed=ref(false);
let generation=0,alive=true,controller:AbortController|undefined;
const nameEdited=ref(false),codeOpen=ref(false),codeSource=ref<'active'|'draft'>('active');
const templates=ref<WebsiteTemplate[]>([]),templateError=ref(''),templateChoice=ref(''),templatePending=ref<string|null>(null);
const templateOptions=computed(()=>[{value:'',label:'空白网站'},...templates.value.map(t=>({value:t.id,label:t.name}))]);
const connection=computed<ConnectionDraft>(()=>input.value.connection||{transport:selected.value?.mode==='isolated_proxy'?'proxy':'auto',auth_mode:'original',header_name:'Authorization',injection_delivery:'proxy',token:null,clear_token:false});
function setConnection(field:keyof ConnectionDraft,value:unknown){input.value.connection={...connection.value,[field]:value};}
const copyCode=(code:WebsiteDraft['custom']|null)=>({enabled:code?.enabled??false,css:code?.css||'',js:code?.js||'',timing:code?.timing||'dom_ready' as const});
const codeBuffers=ref<Partial<Record<'active'|'draft',NonNullable<WebsiteDraft['custom']>>>>({});
const hiddenCodeDirty=computed(()=>Object.entries(codeBuffers.value).some(([source,code])=>source!==codeSource.value&&JSON.stringify(code)!==JSON.stringify(copyCode(selected.value?.injection?.[source as 'active'|'draft']))));
const dirty=computed(()=>backgroundTouched.value||JSON.stringify(input.value)!==original.value||hiddenCodeDirty.value);
const distinctDraft=computed(()=>!!selected.value?.injection?.draft&&JSON.stringify(copyCode(selected.value.injection.draft))!==JSON.stringify(copyCode(selected.value.injection.active)));
function switchCode(source:'active'|'draft'){
 if(source===codeSource.value)return;
 if(input.value.custom)codeBuffers.value[codeSource.value]={...input.value.custom};
 input.value.custom={...(codeBuffers.value[source]||copyCode(selected.value?.injection?.[source]))};codeSource.value=source;codeOpen.value=true;
}
async function loadTemplates(){try{const items=await getWebsiteTemplates();if(alive){templates.value=items;templateError.value='';}}catch{if(alive)templateError.value='模板未加载，可重试；现有代码仍可编辑。';}}
function chooseTemplate(value:string|number|boolean){const id=String(value);if(selected.value||dirty.value){templatePending.value=id;return;}applyTemplate(id);}
function applyTemplate(id:string){
 const template=templates.value.find(t=>t.id===id);if(id&&!template)return;
 const draft=JSON.parse(JSON.stringify(template?.draft||fresh()));
 input.value={...input.value,...draft,address:selected.value?input.value.address:(draft.address||input.value.address),template_id:template?.id||null,connection:draft.connection?{...draft.connection,token:null,clear_token:false}:fresh().connection};
 backgroundTouched.value=true;templateChoice.value=id;templatePending.value=null;codeOpen.value=true;codeSource.value='active';delete codeBuffers.value.active;delete codeBuffers.value.draft;nameEdited.value=!!input.value.name;
}
void loadTemplates();
const key=websiteSaveKey();
const pending=ref<{id:string;payload:WebsiteDraft}|null>(null);
const uncertain=ref<(WebsiteDraft & {idempotency_key:string})|null>(null);
const rollbackPending=ref<string|null>(null),deleting=ref(false),deletePending=ref(false);
watch(()=>busy.value||!!pending.value||!!uncertain.value||!!rollbackPending.value||deletePending.value,value=>emit('busy',value),{flush:'sync'});
async function commit(payload:WebsiteDraft & {idempotency_key:string}){
 try{const item=await saveWebsiteDraft(props.id,payload);if(!alive)return;uncertain.value=null;selected.value=item;pending.value={id:item.id,payload};await reconcile();}
 catch(e){const status=(e as {status?:number}).status;if(!status||status>=500||status===408){if(props.id){pending.value={id:props.id,payload};await reconcile();}else{uncertain.value=payload;message.value='保存结果不确定；请用同一幂等请求确认结果，不要重新创建。';}return;}throw e;}
}
async function confirmSave(){if(!uncertain.value||busy.value)return;busy.value=true;try{await commit(uncertain.value);}catch(e){message.value=websiteError(e);}finally{if(alive)busy.value=false;}}
async function reconcile(){
 if(!pending.value)return;busy.value=true;
 try{const {id,payload}=pending.value;const readback=await getWebsite(id);if(!alive)return;
  if(readback.browser_url!==payload.address||readback.name!==(payload.name||readback.name)||readback.icon!==payload.icon||(readback.keep_alive===true)!==payload.keep_alive||(readback.mode==='link')!==(payload.open_behavior==='external'))throw new Error('保存内容回读不一致');
  if(payload.background!==undefined&&readback.background!==payload.background)throw new Error('背景回读不一致');
  if(payload.template_id!==undefined&&readback.template_id!==payload.template_id)throw new Error('模板来源回读不一致');
  if(payload.connection){const saved=readback.connection;if(!saved||(['transport','auth_mode','header_name','injection_delivery'] as const).some(field=>saved[field]!==payload.connection![field]))throw new Error('连接回读不一致');if(payload.connection.clear_token&&saved.has_token||payload.connection.token&&!payload.connection.clear_token&&!saved.has_token)throw new Error('凭据状态回读不一致');}
  if(payload.request_policy){const policy=readback.request_policy;if(!policy||policy.protect_other_writes!==payload.request_policy.protect_other_writes||JSON.stringify(policy.management_prefixes)!==JSON.stringify(payload.request_policy.management_prefixes)||JSON.stringify(policy.read_post_paths)!==JSON.stringify(payload.request_policy.read_post_paths))throw new Error('请求策略回读不一致');}
  if(payload.custom){
   const draft=readback.injection?.draft,active=readback.injection?.active;
   if(!draft||(['enabled','css','js','timing'] as const).some(field=>draft[field]!==payload.custom![field]))throw new Error('代码草稿回读不一致');
   if(payload.custom.enabled&&(!active||(['enabled','css','js','timing'] as const).some(field=>active[field]!==payload.custom![field])))throw new Error('生效代码回读不一致');
   if(!payload.custom.enabled&&active?.enabled)throw new Error('停用状态回读不一致');
  }
  if(!alive)return;if(!await loadNavigation({force:true}))throw new Error('导航回读失败');if(!alive)return;
  const row=navigationRows.value.find(x=>x.id===id);if(!row||row.label!==readback.name||row.icon!==payload.icon||row.visible!==payload.visible)throw new Error('导航显示回读不一致');
  if(payload.background!==undefined)confirmWebsiteBackground(readback);
  pending.value=null;emit('dirty',false);emit('saved');
 }catch{if(alive)message.value='保存结果尚未确认；保留草稿，请重试回读，不要重复提交。';}
 finally{if(alive)busy.value=false;}
}
watch(dirty,value=>emit('dirty',value),{flush:'sync'});

watch(()=>[input.value.address,input.value.open_behavior,JSON.stringify(input.value.custom),JSON.stringify(input.value.connection)],()=>{generation++;controller?.abort();checking.value=false;if(result.value)stale.value=true;},{flush:'sync'});
async function read(){
 if(!props.id)return;
 busy.value=true;loadFailed.value=false;
 try{const item=await getWebsite(props.id);if(!alive)return;selected.value=item;
  const custom=item.injection?.active||item.injection?.draft;
  input.value={address:item.browser_url,name:navigationRows.value.find(x=>x.id===item.id)?.label||item.name,icon:navigationRows.value.find(x=>x.id===item.id)?.icon||item.icon,visible:navigationRows.value.find(x=>x.id===item.id)?.visible??true,keep_alive:item.keep_alive===true,open_behavior:item.mode==='link'?'external':'embedded',custom:copyCode(custom),template_id:item.template_id,connection:item.connection?{transport:item.connection.transport,auth_mode:item.connection.auth_mode,header_name:item.connection.header_name,injection_delivery:item.connection.injection_delivery,token:null,clear_token:false}:undefined,background:effectiveWebsiteBackground(item).mode,request_policy:item.request_policy};
  templateChoice.value=item.template_id||'';codeSource.value=item.injection?.active?'active':'draft';codeOpen.value=!!custom?.css||!!custom?.js;delete codeBuffers.value.active;delete codeBuffers.value.draft;
  backgroundTouched.value=false;original.value=JSON.stringify(input.value);nameEdited.value=true;emit('dirty',false);
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
 try{const current=await checkWebsiteDraft({address:input.value.address,open_behavior:input.value.open_behavior,custom_enabled:input.value.custom?.enabled===true,connection:input.value.connection,module_id:props.id},controller.signal);
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
  if(!alive)return;if(!await loadNavigation({force:true}))throw new Error('导航回读失败');if(!alive)return;deleting.value=false;emit('dirty',false);emit('saved');
 }catch{if(alive)message.value='删除结果尚未确认，请重试回读；不删除原网站数据。';}finally{if(alive)busy.value=false;}}
async function rollbackRead(){if(!props.id||!rollbackPending.value)return;busy.value=true;try{const item=await getWebsite(props.id);if(!alive)return;if(rollbackPending.value!=='unknown'&&item.injection?.active?.version!==rollbackPending.value)throw new Error('版本回读不一致');if(!await loadNavigation({force:true}))throw new Error('导航回读失败');if(!alive)return;selected.value=item;const custom=item.injection?.active||item.injection?.draft;if(custom)input.value.custom=copyCode(custom);codeSource.value='active';delete codeBuffers.value.active;delete codeBuffers.value.draft;original.value=JSON.stringify(input.value);rollbackPending.value=null;emit('dirty',false);message.value='已回退并回读活动版本；网站保活配置已刷新。';}catch{if(alive)message.value='回退结果未确认，请刷新活动版本，不要重复回退。';}finally{if(alive)busy.value=false;}}
async function rollback(){if(!props.id||busy.value||dirty.value)return;busy.value=true;try{const state=await rollbackInjection(props.id) as {active?:{version?:string}};rollbackPending.value=state.active?.version||'unknown';await rollbackRead();}catch(e){if(!(e as {status?:number}).status)rollbackPending.value='unknown';message.value=websiteError(e);}finally{if(alive)busy.value=false;}}
async function enableSaved(){if(!selected.value||dirty.value||!input.value.custom||stale.value||result.value?.injection.status!=='supported')return;input.value.custom.enabled=true;await save();}
async function save(){
 if(busy.value||checking.value||loadFailed.value||pending.value||uncertain.value||hiddenCodeDirty.value)return;busy.value=true;
 try{const check=await detect();if(!check)return;
  if(!check.can_save){message.value='当前设置不能保存；请按检测结果处理或显式选择新窗口后重试。';return;}
  const payload:WebsiteDraft & {idempotency_key:string}={...JSON.parse(JSON.stringify(input.value)),name:input.value.name?.trim()||undefined,idempotency_key:key};
  if(selected.value&&!backgroundTouched.value&&input.value.background===JSON.parse(original.value).background)delete payload.background;
  // A metadata-only edit must not overwrite a distinct saved draft with the active copy.
  if(selected.value&&codeSource.value==='active'&&JSON.stringify(input.value.custom)===JSON.stringify(JSON.parse(original.value).custom))delete payload.custom;
  await commit(payload);
 }catch(e){if(!alive)return;const detail=(e as {detail?:{code?:string;check?:WebsiteCheck}}).detail;
  if(detail?.code==='website_check_failed'&&detail.check){result.value=detail.check;stale.value=false;message.value='保存时重新检测未通过，修改已保留。';}
  else message.value=e instanceof Error&&!(e as {status?:number}).status?e.message:websiteError(e);
 }finally{if(alive)busy.value=false;}
}
</script>
<template><form class="inline-editor" @submit.prevent="save"><header class="editor-head"><h3>{{id?'编辑网站':'添加网站'}}</h3><button type="button" aria-label="收起编辑" :disabled="busy||!!pending||!!uncertain||!!rollbackPending||deletePending" @click="emit('cancel')"><Icon name="x" :size="16"/></button></header><fieldset :disabled="busy||loadFailed||!!pending||!!uncertain||!!rollbackPending||deletePending"><label>模板<Dropdown :model-value="templateChoice" :options="templateOptions" @update:model-value="chooseTemplate" /></label><p v-if="templateError" role="alert">{{templateError}} <button type="button" @click="loadTemplates">重试模板</button></p><button v-if="templateChoice" type="button" @click="templatePending=templateChoice">恢复模板代码</button><div class="address-row"><label>网站地址<input v-model="input.address" aria-label="网站地址" required placeholder="输入域名或完整网址" /></label><button type="button" :disabled="checking" @click="detect">检测</button></div>
<p v-if="stale" role="status">需重新检测</p><section v-if="result&&!stale" class="check-result" aria-label="检测结果"><strong>{{result.embedding.reason}}</strong><p>服务端：{{result.access.status==='reachable'?'可访问':result.access.status==='login_required'?'返回认证响应':result.access.status==='blocked'?'拒绝访问':'尚未确认'}} · 浏览器内容尚未确认，响应头检测不保证登录与实际页面可用。</p><p>{{result.injection.reason}}</p><p v-for="issue in result.issues" :key="issue">{{issue}}</p><details v-if="result.help" open><summary>{{result.help.title}}</summary><code v-if="result.help.location">{{result.help.location}}</code><p v-for="line in result.help.instructions" :key="line">{{line}}</p></details></section>
<label class="name-field">显示名称<input v-model="input.name" aria-label="显示名称" maxlength="80" @input="nameEdited=true" /></label>
<IconPicker v-model="input.icon" :name="input.name||''"/><div class="connection-grid"><label>打开方式<Dropdown :model-value="input.open_behavior" :options="[{value:'embedded',label:'在 Stella 内打开'},{value:'external',label:'新窗口打开'}]" @update:model-value="input.open_behavior=$event as WebsiteDraft['open_behavior']" /></label><label>传输方式<Dropdown :model-value="connection.transport" :options="[{value:'auto',label:'自动选择'},{value:'proxy',label:'隔离代理'},{value:'direct',label:'原站直连'}]" @update:model-value="setConnection('transport',$event)" /></label><label>背景<Dropdown :model-value="input.background||'solid'" :options="[{value:'solid',label:'纯色背景'},{value:'home',label:'主页背景图 / 视频'}]" @update:model-value="chooseBackground" /></label></div>
<p v-if="legacyBackground" role="status">当前背景沿用旧偏好，仅此设备生效；重新选择背景并保存后，将使用网站级设置，不再沿用本机旧开关。</p><details class="auth-options" :open="connection.auth_mode!=='original'"><summary>认证与连接选项</summary><label>认证方式<Dropdown :model-value="connection.auth_mode" :options="[{value:'original',label:'原站登录'},{value:'header',label:'服务端 Header 凭据'},{value:'oidc',label:'已有 OIDC 登录'}]" @update:model-value="setConnection('auth_mode',$event)" /></label><p v-if="connection.auth_mode==='oidc'">保留原网站域名、账号与已配置的 OIDC 流程；这里不会替原站创建 OIDC 配置。</p><template v-if="connection.auth_mode==='header'"><label>Header 名称<input :value="connection.header_name" aria-label="Header 名称" @input="setConnection('header_name',($event.target as HTMLInputElement).value)" /></label><label>Token<input :value="connection.token||''" type="password" aria-label="Token" autocomplete="new-password" :placeholder="selected?.connection?.has_token?'已保存 · 留空保持':'输入服务端凭据'" @input="setConnection('token',($event.target as HTMLInputElement).value||null)" /></label><label class="check"><input type="checkbox" :checked="connection.clear_token" @change="setConnection('clear_token',($event.target as HTMLInputElement).checked)"/>清除已保存凭据</label></template><label>代码交付<Dropdown :model-value="connection.injection_delivery" :options="[{value:'proxy',label:'代理注入'},{value:'loader',label:'原站加载器'}]" @update:model-value="setConnection('injection_delivery',$event)" /></label><p v-if="connection.injection_delivery==='loader'">直连网站需安装加载器，才会执行保存的代码。</p><p v-if="selected&&connection.injection_delivery==='loader'"><code>{{'/website-assets/'+selected.id+'.js'}}</code></p></details><label class="check"><input v-model="input.keep_alive" type="checkbox"/>切页保留现场（最多 3 个网站）</label>
<details v-if="input.custom" class="custom" :open="codeOpen" @toggle="codeOpen=($event.target as HTMLDetailsElement).open"><summary>自定义外观与脚本（可选）</summary><p v-if="input.background==='home'">主页背景只用于网站外层；页面透明效果由这里可见的 CSS / JavaScript 配合，不会偷偷修改原站样式。</p><p>尚未保存的草稿不会执行；不在 Stella 页面运行代码。请勿填入密码或 Token。保存时服务端校验语法；不支持注入仍可保留停用草稿。</p><p v-if="result&&!stale">{{result.injection.reason}}</p><details v-if="selected?.injection?.active" aria-label="活动版本内容"><summary>查看当前生效代码（只读）</summary><p>活动版本：{{selected.injection.active.version||'无'}}（{{selected.injection.active.enabled?'启用':'停用'}}，只读）</p><label>活动版本 CSS<textarea :value="selected.injection.active.css" aria-label="活动版本 CSS" readonly spellcheck="false" /></label><label>活动版本 JavaScript<textarea :value="selected.injection.active.js" aria-label="活动版本 JavaScript" readonly spellcheck="false" /></label></details><div v-if="distinctDraft" class="version-switch"><button type="button" :aria-pressed="codeSource==='active'" @click="switchCode('active')">当前生效代码</button><button type="button" :aria-pressed="codeSource==='draft'" @click="switchCode('draft')">已保存草稿</button></div><p>{{codeSource==='draft'&&selected?.injection?.draft?'编辑内容：已保存草稿（与活动版本分开）':selected?.injection?.active?'编辑内容：活动版本的副本（修改后保存为草稿）':'编辑内容：新草稿'}}</p><label class="check"><input v-model="input.custom.enabled" type="checkbox"/>保存时启用自定义（会在目标网站执行，需检测支持）</label><label>自定义 CSS<textarea v-model="input.custom.css" aria-label="自定义 CSS" spellcheck="false" /></label><label>自定义 JavaScript<textarea v-model="input.custom.js" aria-label="自定义 JavaScript" spellcheck="false" /></label><p>当前生效：{{selected?.injection?.active?.version||'无'}} · 上一版本：{{selected?.injection?.previous?.version||'无'}}</p><button type="button" :disabled="!selected||dirty||stale||result?.injection.status!=='supported'" @click="enableSaved">应用保存的版本</button><button v-if="selected?.injection?.previous" type="button" :disabled="dirty||!!rollbackPending||deletePending" @click="rollback">回退上一版本</button></details>
<p v-if="hiddenCodeDirty" role="status">另一份代码有未保存修改，请切回该版本处理后再保存。</p><div class="actions"><button v-if="id" type="button" @click="deleting=true">删除网站入口</button><button type="button" @click="emit('cancel')">取消</button><button type="submit" :disabled="hiddenCodeDirty">保存</button></div></fieldset><p v-if="message" role="alert">{{message}}</p><button v-if="rollbackPending" type="button" :disabled="busy" @click="rollbackRead">回退结果回读</button><button v-if="uncertain" type="button" :disabled="busy" @click="confirmSave">确认保存结果</button><button v-if="pending" type="button" :disabled="busy" @click="reconcile">重试回读</button><button v-if="loadFailed" type="button" @click="read">重试读取</button><Teleport to="body"><div v-if="templatePending!==null" class="mask"><section role="dialog" aria-modal="true" aria-label="替换模板" class="dialog"><h3>替换当前配置与代码？</h3><p>模板是独立副本，替换会覆盖当前未保存内容；现有网站地址保持不变。</p><button type="button" @click="templatePending=null">继续编辑</button><button type="button" @click="applyTemplate(templatePending!)">确认替换模板</button></section></div><div v-if="deleting" class="mask"><section role="dialog" aria-modal="true" aria-label="删除网站入口" class="dialog"><h3>删除网站入口？</h3><p>仅删除 Stella 入口与配置，不删除原网站数据、不卸载服务。</p><button type="button" :disabled="busy||deletePending" @click="deleting=false">取消删除</button><button type="button" :disabled="busy" @click="remove">{{deletePending?'重试删除回读':'确认删除入口'}}</button></section></div></Teleport></form></template>
<style scoped>.inline-editor{padding:18px;margin-bottom:14px;background:var(--bg-base);border:1px solid #7085a94d;border-radius:10px;min-width:0}fieldset{border:0;padding:0;margin:0;min-width:0}.editor-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}.editor-head h3{font-size:14px;margin:0}.editor-head button{display:flex;align-items:center;padding:7px}label{display:block;font-size:12px;color:var(--text-lo);margin:12px 0}input:not([type=checkbox]){display:block;box-sizing:border-box;width:100%;padding:8px 10px;border:1px solid #ffffff20;border-radius:7px;background:var(--bg-base);color:var(--text-hi);min-width:0;margin-top:5px}button{font:inherit;white-space:nowrap;padding:7px 11px;background:var(--bg-raised);border:1px solid #ffffff20;border-radius:7px;color:var(--text-hi);cursor:pointer}button:disabled{opacity:.45}.address-row{display:flex;gap:10px;align-items:end}.address-row label{flex:1;min-width:0;margin:0}.address-row button{flex-shrink:0}.name-field{width:220px;max-width:100%}.connection-grid{display:flex;flex-wrap:wrap;gap:12px 24px}.auth-options{margin:12px 0}.version-switch{display:flex;gap:8px;margin:12px 0}.version-switch [aria-pressed=true]{border-color:var(--accent);color:var(--accent)}.check{display:flex;gap:8px;align-items:center}.actions{display:flex;gap:10px;justify-content:flex-end;margin-top:18px}p{font-size:12px;line-height:1.7;color:var(--text-lo)}.check-result{margin:14px 0;padding:14px;border:1px solid #ffffff20;border-radius:8px;overflow-wrap:anywhere}textarea{display:block;width:100%;box-sizing:border-box;min-width:0;height:130px;margin-top:6px;padding:10px;background:var(--bg-base);color:var(--text-hi);border:1px solid #ffffff20;border-radius:7px;font-family:monospace}summary{cursor:pointer}code{white-space:normal;overflow-wrap:anywhere}.mask{position:fixed;inset:0;z-index:1000;background:#080c16b8;display:grid;place-items:center;padding:18px}.dialog{background:var(--bg-panel);padding:24px;border:1px solid #ffffff20;border-radius:14px;width:min(460px,100%)}.dialog button{margin-right:8px}</style>
