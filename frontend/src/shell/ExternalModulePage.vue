<script setup lang="ts">
import {ref,watch,onBeforeUnmount,nextTick} from 'vue';
import {getWebsite,launchWebsite,websiteError,type Website} from '../api/integrations';
import {checkWebsiteDraft,type WebsiteCheck} from '../api/websiteSettings';
import {auth} from '../modules/home/auth';
import Icon from './Icon.vue';
const props=withDefaults(defineProps<{id:string;active?:boolean}>(),{active:true});
// A retained page owns an immutable module ID, not global useRoute().params.
const website=ref<Website|null>(null),url=ref(''),error=ref(''),status=ref('连接中…'),loading=ref(false),frameKey=ref(0);
const check=ref<WebsiteCheck|null>(null),blocked=ref(false);
const frameName='stella-external-module-frame-'+props.id;
let generation=0,timer:ReturnType<typeof setTimeout>|undefined,request:AbortController|undefined;
function cancel(){generation++;request?.abort();request=undefined;clearTimeout(timer);loading.value=false;}
function safeURL(value:string){const result=new URL(value,location.origin);if(!['https:','http:'].includes(result.protocol)||result.username||result.password)throw new Error('Invalid launch URL');return result.href;}
async function load(){
 if(!props.active||!auth.me||auth.sessionClosing)return;
 cancel();const id=props.id,owner=auth.me.id,session=auth.sessionGeneration,seq=generation;
 const controller=request=new AbortController();
 const valid=()=>seq===generation&&!controller.signal.aborted&&owner===auth.me?.id&&session===auth.sessionGeneration&&!auth.sessionClosing&&props.active;
 check.value=null;blocked.value=false;loading.value=true;error.value='';url.value='';website.value=null;status.value='连接中…';
 try{
  const item=await getWebsite(id,controller.signal);if(!valid())return;
  if(!item.enabled)throw new Error('Module disabled');
  website.value=item;
  if(item.mode==='iframe'){
   try{const result=await checkWebsiteDraft({address:item.browser_url,open_behavior:'embedded',custom_enabled:false},controller.signal);if(!valid())return;check.value=result;
    if(result.embedding.status==='blocked'){blocked.value=true;url.value=safeURL(item.browser_url);status.value=result.embedding.reason;loading.value=false;return;}
   }catch{if(!valid())return;status.value='检测未完成，浏览器内容状态未知';}
  }
  const launch=await launchWebsite(id,controller.signal);if(!valid())return;
  website.value=item;frameKey.value++;const safe=safeURL(launch.url);
  if(item.mode==='link'){url.value=safe;status.value='外链模式：请点击新窗口打开';loading.value=false;return;}
  if(launch.method==='POST'){
   if(item.mode!=='isolated_proxy'||new URL(safe).origin!==item.origin||new URL(safe).origin===location.origin)throw new Error('Unsafe bootstrap origin');
   url.value='about:blank';await nextTick();if(!valid())return;
   const form=document.createElement('form');form.method='POST';form.action=safe;form.target=frameName;form.hidden=true;
   for(const [name,value] of Object.entries(launch.fields||{})){const field=document.createElement('input');field.type='hidden';field.name=name;field.value=value;form.append(field);}
   document.body.append(form);try{form.submit();}finally{form.remove();}
  }else url.value=safe;
  timer=setTimeout(()=>{if(valid()){loading.value=false;status.value='导航耗时较长或被目标策略限制，请重连或新窗口打开';}},20000);
 }catch(e){if(valid()){error.value=websiteError(e);loading.value=false;}}
 finally{if(request===controller)request=undefined;}
}
function loaded(){if(!url.value||blocked.value)return;clearTimeout(timer);loading.value=false;status.value='浏览器内容状态未知；load 事件不代表页面可用或登录成功';}
watch(()=>props.id,load,{immediate:true});
watch(()=>props.active,active=>{if(!active){cancel();if(!url.value)status.value='连接已暂停，请手动重新连接';}},{flush:'sync'});
watch(()=>[auth.me?.id,auth.sessionGeneration,auth.sessionClosing],()=>{cancel();url.value='';website.value=null;},{flush:'sync'});
onBeforeUnmount(cancel);
</script>
<template><section class="external-page"><header><h1><Icon :name="website?.icon||'globe'" :size="18"/>{{website?.name||'网站模块'}}</h1><div class="actions"><button :disabled="loading" @click="load">重新连接</button><a v-if="website" :href="website.mode==='isolated_proxy'?undefined:url" :aria-disabled="website.mode==='isolated_proxy'" target="_blank" rel="noopener noreferrer">新窗口打开</a><RouterLink :to="{path:'/settings',query:{section:'navigation',module:props.id}}">连接设置</RouterLink></div></header><p v-if="error" role="alert">{{error}}</p><p v-else role="status">{{status}}</p><section v-if="check?.help" class="check-help"><p>{{check.help.title}}</p><p v-if="check.help.location"><code>{{check.help.location}}</code></p><p v-for="line in check.help.instructions" :key="line">{{line}}</p></section><p v-if="website?.keep_alive">已保留现场；第三方网站可能自行后台运行。此缓存不延长会话或管理授权，授权过期后请手动重新连接。</p><p v-if="website?.mode==='isolated_proxy'">独立代理启动票据只经 POST 提交，不包含在 URL 中。新窗口请从原网站域名手动登录。</p><iframe v-if="website && website.mode!=='link' && url && !blocked" :key="frameKey" ref="frame" :name="frameName" :title="website.name" :src="url" referrerpolicy="no-referrer" allow="fullscreen" @load="loaded" /></section></template>
<style scoped>.external-page{display:flex;flex-direction:column;height:100%;min-height:300px;background:var(--bg-panel);border:1px solid #ffffff12;border-radius:12px;overflow:hidden}header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;flex-wrap:wrap}h1{display:flex;align-items:center;gap:8px;font-size:15px}.actions{display:flex;gap:8px;flex-wrap:wrap}button,a{padding:7px 10px;background:var(--bg-raised);border:1px solid #ffffff15;border-radius:7px;color:var(--text-hi);font-size:12px;white-space:nowrap;cursor:pointer}p{padding:8px 16px;color:var(--text-lo);font-size:12px}iframe{width:100%;flex:1;min-height:0;border:0;background:#14171f}[role=alert]{color:var(--pink)}[aria-disabled=true]{opacity:.45;pointer-events:none}</style>
