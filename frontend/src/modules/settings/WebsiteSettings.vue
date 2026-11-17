<script setup lang="ts">
import {ref,watch,onBeforeUnmount,nextTick,computed} from 'vue';
import {getWebsite,deleteWebsite,websiteError,type Website} from '../../api/integrations';
import HelpHint from './HelpHint.vue';
import {checkWebsiteDraft,saveWebsiteDraft,getWebsiteSaveReceipt,type WebsiteSaveResult,type ConnectionDraft,type WebsiteDraft,type WebsiteCheck} from '../../api/websiteSettings';
import {websiteSaveKey} from '../../api/websiteSaveKey';
import Icon from '../../shell/Icon.vue';
import Dropdown from '../../shell/Dropdown.vue';
import IconPicker from './IconPicker.vue';
import WebsiteAccessGuide from './WebsiteAccessGuide.vue';
import {loadNavigation,navigationRows,navigationEpoch,mergeNavigationSnapshot,resetNavigation} from '../../stores/navigation';
import {effectiveWebsiteBackground,confirmWebsiteBackground} from '../../stores/websiteBackground';
import {toast} from '../../composables/useToast';
const props=defineProps<{id?:string}>();
const emit=defineEmits<{dirty:[value:boolean];cancel:[];saved:[];busy:[value:boolean]}>();
const fresh=():WebsiteDraft=>({address:'',address_mode:'domain',alternate_address:null,private_address:null,entry_policy:'follow',access_adapter:'auto',name:'',icon:'globe',visible:true,keep_alive:true,open_behavior:'embedded',custom:{enabled:false,css:'',js:'',timing:'dom_ready'},template_id:null,connection:{transport:'auto',auth_mode:'original',header_name:'Authorization',token:null,clear_token:false,injection_delivery:'proxy'},background:'solid'});
const input=ref(fresh()),original=ref(JSON.stringify(input.value)),selected=ref<Website|null>(null);
const backgroundTouched=ref(false);
function inferAddressMode(address:string):'ip'|'domain'{try{const host=new URL(address).hostname;return host.includes(':')||/^\d+\.\d+\.\d+\.\d+$/.test(host)?'ip':'domain';}catch{return 'domain';}}
// A legacy registry mapping is not represented by the optional input fields.
// Preserve it on unrelated edits, but explicit address/mode edits adopt the
// complete visible mapping (including null for an intentionally empty other).
const legacyMappingTouched=ref(false),mappingEdited=ref(false);
function editMapping(field:'address'|'alternate'|'mode'){
 if(field!=='address'&&selected.value&&!selected.value.mapping_configured)legacyMappingTouched.value=true;
 const prior=JSON.parse(original.value) as WebsiteDraft;
 // Only user events establish mapping intent, never a check's normalization.
 mappingEdited.value=legacyMappingTouched.value||input.value.address!==prior.address||input.value.address_mode!==prior.address_mode||(input.value.alternate_address||null)!==(prior.alternate_address||null);
}
const retainedLegacyMapping=computed(()=>!!selected.value&&!selected.value.mapping_configured&&!mappingEdited.value);
function mappingDraft():Pick<WebsiteDraft,'address_mode'|'alternate_address'>{
 return !selected.value||mappingEdited.value?{address_mode:input.value.address_mode,alternate_address:input.value.alternate_address||null}:{};
}
const legacyBackground=computed(()=>effectiveWebsiteBackground(selected.value).legacy);
function chooseBackground(value:string|number|boolean){if(value==='home'||value==='solid'){input.value.background=value;backgroundTouched.value=true;}}
const result=ref<WebsiteCheck|null>(null),stale=ref(false),busy=ref(false),checking=ref(false),message=ref(''),loadFailed=ref(false);
let generation=0,alive=true,controller:AbortController|undefined;
const nameEdited=ref(false),codeOpen=ref(false);
const effectiveAdapter=computed<'generic'|'openlist'|'immich'>(()=>input.value.access_adapter&&input.value.access_adapter!=='auto'?input.value.access_adapter:result.value?.software?.type==='openlist'||result.value?.software?.type==='immich'?result.value.software.type:input.value.template_id==='openlist'||input.value.template_id==='immich'?input.value.template_id:'generic');
const mainOrigin=window.location.origin;
const softwareUnknown=computed(()=>!!result.value&&!stale.value&&(!result.value.software||result.value.software.type==='unknown'));
const connection=computed<ConnectionDraft>(()=>input.value.connection||{transport:selected.value?.mode==='isolated_proxy'?'proxy':'auto',auth_mode:'original',header_name:'Authorization',injection_delivery:'proxy',token:null,clear_token:false});
const customHeaderOpen=ref(false);
function setConnection(field:keyof ConnectionDraft,value:unknown){
 if(field==='auth_mode'&&value==='header'&&input.value.open_behavior==='external'){message.value='请先选择「改为 Stella 内打开」，保存前会检查能否嵌入。';return;}
 if(field==='transport'&&value==='direct'&&connection.value.auth_mode==='header')return;
 const next={...connection.value,[field]:value};
 if(field==='transport'&&value==='direct'||field==='injection_delivery'&&value==='loader'){
  next.injection_delivery='loader';
  if(field==='injection_delivery')next.transport='direct';
  if(next.auth_mode==='header'){next.auth_mode='original';message.value='原站直连不发送 Header 凭据，已改为原站登录。';}
 }
 if(field==='transport'&&value==='proxy'||field==='injection_delivery'&&value==='proxy'){
  next.injection_delivery='proxy';if(next.transport==='direct')next.transport='proxy';
 }
 if(field==='auth_mode'&&value==='header'){if(next.transport==='direct')next.transport='proxy';next.injection_delivery='proxy';}
 if(field==='transport'&&value==='auto')next.injection_delivery='proxy';
 input.value.connection=next;
}
const copyCode=(code:WebsiteDraft['custom']|null)=>({enabled:code?.enabled??false,css:code?.css||'',js:code?.js||'',timing:code?.timing||'dom_ready' as const});
const dirty=computed(()=>backgroundTouched.value||mappingEdited.value||JSON.stringify({...input.value,alternate_address:input.value.alternate_address||null})!==original.value);
const distinctDraft=computed(()=>!!selected.value?.injection?.draft&&JSON.stringify(copyCode(selected.value.injection.draft))!==JSON.stringify(copyCode(selected.value.injection.active)));
const key=websiteSaveKey();
const ownerEpoch=navigationEpoch();
let editGeneration=0;
watch(input,()=>{editGeneration++;},{deep:true,flush:'sync'});
type MappingExpectation={alternateAddress:string|null;addressMode:'ip'|'domain'|null;configured:boolean};
const pending=ref<{id:string;payload:WebsiteDraft;retainedDraft?:WebsiteDraft['custom'];privateAddress:string|null;connection?:Website['connection'];mapping:MappingExpectation;submittedGeneration:number}|null>(null);
const uncertain=ref<(WebsiteDraft & {idempotency_key:string})|null>(null);
const deleting=ref(false),deletePending=ref(false);
let dialogTrigger:HTMLElement|null=null;
watch(deleting,async value=>{if(value){dialogTrigger=document.activeElement as HTMLElement;await nextTick();(document.querySelector('[aria-label="删除网站入口"][role="dialog"] button') as HTMLElement|null)?.focus();}else{await nextTick();dialogTrigger?.focus();dialogTrigger=null;}});
function trapDialog(event:KeyboardEvent){if(event.key!=='Tab')return;const buttons=Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));const first=buttons[0],last=buttons.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}
watch(()=>busy.value||!!pending.value||!!uncertain.value||deletePending.value,value=>emit('busy',value),{flush:'sync'});
async function commit(payload:WebsiteDraft & {idempotency_key:string}){
 const submittedGeneration=editGeneration;
 // Keep the detail's version with the submitted intent, not a later sidebar GET.
 if(props.id&&payload.expected_revision===undefined&&selected.value?.read_revision!==undefined)payload={...payload,expected_revision:selected.value.read_revision};
 const retainedDraft=payload.preserve_saved_draft?copyCode(selected.value?.injection?.draft):undefined;
 const privateAddress=payload.private_address===undefined?selected.value?.private_address||null:payload.private_address;
 const connection=selected.value?.connection?JSON.parse(JSON.stringify(selected.value.connection)) as Website['connection']:undefined;
 const mapping:MappingExpectation={alternateAddress:payload.alternate_address===undefined?selected.value?.alternate_address||null:payload.alternate_address,addressMode:payload.address_mode===undefined?selected.value?.address_mode||null:payload.address_mode,configured:payload.alternate_address!==undefined||selected.value?.mapping_configured===true};
 try{const item=await saveWebsiteDraft(props.id,payload);if(!alive||ownerEpoch!==navigationEpoch())return;uncertain.value=null;pending.value={id:item.id,payload,retainedDraft,privateAddress,connection,mapping,submittedGeneration};await reconcile(item);}
 catch(e){const status=(e as {status?:number}).status;if((status===401||status===403)&&ownerEpoch===navigationEpoch())resetNavigation();if(!status||status>=500||status===408){if(props.id){pending.value={id:props.id,payload,retainedDraft,privateAddress,connection,mapping,submittedGeneration};await reconcile();}else{uncertain.value=payload;message.value='保存结果不确定；请用同一幂等请求确认结果，不要重新创建。';}return;}throw e;}
}
async function confirmSave(){if(!uncertain.value||busy.value)return;busy.value=true;try{await commit(uncertain.value);}catch(e){message.value=websiteError(e);}finally{if(alive)busy.value=false;}}
async function reconcile(ack?:WebsiteSaveResult){
 if(!pending.value)return;busy.value=true;
 try{const {id,payload}=pending.value;const readback=ack||await getWebsiteSaveReceipt(id,(payload as WebsiteDraft & {idempotency_key:string}).idempotency_key);if(!alive||ownerEpoch!==navigationEpoch())return;
  if(readback.id!==id||readback.idempotency_key!==(payload as WebsiteDraft & {idempotency_key:string}).idempotency_key)throw new Error('保存回执不匹配');
  const expectedAddress=new URL(payload.address.includes('://')?payload.address:'https://'+payload.address);
  if(new URL(readback.browser_url).href!==expectedAddress.href||readback.name!==(payload.name||readback.name)||readback.icon!==payload.icon||(payload.keep_alive!==undefined&&(readback.keep_alive===true)!==payload.keep_alive)||(readback.mode==='link')!==(payload.open_behavior==='external'))throw new Error('保存内容回读不一致');
  if(payload.background!==undefined&&readback.background!==payload.background)throw new Error('背景回读不一致');
  if((readback.private_address||null)!==pending.value.privateAddress||(readback.entry_policy||'follow')!==(payload.entry_policy||'follow'))throw new Error('入口回读不一致');
  const expectedMapping=pending.value.mapping;
  if((readback.alternate_address||null)!==expectedMapping.alternateAddress||(readback.address_mode||null)!==expectedMapping.addressMode||(readback.mapping_configured===true)!==expectedMapping.configured)throw new Error('网站地址映射回读不一致');
  if(payload.access_adapter!==undefined&&(readback.access_adapter||'auto')!==payload.access_adapter)throw new Error('网站类型回读不一致');
  if(payload.template_id!==undefined&&readback.template_id!==payload.template_id)throw new Error('原设置回读不一致');
  if(payload.connection){const saved=readback.connection;if(!saved||(['transport','auth_mode','header_name','injection_delivery'] as const).some(field=>saved[field]!==payload.connection![field]))throw new Error('连接回读不一致');if(payload.connection.clear_token&&saved.has_token||payload.connection.token&&!payload.connection.clear_token&&!saved.has_token)throw new Error('凭据状态回读不一致');}
  if(!payload.connection&&pending.value.connection){const saved=readback.connection,expected=pending.value.connection;if(!saved||(['transport','auth_mode','header_name','injection_delivery','has_token'] as const).some(field=>saved[field]!==expected[field]))throw new Error('原连接回读不一致');}
  if(payload.request_policy){const policy=readback.request_policy;if(!policy||policy.protect_other_writes!==payload.request_policy.protect_other_writes||JSON.stringify(policy.management_prefixes)!==JSON.stringify(payload.request_policy.management_prefixes)||JSON.stringify(policy.read_post_paths)!==JSON.stringify(payload.request_policy.read_post_paths))throw new Error('请求策略回读不一致');}
  if(payload.custom){
   const draft=readback.injection?.draft,active=readback.injection?.active;
   const expectedDraft=payload.preserve_saved_draft?pending.value.retainedDraft:payload.custom;
   if(!draft||!expectedDraft||(['enabled','css','js','timing'] as const).some(field=>draft[field]!==expectedDraft[field]))throw new Error('代码草稿回读不一致');
   if((payload.custom.enabled||payload.custom.css||payload.custom.js||payload.preserve_saved_draft)&&(!active||(['enabled','css','js','timing'] as const).some(field=>active[field]!==payload.custom![field])))throw new Error('生效代码回读不一致');
   if(!payload.custom.enabled&&active?.enabled)throw new Error('停用状态回读不一致');
  }
  if(!alive)return;mergeNavigationSnapshot(readback.navigation,ownerEpoch);selected.value={...readback,read_revision:readback.navigation.revision};
  const row=navigationRows.value.find(x=>x.id===id);if(!row||row.label!==readback.name||row.icon!==payload.icon||row.visible!==payload.visible)throw new Error('导航显示回读不一致');
  if(payload.background!==undefined)confirmWebsiteBackground(readback);
  if(editGeneration!==pending.value.submittedGeneration){pending.value=null;message.value='已确认本次提交，后续修改尚未保存';return;}
  pending.value=null;message.value='';toast('网站已保存');emit('dirty',false);emit('saved');
 }catch{if(alive)message.value='保存结果尚未确认；保留草稿，请重试回读，不要重复提交。';}
 finally{if(alive)busy.value=false;}
}
watch(dirty,value=>emit('dirty',value),{flush:'sync'});

