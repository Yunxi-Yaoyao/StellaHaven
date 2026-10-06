<script setup lang="ts">
import {ref,onMounted} from 'vue';
import {security,securityChecked,loadSecurity} from '../home/auth';
import {api} from '../../api/client';
const password=ref(''),newPassword=ref(''),repeat=ref(''),message=ref(''),busy=ref(false);
const mode=ref<'setup'|'unlock'|'password'|'disable'|'enable'|null>(null);
onMounted(()=>loadSecurity().catch(()=>message.value='安全状态读取失败；管理操作仍需服务端验证'));
function open(next:typeof mode.value){mode.value=next;password.value='';newPassword.value='';repeat.value='';message.value='';}
async function submit() {
 if ((mode.value==='setup'||mode.value==='password') && newPassword.value!==repeat.value){message.value='两次管理密码不一致';return;}
 busy.value=true;message.value='';
 try {
  if(mode.value==='setup')await api('/auth/admin/setup',{method:'POST',body:JSON.stringify({user_password:password.value,new_password:newPassword.value})});
  if(mode.value==='unlock')await api('/auth/admin/unlock',{method:'POST',body:JSON.stringify({password:password.value})});
  if(mode.value==='password')await api('/auth/admin/password',{method:'POST',body:JSON.stringify({current_password:password.value,new_password:newPassword.value})});
  if(mode.value==='disable'||mode.value==='enable')await api('/auth/security',{method:'PUT',body:JSON.stringify({enabled:mode.value==='enable',password:password.value})});
  await loadSecurity();mode.value=null;message.value='安全状态已更新';
 }catch{message.value='操作未完成，请检查密码或稍后重试';}
 finally{password.value='';newPassword.value='';repeat.value='';busy.value=false;}
}
async function lock(){try{await api('/auth/admin/lock',{method:'POST'});await loadSecurity();}catch{message.value='锁回失败，请重试';}}
</script>
<template><section class="security-card"><h2>管理保护</h2><template v-if="securityChecked"><div class="state"><span>{{security.enabled?'管理保护已开启':'管理保护已关闭'}}</span><span>{{security.enabled?(security.elevated?'管理权限已解锁':'管理权限未解锁'):'登录态可直接管理'}}</span></div><p v-if="security.expires_at && security.elevated">提权有效至 {{new Date(security.expires_at).toLocaleString()}}</p><p v-if="!security.configured">尚未设置管理密码。请验证当前登录密码，并设置独立管理密码；危险操作保持锁定。</p><p v-else>日常密码用于登录；管理密码仅用于危险操作授权。授权由服务器会话保存，退出或改密后失效。</p><div class="buttons"><button v-if="!security.configured" @click="open('setup')">设置管理密码</button><template v-else><button v-if="security.enabled && !security.elevated" @click="open('unlock')">解锁管理权限</button><button v-if="security.enabled && security.elevated" @click="lock">立即锁回</button><button @click="open('password')">修改管理密码</button><button v-if="security.enabled" @click="open('disable')">关闭管理保护</button><button v-else @click="open('enable')">开启管理保护</button></template></div></template><p v-else>读取安全状态…</p>
<form v-if="mode" @submit.prevent="submit"><p v-if="mode==='disable'">关闭后，任何已登录会话可直接管理。必须再次验证管理密码。</p><div class="fields"><label>{{mode==='setup'?'当前登录密码':'当前管理密码'}}<input v-model="password" type="password" autocomplete="current-password" required /></label><template v-if="mode==='setup'||mode==='password'"><label>新管理密码<input v-model="newPassword" type="password" minlength="10" maxlength="256" autocomplete="new-password" required /></label><label>再次输入管理密码<input v-model="repeat" type="password" minlength="10" maxlength="256" autocomplete="new-password" required /></label></template></div><div class="buttons"><button type="button" :disabled="busy" @click="open(null)">取消</button><button :disabled="busy" type="submit">{{mode==='disable'?'验证并关闭保护':mode==='enable'?'验证并开启保护':'确认安全变更'}}</button></div></form><p v-if="message" role="status">{{message}}</p></section></template>
<style scoped>.security-card{background:var(--bg-panel);border:1px solid #ffffff12;padding:20px;border-radius:14px;margin-bottom:18px}h2{font-size:15px;margin-bottom:12px}p{color:var(--text-lo);font-size:12px;line-height:1.7;margin:10px 0}.state,.buttons{display:flex;gap:10px;flex-wrap:wrap}.state{font-size:13px;color:var(--accent)}.fields{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0}label{display:flex;align-items:center;gap:8px;font-size:12px}input{width:180px;max-width:100%;background:var(--bg-base);border:1px solid #ffffff20;padding:8px;border-radius:7px;color:var(--text-hi)}button{padding:7px 12px;background:var(--bg-raised);border:1px solid #ffffff20;color:var(--text-hi);border-radius:7px;white-space:nowrap;cursor:pointer}@media(max-width:600px){label{width:100%;justify-content:space-between}input{width:55%}}</style>
