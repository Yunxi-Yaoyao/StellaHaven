<script setup lang="ts">
import {ref,watch,onBeforeUnmount,nextTick,computed} from 'vue';
import {getWebsite,launchWebsite,websiteError,type Website} from '../api/integrations';
import {auth,displayBg} from '../modules/home/auth';
import {effectiveWebsiteBackground} from '../stores/websiteBackground';
import {navigation} from '../stores/navigation';
import {useBackgroundMedia} from '../modules/home/backgroundMedia';
import ExternalLoadingState from './ExternalLoadingState.vue';
const props=withDefaults(defineProps<{id:string;active?:boolean}>(),{active:true});
// A retained page owns an immutable module ID, not global useRoute().params.
const fetchedWebsite=ref<Website|null>(null),url=ref(''),error=ref(''),loading=ref(false),frameKey=ref(0);
const hasDocument=ref(false),hasPresented=ref(false),stage=ref('正在读取网站配置…');
const loadingStage=computed(()=>awaitingBackground.value&&!loading.value?'正在准备外观…':stage.value);
// Navigation can contain only a summary; active code always comes from owned detail.
const website=computed(()=>{const detail=fetchedWebsite.value;if(!detail)return null;const summary=navigation.modules.find(item=>item.id===props.id);return summary?.background!==undefined?{...detail,background:summary.background}:detail;});
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
watch(hasDocument,()=>{if(hasDocument.value)hasPresented.value=true;},{flush:'sync'});
let presentationRequest='',presentationScheme='normal',presentationTimer:ReturnType<typeof setTimeout>|undefined;
const launchOrigin=ref('');
function targetOrigin(){const item=website.value;return item?(launchOrigin.value||(item.mode==='isolated_proxy'?item.origin:new URL(item.browser_url,location.origin).origin)):undefined;}
// Template code alone owns inner transparency. Never read or mutate cross-origin DOM.
function notifyBackground(){
 const item=website.value,origin=targetOrigin();
 if(!item||!url.value||!origin||!props.active||!auth.me||auth.sessionClosing||!frameEl.value?.contentWindow)return;
 // The child canvas must match the host's scheme, not just transparent CSS.
 // Send an enum only; never change the user's selected host theme.
 const colorScheme=getComputedStyle(document.documentElement).colorScheme;
 const canvasScheme=colorScheme==='dark'||colorScheme==='light'?colorScheme:'normal';
 presentationScheme=canvasScheme;
 frameEl.value.contentWindow.postMessage({type:'stella-bg-mode',mode:homeBackground.value?'image':'solid',color_scheme:canvasScheme,module_id:item.id,request_id:presentationRequest},origin);
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
 if(!presentationEnabled.value||data?.type!=='stella-bg-ready'||data.module_id!==props.id||data.request_id!==presentationRequest||data.mode!==(homeBackground.value?'image':'solid')||data.color_scheme!==presentationScheme)return;
 backgroundReady.value=true;presentationError.value='';clearTimeout(presentationTimer);
}
window.addEventListener('message',receivePresentation);
watch([homeBackground,presentationEnabled,frameKey,url],beginPresentation,{flush:'sync',immediate:true});
const blocked=ref(false),paused=ref(false),timedOut=ref(false);
const notice=computed(()=>error.value || presentationError.value || (blocked.value?'该网站不允许在这里打开喵~':paused.value?'连接已暂停，点击重新连接喵~':timedOut.value?'加载较慢，可以重新连接喵~':website.value?.mode==='link'?'此网站保留了旧外链配置，请在连接设置中检查并改为站内打开':''));
const frameName='stella-external-module-frame-'+props.id;
let generation=0,timer:ReturnType<typeof setTimeout>|undefined,request:AbortController|undefined;
function cancel(){generation++;request?.abort();request=undefined;clearTimeout(timer);loading.value=false;}
function safeURL(value:string){const result=new URL(value,location.origin);if(!['https:','http:'].includes(result.protocol)||result.username||result.password)throw new Error('Invalid launch URL');return result.href;}
async function load(){
 if(!props.active||!auth.me||auth.sessionClosing)return;
 cancel();const id=props.id,owner=auth.me.id,session=auth.sessionGeneration,seq=generation;
 const controller=request=new AbortController();
 const valid=()=>seq===generation&&!controller.signal.aborted&&owner===auth.me?.id&&session===auth.sessionGeneration&&!auth.sessionClosing&&props.active;
 timer=setTimeout(()=>{if(valid()){cancel();timedOut.value=true;}},20000);
 blocked.value=false;paused.value=false;timedOut.value=false;loading.value=true;error.value='';stage.value='正在读取网站配置…';
 try{
  const item=await getWebsite(id,controller.signal);if(!valid())return;
  if(!item)throw new Error('Module missing');
  if(!item.enabled)throw new Error('Module disabled');
  fetchedWebsite.value=item;
  stage.value='正在启动网站…';
  const launch=await launchWebsite(id,controller.signal);if(!valid())return;
  const safe=safeURL(launch.url),origin=new URL(safe).origin;
  // Bind every launch method to its issued source and target before probing,
  // mounting or sending presentation messages. Direct GET is not an exception.
  if((launch.source_origin!==undefined&&launch.source_origin!==location.origin)||(launch.target_origin!==undefined&&launch.target_origin!==origin))throw new Error('Unsafe launch origin');
  // Launch/save enforce target policy; a redundant network probe must not gate content.
  stage.value='等待页面响应…';
  fetchedWebsite.value=item;
  if(item.mode==='link'){url.value=safe;loading.value=false;clearTimeout(timer);return;}
  if(launch.method==='POST'){
   if(item.mode!=='isolated_proxy'||new URL(safe).origin===(location.origin)||new URL(safe).origin!==(launch.target_origin||item.origin)||(launch.source_origin!==undefined&&launch.source_origin!==location.origin))throw new Error('Unsafe bootstrap origin');
   launchOrigin.value=new URL(safe).origin;frameKey.value++;
   url.value='about:blank';await nextTick();if(!valid())return;
   const form=document.createElement('form');form.method='POST';form.action=safe;form.target=frameName;form.hidden=true;
   for(const [name,value] of Object.entries(launch.fields||{})){const field=document.createElement('input');field.type='hidden';field.name=name;field.value=value;form.append(field);}
   document.body.append(form);try{form.submit();}finally{form.remove();}
  }else{launchOrigin.value=new URL(safe).origin;frameKey.value++;url.value=safe;}
 }catch(e){if(valid()){error.value=websiteError(e);loading.value=false;clearTimeout(timer);}}
 finally{if(request===controller)request=undefined;}
}
// Dismiss the navigation indicator; never equate cross-origin load with login/readiness.
function loaded(){if(!url.value||blocked.value)return;if(request){notifyBackground();return;}clearTimeout(timer);loading.value=false;timedOut.value=false;hasDocument.value=true;notifyBackground();}
defineExpose({reconnect:()=>{void load();}});
watch(()=>props.id,load,{immediate:true});
watch(()=>props.active,active=>{if(!active){cancel();clearTimeout(presentationTimer);if(!url.value)paused.value=true;}else if(url.value){if(awaitingBackground.value)beginPresentation();else notifyBackground();}},{flush:'sync'});
// fetchMe replaces the user object during polling; only identity/session changes invalidate a connection.
watch([()=>auth.me?.id,()=>auth.sessionGeneration,()=>auth.sessionClosing],()=>{cancel();url.value='';hasDocument.value=false;hasPresented.value=false;fetchedWebsite.value=null;error.value='';blocked.value=false;paused.value=false;timedOut.value=false;},{flush:'sync'});
onBeforeUnmount(()=>{cancel();clearTimeout(presentationTimer);presentationRequest='';window.removeEventListener('message',receivePresentation);});
</script>

