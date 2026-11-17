<script setup lang="ts">
import {toast} from "../../composables/useToast";
import HelpHint from "./HelpHint.vue";
import {ref,reactive,computed,onMounted,onBeforeUnmount,onActivated,onDeactivated,nextTick,watch,inject} from 'vue';
import {matchedRouteKey,routeLocationKey,onBeforeRouteLeave,onBeforeRouteUpdate} from 'vue-router';
import {getAuthProvider,createAuthClient,updateAuthClient,deleteAuthClient,revealAuthClientSecret,rotateAuthClientSecret,type AuthClient,type AuthProviderConfig} from '../../api/authProvider';
import {isAdmin,auth} from '../home/auth';
import Icon from '../../shell/Icon.vue';
import Dropdown from '../../shell/Dropdown.vue';
import ClientCallbackEditor from './ClientCallbackEditor.vue';
import {importCallbacks,expandCallbacks,callbackDiff,callbackProblem} from './clientCallbacks';
import type {UpdateAuthClient} from '../../api/authProvider';
// The retained SettingsPage owns query and route admission; standalone usage retains its own guards.
const props=defineProps<{navigationManaged?:boolean}>();
const config=ref<AuthProviderConfig|null>(null),loading=ref(false),error=ref('');
const editor=ref(false),busy=ref(false),formError=ref(''),notice=ref('');
const draft=reactive({client_id:'',name:'',enabled:true,scopes:'openid profile email'});
const callbackDraft=ref(importCallbacks([]));
const reviewed=ref('');
const original=ref<AuthClient|null>(null);
const callbacks=computed(()=>expandCallbacks(callbackDraft.value));
const redirectsDiff=computed(()=>callbackDiff(original.value?.redirect_uris||[],callbacks.value));
const fingerprint=computed(()=>JSON.stringify([draft,callbackDraft.value]));
const reviewReady=computed(()=>reviewed.value===fingerprint.value);
const emit=defineEmits<{dirty:[value:boolean];busy:[value:boolean]}>();
const initialDraft=ref('');
const dirty=computed(()=>editor.value&&fingerprint.value!==initialDraft.value);
watch(dirty,value=>emit('dirty',value),{flush:'sync'});
const leaving=ref<((value:boolean)=>void)|null>(null),leaveDialog=ref<HTMLElement|null>(null);
let leaveFocus:HTMLElement|null=null;
let editorFocus:HTMLElement|null=null;
async function beforeLeave():Promise<boolean>{
 clearSecret();
 if(locked.value){actionError.value='请先完成当前操作与结果回读。';return false;}
 if(!dirty.value)return true;
 return new Promise(resolve=>{leaving.value?.(false);leaving.value=resolve;leaveFocus=document.activeElement as HTMLElement;void nextTick(()=>leaveDialog.value?.querySelector<HTMLElement>('button')?.focus());});
}
function resolveLeave(discard:boolean){const resolve=leaving.value;leaving.value=null;if(discard)closeEditor();else void nextTick(()=>leaveFocus?.focus());resolve?.(discard);}
function leaveKeys(event:KeyboardEvent){
 if(event.isComposing)return;
 if(event.key==='Escape'){event.preventDefault();resolveLeave(false);}
 if(event.key==='Tab'){const buttons=leaveDialog.value?.querySelectorAll<HTMLButtonElement>('button');if(!buttons?.length)return;const target=event.shiftKey?buttons[buttons.length-1]:buttons[0];if((!event.shiftKey&&document.activeElement===buttons[buttons.length-1])||(event.shiftKey&&document.activeElement===buttons[0])){event.preventDefault();target?.focus();}}
}
function unload(event:BeforeUnloadEvent){if(active&&(dirty.value||locked.value)){event.preventDefault();event.returnValue='';}}
defineExpose({beforeLeave});
const scopes=computed(()=>draft.scopes.split(/\s+/).filter(Boolean));
const changes=computed(()=>{
 const before=original.value;if(!before)return [];
 return [
  {label:'应用名称',before:before.name,after:draft.name.trim()},
  {label:'回调地址',before:before.redirect_uris.join('\n'),after:callbacks.value.join('\n')},
  {label:'状态',before:before.enabled?'已启用':'已停用',after:draft.enabled?'已启用':'已停用'},
  {label:'授权范围',before:before.scopes.join(' '),after:scopes.value.join(' ')},
 ].filter(c=>c.before!==c.after);
});
const form=ref<HTMLElement|null>(null);
const secret=ref<{id:string;value:string;existing?:boolean}|null>(null);
const revealing=ref(false);
let secretEpoch=0;
function clearSecret(){secretEpoch++;secret.value=null;revealing.value=false;}
async function revealSecret(client:AuthClient){
 if(locked.value||!isAdmin.value||!client.has_secret)return;
 clearSecret();const ticket=secretEpoch,epoch=accessEpoch;
 revealing.value=true;actionError.value='';notice.value='';
 const current=()=>active&&isAdmin.value&&epoch===accessEpoch&&ticket===secretEpoch;
 try{
  const result=await revealAuthClientSecret(client.client_id);
  if(!current())return;
  if(result.client_id!==client.client_id||typeof result.client_secret!=='string'||!result.client_secret)throw new Error('Invalid reveal response');
  secret.value={id:client.client_id,value:result.client_secret,existing:true};
 }catch{if(current()){secret.value=null;actionError.value='密钥未显示，请确认用户登录与请求权限后重试；未生成或轮换密钥。';}}
 finally{if(ticket===secretEpoch)revealing.value=false;}
}
const confirmation=ref<{kind:'rotate'|'delete';client:AuthClient}|null>(null),confirmInput=ref(''),actionError=ref('');
const dialog=ref<HTMLElement|null>(null);
let returnFocus:HTMLElement|null=null;
async function restoreFocus(){const target=returnFocus;returnFocus=null;await nextTick();if(target?.isConnected)target.focus();}
async function closeConfirmation(){if(locked.value)return;clearSecret();confirmation.value=null;await restoreFocus();}
function dialogKeys(event:KeyboardEvent){
 if(event.isComposing)return;
 if(event.key==='Escape'){event.preventDefault();closeConfirmation();return;}
 if(event.key!=='Tab')return;
 const controls=[...dialog.value!.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), [tabindex="0"]')];
 const first=controls[0],last=controls.at(-1);
 if(!first){event.preventDefault();dialog.value?.focus();return;}
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
 else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
}
async function dropdownKeys(event:KeyboardEvent){
 if(event.isComposing)return;
 const group=event.currentTarget as HTMLElement,trigger=group.querySelector<HTMLButtonElement>('.dd-btn')!;
 if(event.key==='Escape'){event.preventDefault();event.stopPropagation();document.dispatchEvent(new MouseEvent('click'));trigger.focus();return;}
 if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
 event.preventDefault();
 if(!group.querySelector('.dd-menu')){trigger.click();await nextTick();}
 const items=[...group.querySelectorAll<HTMLButtonElement>('.dd-item')],index=items.indexOf(document.activeElement as HTMLButtonElement);
 const next=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowUp'?-1:1)+items.length)%items.length;
 items[next]?.focus();
}
type Pending = {kind:'create'|'edit'|'toggle'|'rotate'|'delete';id:string;expected?:{name:string;redirect_uris:string[];enabled:boolean;scopes:string[]};received:boolean};
const pending=ref<Pending|null>(null),mismatch=ref(false);
const locked=computed(()=>busy.value||!!pending.value||revealing.value);
watch(locked,value=>emit('busy',value),{flush:'sync'});
let accessEpoch=0,active=true;
onDeactivated(()=>{active=false;accessEpoch++;clearSecret();confirmation.value=null;});
onActivated(()=>{active=true;if(pending.value&&!busy.value)void readResult();else if(!config.value)void load();});
watch(isAdmin,allowed=>{accessEpoch++;clearSecret();config.value=null;if(allowed)void (pending.value?readResult():load());},{flush:'sync'});
watch(()=>[auth.sessionGeneration,auth.requestEpoch,auth.sessionClosing,auth.suspended,auth.me?.id],()=>{accessEpoch++;clearSecret();},{flush:'sync'});
const route=inject(routeLocationKey,null);
watch(()=>route?.fullPath,()=>{accessEpoch++;clearSecret();},{flush:'sync'});
if(inject(matchedRouteKey,null)&&!props.navigationManaged){
 onBeforeRouteLeave(()=>beforeLeave());
 onBeforeRouteUpdate((to,from)=>to.fullPath===from.fullPath?true:beforeLeave());
}
const same=(a:string[],b:string[])=>a.length===b.length&&a.every((v,i)=>v===b[i]);
function problem(e:unknown){
 const value=e as {status?:number;detail?:unknown};
 if(value.status===403)return '当前会话无权修改认证配置（403）；输入已保留';
 if(value.status===401)return '登录已失效，请重新登录后继续；输入已保留';
 return typeof value.detail==='string'?value.detail:'操作未完成，请重试；输入已保留';
}
async function readResult(){
 const request=pending.value;if(!request)return;
 const epoch=accessEpoch;
 busy.value=true;mismatch.value=false;
 try{
  const read=await getAuthProvider();if(!active||!isAdmin.value||epoch!==accessEpoch)return;config.value=read;
  const client=read.clients.find(c=>c.client_id===request.id),expected=request.expected;
  const matches=request.kind==='delete'?!client:request.kind==='rotate'?!!client?.has_secret&&request.received:!!client&&!!expected&&client.name===expected.name&&client.enabled===expected.enabled&&same(client.redirect_uris,expected.redirect_uris)&&same(client.scopes,expected.scopes);
  if(!matches){mismatch.value=true;actionError.value=request.kind==='rotate'?'轮换结果未确认，密钥未收到；未自动重试。':'读取结果与提交不一致；草稿已保留，未自动重发。';return;}
  const messages={create:'应用已创建',edit:'变更已保存',toggle:'应用状态已更新',rotate:'密钥已轮换',delete:'应用已删除'};
  toast(messages[request.kind]);
  notice.value=request.kind==='create'&&!secret.value?'密钥未收到，可点击「查看现有密钥」重新读取，无需轮换':'';
  if(request.kind==='create'||request.kind==='edit')closeEditor();
  const wasConfirmation=!!confirmation.value;pending.value=null;confirmation.value=null;busy.value=false;actionError.value='';if(wasConfirmation)await restoreFocus();
 }catch{actionError.value='读取结果失败，尚未确认；请重试读取结果，不会重复提交。';}
 finally{busy.value=false;}
}
async function perform(request:Pending,write:()=>Promise<unknown>){
 if(locked.value)return;
 const epoch=accessEpoch;
 if(request.kind==='create'||request.kind==='rotate')secret.value=null;
 pending.value=request;busy.value=true;notice.value='';formError.value='';actionError.value='';mismatch.value=false;
 try{
  const result=await write();request.received=true;
  if(active&&isAdmin.value&&epoch===accessEpoch&&(request.kind==='create'||request.kind==='rotate')){
   const value=(result as {client_secret?:unknown})?.client_secret;
   secret.value=typeof value==='string'&&value?{id:request.id,value}:null;
  }
 }catch(e){
  const status=(e as {status?:number}).status;
  // Explicit rejection is retryable; transport/5xx may already have committed.
  if(status&&status>=400&&status<500){pending.value=null;busy.value=false;if(editor.value)formError.value=problem(e);else actionError.value=problem(e);return;}
 }
 if(active&&isAdmin.value&&epoch===accessEpoch)await readResult();else busy.value=false;
}
function continueEditing(){if(!mismatch.value||busy.value)return;pending.value=null;mismatch.value=false;actionError.value='本次结果未确认，未重发；请核对后再操作。';}
async function toggle(client:AuthClient){
 const expected={name:client.name,redirect_uris:[...client.redirect_uris],scopes:[...client.scopes],enabled:!client.enabled};
 await perform({kind:'toggle',id:client.client_id,expected,received:false},()=>updateAuthClient(client.client_id,{enabled:expected.enabled}));
}
async function ask(kind:'rotate'|'delete',client:AuthClient){clearSecret();returnFocus=document.activeElement as HTMLElement;confirmation.value={kind,client};confirmInput.value='';actionError.value='';await nextTick();(dialog.value?.querySelector<HTMLElement>('input,button')||dialog.value)?.focus();}
async function confirm(){
 const target=confirmation.value;if(!target||locked.value)return;
 if(target.kind==='delete'&&confirmInput.value!==target.client.client_id)return;
 // A new rotation must never leave an older, now invalid secret on screen.
 secret.value=null;
 await perform({kind:target.kind,id:target.client.client_id,received:false},()=>target.kind==='rotate'?rotateAuthClientSecret(target.client.client_id):deleteAuthClient(target.client.client_id));
}
async function copy(value:string,label:string){try{await navigator.clipboard.writeText(value);notice.value=`${label}已复制`;}catch{notice.value=`复制失败，请手动复制${label}`;}}
async function openCreate(){editorFocus=document.activeElement as HTMLElement;clearSecret();editor.value=true;reviewed.value='';if(!original.value&&callbackDraft.value.web.length===0)callbackDraft.value.web.push({origin:'',paths:['']});initialDraft.value=fingerprint.value;formError.value='';notice.value='';await nextTick();form.value?.querySelector<HTMLInputElement>('input')?.focus();}
async function openEdit(client:AuthClient){original.value={...client,redirect_uris:[...client.redirect_uris],scopes:[...client.scopes]};Object.assign(draft,{client_id:client.client_id,name:client.name,enabled:client.enabled,scopes:client.scopes.join(' ')});callbackDraft.value=importCallbacks(client.redirect_uris);await openCreate();}
function closeEditor(){editor.value=false;original.value=null;reviewed.value='';callbackDraft.value=importCallbacks([]);Object.assign(draft,{client_id:'',name:'',enabled:true,scopes:'openid profile email'});const target=editorFocus;editorFocus=null;void nextTick(()=>{if(target?.isConnected)target.focus();});}
async function save(){
 if(locked.value)return;
 const payload={client_id:draft.client_id,name:draft.name.trim(),redirect_uris:callbacks.value,scopes:scopes.value};
 if(!payload.client_id||!payload.name||!payload.redirect_uris.length){formError.value='请填写应用名称、Client ID 和回调地址';return;}
 if(!original.value&&!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(payload.client_id)){formError.value='Client ID 需以字母或数字开头，仅含字母、数字、点、短横线或下划线，最多 64 位';return;}
 const invalid=callbackProblem(callbackDraft.value,original.value?.redirect_uris||[]);
 if(invalid){formError.value=invalid;return;}
 if(!reviewReady.value){reviewed.value=fingerprint.value;formError.value='';await nextTick();form.value?.querySelector<HTMLElement>('[data-review]')?.focus();return;}
 const editing=!!original.value,expected={name:payload.name,redirect_uris:payload.redirect_uris,enabled:editing?draft.enabled:true,scopes:payload.scopes};
 const patch:UpdateAuthClient={};
 if(original.value){
  if(expected.name!==original.value.name)patch.name=expected.name;
  if(expected.enabled!==original.value.enabled)patch.enabled=expected.enabled;
  if(!same(expected.redirect_uris,original.value.redirect_uris))patch.redirect_uris=expected.redirect_uris;
  if(!same(expected.scopes,original.value.scopes))patch.scopes=expected.scopes;
 }
 await perform({kind:editing?'edit':'create',id:payload.client_id,expected,received:false},()=>editing?updateAuthClient(payload.client_id,patch):createAuthClient(payload));
}
onBeforeUnmount(()=>{active=false;accessEpoch++;reloadPending=false;clearSecret();leaving.value?.(false);window.removeEventListener('beforeunload',unload);});
let loadEpoch:number|null=null,reloadPending=false;
async function load(){
 if(!active||!isAdmin.value||locked.value)return;
 // Mounted/activated may share a flight; only a newer access generation queues a replacement.
 if(loading.value){if(loadEpoch!==accessEpoch)reloadPending=true;return;}
 const epoch=accessEpoch;loadEpoch=epoch;loading.value=true;error.value='';
 const current=()=>active&&isAdmin.value&&epoch===accessEpoch;
 try{const read=await getAuthProvider();if(current())config.value=read;}
 catch(e){if(current())error.value=(e as {status?:number}).status===403?'当前会话无权读取认证配置（403）。':'认证配置读取失败，请重试';}
 finally{
  loadEpoch=null;loading.value=false;
  if(reloadPending){reloadPending=false;void load();}
 }
}
onMounted(()=>{window.addEventListener('beforeunload',unload);void load();});
</script>
<template>
 <section class="provider-card" aria-labelledby="provider-title">
  <h2 id="provider-title"><Icon name="link" :size="18"/> Stella 单点登录</h2>
  <p v-if="!isAdmin" class="access-gate">请登录用户账号后查看和修改接入配置。</p>
  <p v-if="loading" role="status">读取认证配置…</p>
  <p v-if="error" role="alert">{{error}} <button class="st-button" @click="load">重试读取</button></p>
   <div v-if="leaving" class="confirm-mask" @click.self="resolveLeave(false)"><section ref="leaveDialog" class="confirmation" role="alertdialog" aria-modal="true" aria-label="尚有未保存的应用配置" @keydown="leaveKeys"><h3>保留这份草稿？</h3><p>当前应用配置尚未保存，离开会放弃这些修改。</p><div class="actions"><button class="st-button" @click="resolveLeave(false)">继续编辑</button><button class="st-button" @click="resolveLeave(true)">放弃草稿并离开</button></div></section></div>
  <template v-if="config">
   <dl class="endpoints"><div><dt>Issuer</dt><dd><code>{{config.issuer}}</code><button class="st-button" @click="copy(config.issuer,'Issuer')">复制 Issuer</button></dd></div><div><dt>自动发现</dt><dd><code>{{config.discovery_url}}</code><button class="st-button" @click="copy(config.discovery_url,'自动发现')">复制自动发现</button></dd></div></dl>
   <details><summary>端点详情</summary><dl class="endpoints"><div v-for="endpoint in [{key:'authorization_endpoint',label:'授权端点'},{key:'token_endpoint',label:'令牌端点'},{key:'userinfo_endpoint',label:'用户信息'},{key:'jwks_uri',label:'公钥集'}] as const" :key="endpoint.key"><dt>{{endpoint.label}}</dt><dd><code>{{config[endpoint.key]}}</code></dd></div></dl></details>
   <div class="group-head"><h3>应用接入<HelpHint label="默认身份范围说明">默认提供身份识别、基本资料和邮箱；已有应用保持原授权范围。</HelpHint></h3><button class="st-button" :disabled="locked || editor || !!confirmation" @click="openCreate"><Icon name="plus"/> 连接应用</button></div>

   <Transition name="auth-expand"><form v-if="editor" ref="form" @submit.prevent="save">
    <fieldset :disabled="locked" :aria-describedby="formError?'auth-client-error':undefined"><div class="form-row"><label>应用名称<input v-model="draft.name" aria-label="应用名称" required maxlength="128"/></label><label>Client ID<input v-model="draft.client_id" aria-label="Client ID" :readonly="!!original" required maxlength="64" autocomplete="off" spellcheck="false"/></label></div>
    <ClientCallbackEditor v-model="callbackDraft"/>

    <details><summary>授权范围与状态</summary><p id="scope-help">openid：确认身份；profile：姓名、头像等基本资料；email：邮箱。只选原应用实际需要的范围。</p><div class="form-row"><label>授权范围<input v-model="draft.scopes" aria-label="授权范围" aria-describedby="scope-help" required spellcheck="false"/></label><div v-if="original" class="status-field" role="group" aria-label="应用状态" @keydown="dropdownKeys"><span>状态</span><Dropdown v-model="draft.enabled" :options="[{value:true,label:'已启用'},{value:false,label:'已停用'}]"/></div></div></details>
    </fieldset>
    <section v-if="reviewReady" class="review" aria-label="变更预览" tabindex="-1" data-review><h3>确认本次变更</h3><div class="callback-diff" aria-label="回调变更摘要"><p>新增 {{redirectsDiff.added.length}} · 移除 {{redirectsDiff.removed.length}}</p><ins v-for="uri in redirectsDiff.added" :key="uri">+ {{uri}}</ins><del v-for="uri in redirectsDiff.removed" :key="uri">− {{uri}}</del><p v-if="!redirectsDiff.added.length&&!redirectsDiff.removed.length">完整回调登记不变。</p></div><p>{{original?'Client ID 不变，不轮换现有密钥。修改回调、范围或启用状态会正常更新凭据版本。':'创建后生成此应用自己的密钥；请在原应用的服务端 OIDC 设置中填写，不要放入浏览器脚本。'}}</p></section>
    <div v-if="original && changes.length" class="diff" aria-label="变更摘要"><div v-for="change in changes.filter(c=>c.label!=='回调地址')" :key="change.label"><strong>{{change.label}}</strong><del>{{change.before}}</del><ins>{{change.after}}</ins></div><span v-if="!reviewReady && (redirectsDiff.added.length||redirectsDiff.removed.length)">回调地址：新增 {{redirectsDiff.added.length}} · 移除 {{redirectsDiff.removed.length}}</span></div>
    <p v-if="formError" id="auth-client-error" role="alert">{{formError}}</p>
    <div class="actions"><button class="st-button" type="button" :disabled="locked" @click="closeEditor">取消</button><button class="st-button is-primary" type="submit" :disabled="locked || (!!original && !changes.length)">{{busy?'保存中…':reviewReady?(original?'保存变更':'创建应用'):'预览变更'}}</button></div>
   </form></Transition>
   <section v-if="secret" class="secret-panel" aria-label="应用密钥"><strong>{{secret.id}} · {{secret.existing?'现有密钥':'新密钥'}}</strong><p>{{secret.existing?'仅在当前登录会话中显示；查看不会改变密钥或影响现有连接。':'新密钥仅显示这一次；隐藏后可通过「查看现有密钥」重新读取，无需轮换。'}}</p><code>{{secret.value}}</code><div class="actions"><button class="st-button" @click="copy(secret.value,'密钥')">复制密钥</button><button class="st-button" @click="clearSecret">隐藏密钥</button></div></section>
   <p v-if="notice" role="status">{{notice}}</p>
   <p v-if="actionError && !confirmation" role="alert">{{actionError}}</p>
   <div v-if="pending && !confirmation" class="actions"><button class="st-button" :disabled="busy" @click="readResult">重试读取结果</button><button class="st-button" v-if="mismatch" :disabled="busy" @click="continueEditing">继续编辑，不重发</button></div>
   <Transition name="auth-expand"><div v-if="confirmation" class="confirm-mask" @click.self="closeConfirmation"><form ref="dialog" class="confirmation" role="dialog" aria-modal="true" tabindex="-1" :aria-label="confirmation.kind==='delete'?'删除应用':'轮换应用密钥'" @submit.prevent="confirm" @keydown="dialogKeys">
    <h3>{{confirmation.kind==='delete'?'删除':'轮换密钥'}} · {{confirmation.client.name}}</h3><p>Client ID：<code>{{confirmation.client.client_id}}</code></p>
    <p>{{confirmation.kind==='delete'?'删除后，此应用将无法继续使用 Stella 登录。':'旧密钥将立即失效。请将新密钥同步到此应用，否则无法继续登录。'}}</p>
    <label v-if="confirmation.kind==='delete'">输入 Client ID 确认删除<input v-model="confirmInput" :disabled="locked" aria-label="输入 Client ID 确认删除" autocomplete="off" spellcheck="false"/></label>
    <p v-if="actionError" role="alert">{{actionError}}</p>
    <div v-if="pending" class="actions"><button class="st-button" type="button" :disabled="busy" @click="readResult">重试读取结果</button><button class="st-button" v-if="mismatch" type="button" :disabled="busy" @click="continueEditing">继续编辑，不重发</button></div>
    <div class="actions"><button class="st-button" type="button" :disabled="locked" @click="closeConfirmation">取消</button><button type="submit" class="danger st-button is-danger" :disabled="locked || (confirmation.kind==='delete' && confirmInput!==confirmation.client.client_id)">{{confirmation.kind==='delete'?'确认删除':'确认轮换'}}</button></div>
   </form></div></Transition>
   <details data-connected-apps>
   <summary>已连接应用（{{config.clients.length}}）</summary>
   <p v-if="!config.clients.length">尚未连接应用。</p>
   <details v-for="client in config.clients" :key="client.client_id" class="client-row" data-client-details>
    <summary class="client-head"><strong>{{client.name}}</strong><span class="badge">{{client.enabled?'已启用':'已停用'}}</span><span class="hint">高级详情</span></summary>
    <div class="client-meta">Client ID <code>{{client.client_id}}</code> · 密钥{{client.has_secret?'已设置':'未设置'}}</div>
    <details><summary>已登记回调 · {{client.redirect_uris.length}} 条</summary><div v-for="uri in client.redirect_uris" :key="uri" class="callback">{{uri==='app.immich:///oauth-callback'?'Immich移动App · ':''}}{{uri}}</div></details>
    <details><summary>原应用后台填写什么？</summary><HelpHint label="原应用单点登录配置说明">在原应用官方 OIDC 设置中填入当前 Issuer、Client ID 和所需授权范围，密钥单独按需查看；不需要注入脚本。回调路径请按原应用说明核实。</HelpHint><dl class="endpoints"><div><dt>Client ID</dt><dd><code>{{client.client_id}}</code><button class="st-button" @click="copy(client.client_id,'Client ID')">复制 Client ID</button></dd></div><div><dt>授权范围</dt><dd><code>{{client.scopes.join(' ')}}</code><button class="st-button" @click="copy(client.scopes.join(' '),'授权范围')">复制授权范围</button></dd></div></dl></details>
    <div class="actions"><button class="st-button" :disabled="locked || editor || !!confirmation || !client.has_secret" @click="revealSecret(client)">查看现有密钥</button><button class="st-button" :disabled="locked || editor || !!confirmation" @click="openEdit(client)"><Icon name="edit"/> 编辑</button><button class="st-button" :disabled="locked || editor || !!confirmation" @click="toggle(client)">{{client.enabled?'停用':'启用'}}</button><button class="st-button" :disabled="locked || editor || !!confirmation" @click="ask('rotate',client)">轮换密钥</button><button class="danger st-button is-danger" :disabled="locked || editor || !!confirmation" @click="ask('delete',client)"><Icon name="trash"/> 删除</button></div>
   </details>
   </details>
  </template>
 </section>
