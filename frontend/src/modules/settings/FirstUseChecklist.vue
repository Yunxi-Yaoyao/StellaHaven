<script setup lang="ts">
import {ref,computed,watch,onBeforeUnmount} from 'vue';
import {useRouter} from 'vue-router';
import {auth,loggedIn} from '../home/auth';
const router=useRouter();
defineProps<{embedded?:boolean}>();
type State='loading'|'ready'|'todo'|'error';
const steps=[
 {key:'entry',title:'确认默认入口',to:'/settings?section=services#site-addresses'},
 {key:'alternate',title:'其他入口（可选）',to:'/settings?section=services#site-addresses'},
 {key:'mail',title:'邮件服务（可选）',to:'/settings?section=services#email-service'},
 {key:'email',title:'验证账号邮箱（可选）',to:'/settings?section=account'},
 {key:'backup',title:'备份目录与计划',to:'/settings?section=backups'},
 {key:'node',title:'接入首个节点',to:'/status?view=nodes'},
];
const states=ref<Record<string,{state:State;detail:string}>>({});
const skipped=ref<string[]>([]);
let generation=0,controller=new AbortController();
const owner=computed(()=>loggedIn.value?auth.me?.id:null);
function key(){return `stella_first_use:${owner.value}`;}
function persist(){if(owner.value)try{localStorage.setItem(key(),JSON.stringify(skipped.value));}catch{/* Storage is optional. */}}
function skip(k:string){skipped.value=skipped.value.includes(k)?skipped.value.filter(v=>v!==k):[...skipped.value,k];persist();}
function skipAll(){skipped.value=steps.map(s=>s.key);persist();}
async function load(){
 controller.abort();controller=new AbortController();const seq=++generation,signal=controller.signal;
 states.value={};if(!owner.value)return;
 const current=()=>seq===generation&&!!owner.value&&!signal.aborted;
 const read=async(path:string)=>{const r=await fetch(path,{method:'GET',credentials:'same-origin',cache:'no-store',signal});if(!r.ok)throw Error('read');return r.json();};
 const task=async(keys:string[],path:string,decode:(v:any)=>Record<string,{state:State;detail:string}>)=>{for(const k of keys)states.value[k]={state:'loading',detail:'正在读取…'};try{const result=decode(await read(path));if(current())Object.assign(states.value,result);}catch{if(current())for(const k of keys)states.value[k]={state:'error',detail:'读取失败，状态未确认'};}};
 const status=(ready:boolean,yes:string,no:string)=>({state:ready?'ready' as const:'todo' as const,detail:ready?yes:no});
 await Promise.all([
 task(['entry','alternate'],'/config/access-entries',v=>{if(typeof v.settings?.public_origin!=='string'||!('private_origin' in v.settings))throw Error('schema');return {entry:status(!!v.settings.public_origin,v.settings.public_origin+' · 已应用（不代表网络验证）','尚未应用默认入口地址'),alternate:status(!!v.settings.private_origin,v.settings.private_origin,'未配置，可跳过')};}),
 task(['mail'],'/auth/email-service',v=>{if(typeof v.ready!=='boolean')throw Error('schema');return {mail:status(v.ready,'发信服务可用（不代表邮件已送达）','发信服务尚不可用，可跳过')};}),
 task(['email'],'/auth/me',v=>{if(typeof v.email_verified!=='boolean'||typeof v.email!=='string')throw Error('schema');return {email:status(!!v.email&&v.email_verified,'账号邮箱已验证',v.email?'邮箱尚未验证':'未绑定邮箱，可跳过')};}),
 task(['backup'],'/operations/backups',v=>{if(typeof v.config?.enabled!=='boolean'||typeof v.config?.directory!=='string'||typeof v.storage?.available!=='boolean')throw Error('schema');return {backup:status(v.config.enabled&&!!v.config.directory&&v.storage.available,'目录可用，备份计划已启用（不代表已有成功备份）','请在备份与恢复中确认目录和计划')};}),
 task(['node'],'/nodes/',v=>{if(!Array.isArray(v))throw Error('schema');const node=v.find(n=>['online','offline'].includes(n.status)&&typeof n.last_seen_at==='string'&&Number.isFinite(Date.parse(n.last_seen_at)));return {node:status(!!node,'已收到节点认证心跳','尚无节点心跳；待报到不算接入')};}),
 ]);
}
watch(()=>[owner.value,auth.sessionGeneration,auth.requestEpoch] as const,()=>{skipped.value=[];if(owner.value)try{const value=JSON.parse(localStorage.getItem(key())||'[]');if(Array.isArray(value))skipped.value=value.filter((v:unknown)=>typeof v==='string'&&steps.some(s=>s.key===v));}catch{/* Ignore invalid local state. */}void load();},{immediate:true,flush:'sync'});
onBeforeUnmount(()=>{generation++;controller.abort();});
</script>
<template>
<section class="first-use" aria-label="首次使用清单">
 <header><h2 v-if="!embedded">首次使用清单</h2><p>账号已可使用。按需完善，也可以全部暂跳过；以后从设置或帮助返回这里。</p></header>
 <p v-if="!owner" role="status">请登录后查看清单。</p>
 <ol v-else><li v-for="step in steps" :key="step.key" :data-step="step.key">
  <div class="step-copy"><h3>{{step.title}}</h3><p :class="states[step.key]?.state" role="status">{{states[step.key]?.detail||'状态未确认'}}</p><small v-if="skipped.includes(step.key)">已暂跳过</small></div>
  <div class="step-actions"><RouterLink :to="step.to">前往设置</RouterLink><button type="button" @click="skip(step.key)">{{skipped.includes(step.key)?'取消跳过':'暂跳过'}}</button></div>
 </li></ol>
 <footer><button type="button" @click="load">刷新状态</button><button type="button" @click="skipAll">全部暂跳过</button><button class="st-button is-primary" type="button" @click="router.push('/')">返回主站</button></footer>
</section>
</template>
<style scoped>
.first-use{color:var(--text-hi);min-width:0}.first-use h2{font-size:20px;margin:0 0 10px;font-weight:550}.first-use header p,.step-copy p{color:var(--text-lo);font-size:14px;line-height:1.65;margin:6px 0}.first-use ol{padding:0;margin:20px 0;list-style:none}.first-use li{display:flex;gap:16px;justify-content:space-between;align-items:center;padding:16px 0;border-bottom:1px solid var(--control-border)}.step-copy{min-width:0}.step-copy h3{font-size:15px;font-weight:550;margin:0}.step-copy p{overflow-wrap:anywhere}.step-copy .error{color:var(--error,#ed9696)}.step-copy .ready{color:var(--accent)}small{color:var(--text-lo)}.step-actions,footer{display:flex;gap:10px;align-items:center;flex-shrink:0}footer{flex-wrap:wrap;justify-content:flex-end}button,a{font:inherit;font-size:14px;color:var(--text-hi);min-height:38px;display:inline-flex;align-items:center;justify-content:center;padding:6px 10px;border:1px solid var(--control-border);border-radius:7px;background:transparent;text-decoration:none;box-sizing:border-box;cursor:pointer;white-space:nowrap}button:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:3px}@media(max-width:600px){.first-use li{align-items:flex-start;flex-direction:column;gap:8px}.step-actions{align-self:flex-end}button,a{min-height:44px}footer{justify-content:flex-start}}
</style>
