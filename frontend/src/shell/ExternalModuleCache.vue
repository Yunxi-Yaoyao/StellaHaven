<script setup lang="ts">
import {ref,watch,computed,defineAsyncComponent} from 'vue';
import {useRoute} from 'vue-router';
import {auth,loggedIn} from '../modules/home/auth';
import {navigation,navigationRows} from '../stores/navigation';
const ExternalModulePage=defineAsyncComponent(()=>import('./ExternalModulePage.vue'));
const route=useRoute();
type Entry={key:number;id:string; cached:boolean; fingerprint:string; used:number};
const entries=ref<Entry[]>([]);let clock=0;
const activeId=computed(()=>route.name==='external-module'?String(route.params.id):'');
function allowed(id:string){return loggedIn.value&&!auth.sessionClosing&&navigation.modules.some(m=>m.id===id&&m.enabled)&&navigationRows.value.some(r=>r.id===id&&r.visible);}
// Background is reactive in the page. Active code/connection changes need a new document;
// draft-only changes must not disturb the retained browsing context.
function fingerprint(id:string){const m=navigation.modules.find(m=>m.id===id);return m?JSON.stringify([m.mode,m.adapter,m.browser_url,m.target_id,m.initial_path,m.origin,m.keep_alive,m.connection,m.injection?.active]):'';}
watch(()=>[activeId.value,auth.me?.id,auth.sessionGeneration,auth.sessionClosing,auth.suspended,navigation.loaded,navigation.modules,navigation.entries],(_value,previous)=>{
 if(previous?.[1]!==auth.me?.id||previous?.[2]!==auth.sessionGeneration)entries.value=[];
 entries.value=entries.value.filter(e=>allowed(e.id)&&e.fingerprint===fingerprint(e.id)&&(e.cached||e.id===activeId.value));
 const id=activeId.value;if(!id||!navigation.loaded||!allowed(id))return;
 const existing=entries.value.find(e=>e.id===id);if(existing){existing.used=++clock;return;}
 const m=navigation.modules.find(m=>m.id===id)!;
 const cached=m.keep_alive===true&&m.mode!=='link';
 if(cached&&entries.value.filter(e=>e.cached).length>=3){const oldest=entries.value.filter(e=>e.cached).reduce((a,b)=>a.used<b.used?a:b);entries.value=entries.value.filter(e=>e!==oldest);}
 // Keep DOM insertion order stable: moving an iframe can reload its browsing context.
 entries.value.push({key:++clock,id,cached,fingerprint:fingerprint(id),used:clock});
},{deep:true,immediate:true,flush:'sync'});
</script>
<template><div v-show="activeId" class="external-cache"><ExternalModulePage v-for="entry in entries" :key="entry.key" v-show="activeId===entry.id" :id="entry.id" :active="activeId===entry.id" /><p v-if="activeId&&navigation.loaded&&!allowed(activeId)" role="alert">网站入口不存在、已隐藏或已禁用</p><p v-else-if="activeId&&!navigation.loaded" role="status">正在加载网站配置…</p></div></template>
<style scoped>.external-cache{height:100%;min-height:300px}</style>
