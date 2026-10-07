<script setup lang="ts">
import {ref,computed,watch,onBeforeUnmount} from 'vue';
import {getServiceSettings,putServiceSettings,checkServiceSettings,matchesService,type CustomCode,type ServicePayload,type ServiceSettings,type ServiceSite,type DriveConnection,type GalleryConnection} from '../../api/serviceSettings';
import {validateBuiltin,rollbackBuiltin} from '../../api/builtinInjection';
import {navigation} from '../../stores/navigation';
import {readDriveBackground,saveDriveBackground} from '../drive/driveBackground';
import ServiceAppearancePreview from './ServiceAppearancePreview.vue';
import IconPicker from './IconPicker.vue';
import Dropdown from '../../shell/Dropdown.vue';
const props=defineProps<{site:ServiceSite}>();
const emit=defineEmits<{dirty:[value:boolean];busy:[value:boolean];saved:[];cancel:[]}>();
const data=ref<ServiceSettings|null>(null),message=ref(''),busy=ref(false),token=ref(''),clearToken=ref(false);
const background=ref(readDriveBackground()),originalBackground=ref(background.value);
function saveBackground(){try{saveDriveBackground(background.value);originalBackground.value=background.value;message.value='背景已保存，仅当前设备生效。';return true;}catch{message.value='本机存储不可用，背景尚未保存。';return false;}}
type Pending={kind:'save';payload:ServicePayload;uncertain:boolean}|{kind:'draft';code:CustomCode}|{kind:'rollback';version:string};
const pending=ref<Pending|null>(null),original=ref(''),readConfirmed=ref(false);
function resumeEditing(){if(busy.value||!readConfirmed.value)return;pending.value=null;message.value='已读取服务端当前状态，保留本地输入继续编辑；未再次发送修改。';}
const custom=ref<CustomCode>({enabled:false,css:'',js:'',timing:'dom_ready',csp_policy:'reject'}),originalCustom=ref(''),applyDraft=ref(false);
const customDirty=computed(()=>JSON.stringify(custom.value)!==originalCustom.value);
const copyCode=(code:ServiceSettings['injection']['active']|CustomCode):CustomCode=>({enabled:code.enabled,css:code.css,js:code.js,timing:code.timing,csp_policy:'reject'});
const checking=ref(false),checkMessage=ref('');let checkGeneration=0;
watch(()=>JSON.stringify(payload(false)?.connection),()=>{checkGeneration++;if(checking.value||checkMessage.value)checkMessage.value='需重新检测';checking.value=false;},{flush:'sync'});
async function detect(){
 if(!valid()||checking.value)return;const generation=++checkGeneration;checking.value=true;checkMessage.value='';
 try{const result=await checkServiceSettings(props.site,payload(false)!.connection);if(alive&&generation===checkGeneration)checkMessage.value=(result.message|| (result.ok?'服务端可访问':'服务端检测未通过'))+'；浏览器嵌入与登录状态尚未确认。';}
 catch(e){if(alive&&generation===checkGeneration)checkMessage.value=describe(e);}
 finally{if(alive&&generation===checkGeneration)checking.value=false;}
}
const locked=computed(()=>busy.value||!!pending.value);
watch(locked,value=>emit('busy',value),{flush:'sync'});
const drive=computed(()=>data.value!.connection as DriveConnection);
const gallery=computed(()=>data.value!.connection as GalleryConnection);
function payload(includeCustom=true):ServicePayload|null {
 if(!data.value)return null;
 return {name:data.value.name.trim(),icon:data.value.icon,visible:data.value.visible,
 connection:props.site==='drive'?{service_url:drive.value.service_url.trim(),auth_mode:drive.value.auth_mode,token:token.value||null,clear_token:clearToken.value}:{...gallery.value},appearance:{...data.value.appearance},...(includeCustom&&(customDirty.value||applyDraft.value)?{custom:{...custom.value}}:{})};
}
const dirty=computed(()=>!!data.value&&(JSON.stringify(payload(false))!==original.value||customDirty.value||background.value!==originalBackground.value));
watch(dirty,value=>emit('dirty',value),{flush:'sync'});
function describe(error:unknown){const d=(error as {detail?:unknown})?.detail;return typeof d==='string'?d:'设置未保存，请检查输入后重试。';}
function valid(){
 const current=payload();if(!current||!current.name){message.value='请填写显示名称';return false;}
 const urls=props.site==='drive'?[drive.value.service_url]:[gallery.value.browser_url,gallery.value.upstream_url,gallery.value.alternate_browser_url].filter(Boolean);
 try{for(const value of urls){const u=new URL(value);if(!['http:','https:'].includes(u.protocol)||u.username||u.password)throw Error();}}
 catch{message.value='请输入有效的 HTTP / HTTPS 地址，不要在地址里填写凭据。';return false;}
 if(props.site==='drive'&&token.value&&clearToken.value){message.value='填写新 Token 和清除 Token 不能同时选择。';return false;}
 return true;
}
async function reconcile(){
 if(!pending.value)return;busy.value=true;readConfirmed.value=false;
 try{
  const readback=await getServiceSettings(props.site);if(!alive)return;
  readConfirmed.value=true;const current=pending.value;
  if(current.kind==='draft'){
   if(!readback.injection.draft||Object.entries(current.code).some(([k,v])=>(readback.injection.draft as unknown as Record<string,unknown>)[k]!==v))throw Error('draft mismatch');
   data.value!.injection=readback.injection;originalCustom.value=JSON.stringify(custom.value);applyDraft.value=true;pending.value=null;message.value='草稿已保存并回读，尚未执行；主保存将应用本次编辑的代码。';return;
  }
  if(current.kind==='rollback'){
   if(readback.injection.active.version!==current.version)throw Error('version mismatch');
   data.value!.injection=readback.injection;applyDraft.value=false;pending.value=null;message.value='回退已回读；活动版本已更新，已保存草稿保持不变。';return;
  }
  if(!matchesService(readback,current.payload))throw Error('mismatch');
  if(current.uncertain&&'token' in current.payload.connection&&current.payload.connection.token){message.value='非敏感设置已回读，但无法通过脱敏结果确认新 Token；未自动重发。请核对连接后继续编辑。';return;}
  const existing=navigation.entries.find(x=>x.id===props.site);
  const entry={id:props.site,title:readback.name,icon:readback.icon,visible:readback.visible};
  if(existing)Object.assign(existing,entry);else navigation.entries.push(entry);
  if(props.site==='drive'&&background.value!==originalBackground.value&&!saveBackground())return;
  pending.value=null;emit('dirty',false);emit('saved');
 }catch{if(alive)message.value='保存结果尚未确认，输入已保留；请重试回读，不会重复保存。';}
 finally{if(alive)busy.value=false;}
}
async function save(){
 if(locked.value||!valid())return;busy.value=true;message.value='';
 const current=JSON.parse(JSON.stringify(payload())) as ServicePayload;
 try{await putServiceSettings(props.site,current);if(!alive)return;pending.value={kind:'save',payload:current,uncertain:false};}
 catch(e){if(!alive)return;const status=(e as {status?:number}).status;if(!status||status>=500||status===408)pending.value={kind:'save',payload:current,uncertain:true};else message.value=describe(e);}
 if(pending.value)await reconcile();
 if(alive)busy.value=false;
}
async function saveDraft(){
 if(locked.value)return;busy.value=true;message.value='';const code={...custom.value};
 try{const result=await validateBuiltin(props.site,code);if(!alive)return;if(!result.valid){message.value=result.errors.join('；')||'自定义校验失败';return;}pending.value={kind:'draft',code};}
 catch(e){if(!alive)return;const status=(e as {status?:number}).status;if(!status||status>=500||status===408)pending.value={kind:'draft',code};else message.value=describe(e);}
 finally{if(alive)busy.value=false;}
 if(pending.value)await reconcile();
}
async function rollback(){
 if(locked.value||dirty.value||!data.value?.injection.previous)return;
 busy.value=true;message.value='';const version=data.value.injection.previous.version;
 try{const result=await rollbackBuiltin(props.site);if(alive)pending.value={kind:'rollback',version:result.active.version};}
 catch(e){if(!alive)return;const status=(e as {status?:number}).status;if(!status||status>=500||status===408)pending.value={kind:'rollback',version};else message.value=describe(e);}
 finally{if(alive)busy.value=false;}
 if(pending.value)await reconcile();
}
let alive=true;
onBeforeUnmount(()=>{alive=false;});
async function read(){
 busy.value=true;emit('busy',true);message.value='';
 try{const result=await getServiceSettings(props.site);if(alive){data.value=result;custom.value=copyCode(result.injection.draft||result.injection.active);originalCustom.value=JSON.stringify(custom.value);original.value=JSON.stringify(payload(false));}}
 catch{if(alive)message.value='设置读取失败，请重试。';}
 finally{if(alive){busy.value=false;emit('busy',false);}}
}
void read();
</script>
<template><form class="service-editor inline-editor" @submit.prevent="save">
 <header><h3>{{site==='drive'?'OpenList':'Immich'}} · 接入服务</h3><button type="button" :disabled="locked" @click="emit('cancel')">收起编辑</button></header>
 <fieldset v-if="data" :disabled="locked">
  <h4>连接与登录</h4>
  <div class="identity-fields"><label class="name-field">显示名称<input v-model="data.name" aria-label="显示名称" maxlength="80" required/></label><IconPicker v-model="data.icon" :name="data.name"/></div>
  <template v-if="site==='drive'">
   <label>OpenList 服务地址<input v-model="drive.service_url" aria-label="OpenList 服务地址" required/></label>
   <label>登录方式<Dropdown v-model="drive.auth_mode" :options="[{value:'manual',label:'原站手动登录'},{value:'token',label:'服务端凭据免登录'}]"/></label>
   <div v-if="drive.auth_mode==='token'"><label>Token<input v-model="token" aria-label="Token" type="password" autocomplete="new-password" :placeholder="drive.has_token?'已保存，留空保持不变':'填写服务端凭据'"/></label><label class="check"><input v-model="clearToken" type="checkbox"/>清除已保存 Token</label></div>
  </template>
  <template v-else>
   <label>Immich 浏览器地址<input v-model="gallery.browser_url" aria-label="Immich 浏览器地址" required/></label>
   <label>登录方式<Dropdown v-model="gallery.auth_mode" :options="[{value:'manual',label:'原站手动登录'},{value:'oidc',label:'OIDC 单点登录'}]"/></label>
   <details><summary>备用入口与登录明细</summary><label>备用浏览器地址<input v-model="gallery.alternate_browser_url" aria-label="备用浏览器地址"/></label><label>健康检查地址<input v-model="gallery.upstream_url" aria-label="健康检查地址"/></label><template v-if="data.oidc"><p>{{data.oidc.client_registered?'Stella 客户端已登记':'Stella 客户端尚未登记'}}；登录方式仅选择已有流程，不会更改原站 OAuth 配置或账号绑定。</p><dl><dt>Issuer</dt><dd>{{data.oidc.issuer}}</dd><dt>Client ID</dt><dd>{{data.oidc.client_id}}</dd><dt>回调地址</dt><dd v-for="uri in data.oidc.redirect_uris" :key="uri">{{uri}}</dd></dl></template></details>
  </template>
  <button type="button" :disabled="checking" @click="detect">检测连接</button><p v-if="checkMessage" role="status">{{checkMessage}}</p>
  <section class="appearance" aria-label="外观"><h4>外观</h4>
   <template v-if="site==='drive'">
    <label class="check"><input v-model="data.appearance.theme" type="checkbox" true-value="stella" false-value="original" aria-label="Stella 主题"/>Stella 主题<span>关闭保留原站配色</span></label>
    <label class="check"><input v-model="data.appearance.simplified" type="checkbox" aria-label="简洁显示"/>简洁显示<span>整理品牌与布局</span></label>
    <p>主题与简洁显示仅作用于 Stella 嵌入内；不改变原站文件或视图偏好。</p>
    <div v-if="data.capabilities.background" class="device-background"><label class="check"><input v-model="background" type="checkbox" true-value="image" false-value="solid" aria-label="主页背景"/>主页背景<span>关闭使用纯色</span></label><p>背景仅保存在当前设备，支持主页图片或视频；不随账号同步。</p><button type="button" :disabled="background===originalBackground" @click="saveBackground">保存本机背景</button></div>
   </template>
   <template v-else><label class="check"><input v-model="data.appearance.logo" type="checkbox" true-value="stella" false-value="original" aria-label="Stella Logo"/>Stella Logo<span>关闭保留原 Logo</span></label><p>作用于整个原站域名，独立打开 Immich 也会生效。</p></template>
   <ServiceAppearancePreview :site="site" :appearance="data.appearance" :background="background"/>
  </section>
  <details class="advanced"><summary>高级自定义</summary>
   <p>主保存会校验并应用本次编辑的自定义；仅保存草稿不会执行。关闭自定义不影响必要兼容代码。请勿写入密码或 Token。</p>
   <label class="check"><input v-model="custom.enabled" type="checkbox" aria-label="启用自定义"/>启用自定义</label>
   <label>自定义 CSS<textarea v-model="custom.css" aria-label="自定义 CSS" spellcheck="false"/></label>
   <label>自定义 JavaScript<textarea v-model="custom.js" aria-label="自定义 JavaScript" spellcheck="false"/></label>
   <button type="button" @click="saveDraft">仅保存草稿</button>
   <details class="technical"><summary>执行时机、活动版本与兼容信息</summary>
    <label>执行时机<Dropdown v-model="custom.timing" :options="[{value:'dom_ready',label:'页面就绪后'},{value:'document_start',label:'页面开始时'}]"/></label>
    <p>当前活动：{{data.injection.active.version}}（{{data.injection.active.enabled?'启用':'停用'}}） · 上一版：{{data.injection.previous?.version||'无'}}</p>
    <label>活动版本 CSS<textarea :value="data.injection.active.css" aria-label="活动版本 CSS" readonly/></label>
    <label>活动版本 JavaScript<textarea :value="data.injection.active.js" aria-label="活动版本 JavaScript" readonly/></label>
    <p>编辑区：{{data.injection.draft?'已保存草稿（与活动版本分开）':'活动版本的副本'}}。</p>
    <button type="button" :disabled="dirty||!data.injection.previous" @click="rollback">回退上一版本</button><p v-if="dirty">回退前请先保存或放弃当前修改。</p>
    <p v-for="item in data.compatibility" :key="item">{{item}}</p>
   </details>
  </details>
  <div class="actions"><button type="button" @click="emit('cancel')">取消</button><button type="submit">保存</button></div>
 </fieldset>
 <button v-if="pending" type="button" :disabled="busy" @click="reconcile">重试回读</button>
 <button v-if="pending&&readConfirmed" type="button" :disabled="busy" @click="resumeEditing">继续编辑，不重发</button>
 <p v-if="message" role="alert">{{message}}</p><button v-if="!data&&!busy" type="button" @click="read">重试读取</button>
