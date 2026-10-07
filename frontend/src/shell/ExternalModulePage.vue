<script setup lang="ts">
import {ref,watch,onBeforeUnmount,nextTick,computed} from 'vue';
import {getWebsite,launchWebsite,websiteError,type Website} from '../api/integrations';
import {checkWebsiteDraft} from '../api/websiteSettings';
import {auth,displayBg} from '../modules/home/auth';
import {effectiveWebsiteBackground} from '../stores/websiteBackground';
import {navigation} from '../stores/navigation';
import {useBackgroundMedia} from '../modules/home/backgroundMedia';
const props=withDefaults(defineProps<{id:string;active?:boolean}>(),{active:true});
// A retained page owns an immutable module ID, not global useRoute().params.
const fetchedWebsite=ref<Website|null>(null),url=ref(''),error=ref(''),loading=ref(false),frameKey=ref(0);
const website=computed(()=>navigation.loaded?navigation.modules.find(item=>item.id===props.id)||null:fetchedWebsite.value);
const frameEl=ref<HTMLIFrameElement|null>(null);
const homeBackground=computed(()=>effectiveWebsiteBackground(website.value).mode==='home');
const videoBackground=computed(()=>/\.(mp4|webm)(?:[?#]|$)/i.test(displayBg.value));
// Resolve the existing quality/poster selection, never fetch the original first.
// A background consumer starts after launch; large media must not delay its ticket.
const mediaUrl=computed(()=>homeBackground.value&&props.active&&url.value?displayBg.value:'');
const {source:mediaSource,poster:mediaPoster}=useBackgroundMedia(mediaUrl);
const backgroundStyle=computed(()=>{const image=videoBackground.value?mediaPoster.value:mediaSource.value;return homeBackground.value&&image?{backgroundImage:`url(${JSON.stringify(image)})`,backgroundSize:'cover',backgroundPosition:'center'}:{};});
// The visible, enabled code opts into style readiness; no adapter/template ID special cases.
const presentationEnabled=computed(()=>!!website.value?.injection?.active?.enabled&&website.value.injection.active.js.includes('/* stella:background-ready:v1 */'));
const backgroundReady=ref(false),presentationError=ref('');
const awaitingBackground=computed(()=>presentationEnabled.value&&homeBackground.value&&!backgroundReady.value);
let presentationRequest='',presentationTimer:ReturnType<typeof setTimeout>|undefined;
function targetOrigin(){const item=website.value;return item?(item.mode==='isolated_proxy'?item.origin:new URL(item.browser_url,location.origin).origin):undefined;}
// Template code alone owns inner transparency. Never read or mutate cross-origin DOM.
function notifyBackground(){
 const item=website.value,origin=targetOrigin();
 if(!item||!url.value||!origin||!props.active||!auth.me||auth.sessionClosing||!frameEl.value?.contentWindow)return;
 frameEl.value.contentWindow.postMessage({type:'stella-bg-mode',mode:homeBackground.value?'image':'solid',module_id:item.id,request_id:presentationRequest},origin);
}
function beginPresentation(){
 clearTimeout(presentationTimer);presentationError.value='';backgroundReady.value=false;
 presentationRequest=crypto.randomUUID();
 if(awaitingBackground.value&&url.value&&props.active)presentationTimer=setTimeout(()=>{
  presentationError.value='背景样式未就绪，请重新连接或检查自定义代码';loading.value=false;
 },20000);
 notifyBackground();
}
function receivePresentation(event:MessageEvent){
 if(!props.active||!auth.me||auth.sessionClosing||!url.value||event.source!==frameEl.value?.contentWindow||event.origin!==targetOrigin())return;
 if(event.data?.type==='stella-bg-request'){notifyBackground();return;}
 const data=event.data;
 if(!presentationEnabled.value||data?.type!=='stella-bg-ready'||data.module_id!==props.id||data.request_id!==presentationRequest||data.mode!==(homeBackground.value?'image':'solid'))return;
 backgroundReady.value=true;presentationError.value='';clearTimeout(presentationTimer);
}
window.addEventListener('message',receivePresentation);
watch([homeBackground,presentationEnabled,frameKey,url],beginPresentation,{flush:'sync',immediate:true});
const blocked=ref(false),paused=ref(false),timedOut=ref(false);
const notice=computed(()=>error.value || presentationError.value || (blocked.value?'该网站不允许在这里打开喵~':paused.value?'连接已暂停，点击重新连接喵~':timedOut.value?'加载较慢，可以重新连接喵~':website.value?.mode==='link'?'此网站在新窗口打开喵~':''));
const frameName='stella-external-module-frame-'+props.id;
let generation=0,timer:ReturnType<typeof setTimeout>|undefined,request:AbortController|undefined;
function cancel(){generation++;request?.abort();request=undefined;clearTimeout(timer);loading.value=false;}
function safeURL(value:string){const result=new URL(value,location.origin);if(!['https:','http:'].includes(result.protocol)||result.username||result.password)throw new Error('Invalid launch URL');return result.href;}
async function load(){
 if(!props.active||!auth.me||auth.sessionClosing)return;
 cancel();const id=props.id,owner=auth.me.id,session=auth.sessionGeneration,seq=generation;
 const controller=request=new AbortController();
 const valid=()=>seq===generation&&!controller.signal.aborted&&owner===auth.me?.id&&session===auth.sessionGeneration&&!auth.sessionClosing&&props.active;
 blocked.value=false;paused.value=false;timedOut.value=false;loading.value=true;error.value='';url.value='';fetchedWebsite.value=null;
 try{
  const item=navigation.loaded?navigation.modules.find(item=>item.id===id):await getWebsite(id,controller.signal);if(!valid())return;
  if(!item)throw new Error('Module missing');
  if(!item.enabled)throw new Error('Module disabled');
  fetchedWebsite.value=item;
  if(item.mode==='iframe'){
   try{const result=await checkWebsiteDraft({address:item.browser_url,open_behavior:'embedded',custom_enabled:false},controller.signal);if(!valid())return;
    if(result.embedding.status==='blocked'){blocked.value=true;url.value=safeURL(item.browser_url);loading.value=false;return;}
   }catch{if(!valid())return;/* An unavailable probe does not prove the browser will fail. */}
  }
  const launch=await launchWebsite(id,controller.signal);if(!valid())return;
  fetchedWebsite.value=item;frameKey.value++;const safe=safeURL(launch.url);
  if(item.mode==='link'){url.value=safe;loading.value=false;return;}
  if(launch.method==='POST'){
   if(item.mode!=='isolated_proxy'||new URL(safe).origin!==item.origin||new URL(safe).origin===location.origin)throw new Error('Unsafe bootstrap origin');
   url.value='about:blank';await nextTick();if(!valid())return;
   const form=document.createElement('form');form.method='POST';form.action=safe;form.target=frameName;form.hidden=true;
   for(const [name,value] of Object.entries(launch.fields||{})){const field=document.createElement('input');field.type='hidden';field.name=name;field.value=value;form.append(field);}
   document.body.append(form);try{form.submit();}finally{form.remove();}
  }else url.value=safe;
  timer=setTimeout(()=>{if(valid()){loading.value=false;timedOut.value=true;}},20000);
 }catch(e){if(valid()){error.value=websiteError(e);loading.value=false;}}
 finally{if(request===controller)request=undefined;}
}
// Dismiss the navigation indicator; never equate cross-origin load with login/readiness.
function loaded(){if(!url.value||blocked.value)return;clearTimeout(timer);loading.value=false;timedOut.value=false;notifyBackground();}
watch(()=>props.id,load,{immediate:true});
watch(()=>props.active,active=>{if(!active){cancel();clearTimeout(presentationTimer);if(!url.value)paused.value=true;}else if(url.value){if(awaitingBackground.value)beginPresentation();else notifyBackground();}},{flush:'sync'});
// fetchMe replaces the user object during polling; only identity/session changes invalidate a connection.
watch([()=>auth.me?.id,()=>auth.sessionGeneration,()=>auth.sessionClosing],()=>{cancel();url.value='';fetchedWebsite.value=null;error.value='';blocked.value=false;paused.value=false;timedOut.value=false;},{flush:'sync'});
onBeforeUnmount(()=>{cancel();clearTimeout(presentationTimer);presentationRequest='';window.removeEventListener('message',receivePresentation);});
</script>

<template>
 <section class="external-page" :class="{'home-background':homeBackground}" :style="backgroundStyle">
  <video v-if="homeBackground&&videoBackground&&props.active&&mediaSource" class="bg-video" :src="mediaSource" :poster="mediaPoster||undefined" autoplay muted loop playsinline />
  <div v-if="notice" class="connection-notice">
   <p :role="error || blocked || presentationError ? 'alert' : 'status'">{{notice}}</p>
   <div class="recovery-actions">
    <button v-if="website?.mode!=='link'" :disabled="loading" @click="load">重新连接</button>
    <a v-if="url && website && website.mode!=='isolated_proxy'" :href="url" target="_blank" rel="noopener noreferrer">新窗口打开</a>
    <RouterLink :to="{path:'/settings',query:{section:'navigation',module:props.id}}">连接设置</RouterLink>
   </div>
  </div>
  <span v-else-if="loading||awaitingBackground" class="loading-hint" role="status">{{awaitingBackground?'正在准备背景样式…':'正在加载…'}}</span>
  <iframe ref="frameEl" v-if="website && website.mode!=='link' && url && !blocked" :key="frameKey" :style="{visibility:awaitingBackground?'hidden':'visible'}" :aria-hidden="awaitingBackground" :name="frameName" :title="website.name" :src="url" referrerpolicy="no-referrer" allow="fullscreen" @load="loaded" />
 </section>
</template>

<style scoped>
.external-page{position:relative;display:flex;flex-direction:column;height:100%;min-height:300px;overflow:hidden;background:#14171f}
.bg-video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;pointer-events:none}
.home-background iframe{background:transparent}
iframe{position:relative;display:block;width:100%;flex:1;min-height:0;border:0;background:#14171f}
.loading-hint{position:absolute;z-index:1;top:12px;right:16px;padding:4px 8px;border-radius:6px;background:var(--bg-panel);color:var(--text-lo);font-size:12px;pointer-events:none}
.connection-notice{padding:14px 16px;background:var(--bg-panel);color:var(--text-lo);font-size:13px}
.connection-notice p{margin:0 0 10px;line-height:1.6}
.recovery-actions{display:flex;flex-wrap:wrap;gap:8px}
.recovery-actions button,.recovery-actions a{padding:6px 10px;border:1px solid #ffffff15;border-radius:7px;background:var(--bg-raised);color:var(--text-hi);font:inherit;text-decoration:none;white-space:nowrap;cursor:pointer}
[role=alert]{color:var(--pink)}
</style>
