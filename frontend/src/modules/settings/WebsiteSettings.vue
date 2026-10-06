<script setup lang="ts">
import {ref,computed,watch} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {navigation,loadNavigation,navigationIcons} from '../../stores/navigation';
import {getWebsite,createWebsite,updateWebsite,deleteWebsite,checkWebsite,validateInjection,applyInjection,rollbackInjection,getTargets,getPresets,resolveTarget,createTarget,splitProxyUrl,websiteError,type Website,type Injection,type WebsiteInput,type Target,type TargetInput} from '../../api/integrations';
import Dropdown from '../../shell/Dropdown.vue';
import Icon from '../../shell/Icon.vue';
const route=useRoute(),router=useRouter();
const editing=ref(false),selected=ref<Website|null>(null),busy=ref(false),message=ref(''),deleteTarget=ref<Website|null>(null),targets=ref<Target[]>([]),preview=ref(false),validated=ref(false);
const fresh=():WebsiteInput=>({name:'',browser_url:'',icon:'globe',mode:'iframe',adapter:'generic',target_id:null,initial_path:'/',enabled:true,keep_alive:false});
const input=ref<WebsiteInput>(fresh());
const approveFixed=ref(false),controlled=ref(false),allowPrivate=ref(false),upstream=ref(''),autoTarget=ref<string|null>(null),autoApproval=ref<TargetInput|null>(null),uncertainWrite=ref(false);
function resetApproval(){approveFixed.value=false;controlled.value=false;allowPrivate.value=false;upstream.value='';autoTarget.value=null;autoApproval.value=null;uncertainWrite.value=false;}
watch(()=>[input.value.browser_url,input.value.mode,input.value.adapter,upstream.value,controlled.value,allowPrivate.value],()=>{approveFixed.value=false;if(autoTarget.value&&input.value.target_id===autoTarget.value)input.value.target_id=null;autoTarget.value=null;autoApproval.value=null;});
const needsApproval=computed(()=>input.value.mode==='isolated_proxy'&&!input.value.target_id);
const draft=ref<Injection>({enabled:false,css:'',js:'',timing:'dom_ready',csp_policy:'reject'});
const preset=ref<{css:string;js:string;readonly:boolean;status:string}|null>(null);
async function readPreset(){try{const all=await getPresets();preset.value=all[input.value.adapter==='openlist'?'openlist':'generic']||null;}catch(e){message.value=websiteError(e);}}
function copyPreset(){if(preset.value)draft.value={...draft.value,css:preset.value.css,js:preset.value.js};}
const iconOptions=navigationIcons.map(value=>({value,label:value}));
const modes=[{value:'iframe',label:'iframe 直连'},{value:'link',label:'外链打开'},{value:'openlist',label:'OpenList 兼容路径'},{value:'isolated_proxy',label:'独立域名代理'}];
const adapters=[{value:'generic',label:'通用网站'},{value:'immich',label:'Immich（保留原域名 / OIDC）'},{value:'openlist',label:'OpenList'}];
const timing=[{value:'dom_ready',label:'DOM ready（默认）'},{value:'document_start',label:'document start（DOM 未就绪）'}];
const supportsInjection=computed(()=>selected.value?.capabilities?.injection===true);
const previewDocument=computed(()=>`<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><style>body{background:#14171f;color:#c9d4e8;padding:20px}${draft.value.css.replace(/<\/style/gi,'&lt;/style')}</style><h1>网站外观 Mock 预览</h1><p>示例内容；不连接原服务、不执行 JavaScript。</p>`);
watch(draft,()=>{validated.value=false;preview.value=false;},{deep:true});
async function edit(id:string) {busy.value=true;message.value='';try{const item=await getWebsite(id);resetApproval();selected.value=item;input.value={name:item.name,browser_url:item.browser_url,icon:item.icon,mode:item.mode,adapter:item.adapter,target_id:item.target_id||null,initial_path:item.initial_path||'/',enabled:item.enabled,keep_alive:item.keep_alive===true};draft.value={...(item.injection?.draft||item.injection?.active||{enabled:false,css:'',js:'',timing:'dom_ready',csp_policy:'reject'})};preset.value=null;editing.value=true;}catch(e){message.value=websiteError(e);}finally{busy.value=false;}}
watch(()=>route.query.module,id=>{if(typeof id==='string'&&!['drive','gallery','home'].includes(id))void edit(id);},{immediate:true});
function add(){resetApproval();selected.value=null;input.value=fresh();editing.value=true;message.value='';preview.value=false;}
async function save(){
 if(busy.value||uncertainWrite.value)return;
 busy.value=true;message.value='';let creating=false;
 try{
  const payload={...input.value};
  if(needsApproval.value){
   if(!approveFixed.value)throw new Error('请明确勾选“为此网址批准固定目标”');
   const browser=splitProxyUrl(payload.browser_url);
   let origin=browser.origin;
   if(payload.adapter==='immich'){
    if(!controlled.value)throw new Error('Immich 原域名接管必须明确勾选受控服务');
    if(!/^https:\/\/immich\.(xiya\.live|yunxi\.life)\/?$/.test(payload.browser_url))throw new Error('Immich 代理需要保留已批准的原 HTTPS 根域名');
    if(!upstream.value)throw new Error('请填写独立上游根地址');
    origin=upstream.value;
   }
   const result=await resolveTarget(origin,allowPrivate.value);
   if(result.status!=='resolved'||!result.resolved_ips.length)throw new Error('未取得可批准的固定 IP');
   if(payload.adapter!=='immich')payload.initial_path=input.value.initial_path=browser.initial_path;
   const approval:TargetInput={name:payload.name,upstream_url:result.normalized_origin,allowed_ips:[...result.resolved_ips],controlled:controlled.value,headers:{}};
   creating=true;const target=await createTarget(approval);creating=false;
   // Preserve the created target for a retry; never recreate it after a module failure.
   input.value.target_id=payload.target_id=target.id;autoTarget.value=target.id;autoApproval.value=approval;
  }
  if(autoTarget.value===payload.target_id&&autoApproval.value){
   const approved=(await getTargets()).find(t=>t.id===payload.target_id),expected=autoApproval.value;
   if(!approved||approved.upstream_url.replace(/\/$/,'')!==expected.upstream_url||approved.controlled!==expected.controlled||JSON.stringify([...(approved.allowed_ips||[])].sort())!==JSON.stringify([...expected.allowed_ips].sort()))throw new Error('固定目标保存结果未确认');
  }
  let item:Website;
  if(selected.value)item=await updateWebsite(selected.value.id,payload);
  else{creating=true;item=await createWebsite(payload);creating=false;}
  selected.value=item; // A failed readback must retry PATCH, not duplicate POST.
  await getWebsite(item.id);await loadNavigation();editing.value=false;message.value='网站入口已更新';
 }catch(e){
  const status=(e as any)?.status;
  if(creating&&(!status||status>=500||status===408)){uncertainWrite.value=true;message.value='创建结果未确认；为避免重复已暂停再次创建。请刷新入口列表及已批准上游核对，再编辑已有入口。';}
  else message.value=e instanceof Error&&!status?e.message:websiteError(e);
 }finally{busy.value=false;}
}
async function duplicate(item:Website){busy.value=true;try{const result=await createWebsite({name:item.name+' 副本',browser_url:item.browser_url,icon:item.icon,mode:item.mode,adapter:item.adapter,target_id:item.target_id||null,initial_path:item.initial_path||'/',enabled:item.enabled,keep_alive:item.keep_alive===true});await getWebsite(result.id);await loadNavigation();}catch(e){message.value=websiteError(e);}finally{busy.value=false;}}
async function remove(){if(!deleteTarget.value)return;busy.value=true;try{const id=deleteTarget.value.id;await deleteWebsite(id);try{await getWebsite(id);throw new Error('删除结果未确认');}catch(e){if((e as any).status!==404)throw e;}deleteTarget.value=null;editing.value=false;await loadNavigation();await router.replace({path:'/settings',query:{section:'navigation'}});message.value='仅删除 Stella 入口，原网站数据未修改';}catch(e){message.value=websiteError(e);}finally{busy.value=false;}}
async function probe(){if(!selected.value)return;try{const result=await checkWebsite(selected.value.id);message.value=result.reason+'；浏览器内部状态不可读';}catch(e){message.value=websiteError(e);}}
async function validate(){if(!selected.value)return;busy.value=true;try{const result=await validateInjection(selected.value.id,draft.value);validated.value=result.valid;message.value=result.valid?'草稿校验通过，尚未应用':result.errors.join('；');}catch(e){message.value=websiteError(e);}finally{busy.value=false;}}
async function publish(rollback=false){if(!selected.value)return;busy.value=true;try{if(rollback)await rollbackInjection(selected.value.id);else await applyInjection(selected.value.id);selected.value=await getWebsite(selected.value.id);message.value=rollback?'已回退上一版本，重载模块后生效':'注入版本已应用，重载模块后生效';}catch(e){message.value=websiteError(e);}finally{busy.value=false;}}
async function fetchTargets(){try{targets.value=await getTargets();}catch(e){message.value=websiteError(e);}}
</script>
<template><section class="websites"><header><h2>网站入口</h2><button :disabled="busy" @click="add"><Icon name="plus"/>新增网站</button></header><p>基础只填写名称、URL、模板。独立代理由预配入口自动分配域名，无需逐网站配置 DNS。</p>
<div v-for="item in navigation.modules" :key="item.id" class="website-row"><Icon :name="item.icon"/><RouterLink :to="'/apps/'+item.id">{{item.name}}</RouterLink><span>{{item.mode}}</span><div class="actions"><button :aria-label="'编辑 '+item.name" :disabled="busy" @click="edit(item.id)">编辑</button><button :aria-label="'复制 '+item.name" :disabled="busy" @click="duplicate(item)">复制</button><button :aria-label="'删除 '+item.name" :disabled="busy" @click="deleteTarget=item">删除</button></div></div>
<form v-if="editing" @submit.prevent="save"><fieldset :disabled="busy"><div class="fields"><label>网站名称<input v-model="input.name" required maxlength="80" /></label><label>网站 URL<input v-model="input.browser_url" type="url" required placeholder="https://example.com/?q=1#start" /></label><label>接入模板<Dropdown v-model="input.adapter" :options="adapters" /></label><label>图标<Dropdown v-model="input.icon" :options="iconOptions" /></label></div>
<label class="check"><input v-model="input.keep_alive" type="checkbox"/>切页保留现场（最多 3 个网站）</label><p>默认关闭。开启后保留页面输入与滚动位置；超过 3 项按最近访问淘汰，笔记缓存独立。第三方网站可能自行后台运行；此开关不延长登录或管理授权。</p>
<details><summary>高级接入</summary><div class="fields"><label>打开方式<Dropdown v-model="input.mode" :options="modes" /></label><label>起始路径<input v-model="input.initial_path" /></label><label class="check"><input v-model="input.enabled" type="checkbox"/>启用入口</label></div><template v-if="input.mode==='isolated_proxy'"><p>可在本页批准新固定目标，也可复用已批准上游；不接受任意开放代理。</p><button type="button" @click="fetchTargets">选择已批准上游</button><Dropdown v-model="input.target_id" :options="targets.map(t=>({value:t.id,label:t.name}))" /><p v-if="selected?.origin">自动入口：{{selected.origin}}</p></template><p v-if="input.adapter==='immich'">保留原 Immich 浏览器域名及已有 OIDC 账号绑定；切换代理前另行确认回调兼容性。</p><p v-if="input.mode==='iframe'">跨域直连不能由 Stella 修改 DOM，iframe load 不代表站内登录或内容成功。</p></details>
<section v-if="needsApproval" class="approval"><h3>批准固定上游</h3><p>点击保存时仅解析 DNS，冻结当次 IP、协议和端口；不会抓取网站、复制登录密码或自动修改 CSP。解析超出批准 IP 将拒绝连接，需重新批准。</p><label v-if="input.adapter==='immich'">独立上游根地址<input v-model="upstream" type="url" required placeholder="http://10.66.0.2:12020/" /></label><label class="check"><input v-model="controlled" type="checkbox"/>此上游为我自有或明确受控的服务</label><label class="check"><input v-model="allowPrivate" type="checkbox"/>允许此固定目标访问私网或本机地址</label><label class="check"><input v-model="approveFixed" type="checkbox" required/>为此网址批准固定目标</label><p v-if="input.adapter!=='immich'">起始路径、query 和 hash 取自网站 URL；上游仅保存 origin。HTTP 私网上游由 HTTPS 独立入口代理，不直连浏览器 iframe。</p></section>
<div class="actions"><button type="button" :disabled="busy" @click="editing=false">取消编辑</button><button v-if="selected" type="button" :disabled="busy" @click="probe">只读检测</button><button type="submit" :disabled="busy||uncertainWrite">{{needsApproval?(selected?'批准固定上游并应用变更':'批准固定上游并创建网站'):(selected?'应用接入变更':'创建网站')}}</button></div></fieldset>
<p v-if="selected && selected.adapter !== 'generic'"><RouterLink :to="{path:'/settings',query:{section:'navigation',module:selected.adapter === 'openlist' ? 'drive' : 'gallery'}}">前往此服务的统一连接与注入设置</RouterLink> · 所有同模板入口共用一份活动注入，不在这里保存另一份影子版本。</p><details v-if="selected && selected.adapter === 'generic'" class="injection"><summary>注入与外观</summary><button type="button" :disabled="busy" @click="readPreset">读取内置预设</button><div v-if="preset"><p>只读内置预设 · {{preset.status === 'builtin_response_loader' ? '由内置服务统一设置管理' : '注入已加载不等于网站 ready'}}</p><label class="code">内置 CSS（只读）<textarea :value="preset.css" readonly /></label><label class="code">内置 JavaScript（只读）<textarea :value="preset.js" readonly /></label><button type="button" @click="copyPreset">复制预设到草稿</button></div><p>受信任代码仅运行于目标模块。预览不代表上游兼容；已打开页面需手动重载，不强制打断编辑。</p><p v-if="!supportsInjection">此接法不支持注入，不能应用代码。请显式选择受控代理模式。</p><label class="check"><input v-model="draft.enabled" type="checkbox" :disabled="!supportsInjection"/>启用注入</label><div class="fields"><label>执行时机<Dropdown v-model="draft.timing" :options="timing" /></label><label>CSP 策略<Dropdown v-model="draft.csp_policy" :options="[{value:'reject',label:'保留 / 拒绝冲突'},{value:'controlled',label:'仅明确批准受控目标'}]" /></label></div><label class="code">CSS 代码<textarea v-model="draft.css" spellcheck="false" /></label><label class="code">JavaScript 代码<textarea v-model="draft.js" spellcheck="false" /></label><div class="actions"><button type="button" :disabled="busy||!supportsInjection" @click="validate">校验并保存草稿</button><button type="button" @click="preview=!preview">Mock 预览</button><button type="button" :disabled="busy||!validated||!supportsInjection" @click="publish()">应用注入版本</button><button type="button" :disabled="busy||!selected.injection?.previous" @click="publish(true)">回退上一版本</button></div><p>活动版本：{{selected.injection?.active?.version||'未应用'}} · 上一版本：{{selected.injection?.previous?.version||'无'}}</p><iframe v-if="preview" title="Mock 外观预览（不执行 JS）" sandbox="" :srcdoc="previewDocument" class="preview" /></details></form><p v-if="message" role="status">{{message}}</p>
<Teleport to="body"><div v-if="deleteTarget" class="mask" @click.self="!busy && (deleteTarget=null)"><section class="dialog" role="dialog" aria-modal="true" aria-label="删除网站入口"><h2>删除 {{deleteTarget.name}} 的入口？</h2><p>只删除 Stella 入口和配置，不删除原网站数据、不卸载服务。</p><div class="actions"><button :disabled="busy" @click="deleteTarget=null">取消</button><button :disabled="busy" @click="remove">确认删除入口</button></div></section></div></Teleport></section></template>
<style scoped>fieldset{border:0;padding:0;margin:0;min-width:0}.approval{border:1px solid #ffffff20;border-radius:10px;padding:14px;margin:14px 0}.approval h3{font-size:13px;margin:0}.approval .check{margin:12px 0;white-space:normal;align-items:flex-start}.approval input[type=checkbox]{flex-shrink:0}.websites{margin-top:18px;background:var(--bg-panel);padding:20px;border-radius:14px;border:1px solid #ffffff12}header,.website-row,.actions{display:flex;align-items:center;gap:10px}header{justify-content:space-between}h2{font-size:15px}p{font-size:12px;color:var(--text-lo);line-height:1.7;margin:10px 0}.website-row{padding:10px 0;border-top:1px solid #ffffff10;flex-wrap:wrap}.website-row>a{flex:1}.website-row>span{font-size:11px;color:var(--text-faint)}button{display:inline-flex;align-items:center;gap:6px;padding:7px 11px;background:var(--bg-raised);border:1px solid #ffffff20;border-radius:7px;color:var(--text-hi);white-space:nowrap;flex-shrink:0;cursor:pointer}button:disabled{opacity:.4}.fields{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}label{display:flex;align-items:center;gap:8px;font-size:12px;min-width:0}input:not([type=checkbox]),textarea{background:var(--bg-base);border:1px solid #ffffff20;border-radius:7px;color:var(--text-hi);padding:8px;min-width:0;flex:1;width:100%}.actions{justify-content:flex-end;flex-wrap:wrap;margin-top:12px}.check{white-space:nowrap}summary{font-size:13px;color:var(--accent);cursor:pointer;margin:12px 0}.code{display:block;margin-top:14px}.code textarea{display:block;width:100%;margin-top:8px;height:130px;font-family:monospace}.preview{width:100%;height:220px;border:1px solid #ffffff18;border-radius:8px}.mask{position:fixed;inset:0;z-index:1000;background:#080c16b8;display:grid;place-items:center;padding:18px}.dialog{background:var(--bg-panel);border:1px solid #ffffff20;border-radius:14px;padding:24px;width:min(460px,100%)}@media(max-width:650px){.fields{grid-template-columns:1fr}.websites{padding:14px}.website-row .actions{width:100%}label :deep(.dd-btn){min-width:120px}}</style>