</template>
<style scoped>
.provider-card{background:color-mix(in srgb,var(--bg-panel) 90%,transparent);border:1px solid var(--control-border,var(--accent-dim));border-radius:16px;padding:20px 22px;margin-bottom:18px;color:var(--text-hi);min-width:0}
h2,.group-head,.client-head,.actions{display:flex;align-items:center;gap:10px}
h2{font-size:17px;font-weight:600;margin:0 0 14px}h3{font-size:15px;font-weight:550;margin:0}.group-head{justify-content:space-between;margin:22px 0 12px}
p,summary{font-size:14px;color:var(--text-lo);line-height:1.7}p{margin:10px 0}.hint{font-size:12px}.access-gate{margin-bottom:0}
button:not(.st-button){display:inline-flex;align-items:center;justify-content:center;gap:5px;border:1px solid var(--control-border,var(--accent-dim));border-radius:8px;background:var(--bg-raised);color:var(--text-hi);font:inherit;font-size:13px;padding:8px 12px;cursor:pointer;white-space:nowrap;min-height:36px;flex-shrink:0;transition:background 220ms,border-color 220ms,color 220ms}
button:not(.st-button):hover:not(:disabled){border-color:var(--accent-dim);background:var(--bg-panel)}button:not(.st-button):disabled{opacity:.45;cursor:not-allowed}button:not(.st-button):focus-visible,input:focus-visible,textarea:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.danger:not(.st-button){color:var(--danger);border-color:var(--danger)}
.endpoints{font-size:13px;margin:0}.endpoints>div{display:grid;grid-template-columns:86px minmax(0,1fr);gap:12px;padding:7px 0;align-items:center}.endpoints dt{color:var(--text-lo);overflow-wrap:anywhere}.endpoints dd{display:flex;align-items:center;gap:12px;justify-content:space-between;margin:0;min-width:0}.endpoints code{min-width:0;overflow-wrap:anywhere;font-size:12.5px}.endpoints button:not(.st-button){font-size:12px;padding:6px 9px;min-height:34px}
details{margin-top:10px}summary{cursor:pointer;min-height:30px}.client-row{border-top:1px solid var(--control-border,var(--accent-dim));padding:14px 0}.client-row:last-child{padding-bottom:0}.client-head{justify-content:space-between;flex-wrap:wrap}.client-head strong{flex:1;min-width:0}.client-head strong{font-weight:550;font-size:14px;overflow-wrap:anywhere}.badge{font-size:12px;color:var(--accent);white-space:nowrap}.client-meta{font-size:12px;color:var(--text-lo);margin:7px 0}.callback{font-size:13px;overflow-wrap:anywhere;color:var(--text-lo);line-height:1.7}code{overflow-wrap:anywhere}
form{padding:16px;border:1px solid var(--control-border,var(--accent-dim));border-radius:12px;background:color-mix(in srgb,var(--bg-base) 60%,transparent);margin:14px 0}fieldset{border:0;padding:0;margin:0;min-width:0}.form-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,.75fr);gap:14px;margin-bottom:12px}label{display:flex;flex-direction:column;gap:7px;color:var(--text-lo);font-size:12px;min-width:0}.full-field{margin-bottom:12px}input,textarea{display:block;box-sizing:border-box;min-width:0;width:100%;padding:9px 11px;border:1px solid var(--control-border,var(--accent-dim));border-radius:8px;background:var(--bg-base);color:var(--text-hi);font:inherit;font-size:13px}input[readonly]{color:var(--text-lo)}textarea{resize:vertical;line-height:1.65}textarea::placeholder{color:var(--text-lo)}.status-field{display:flex;flex-direction:column;gap:7px;font-size:12px;color:var(--text-lo)}.status-field :deep(.dd-btn){min-height:37px}
.actions{justify-content:flex-end;flex-wrap:wrap;margin-top:12px;gap:8px}.client-row .actions{margin-top:10px}.client-row .actions button:not(.st-button){font-size:12px;padding:6px 10px}.secret-panel{margin:14px 0;padding:16px;border-radius:12px;border:1px solid var(--accent-dim);background:color-mix(in srgb,var(--accent) 5%,var(--bg-base));font-size:13px}.secret-panel>code{display:block;padding:10px;background:var(--bg-base);border-radius:6px;user-select:all}.diff{border-top:1px solid var(--control-border,var(--accent-dim));padding-top:10px;margin-top:10px;font-size:12px}.diff>div{display:grid;grid-template-columns:70px minmax(0,1fr) minmax(0,1fr);gap:10px;padding:5px 0}.diff strong{color:var(--text-lo);font-weight:500}.diff del,.diff ins{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}.diff del{color:var(--text-lo)}.diff ins{color:var(--accent);text-decoration:none}
.confirm-mask{position:fixed;inset:0;z-index:135;display:flex;align-items:center;justify-content:center;padding:20px;background:color-mix(in srgb,var(--bg-base) 70%,transparent);backdrop-filter:blur(5px)}.confirmation{width:min(460px,100%);max-height:85dvh;overflow:auto;margin:0;padding:22px;background:var(--bg-panel);box-shadow:0 20px 70px #0006;outline:none}.confirmation h3{font-size:16px;color:var(--danger);overflow-wrap:anywhere}.confirmation .actions{margin-top:18px}
.review{padding:16px;margin:14px 0;border-radius:10px;border:1px solid var(--accent-dim);background:color-mix(in srgb,var(--accent) 4%,var(--bg-base))}.review:focus{outline:2px solid var(--accent);outline-offset:3px}.callback-diff ins,.callback-diff del{display:block;overflow-wrap:anywhere;white-space:pre-wrap;font-size:13px;line-height:1.8}.callback-diff ins{color:var(--accent);text-decoration:none}.callback-diff del{color:var(--danger)}
[role="alert"]{color:var(--warning);overflow-wrap:anywhere}[role="status"]{color:var(--accent)}
.auth-expand-enter-active,.auth-expand-leave-active{transition:opacity 220ms,transform 220ms}.auth-expand-enter-from,.auth-expand-leave-to{opacity:0;transform:translateY(-6px)}.auth-expand-leave-active{pointer-events:none}
@media(max-width:600px){.provider-card{padding:18px 14px}.endpoints>div{grid-template-columns:1fr;gap:4px}.endpoints dd{gap:8px}.form-row{grid-template-columns:1fr;gap:12px}.diff>div{grid-template-columns:1fr;gap:4px}.actions button:not(.st-button){min-height:44px}.confirm-mask{padding:14px}.confirmation{padding:18px}.group-head{gap:8px;flex-wrap:wrap}form{padding:12px}.endpoints dd{flex-wrap:wrap}.endpoints button:not(.st-button){min-height:44px}}
@media(prefers-reduced-motion:reduce){.auth-expand-enter-active,.auth-expand-leave-active,button:not(.st-button){transition:none}.auth-expand-enter-from,.auth-expand-leave-to{transform:none}}
</style>
