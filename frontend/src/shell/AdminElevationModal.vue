<script setup lang="ts">
import {ref,watch,onBeforeUnmount,nextTick} from 'vue';
import {api,setElevationHandler} from '../api/client';
import {auth,loadSecurity,isAdmin} from '../modules/home/auth';
import {elevation,requestElevation,finishElevation} from './elevation';
const password=ref(''),newPassword=ref(''),repeat=ref(''),error=ref(''),busy=ref(false),first=ref<HTMLInputElement>();
let previousFocus:HTMLElement|null=null;
setElevationHandler(requestElevation);
watch(()=>[auth.me?.id,auth.suspended,auth.sessionClosing],()=>{password.value='';newPassword.value='';repeat.value='';finishElevation(false);});
watch(()=>elevation.open,async open=>{password.value='';newPassword.value='';repeat.value='';error.value='';if(open){previousFocus=document.activeElement as HTMLElement;await nextTick();first.value?.focus();}else previousFocus?.focus();});
onBeforeUnmount(()=>{setElevationHandler();finishElevation(false);});
async function verify() {
 if(elevation.code==='admin_setup_required' && newPassword.value!==repeat.value){error.value='两次管理密码不一致';return;}
 busy.value=true;error.value='';
 try {
  if(elevation.code==='admin_setup_required') {
   await api('/auth/admin/setup',{method:'POST',body:JSON.stringify({user_password:password.value,new_password:newPassword.value})});
   await api('/auth/admin/unlock',{method:'POST',body:JSON.stringify({password:newPassword.value})});
  } else await api('/auth/admin/unlock',{method:'POST',body:JSON.stringify({password:password.value})});
  await loadSecurity();if(!isAdmin.value)throw new Error('Management grant not confirmed');password.value='';newPassword.value='';repeat.value='';elevation.ready=true;
 } catch { error.value='验证未通过，请检查密码或稍后重试';password.value='';newPassword.value='';repeat.value=''; }
 finally {busy.value=false;}
}
function trap(event:KeyboardEvent) {if(event.key!=='Tab')return;const nodes=(event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('input,button:not(:disabled)');const a=nodes[0],z=nodes[nodes.length-1];if(event.shiftKey&&document.activeElement===a){event.preventDefault();z?.focus();}else if(!event.shiftKey&&document.activeElement===z){event.preventDefault();a?.focus();}}
</script>
<template><Teleport to="body"><div v-if="elevation.open" class="admin-mask" @keydown.esc="!busy && finishElevation(false)" @click.self="!busy && finishElevation(false)"><section class="admin-dialog" role="dialog" aria-modal="true" aria-labelledby="admin-title" @keydown="trap">
<h2 id="admin-title">{{ elevation.ready ? '确认重试操作' : elevation.code==='admin_setup_required' ? '首次设置管理密码' : '解锁管理权限' }}</h2>
<template v-if="elevation.ready"><p>已验证管理权限。是否重试刚才被拒绝的操作？只重试一次，不执行其他操作。</p><p class="operation">{{ elevation.path }}</p><footer><button @click="finishElevation(false)">不重试</button><button @click="finishElevation(true)">确认重试一次</button></footer></template>
<form v-else @submit.prevent="verify"><p>日常登录不会获得管理权限。管理密码独立设置，不预填、不复用登录密码。</p><label>{{ elevation.code==='admin_setup_required'?'当前登录密码':'管理密码' }}<input ref="first" v-model="password" type="password" autocomplete="current-password" required /></label>
<template v-if="elevation.code==='admin_setup_required'"><label>新管理密码<input v-model="newPassword" type="password" autocomplete="new-password" minlength="10" maxlength="256" required /></label><label>再次输入管理密码<input v-model="repeat" type="password" autocomplete="new-password" minlength="10" maxlength="256" required /></label></template><p v-if="error" role="alert">{{ error }}</p><footer><button type="button" :disabled="busy" @click="finishElevation(false)">取消</button><button type="submit" :disabled="busy">{{ busy?'验证中…':'验证管理权限' }}</button></footer></form>
</section></div></Teleport></template>
<style scoped>.admin-mask{position:fixed;inset:0;background:#080c16b8;z-index:1100;display:grid;place-items:center;padding:18px}.admin-dialog{width:min(440px,100%);max-height:90vh;overflow:auto;border:1px solid #ffffff20;border-radius:14px;background:var(--bg-panel);padding:24px;color:var(--text-hi)}h2{font-size:18px}p{font-size:13px;line-height:1.7;color:var(--text-lo)}label{display:grid;gap:7px;font-size:13px;margin:14px 0}input{padding:10px;background:var(--bg-base);border:1px solid #ffffff25;border-radius:7px;color:inherit;width:100%}footer{display:flex;justify-content:flex-end;gap:8px;margin-top:20px}button{padding:8px 12px;background:var(--bg-raised);color:inherit;border:1px solid #ffffff25;border-radius:7px;white-space:nowrap;cursor:pointer}.operation{overflow-wrap:anywhere}[role=alert]{color:var(--pink)}</style>