watch(()=>[input.value.address,input.value.address_mode,input.value.alternate_address,input.value.entry_policy,input.value.open_behavior,JSON.stringify(input.value.custom),JSON.stringify(input.value.connection)],()=>{generation++;controller?.abort();checking.value=false;if(result.value)stale.value=true;},{flush:'sync'});
async function read(){
 if(!props.id)return;
 busy.value=true;loadFailed.value=false;
 try{const item=await getWebsite(props.id);if(!alive)return;selected.value=item;
  // A historical saved draft is not the currently applied code.
  const custom=item.injection?.active;
  input.value={address:item.browser_url,address_mode:item.address_mode||inferAddressMode(item.browser_url),alternate_address:item.mapping_configured?item.alternate_address||null:item.mode==='isolated_proxy'?null:item.private_address||null,private_address:item.private_address||null,entry_policy:item.entry_policy||'follow',access_adapter:item.access_adapter||'auto',name:navigationRows.value.find(x=>x.id===item.id)?.label||item.name,icon:navigationRows.value.find(x=>x.id===item.id)?.icon||item.icon,visible:navigationRows.value.find(x=>x.id===item.id)?.visible??true,open_behavior:item.mode==='link'?'external':'embedded',custom:copyCode(custom),template_id:item.template_id,connection:item.connection?{transport:item.connection.transport,auth_mode:item.connection.auth_mode,header_name:item.connection.header_name,injection_delivery:item.connection.injection_delivery,token:null,clear_token:false}:undefined,background:effectiveWebsiteBackground(item).mode,request_policy:item.request_policy};
  codeOpen.value=false;customHeaderOpen.value=!!item.connection&&item.connection.auth_mode==='header'&&item.connection.header_name!=='Authorization';
  backgroundTouched.value=false;legacyMappingTouched.value=false;mappingEdited.value=false;original.value=JSON.stringify(input.value);nameEdited.value=true;emit('dirty',false);
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
 try{const current=await checkWebsiteDraft({address:input.value.address,...mappingDraft(),open_behavior:input.value.open_behavior,custom_enabled:input.value.custom?.enabled===true,connection:input.value.connection,module_id:props.id,...(input.value.access_adapter==='openlist'||input.value.access_adapter==='immich'?{website_type:input.value.access_adapter}:{})},controller.signal);
  if(!alive||seq!==generation)return null;
  // Rejected/invalid normalization must never erase the user's address draft.
  try{const normalized=new URL(current.normalized_url);if(['http:','https:'].includes(normalized.protocol)&&normalized.hostname)input.value.address=current.normalized_url;}catch{/* Keep the original address and show the structured check below. */}
  if(current.alternate_normalized_url){try{const normalized=new URL(current.alternate_normalized_url);if(['http:','https:'].includes(normalized.protocol)&&normalized.hostname)input.value.alternate_address=current.alternate_normalized_url;}catch{/* Retain the exact alternate draft on failed validation. */}}
  if(!nameEdited.value&&!input.value.name)input.value.name=current.name_suggestion;
  result.value=current;stale.value=false;return current;
 }catch(e){if(alive&&seq===generation)message.value=websiteError(e);return null;}
 finally{if(alive&&seq===generation)checking.value=false;}
}
async function remove(){if(!props.id||busy.value)return;busy.value=true;
 try{if(!deletePending.value){await deleteWebsite(props.id);deletePending.value=true;}
  try{await getWebsite(props.id);throw new Error('删除回读不一致');}catch(e){if((e as {status?:number}).status!==404)throw e;}
  if(!alive)return;if(!await loadNavigation({force:true}))throw new Error('导航回读失败');if(!alive)return;if(navigationRows.value.some(row=>row.id===props.id))throw new Error('删除导航回读不一致');deleting.value=false;message.value='';toast('网站入口已删除');emit('dirty',false);emit('saved');
 }catch{if(alive)message.value='删除结果尚未确认，请重试回读；不删除原网站数据。';}finally{if(alive)busy.value=false;}}
async function save(){
 if(busy.value||checking.value||loadFailed.value||pending.value||uncertain.value)return;busy.value=true;
 try{
  // Initial OpenList compatibility generates content, unlike ordinary saves.
  // Keep its one necessary diagnostic; the server still owns save validation.
  if(!selected.value&&input.value.open_behavior==='embedded'&&effectiveAdapter.value==='openlist'&&!input.value.custom?.css&&!input.value.custom?.js){
   const check=await detect();if(!check)return;
   if(check.compatibility&&check.injection.status==='supported')input.value.custom=copyCode(check.compatibility);
  }
  const payload:WebsiteDraft & {idempotency_key:string}={...JSON.parse(JSON.stringify(input.value)),name:input.value.name?.trim()||undefined,idempotency_key:key};
  delete payload.alternate_address;delete payload.address_mode;Object.assign(payload,mappingDraft());
  // Do not rewrite legacy flags on edit; readback checks only fields actually sent.
  if(selected.value)delete payload.keep_alive;
  // Generated proxy entries belong to the registry. Omission preserves legacy
  // values; explicit null would delete them. Unedited direct alternatives also stay untouched.
  delete payload.private_address;
  // Unchanged transport/auth/header metadata must not be republished. Explicit
  // token/login edits still send the complete compatible DTO (the API is not a nested PATCH).
  if(selected.value&&JSON.stringify(input.value.connection)===JSON.stringify(JSON.parse(original.value).connection))delete payload.connection;
  if(selected.value&&!backgroundTouched.value&&input.value.background===JSON.parse(original.value).background)delete payload.background;
  // A metadata-only edit must not overwrite a distinct saved draft with the active copy.
  if(selected.value&&JSON.stringify(input.value.custom)===JSON.stringify(JSON.parse(original.value).custom))delete payload.custom;
  if(payload.custom&&distinctDraft.value)payload.preserve_saved_draft=true;
  await commit(payload);
 }catch(e){if(!alive)return;const detail=(e as {detail?:{code?:string;check?:WebsiteCheck}}).detail;
  if(detail?.code==='website_check_failed'&&detail.check){result.value=detail.check;stale.value=false;message.value='保存时重新检测未通过，修改已保留。';}
  else message.value=e instanceof Error&&!(e as {status?:number}).status?e.message:websiteError(e);
 }finally{if(alive)busy.value=false;}
}
</script>
<template>
<form class="inline-editor" @submit.prevent="save">
 <header class="editor-head"><h3>{{id?'编辑网站':'添加网站'}}</h3><button class="st-button" type="button" aria-label="收起编辑" :disabled="busy||!!pending||!!uncertain||deletePending" @click="emit('cancel')"><Icon name="x" :size="18"/></button></header>
 <fieldset :disabled="busy||loadFailed||!!pending||!!uncertain||deletePending">
  <div class="identity-grid">
   <div class="website-setting-row"><span>地址模式</span><Dropdown :model-value="input.address_mode||'domain'" :options="[{value:'ip',label:'私网 IP / 端口'},{value:'domain',label:'域名'}]" @update:model-value="input.address_mode=$event as 'ip'|'domain';editMapping('mode')" /></div>
   <div class="website-setting-row"><label for="website-address">默认入口地址</label><div class="address-row"><input id="website-address" v-model="input.address" aria-label="网站地址" :placeholder="input.address_mode==='ip'?'http://192.168.1.10:8080':'https://example.com'" @input="editMapping('address')" /><button class="st-button" type="button" :disabled="checking" @click="detect">{{checking?'检测中…':'检测'}}</button></div></div>
   <div class="website-setting-row alternate-row"><label for="website-alternate">其他入口地址</label><div><input id="website-alternate" v-model="input.alternate_address" aria-label="其他入口地址" :placeholder="input.address_mode==='ip'?'可选，如 http://10.0.0.10:8080':'可选，如 https://other.example.com'" @input="editMapping('alternate')" /><p v-if="retainedLegacyMapping" class="mapping-help">沿用旧入口映射，未在此完整展示。修改地址或模式后按这两个地址保存。</p><p v-else class="mapping-help">保存后，其他地址留空则两个 Stella 入口共用默认地址。</p></div></div>
   <div class="website-setting-row"><label for="website-name">显示名称</label><input id="website-name" class="short-input" v-model="input.name" aria-label="显示名称" maxlength="80" placeholder="可选，自动识别" @input="nameEdited=true" /></div>
  </div>
  <div class="website-setting-row website-identity"><span>图标</span><IconPicker v-model="input.icon" :name="input.name||''"/></div>
  <div class="website-setting-row"><span class="row-label">入口选择<HelpHint label="网站入口选择说明">跟随当前：使用当前已登记 Stella 入口对应的网站地址。固定默认：始终使用已部署的默认入口（当前对应原公网入口）。不会自动测速或开通新域名。</HelpHint></span><Dropdown :model-value="input.entry_policy||'follow'" :options="[{value:'follow',label:'跟随当前 Stella 入口'},{value:'public',label:'始终使用默认入口'}]" @update:model-value="input.entry_policy=$event as 'follow'|'public'" /></div>
  <div v-if="input.open_behavior==='external'" class="legacy-link"><p>此旧入口仍按原方式打开，尚未转换。</p><button class="st-button" type="button" @click="input.open_behavior='embedded'">改为 Stella 内打开</button></div>
  <div class="connection-grid">
   <label>登录方式<Dropdown :model-value="connection.auth_mode" :options="[{value:'original',label:'原网站账号'},{value:'header',label:'服务端凭据'},{value:'oidc',label:'Stella 单点登录'}]" @update:model-value="setConnection('auth_mode',$event)" /></label>
   <label>背景<Dropdown :model-value="input.background||'solid'" :options="[{value:'solid',label:'纯色背景'},{value:'home',label:'主页背景图 / 视频'}]" @update:model-value="chooseBackground" /></label>
  </div>
  <p v-if="legacyBackground" role="status">当前背景沿用旧偏好，仅此设备生效；重新选择并保存后使用网站级设置。</p>
  <div v-if="connection.auth_mode==='header'" class="credential-fields">
   <label><span class="field-label">服务端凭据<HelpHint label="服务端凭据说明">默认使用 Authorization；原站要求 Bearer 时，凭据填入 Bearer 加空格及 Token。仅由 Stella 后端发送到原网站，不写入脚本。</HelpHint></span><input :value="connection.token||''" type="password" aria-label="Token" autocomplete="new-password" :placeholder="selected?.connection?.has_token?'已保存 · 留空保持':'例如 Bearer …'" @input="setConnection('token',($event.target as HTMLInputElement).value||null)" /></label>


  </div>
  <WebsiteAccessGuide :adapter="effectiveAdapter" :mode="selected?.mode||'iframe'" :main-origin="mainOrigin" :id="id" :custom-enabled="input.custom?.enabled===true" :delivery="connection.injection_delivery" :auth-mode="connection.auth_mode"/>

  <p v-if="stale" role="status">需重新检测</p>
  <section v-if="result&&!stale" class="check-result" aria-label="检测结果">
   <strong>{{result.embedding.reason}}</strong>
   <p v-if="result.access.status!=='reachable'">原站登录或页面内容尚未确认。</p>
   <p v-if="input.custom?.enabled||result.injection.status!=='loader_required'">{{result.injection.reason}}</p>
   <p v-for="issue in result.issues" :key="issue">{{issue}}</p>
   <details v-if="result.help" open><summary>{{result.help.title}}</summary><code v-if="result.help.location">{{result.help.location}}</code><p v-for="line in result.help.instructions" :key="line">{{line}}</p></details>
   <p v-if="result.software&&result.software.type!=='unknown'">已识别 {{result.software.type==='openlist'?'OpenList':'Immich'}}</p>
   <template v-if="softwareUnknown"><label>网站类型<Dropdown :model-value="input.access_adapter||'auto'" :options="[{value:'auto',label:'自动'},{value:'openlist',label:'OpenList'},{value:'immich',label:'Immich'}]" @update:model-value="input.access_adapter=$event as WebsiteDraft['access_adapter']" /></label><p class="field-help">未能识别时可指定；不会替换现有代码或凭据。</p></template>
  </section>
  <details v-if="connection.auth_mode==='header'" class="header-options" :open="customHeaderOpen" @toggle="customHeaderOpen=($event.target as HTMLDetailsElement).open"><summary>自定义请求头</summary>
   <label><span class="field-label">请求头名称<HelpHint label="自定义请求头说明">通常无需修改；仅原站明确要求 X-API-Key 或 X-Auth-Token 时覆盖 Authorization。</HelpHint></span><input :value="connection.header_name" aria-label="自定义请求头" placeholder="Authorization" @input="setConnection('header_name',($event.target as HTMLInputElement).value)" /></label>
  </details>
<details v-if="input.custom" class="custom" :open="codeOpen" @toggle="codeOpen=($event.target as HTMLDetailsElement).open">
   <summary>自定义外观与脚本（可选）</summary>
   <div class="code-help"><label class="check"><input v-model="input.custom.enabled" type="checkbox"/>启用自定义代码</label><HelpHint label="网站代码保存说明">这里是当前应用的代码。修改只保留在本次编辑中，点击下方「保存」网站后才会生效；代码只在目标网站执行，请勿填入密码或 Token。</HelpHint><HelpHint v-if="distinctDraft" label="已保留旧草稿说明">另有旧版未应用内容保留在服务器；这里不会用它替换当前代码，保存此网站也会保留那份内容。</HelpHint><HelpHint v-if="input.background==='home'" label="网站背景说明">主页背景显示在网站外层；透明效果仍由下方 CSS / JavaScript 配合。</HelpHint></div>
   <label>自定义 CSS<textarea v-model="input.custom.css" aria-label="自定义 CSS" spellcheck="false" /></label>
   <label>自定义 JavaScript<textarea v-model="input.custom.js" aria-label="自定义 JavaScript" spellcheck="false" /></label>
   <details class="script-options"><summary>脚本运行时机</summary><HelpHint label="脚本运行时机说明">CSS 尽早加入页面；JavaScript 默认等页面节点就绪。开始加载时可能还没有页面节点。</HelpHint><label>运行时机<Dropdown :model-value="input.custom.timing" :options="[{value:'dom_ready',label:'页面就绪后（推荐）'},{value:'document_start',label:'页面开始加载时'}]" @update:model-value="input.custom.timing=$event as 'dom_ready'|'document_start'" /></label></details>
  </details>
  <footer class="actions"><button v-if="id" class="delete-action st-button is-danger is-icon" type="button" aria-label="删除网站入口" title="删除网站入口" @click="deleting=true"><Icon name="trash" :size="18"/></button><button class="st-button" type="button" @click="emit('cancel')">取消</button><button class="primary st-button is-primary" type="submit">保存</button></footer>
 </fieldset>
 <p v-if="message" role="alert">{{message}}</p><button class="st-button" v-if="uncertain" type="button" :disabled="busy" @click="confirmSave">确认保存结果</button><button class="st-button" v-if="pending" type="button" :disabled="busy" @click="reconcile()">重试回读</button><button class="st-button" v-if="loadFailed" type="button" @click="read">重试读取</button>
 <Teleport to="body"><div v-if="deleting" class="mask" @keydown="trapDialog" @keydown.esc="!busy&&!deletePending&&(deleting=false)"><section role="dialog" aria-modal="true" aria-label="删除网站入口" class="dialog"><h3>删除「{{input.name||input.address}}」入口？</h3><p>仅移除 Stella 中的网站入口与配置，不删除原网站数据。</p><div class="actions"><button class="st-button" type="button" :disabled="busy||deletePending" @click="deleting=false">取消</button><button class="danger st-button is-danger" type="button" :disabled="busy" @click="remove">{{deletePending?'重试删除回读':'确认删除入口'}}</button></div></section></div></Teleport>
</form>
</template>
<style scoped>
.mapping-help{margin:5px 0 0;font-size:12px;color:var(--text-lo)}.alternate-row>div{min-width:0}
.field-label,.code-help{display:flex;align-items:center;gap:6px}.inline-editor{padding:16px 0 20px;margin:10px 0 20px;border-block:1px solid var(--control-border);min-width:0;font-size:14px;line-height:1.6;color:var(--text-hi)}fieldset{border:0;padding:0;margin:0;min-width:0}.editor-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}.editor-head h3{font-size:16px;margin:0}.editor-head button,.delete-action{width:38px;padding:0;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0}label{display:block;font-size:14px;color:var(--text-lo);margin:10px 0;min-width:0}input:not([type=checkbox]){display:block;box-sizing:border-box;width:100%;padding:7px 10px;min-height:38px;border:1px solid var(--control-border);border-radius:7px;background:var(--bg-base);color:var(--text-hi);font:inherit;min-width:0;margin-top:5px}.identity-grid{display:grid;grid-template-columns:minmax(150px,220px) minmax(0,1fr);gap:16px;margin:14px 0}.identity-grid label{margin:0}.address-row{display:flex;gap:8px;align-items:end;min-width:0}.address-row label{flex:1;min-width:0}.website-identity{margin:14px 0;min-width:0}.website-identity :deep(.preview-row){margin:0}.connection-grid{display:grid;grid-template-columns:repeat(3,minmax(0,220px));gap:12px}.connection-grid :deep(.dd-btn){min-height:38px;font-size:14px}.credential-fields{display:grid;grid-template-columns:minmax(120px,180px) minmax(0,320px);gap:0 12px}.credential-fields p{grid-column:1/-1;margin-top:0}.header-options,.custom{margin:8px 0;border-top:1px solid var(--control-border);padding-top:6px}.check{display:flex;gap:8px;align-items:center;min-height:38px}.check input{flex-shrink:0}.website-row{display:flex;gap:16px;align-items:center;justify-content:space-between;min-width:0;padding:10px 0;flex-wrap:wrap}.row-label{display:flex;align-items:center}.actions{display:flex;gap:10px;justify-content:flex-end;align-items:center;margin-top:18px}.delete-action{margin-right:auto}p,.field-help{font-size:14px;line-height:1.7;color:var(--text-lo);overflow-wrap:anywhere}p{margin:8px 0}.field-help{display:block}summary{font-size:14px;cursor:pointer;min-height:38px;align-content:center}textarea{display:block;width:100%;box-sizing:border-box;min-height:160px;resize:vertical;margin-top:6px;padding:12px;background:var(--bg-base);color:var(--text-hi);border:1px solid var(--control-border);border-radius:7px;font:13px/1.65 ui-monospace,monospace;tab-size:2}.custom>p{max-width:68ch}.script-options{margin-top:12px}.check-result{padding:12px 0;border-block:1px solid var(--control-border);margin:12px 0}.mask{position:fixed;inset:0;z-index:1000;background:#0009;display:grid;place-items:center;padding:16px}.dialog{box-sizing:border-box;background:var(--bg-panel);padding:24px;width:min(460px,100%);border:1px solid var(--control-border);border-radius:12px}.dialog h3{margin:0;font-size:18px}input:focus-visible,textarea:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}.inline-editor .st-button{min-height:38px}.inline-editor :deep(button:not(.st-button)){min-height:38px;font-size:14px}.inline-editor :deep(.help-hint){padding:0;border:0;background:transparent;width:36px;min-height:36px}.inline-editor :deep(.dd){min-width:0;max-width:100%}.inline-editor :deep(.dd-btn){min-width:0;max-width:100%}.inline-editor :deep(.dd-menu){max-width:min(360px,calc(100vw - 64px));min-width:0}.inline-editor :deep(.dd-item-label){white-space:normal;overflow-wrap:anywhere}.inline-editor :deep(.preview-label){font-size:14px}.inline-editor :deep(.preview-row){max-width:100%}.inline-editor :deep(.sidebar-preview){min-width:0;max-width:100%}
@media(max-width:600px){.inline-editor .st-button,.inline-editor :deep(button:not(.st-button)){min-height:44px}.inline-editor :deep(.help-hint){width:44px;min-height:44px}.inline-editor{padding:12px 0}.identity-grid{grid-template-columns:minmax(0,1fr);gap:10px}.connection-grid{grid-template-columns:minmax(0,1fr);gap:0}.credential-fields{grid-template-columns:minmax(0,1fr)}input:not([type=checkbox]),.connection-grid :deep(.dd-btn),.editor-head button,.delete-action{min-height:44px}.editor-head button,.delete-action{width:44px}summary,.check{min-height:44px}.actions{gap:8px}.actions button{flex-shrink:0}}
.identity-grid,.connection-grid,.credential-fields{display:block;margin:0}.website-setting-row,.connection-grid>label,.credential-fields>label,.entry-options>label{display:grid;grid-template-columns:minmax(140px,1fr) minmax(0,380px);gap:16px;align-items:center;padding:12px 0;margin:0;border-bottom:1px solid var(--control-border)}.website-setting-row>label{margin:0}.website-setting-row>span{color:var(--text-lo)}.website-setting-row input{margin:0}.short-input{max-width:220px}.address-row{align-items:center}.address-row>input{flex:1;min-width:0}.address-row>button{flex:none}.website-identity :deep(.preview-label){display:none}.website-identity :deep(.sidebar-preview){padding:6px 8px}.website-identity{margin:0}.credential-fields>p{margin-top:8px}.entry-options>p{max-width:68ch}.header-options>label{display:grid;grid-template-columns:minmax(140px,1fr) minmax(0,380px)}
@media(max-width:600px){.website-setting-row,.connection-grid>label,.credential-fields>label,.entry-options>label,.header-options>label{grid-template-columns:minmax(0,1fr);gap:6px;padding:10px 0}.short-input{max-width:100%}.website-identity :deep(.preview-row){gap:0}.website-identity :deep(.icon-picker){gap:10px}.credential-fields>p{margin-bottom:10px}}

</style>
