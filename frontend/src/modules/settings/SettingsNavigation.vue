<script setup lang="ts">
import {computed} from 'vue';
import Dropdown from '../../shell/Dropdown.vue';
const props=defineProps<{section:string}>();
const emit=defineEmits<{navigate:[key:string]}>();
const groups=[
 {label:'个人',items:[{key:'account',label:'账号与登录'},{key:'appearance',label:'外观与显示'}]},
 {label:'站点',items:[{key:'navigation',label:'导航与网站'},{key:'services',label:'站点与服务'}]},
 {label:'维护',items:[{key:'backups',label:'备份与恢复'},{key:'performance',label:'性能与存储'}]},
];
const current=computed(()=>props.section==='access'?'services':['profile','authentication'].includes(props.section)?'account':props.section);
const heading=computed(()=>current.value==='first-use'?'首次使用清单':groups.flatMap(g=>g.items).find(i=>i.key===current.value)?.label||'账号与登录');
const options=groups.flatMap(g=>g.items.map(i=>({value:i.key,label:i.label,desc:g.label})));
</script>
<template>
 <div class="settings-layout">
  <aside class="settings-side st-secondary-nav">
   <div class="settings-side-inner">
   <div class="st-secondary-heading"><p class="settings-title">设置</p></div>
   <nav aria-label="设置分组">
    <section v-for="group in groups" :key="group.label" class="st-secondary-group">
     <h2 class="st-secondary-label">{{group.label}}</h2>
     <template v-for="item in group.items" :key="item.key">
      <a class="tab st-secondary-item" :href="`/settings?section=${item.key}`" :aria-current="current===item.key?'page':undefined" @click.prevent="emit('navigate',item.key)">{{item.label}}</a>

     </template>
    </section>
   </nav>

   </div>
  </aside>
  <div class="settings-scene">
   <div class="settings-mobile-nav st-secondary-mobile"><span>设置</span><a v-if="current==='first-use'" class="settings-help-link" href="/settings?section=account" @click.prevent="emit('navigate','account')">返回设置</a><Dropdown v-else :model-value="current" :options="options" @update:model-value="emit('navigate',String($event))" /></div>
   <header class="settings-scene-header"><p>设置 <span aria-hidden="true">/</span> {{heading}}</p><h1>{{heading}}</h1></header>
   <div id="settings-content" :aria-label="heading"><slot /></div><a v-if="current!=='first-use'" class="settings-help-link" href="/settings?section=first-use" @click.prevent="emit('navigate','first-use')">首次使用清单</a> <RouterLink class="settings-help-link" to="/help?section=guide&page=settings">设置与保存说明 <span aria-hidden="true">↗</span></RouterLink>
  </div>
 </div>
</template>
<style scoped>
.settings-layout{display:grid;grid-template-columns:var(--secondary-nav-width) minmax(0,1fr);gap:var(--secondary-nav-gap);min-width:0;min-height:100%;color:var(--text-hi)}
.settings-side{padding-top:40px}
.settings-side-inner{position:sticky;top:40px;max-height:calc(100dvh - 56px);overflow:auto}
.settings-scene{min-width:0;width:100%;max-width:920px;margin-inline:auto;padding-block:36px 40px}
.settings-scene-header{margin:0 0 24px}.settings-scene-header p{font-size:12px;color:var(--text-lo);margin:0 0 18px}.settings-scene-header p span{padding:0 8px}.settings-scene-header h1{font-size:25px;line-height:1.3;letter-spacing:-.4px;font-weight:600;margin:0}
.settings-help-link{display:inline-flex;align-items:center;gap:6px;min-height:38px;color:var(--text-lo);font-size:12px;text-underline-offset:4px;margin-top:12px}
a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:768px){.settings-layout{display:block}.settings-scene{padding-top:0}.settings-scene-header p{display:none}.settings-scene-header{margin-bottom:20px}.settings-scene-header h1{font-size:23px}}
</style>
