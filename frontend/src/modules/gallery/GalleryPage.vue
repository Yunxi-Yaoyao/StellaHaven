<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount} from 'vue';
import {api} from '../../api/client';
import {useRouter} from 'vue-router';
const router=useRouter();
const connected=ref(false),loading=ref(false),error=ref(''),frameKey=ref(0),frame=ref<HTMLIFrameElement|null>(null);
let timer:ReturnType<typeof setTimeout>|undefined,alive=true;
onBeforeUnmount(()=>{alive=false;clearTimeout(timer);});
function loaded(){
 clearTimeout(timer);loading.value=false;error.value='';
 // Same-origin failure responses are observable. Cross-origin load is not proof of readiness.
 try{const text=frame.value?.contentDocument?.body?.innerText||'';
  if(text.trim().startsWith('{')){const body=JSON.parse(text);if(body.detail)error.value=typeof body.detail==='string'?body.detail:'Immich 连接失败，请重试。';}
 }catch{/* The original Immich domain owns its login and UI. */}
}
async function refresh(){
 if(loading.value)return;loading.value=true;error.value='';
 try{await api('/gallery/status');if(!alive)return;connected.value=true;frameKey.value++;
  clearTimeout(timer);timer=setTimeout(()=>{loading.value=false;error.value='Immich 加载较慢或无法嵌入，请重试或在新窗口打开。';},20000);
 }catch(e:any){if(alive){loading.value=false;error.value=typeof e?.detail==='string'?e.detail:'连接加载失败，请重试';}}
}
onMounted(refresh);
</script>
<template><div class="gallery-page">
 <div v-if="error" class="recovery"><p role="alert">{{error}}</p><button :disabled="loading" @click="refresh">重新连接</button><a href="/gallery/connect" target="_blank" rel="noopener noreferrer">新窗口打开</a><button @click="router.push({path:'/settings',query:{section:'navigation',module:'gallery'}})">连接设置</button></div>
 <iframe v-if="connected" :key="frameKey" ref="frame" title="Immich 图库" class="frame ready" src="/gallery/connect" referrerpolicy="no-referrer" allow="fullscreen" @load="loaded" @error="error='Immich 加载失败，请重新连接';loading=false"/>
</div></template>
<style scoped>
.gallery-page{height:100%;min-height:0;overflow:hidden;display:flex;flex-direction:column;background:#14171f}.frame{flex:1;min-height:0;width:100%;background:#14171f;border:0;box-sizing:border-box}.recovery{padding:16px;background:var(--bg-panel);font-size:13px;color:var(--text-lo)}.recovery p{margin:0 0 12px}.recovery button,.recovery a{display:inline-block;padding:7px 12px;margin:0 8px 8px 0;white-space:nowrap;background:var(--bg-raised);color:var(--text-hi);border:1px solid #ffffff20;border-radius:7px;font:inherit;text-decoration:none;cursor:pointer}
</style>
