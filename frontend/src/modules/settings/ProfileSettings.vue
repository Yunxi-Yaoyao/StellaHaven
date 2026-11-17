<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount, onMounted, nextTick } from "vue";
import {auth,currentAvatar} from '../home/auth';
import HelpHint from "./HelpHint.vue";
import EmailStateControl from "./EmailStateControl.vue";
import {toast} from "../../composables/useToast";
import AvatarCropper from "./AvatarCropper.vue";
export interface ProfileRecord {
  id: string | number; display_name: string; username: string;
  email?: string | null; email_verified?: boolean; avatar_url?: string | null;
}
const props=defineProps<{initialProfile:ProfileRecord;avatars?:string[];request:typeof fetch}>();
const emit=defineEmits<{confirmed:[profile:ProfileRecord];editAvatar:[];security:[];services:[];dirty:[value:boolean]}>();
const profile=ref({...props.initialProfile});
type ProfileField='display_name'|'username'|'email'|'avatar_url';
const fieldRevision:Record<ProfileField,number>={display_name:0,username:0,email:0,avatar_url:0};
function beginField(field:ProfileField){fieldRevision[field]++;return {...fieldRevision};}
const avatarImage=computed(()=>profile.value.avatar_url||currentAvatar.value);
const nameOpen=ref(false),usernameOpen=ref(false);
const name=ref(profile.value.display_name), nameBusy=ref(false), nameError=ref('');
async function openField(field:'name'|'username'){if(field==='name')nameOpen.value=true;else usernameOpen.value=true;await nextTick();document.getElementById(`profile-${field}`)?.focus();}
const username=ref(profile.value.username),usernameBusy=ref(false),usernameError=ref('');
let usernamePending:string|null=null;
const usernameConfirmation=ref<{old:string;next:string}|null>(null),usernameDialog=ref<HTMLElement>();
watch(usernameConfirmation,async value=>{if(value){await nextTick();usernameDialog.value?.querySelector<HTMLButtonElement>('button')?.focus();}});
function closeUsernameConfirmation(){usernameConfirmation.value=null;void nextTick(()=>document.getElementById('profile-username')?.focus());}
function confirmationKeys(e:KeyboardEvent){if(e.key==='Escape'){e.stopPropagation();closeUsernameConfirmation();}if(e.key==='Tab'){const buttons=[...usernameDialog.value?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')??[]];if(!buttons.length)return;e.preventDefault();const i=buttons.indexOf(document.activeElement as HTMLButtonElement);buttons[(i+(e.shiftKey?-1:1)+buttons.length)%buttons.length]?.focus();}}
const emailOpen=ref(false),emailDraft=ref(profile.value.email||''),emailCode=ref(''),emailStage=ref<'input'|'code'>('input');
const emailBusy=ref(false),emailError=ref(''),emailServiceReady=ref<boolean|null>(null);
const verificationAddress=ref(''),emailCodeInput=ref<HTMLInputElement>();
let addressRevision=0;
watch(emailDraft,()=>{addressRevision++;if(emailOpen.value&&emailDraft.value.trim()!==verificationAddress.value){emailCode.value='';emailStage.value='input';verificationAddress.value='';}},{flush:'sync'});
let serviceRequest:Promise<void>|null=null;
const serviceError=ref(''),serviceLoading=ref(true),emailStateControl=ref<InstanceType<typeof EmailStateControl>>();
const stateAddress=computed(()=>emailOpen.value?emailDraft.value.trim():(profile.value.email||''));
const isSavedAddress=computed(()=>stateAddress.value===(profile.value.email||''));
const emailState=computed(()=>serviceLoading.value?'loading':serviceError.value?'error':emailServiceReady.value===false?'unavailable':emailServiceReady.value!==true?'unknown':isSavedAddress.value&&profile.value.email_verified===true?'verified':isSavedAddress.value&&profile.value.email&&typeof profile.value.email_verified!=='boolean'?'unknown':'pending');
const emailStateLabel=computed(()=>({loading:'正在读取邮件服务',error:'邮件服务读取失败',unavailable:'邮件服务不可用',unknown:'邮箱状态待确认',verified:'邮箱已验证',pending:!stateAddress.value?'尚未绑定邮箱':isSavedAddress.value?'邮箱待验证':'新邮箱待保存或验证'})[emailState.value]);

const avatarBusy=ref(false),avatarError=ref('');
const composing=ref(false), cropperOpen=ref(false);
const history=ref<string[]>([]),avatars=computed(()=>props.avatars??history.value);
async function loadAvatarHistory(){try{const values=await json('/auth/avatars');if(Array.isArray(values))history.value=values;}catch(e){if(valid())avatarError.value='最近头像读取失败，可重试读取。';}}
onMounted(()=>{if(!props.avatars)void loadAvatarHistory();void loadEmailService();});
async function uploadRequest(path:RequestInfo|URL,init?:RequestInit){ensure();const response=await props.request(path,{...init,signal:controller.signal});ensure();return response;}
let disposed=false, invalidated=false;
const owner=auth.me?.id, generation=auth.sessionGeneration, epoch=auth.requestEpoch;
const controller=new AbortController();
const valid=()=>!disposed&&!invalidated&&!auth.suspended&&!auth.sessionClosing&&owner===auth.me?.id&&generation===auth.sessionGeneration&&epoch===auth.requestEpoch;
function ensure(){if(!valid())throw new DOMException('登录状态已变化','AbortError');}
let namePending:string|null=null;
let emailPending:{address:string;action:'save'|'verify'}|null=null;
const dirty=computed(()=>name.value!==profile.value.display_name || username.value!==profile.value.username || usernameBusy.value || (emailDraft.value!==(profile.value.email||'')||!!emailCode.value) || nameBusy.value || emailBusy.value || avatarBusy.value);
watch(dirty,v=>emit('dirty',v),{immediate:true});
watch(()=>props.initialProfile,p=>{
 if(!valid()||p.id!==profile.value.id)return;
 const clean=name.value===profile.value.display_name;
 const cleanUsername=username.value===profile.value.username;
 const cleanEmail=emailDraft.value===(profile.value.email||'')&&!emailCode.value;
 for(const field of Object.keys(fieldRevision) as ProfileField[])if(p[field]!==profile.value[field])fieldRevision[field]++;
 profile.value={...p};if(clean)name.value=p.display_name;if(cleanUsername)username.value=p.username;if(cleanEmail)emailDraft.value=p.email||'';
});
watch([()=>auth.me?.id,()=>auth.sessionGeneration,()=>auth.requestEpoch,()=>auth.suspended,()=>auth.sessionClosing],()=>{
 invalidated=true;controller.abort();emailStateControl.value?.close();usernameConfirmation.value=null;verificationAddress.value='';name.value='';username.value='';usernamePending=null;emailDraft.value='';emailCode.value='';emailOpen.value=false;
 namePending=null;emailPending=null;cropperOpen.value=false;emit('dirty',false);
},{flush:'sync'});
onBeforeUnmount(()=>{disposed=true;controller.abort();emit('dirty',false);});
function imeGuard(e:KeyboardEvent){if(e.isComposing||composing.value||e.keyCode===229)e.preventDefault();}
async function json(path:string,init?:RequestInit){
 ensure();const response=await props.request(path,{...init,signal:controller.signal});const data=await response.json();ensure();
 if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'请求失败，请重试');
 return data;
}
function confirmed(value:ProfileRecord,revisions:Record<ProfileField,number>){
 ensure();if(value.id!==props.initialProfile.id)throw Error('资料身份尚未确认，请重新登录');
 if(typeof value.display_name!=='string'||typeof value.username!=='string'||typeof value.email_verified!=='boolean')throw Error('资料状态尚未确认，请重试读取');
 const cleanName=name.value===profile.value.display_name,cleanUsername=username.value===profile.value.username,cleanEmail=emailDraft.value===(profile.value.email||'')&&!emailCode.value;
 const merged={...profile.value};
 for(const field of Object.keys(fieldRevision) as ProfileField[]){if(revisions[field]!==fieldRevision[field])continue;if(merged[field]!==value[field]||(field==='email'&&merged.email_verified!==value.email_verified))fieldRevision[field]++;Object.assign(merged,{[field]:value[field]});if(field==='email')merged.email_verified=value.email_verified;}
 profile.value=merged;
 if(cleanName)name.value=merged.display_name;if(cleanUsername)username.value=merged.username;if(cleanEmail)emailDraft.value=merged.email||'';
 emit('confirmed',merged);
}
function errorText(e:unknown){return e instanceof Error?e.message:'请求失败，请重试';}
async function saveName(){
 if(!valid()||composing.value||nameBusy.value||!name.value.trim())return;
 const submitted=name.value.trim(),revisions=beginField('display_name');nameBusy.value=true;nameError.value='';
 try{
  if(namePending!==submitted){await json('/auth/me',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({display_name:submitted})});namePending=submitted;}
  const value=await json('/auth/me');if(value.display_name!==submitted)throw Error('名称尚未确认，请重试读取');
  confirmed(value,revisions);namePending=null;if(name.value.trim()===submitted){name.value=submitted;nameOpen.value=false;}
  toast(name.value.trim()===submitted?'昵称已保存':'上一版昵称已保存，当前草稿尚未保存');
 }catch(e){if(valid())nameError.value=errorText(e);}finally{if(valid())nameBusy.value=false;}
}
async function saveUsername(approved=false){
 if(!valid()||composing.value||usernameBusy.value)return;
 const submitted=approved?usernameConfirmation.value?.next??'':username.value.trim();usernameError.value='';
 if(!submitted){usernameError.value='用户名不能为空';return;}
 if(submitted!==profile.value.username&&(submitted===profile.value.display_name||submitted===(profile.value.email||''))){usernameError.value='用户名不能与昵称或邮箱相同';return;}
 if(!approved&&usernamePending!==submitted&&submitted!==profile.value.username){usernameConfirmation.value={old:profile.value.username,next:submitted};return;}
 usernameConfirmation.value=null;usernameBusy.value=true;const revisions=beginField('username');
 try{
  if(usernamePending!==submitted){await json('/auth/me',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:submitted})});usernamePending=submitted;}
  const value=await json('/auth/me');if(value.username!==submitted)throw Error('用户名尚未确认，请重试读取');
  confirmed(value,revisions);usernamePending=null;if(username.value.trim()===submitted){username.value=submitted;usernameOpen.value=false;}
  toast(username.value.trim()===submitted?'用户名已保存':'上一版用户名已保存，当前草稿尚未保存');
 }catch(e){if(valid())usernameError.value=errorText(e);}finally{if(valid())usernameBusy.value=false;}
}
function loadEmailService(){
 if(serviceRequest)return serviceRequest;
 serviceLoading.value=true;serviceError.value='';
 serviceRequest=(async()=>{try{const service=await json('/auth/email-service');if(typeof service.ready!=='boolean')throw Error('邮件服务状态尚未确认，请重试读取');emailServiceReady.value=service.ready;}catch(e){if(valid()){emailServiceReady.value=null;serviceError.value=errorText(e);}}finally{serviceRequest=null;if(valid())serviceLoading.value=false;}})();return serviceRequest;
}
async function openEmail(){
 if(!valid())return;
 emailError.value='';emailOpen.value=true;
 if(emailServiceReady.value===null)await loadEmailService();
}
async function emailAction(action:'save'|'send'|'resend'|'verify'){
 if(!valid()||composing.value||emailBusy.value)return;
 const address=action==='send'?stateAddress.value:action==='resend'||action==='verify'?verificationAddress.value:emailDraft.value.trim();
 if((action==='resend'||action==='verify')&&address!==stateAddress.value){emailError.value='邮箱已变化，请向当前地址重新发送验证码';return;}
 if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)){emailError.value='请填写有效邮箱地址';return;}
 emailBusy.value=true;emailError.value='';const targetRevision=addressRevision,revisions=action==='save'||action==='verify'?beginField('email'):{...fieldRevision};
 try{
  if(action==='send'||action==='resend'){
   await loadEmailService();ensure();
   if(stateAddress.value!==address||addressRevision!==targetRevision)return;
   if(emailServiceReady.value!==true){emailError.value=serviceError.value||'邮件服务不可用，请先检查服务与通知配置';return;}
   if(isSavedAddress.value&&profile.value.email_verified===true){emailError.value='此邮箱已通过验证，无需再次发送';return;}
   await json(action==='send'?'/auth/email/send-code':'/auth/email/resend',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:address,...(action==='resend'?{purpose:'bind'}:{})})});
   if(stateAddress.value!==address||addressRevision!==targetRevision)return;
   verificationAddress.value=address;emailStage.value='code';toast(action==='resend'?'新验证码已发送，旧码已作废':'验证码已发送，10 分钟内有效');await nextTick();if(valid())emailCodeInput.value?.focus();
  }else{
   if(emailPending?.address!==address||emailPending?.action!==action){
    await json(action==='save'?'/auth/me':'/auth/email/verify',{method:action==='save'?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:address,...(action==='verify'?{code:emailCode.value.trim()}:{})})});
    emailPending={address,action};
   }
   const value=await json('/auth/me');if(value.email!==address||(action==='verify'&&value.email_verified!==true))throw Error('邮箱尚未确认，请重试读取');
   const sameDraft=emailDraft.value.trim()===address;confirmed(value,revisions);emailPending=null;
   emailCode.value='';emailStage.value='input';verificationAddress.value='';emailStateControl.value?.close();
   if(sameDraft){emailDraft.value=address;emailOpen.value=false;}
   toast(sameDraft?(value.email_verified===true?'邮箱已验证':'邮箱已保存，尚未验证'):'上一版邮箱已保存，当前草稿尚未保存');
  }
 }catch(e){if(valid())emailError.value=errorText(e);}finally{if(valid())emailBusy.value=false;}
}
async function pickAvatar(url:string){
 if(!valid()||avatarBusy.value)return;avatarBusy.value=true;avatarError.value='';const revisions=beginField('avatar_url');
 try{await json('/auth/avatar-pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});const value=await json('/auth/me');if(value.avatar_url!==url)throw Error('头像尚未确认，请重试读取');confirmed(value,revisions);toast('头像已更新');if(!props.avatars)void loadAvatarHistory();}
 catch(e){if(valid())avatarError.value=errorText(e);}finally{if(valid())avatarBusy.value=false;}
}
async function refreshAvatar(){
 if(!valid())return;
 const revisions=beginField('avatar_url');try{confirmed(await json('/auth/me'),revisions);toast('头像已更新');if(!props.avatars)void loadAvatarHistory();}catch(e){if(valid())avatarError.value='头像已上传，但读取确认失败，请重试读取。';}
}
defineExpose({refreshAvatar,dirty});
</script>
<template>
  <section class="profile-settings">
    <h2>基础资料</h2>
    <div class="profile-field profile-avatar-row">
      <div class="profile-label">
        头像<HelpHint label="头像说明"
          >使用圆形预览，保留原有裁剪比例与最近 5 个头像。</HelpHint
        >
      </div>
      <div class="profile-control">
        <div class="profile-avatar-current">
          <img
            v-if="avatarImage"
            class="profile-avatar"
            :src="avatarImage"
            alt="当前头像"
          /><span
            v-else
            class="profile-avatar profile-avatar-fallback"
            aria-label="当前无头像"
            >{{ profile.display_name?.slice(0, 1) }}</span
          ><button
            type="button"
            class="profile-button st-button"
            @click="cropperOpen=true;emit('editAvatar')"
          >
            更换头像
          </button>
        </div>
        <div v-if="avatars.length" class="profile-avatar-history">
          <span class="profile-meta">最近使用</span>
          <div class="profile-avatar-options">
            <button
              v-for="(url, i) in avatars.slice(0, 5)"
              :key="url"
              type="button"
              :disabled="avatarBusy"
              :aria-label="`使用最近头像 ${i + 1}`"
              :aria-pressed="url === profile.avatar_url"
              @click="pickAvatar(url)"
            >
              <img :src="url" alt="" />
            </button>
          </div>
        </div>
        <p v-if="avatarError" class="profile-error" role="alert">
          {{ avatarError }}
          <button
            type="button"
            class="profile-button st-button"
            @click="refreshAvatar"
          >
            重试读取
          </button>
        </p>
      </div>
    </div>
    <div class="profile-fields">
      <form class="profile-field profile-data-row" @submit.prevent="saveName">
        <div class="profile-label">
          <label for="profile-name">昵称</label
          ><HelpHint label="昵称说明"
            >显示在 Stella 中的名称。修改后，登录用户名保持不变。</HelpHint
          >
        </div>
        <div class="profile-control">
          <div class="profile-inline profile-data-controls" :class="{'is-editing':nameOpen}">
            <div class="profile-value"><Transition name="profile-value-change"><input v-if="nameOpen" id="profile-name" v-model="name" autocomplete="nickname" required :aria-invalid="!!nameError" :aria-describedby="nameError ? 'profile-name-error' : undefined" @compositionstart="composing=true" @compositionend="composing=false" @keydown.enter="imeGuard" /><span v-else class="profile-value-text">{{profile.display_name}}</span></Transition></div>
            <span class="profile-status-slot" aria-hidden="true"></span>
            <div class="profile-actions"><template v-if="nameOpen"><button type="button" class="profile-button st-button is-ghost" :disabled="nameBusy" @click="nameOpen=false">取消</button><button class="profile-button st-button is-primary" :aria-busy="nameBusy" type="submit" :disabled="nameBusy || !name.trim() || name===profile.display_name"><span class="st-button-label">保存昵称</span></button></template><button v-else type="button" class="profile-button st-button" aria-label="编辑昵称" @click="openField('name')">编辑</button></div>
          </div>
          <p
            v-if="nameError"
            id="profile-name-error"
            class="profile-error"
            role="alert"
          >
            {{ nameError }}
          </p>
        </div>
      </form>
      <form class="profile-field profile-data-row" @submit.prevent="saveUsername()">
        <div class="profile-label">
          <label for="profile-username">用户名</label
          ><HelpHint label="用户名说明"
            >修改后请用新用户名登录；账号、资料与当前会话不变。昵称仍可独立用于登录，若昵称与旧用户名相同，旧文字仍可作为昵称登录。已接入网站可能显示新的用户名。</HelpHint
          >
        </div>
        <div class="profile-control">
          <div class="profile-inline profile-data-controls" :class="{'is-editing':usernameOpen}">
            <div class="profile-value"><Transition name="profile-value-change"><input v-if="usernameOpen" id="profile-username" v-model="username" autocomplete="username" required maxlength="254" :aria-invalid="!!usernameError" :aria-describedby="usernameError ? 'profile-username-error' : undefined" @compositionstart="composing=true" @compositionend="composing=false" @keydown.enter="imeGuard" /><span v-else class="profile-value-text">{{profile.username}}</span></Transition></div>
            <span class="profile-status-slot" aria-hidden="true"></span>
            <div class="profile-actions"><template v-if="usernameOpen"><button type="button" class="profile-button st-button is-ghost" :disabled="usernameBusy" @click="usernameOpen=false">取消</button><button type="submit" class="profile-button st-button is-primary" :disabled="usernameBusy || !username.trim() || username===profile.username" :aria-busy="usernameBusy"><span class="st-button-label">保存用户名</span></button></template><button v-else type="button" class="profile-button st-button" aria-label="编辑用户名" @click="openField('username')">编辑</button></div>
          </div>
          <p v-if="usernameError" id="profile-username-error" class="profile-error" role="alert">{{usernameError}}</p>
        </div>
      </form>
    <div class="profile-field profile-email-field profile-data-row">
      <div class="profile-label"><label :for="emailOpen ? 'profile-email-draft' : undefined">邮箱</label></div>
      <div class="profile-control">
        <form class="profile-email-row profile-data-controls" :class="emailOpen ? 'profile-email-editor is-editing' : 'profile-email-current'" @submit.prevent="emailAction('save')">
          <div class="profile-email-value profile-value"><Transition name="profile-value-change">
            <input v-if="emailOpen" id="profile-email-draft" v-model="emailDraft" type="email" autocomplete="email" aria-label="新邮箱地址" required
              :readonly="emailBusy" :aria-invalid="!!emailError" :aria-describedby="emailError ? 'profile-email-error' : undefined"
              @compositionstart="composing=true" @compositionend="composing=false" @keydown.enter="imeGuard" />
            <span v-else class="profile-email-address profile-value-text">{{profile.email || '尚未绑定'}}</span></Transition>
          </div>
            <EmailStateControl ref="emailStateControl" :state="emailState" :label="emailStateLabel" :disabled="!valid()" @open="loadEmailService">
              <p v-if="serviceLoading" class="email-state-text" role="status">正在读取邮件服务…</p>
              <template v-else-if="serviceError"><p class="profile-error" role="alert">{{serviceError}}</p><button type="button" class="profile-button st-button" @click="loadEmailService">重试读取</button></template>
              <template v-else-if="emailServiceReady===false"><p class="email-state-text"><template v-if="isSavedAddress&&profile.email_verified===true">邮箱已验证，当前发信服务不可用。</template><template v-else>邮件服务不可用。</template>仍可保存邮箱，不会发送邮件。</p><a class="email-service-link" href="/settings?section=services" @click.prevent="emailStateControl?.close();emit('services')">前往站点与服务</a></template>
              <p v-else-if="emailState==='verified'" class="email-state-text">此邮箱已通过验证，无需再次发送验证码。</p>
              <p v-else-if="emailState==='unknown'" class="email-state-text">邮箱验证状态尚未确认，请重新读取资料后再试。</p>
              <p v-else-if="!stateAddress" class="email-state-text">尚未绑定邮箱，请先编辑邮箱地址。</p>
              <p v-else-if="emailStage!=='code' || verificationAddress!==stateAddress" class="email-state-text">{{isSavedAddress ? '此邮箱尚未验证。' : '新地址尚未保存或验证。'}}保存不会发信，也不会自动验证。</p>
              <button v-if="emailState==='pending' && stateAddress && (emailStage!=='code' || verificationAddress!==stateAddress)" type="button" class="profile-button st-button" :disabled="emailBusy" :aria-busy="emailBusy" @click="emailAction('send')">发送验证码</button>
              <form v-if="emailStage==='code' && verificationAddress===stateAddress && emailState!=='verified'" class="profile-email-code-value" @submit.stop.prevent="emailAction('verify')">
                <p class="email-state-text">验证码已发送至 {{verificationAddress}}，10 分钟内有效。</p>
                <label for="profile-email-code">邮箱验证码</label>
                <input id="profile-email-code" ref="emailCodeInput" v-model="emailCode" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required :readonly="emailBusy"
                  :aria-invalid="!!emailError" :aria-describedby="emailError ? 'email-code-error' : undefined" @compositionstart="composing=true" @compositionend="composing=false" @keydown.enter="imeGuard" />
                <div class="email-code-actions"><button type="button" class="profile-button st-button" :disabled="emailBusy || serviceLoading || emailServiceReady!==true" @click="emailAction('resend')">重新发送</button><button type="submit" class="profile-button st-button is-primary" :disabled="emailBusy || emailCode.trim().length!==6" :aria-busy="emailBusy">完成验证</button></div>
              </form>
              <p v-if="emailError" id="email-code-error" class="profile-error" role="alert">{{emailError}}</p>
            </EmailStateControl>
          <div class="profile-email-actions profile-actions">
            <template v-if="emailOpen"><button type="button" class="profile-button st-button is-ghost" :disabled="emailBusy" @click="emailOpen=false;emailStateControl?.close()">取消</button><button type="submit" class="profile-button st-button is-primary" :disabled="emailBusy || !emailDraft.trim()" :aria-busy="emailBusy">保存邮箱</button></template>
            <button v-else type="button" class="profile-button st-button" aria-label="编辑邮箱" :disabled="emailBusy" @click="openEmail">{{profile.email ? '编辑' : '绑定'}}</button>
          </div>
        </form>
        <p v-if="emailError" id="profile-email-error" class="profile-error" role="alert">{{emailError}}</p>
        <p v-if="serviceError" class="profile-error" role="alert">邮件服务读取失败；仍可编辑和保存邮箱。<button type="button" class="profile-button st-button" @click="loadEmailService">重试读取</button></p>
      </div>
    </div>
    </div>
    <footer class="profile-security-link">
      <span>密码、登录设备与会话</span
      ><a href="?section=account#login-security" @click.prevent="emit('security')"
        >前往登录与会话 <span aria-hidden="true">→</span></a
      >
    </footer>
    <AvatarCropper v-if="cropperOpen" :request="uploadRequest" @close="cropperOpen=false" @done="refreshAvatar" />
    <Teleport to="body"><Transition name="profile-confirm"><div v-if="usernameConfirmation" class="profile-confirm-mask" @click.self="closeUsernameConfirmation" @keydown="confirmationKeys"><section ref="usernameDialog" role="dialog" aria-modal="true" aria-label="确认修改用户名" class="profile-confirm-dialog"><h2>确认修改用户名</h2><p class="profile-username-diff"><span>{{usernameConfirmation.old}}</span><span aria-label="改为">→</span><strong>{{usernameConfirmation.next}}</strong></p><p>下次请用新用户名登录。昵称仍可独立用于登录。</p><div class="profile-actions"><button class="st-button is-ghost" type="button" @click="closeUsernameConfirmation">返回编辑</button><button class="st-button is-primary" type="button" @click="saveUsername(true)">确认修改</button></div></section></div></Transition></Teleport>
  </section>
</template>
<style scoped>
.profile-settings { width:100%;max-width:760px;margin-inline:auto;container-type:inline-size;container-name:profile; --settings-label-width: minmax(140px, 200px); --settings-control-width: 440px; }
.profile-confirm-mask{position:fixed;inset:0;z-index:320;background:#090c1280;display:grid;place-items:center;padding:16px;}
.profile-confirm-dialog{box-sizing:border-box;width:min(100%,420px);padding:22px;background:var(--bg-raised);border:1px solid var(--control-border);border-radius:12px;color:var(--text-hi);font-size:14px;line-height:1.6;box-shadow:0 16px 50px #0007;}
.profile-confirm-dialog h2{margin:0;font-size:18px;}.profile-username-diff{display:flex;flex-wrap:wrap;gap:10px;overflow-wrap:anywhere;}.profile-confirm-enter-active,.profile-confirm-leave-active{transition:opacity .15s ease;}.profile-confirm-enter-active .profile-confirm-dialog,.profile-confirm-leave-active .profile-confirm-dialog{transition:transform .15s ease;}.profile-confirm-enter-from,.profile-confirm-leave-to{opacity:0;}.profile-confirm-enter-from .profile-confirm-dialog,.profile-confirm-leave-to .profile-confirm-dialog{transform:translateY(6px);}@media(prefers-reduced-motion:reduce){.profile-confirm-enter-active,.profile-confirm-leave-active,.profile-confirm-enter-active .profile-confirm-dialog,.profile-confirm-leave-active .profile-confirm-dialog{transition:none;}}
.profile-settings h2 { font-size:16px; font-weight:550; margin:0 0 18px; }
.profile-fields { margin:0; }
.profile-field { display:grid; grid-template-columns:var(--settings-label-width) minmax(0,1fr); gap:24px; padding:18px 0; border-bottom:1px solid var(--control-border,var(--accent-dim)); }
.profile-settings > .profile-field:last-of-type { border-bottom:0; }
.profile-label { display:flex; align-items:center; align-self:start; min-height:38px; font-size:14px; font-weight:500; }
.profile-control { min-width:0; }
.profile-data-row { grid-template-columns:100px minmax(0,1fr);gap:20px;padding:12px 0; }
.profile-data-controls { display:grid;grid-template-columns:minmax(0,1fr) 36px 154px;gap:8px;align-items:center;margin:0; }
/* Reading reserves only its actual button; all row-end actions share one stable edge. */
.profile-data-controls:not(.is-editing) { display:flex;gap:8px; }
.profile-data-controls:not(.is-editing) .profile-value { flex:0 1 auto; }
.profile-data-controls:not(.is-editing) .profile-status-slot { display:none; }
.profile-data-controls:not(.is-editing) .profile-actions { flex:none;margin-left:auto;justify-content:flex-end; }
.profile-fields > .profile-data-row:last-child { border-bottom:0; }
.profile-value { min-width:0;position:relative; }
.profile-value-change-enter-active,.profile-value-change-leave-active{transition:opacity .14s ease,transform .14s ease;}.profile-value-change-leave-active{position:absolute;inset:0;pointer-events:none;}.profile-value-change-enter-from,.profile-value-change-leave-to{opacity:0;transform:translateY(3px);}@media(prefers-reduced-motion:reduce){.profile-value-change-enter-active,.profile-value-change-leave-active{transition:none;}}
.profile-value-text { display:block;min-height:38px;align-content:center;overflow-wrap:anywhere;line-height:1.5;font-size:14px; }
.profile-actions { display:flex;gap:8px;justify-content:flex-end;align-items:center;min-height:38px; }
.profile-actions button { white-space:nowrap; }
.profile-actions .is-primary{min-width:92px;}
.profile-data-controls input { box-sizing:border-box;width:100%;max-width:none; }
.profile-settings .profile-control > input { width:min(100%,340px); }
.profile-settings input { display:block; width:100%; min-width:0; min-height:38px; padding:7px 11px; background:var(--control-bg,var(--bg-panel)); color:var(--text-hi); border:1px solid var(--control-border,var(--accent-dim)); border-radius:6px; font:inherit; }
.profile-settings input[readonly] { color:var(--text-lo); background:var(--bg-base); }
.profile-settings input[aria-invalid=true] { border-color:var(--danger); }
.profile-meta { display:inline-block; margin-top:8px; font-size:13px; color:var(--text-lo); }
.profile-error { margin:9px 0 0; font-size:14px; overflow-wrap:anywhere; }
.profile-error { color:var(--danger); }
.profile-settings p { line-height:1.6; }
.profile-settings input:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
.profile-avatar-current { display:flex; align-items:center; gap:18px; flex-wrap:wrap; }
.profile-avatar { display:block; width:64px; height:64px; object-fit:cover; border-radius:50%; border:1px solid var(--control-border,var(--accent-dim)); }
.profile-avatar-fallback { display:grid; place-items:center; font-size:24px; color:var(--accent); background:var(--selected-bg); }
.profile-avatar-history { display:flex; align-items:center; flex-wrap:wrap; gap:14px; margin-top:14px; }
.profile-avatar-history .profile-meta { margin:0; flex:none; }
.profile-avatar-options { display:flex; gap:6px; flex-wrap:wrap; }
.profile-avatar-options button { width:38px; height:38px; padding:3px; border:1px solid transparent; border-radius:50%; background:transparent; cursor:pointer; }
.profile-avatar-options button[aria-pressed=true] { border-color:var(--accent); }
.profile-avatar-options img { display:block; width:100%; height:100%; object-fit:cover; border-radius:50%; }
/* Three responsibilities: field label, bounded value + fixed status slot, row-end actions. */
.profile-email-row { padding:0;min-height:38px; }
.profile-email-address { overflow-wrap:anywhere; min-width:0; line-height:1.5; }
.profile-email-actions { display:flex; align-items:center; justify-content:flex-end; justify-self:end; gap:8px; flex-wrap:nowrap; min-height:38px; margin:0; }
.profile-email-actions button { white-space:nowrap; }
.profile-email-code-value { min-width:0; }
.profile-email-code-value input { box-sizing:border-box; display:block; width:100%; min-width:0; min-height:38px; padding:7px 11px; border:1px solid var(--control-border); border-radius:6px; background:var(--control-bg); color:var(--text-hi); font:inherit; }
.profile-email-code-value > label { display:block; font-size:14px; margin:0 0 7px; }
.email-code-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; margin-top:12px; }
.email-state-text { margin:0 0 10px; line-height:1.6; }
.email-service-link { display:inline-flex; align-items:center; min-height:38px; color:var(--accent); }
.profile-security-link { display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; border-top:1px solid var(--control-border,var(--accent-dim)); margin-top:12px; padding-top:14px; font-size:14px; color:var(--text-lo); }
.profile-security-link a { color:var(--accent); min-height:38px; display:inline-flex; align-items:center; gap:8px; }
.profile-security-link a:hover { text-decoration:underline; }
.profile-disclosure-enter-active,.profile-disclosure-leave-active { transition:height .18s ease,opacity .14s ease,transform .18s ease,margin .18s ease,padding .18s ease; }
.profile-disclosure-enter-from,.profile-disclosure-leave-to { height:0;opacity:0;transform:translateY(-4px);margin-top:0;padding-block:0; }
@media(prefers-reduced-motion:reduce) { .profile-disclosure-enter-active,.profile-disclosure-leave-active{transition:none;} }
@container profile (max-width:540px) {
  .profile-field {grid-template-columns:minmax(0,1fr);gap:4px;}
  .profile-data-row {padding:5px 0;}
  .profile-label{min-height:28px;}
  .profile-data-controls.is-editing{grid-template-columns:minmax(0,1fr) 44px;position:relative;gap:8px 0;}
  .is-editing .profile-value{grid-column:1 / -1;grid-row:1;}
  .is-editing .profile-value input{padding-right:50px;}
  .is-editing .profile-status-slot,.is-editing :deep(.email-state-control){grid-column:2;grid-row:1;z-index:1;}
  .is-editing .profile-actions{grid-column:1 / -1;grid-row:2;width:100%;min-height:44px;}
}
@media(max-width:768px) {
  .profile-data-controls:not(.is-editing) .profile-value-text,.profile-data-controls .profile-actions {min-height:44px;}
  .profile-data-controls .profile-actions button {min-height:44px;min-width:44px;}
}
@media(max-width:768px) { .profile-email-code-value input {min-height:44px;font-size:16px;} }
@media(max-width:768px) { .profile-control { width:100%; }.profile-settings input { min-height:44px; font-size:16px; }.profile-avatar-options button { width:44px;height:44px; }.profile-security-link a { min-height:44px; } }
</style>