</form></template>
<style scoped>
.service-editor{padding:18px;margin:0 0 14px;background:var(--bg-base);border:1px solid #7085a94d;border-radius:10px;min-width:0}header{display:flex;align-items:center;justify-content:space-between;gap:12px}h3,h4{font-size:14px}h4{margin:20px 0 14px}fieldset{border:0;margin:0;padding:0;min-width:0}.identity-fields{display:flex;gap:20px;align-items:start;flex-wrap:wrap}.identity-fields .icon-picker{max-width:100%;width:240px}.name-field{width:220px;max-width:100%}label{display:block;font-size:12px;color:var(--text-lo);margin:12px 0}input:not([type=checkbox]){display:block;box-sizing:border-box;width:100%;min-width:0;margin-top:6px;padding:9px 10px;border:1px solid #ffffff20;border-radius:7px;color:var(--text-hi);background:var(--bg-panel)}button{font:inherit;white-space:nowrap;flex-shrink:0;padding:8px 11px;border:1px solid #ffffff20;border-radius:7px;background:var(--bg-raised);color:var(--text-hi);cursor:pointer}button:disabled{opacity:.45;cursor:default}p,dl{font-size:12px;color:var(--text-lo);line-height:1.7;overflow-wrap:anywhere}dd{margin-left:12px}textarea{display:block;width:100%;box-sizing:border-box;min-width:0;min-height:110px;margin-top:6px;padding:10px;border:1px solid #ffffff20;border-radius:7px;background:var(--bg-panel);color:var(--text-hi);font:12px/1.6 monospace;resize:vertical}.appearance{border-top:1px solid #ffffff12;margin-top:20px}.check span{font-size:11px;opacity:.7}.device-background{padding:0 0 8px}.actions{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}.check{display:flex;align-items:center;gap:8px}summary{cursor:pointer;font-size:13px}details{padding:14px 0;border-top:1px solid #ffffff12;margin-top:16px}@media(max-width:600px){.service-editor{padding:12px}.identity-fields{gap:10px}}
</style>