<template>
 <section class="external-page" :class="{'home-background':homeBackground}" :style="backgroundStyle">
  <video v-if="homeBackground&&videoBackground&&props.active&&mediaSource" class="bg-video" :src="mediaSource" :poster="mediaPoster||undefined" autoplay muted loop playsinline />
  <div v-if="notice" class="connection-notice">
   <p :role="error || blocked || presentationError ? 'alert' : 'status'">{{notice}}</p>
   <div class="recovery-actions">
    <button v-if="website?.mode!=='link'" :disabled="loading" @click="presentationError&&!error?beginPresentation():load()">{{presentationError&&!error?'重试外观':'重新连接'}}</button>
    <RouterLink :to="{path:'/settings',query:{section:'navigation',module:props.id}}">连接设置</RouterLink>
   </div>
  </div>
  <Transition name="external-state"><ExternalLoadingState v-if="!notice&&loading" :name="website?.name" :icon="website?.icon" :stage="loadingStage" :compact="hasPresented" /></Transition>
  <iframe ref="frameEl" v-if="website && website.mode!=='link' && url && !blocked" :key="frameKey" :style="{visibility:'visible'}" :name="frameName" :title="website.name" :src="url" referrerpolicy="no-referrer" allow="fullscreen" @load="loaded" />
 </section>
</template>

<style scoped>
.external-page{position:relative;display:flex;flex-direction:column;height:100%;min-height:300px;overflow:hidden;background:#14171f}
.bg-video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;pointer-events:none}
.home-background iframe{background:transparent}
iframe{position:relative;display:block;width:100%;flex:1;min-height:0;border:0;background:#14171f}
.external-state-enter-active,.external-state-leave-active{transition:opacity .18s ease,transform .18s ease}.external-state-enter-from,.external-state-leave-to{opacity:0;transform:translateY(4px)}
@media(prefers-reduced-motion:reduce){.external-state-enter-active,.external-state-leave-active{transition:none}.external-state-enter-from,.external-state-leave-to{transform:none}}
.connection-notice{padding:14px 16px;background:var(--bg-panel);color:var(--text-lo);font-size:13px}
.connection-notice p{margin:0 0 10px;line-height:1.6}
.recovery-actions{display:flex;flex-wrap:wrap;gap:8px}
.recovery-actions button,.recovery-actions a{padding:6px 10px;border:1px solid #ffffff15;border-radius:7px;background:var(--bg-raised);color:var(--text-hi);font:inherit;text-decoration:none;white-space:nowrap;cursor:pointer}
[role=alert]{color:var(--pink)}
</style>
