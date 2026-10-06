<script setup lang="ts">
import {ref,watch,onMounted} from 'vue';
import {navigation,navigationRows,navigationIcons,loadNavigation,saveNavigation,type NavRow} from '../../stores/navigation';
import Dropdown from '../../shell/Dropdown.vue';
import Icon from '../../shell/Icon.vue';
const rows=ref<(NavRow & {originalLabel:string})[]>([]),busy=ref(false),message=ref('');
const iconOptions=navigationIcons.map(value=>({value,label:value}));
watch(navigationRows,value=>{if(!busy.value)rows.value=value.map(row=>({...row,originalLabel:row.label}));},{immediate:true});
onMounted(()=>{if(!navigation.loaded)void loadNavigation();});
async function persist(reset=false) {
 if(busy.value)return;busy.value=true;message.value='';
 try {await saveNavigation(rows.value,reset);rows.value=navigationRows.value.map(row=>({...row,originalLabel:row.label}));message.value='导航已同步';}
 catch {message.value='导航未保存，保留当前修改。请重试。';}
 finally{busy.value=false;}
}
function move(index:number,delta:number){const next=index+delta;if(next<0||next>=rows.value.length)return;const row=rows.value.splice(index,1)[0];if(row)rows.value.splice(next,0,row);void persist();}
</script>
<template><section class="nav-settings"><header><h2>导航顺序与显示</h2><button :disabled="busy" @click="persist(true)">恢复默认导航</button></header><p>名称、图标、显示与顺序自动同步到服务器。隐藏设置后，侧栏底部账号入口仍可找回。</p><p v-if="navigation.error" role="alert">{{navigation.error}} <button @click="loadNavigation">重试加载</button></p>
<div v-for="(row,index) in rows" :key="row.id" class="nav-row"><Icon :name="row.icon" :size="17" /><input v-model="row.label" :aria-label="'导航名称 '+row.originalLabel" maxlength="80" :disabled="busy" @change="persist()" /><Dropdown :model-value="row.icon" :options="iconOptions" @update:model-value="row.icon=String($event);persist()" /><label class="visible"><input v-model="row.visible" type="checkbox" :aria-label="'显示导航 '+row.originalLabel" :disabled="busy" @change="persist()" />显示</label><button :disabled="busy||index===0" :aria-label="'上移 '+row.originalLabel" @click="move(index,-1)">↑</button><button :disabled="busy||index===rows.length-1" :aria-label="'下移 '+row.originalLabel" @click="move(index,1)">↓</button></div><p v-if="message" role="status">{{message}} <button v-if="message.includes('未保存')" @click="persist()">重试保存</button></p></section></template>
<style scoped>.nav-settings{background:var(--bg-panel);padding:20px;border-radius:14px;border:1px solid #ffffff12}header{display:flex;align-items:center;justify-content:space-between;gap:12px}h2{font-size:15px}p{font-size:12px;color:var(--text-lo);line-height:1.7;margin:12px 0}.nav-row{display:flex;align-items:center;gap:10px;padding:9px 0;border-top:1px solid #ffffff09}.nav-row>input{min-width:0;flex:1;width:100px;padding:7px 9px;border:1px solid #ffffff20;border-radius:7px;background:var(--bg-base);color:var(--text-hi)}button{white-space:nowrap;flex-shrink:0;padding:7px 10px;background:var(--bg-raised);border:1px solid #ffffff20;color:var(--text-hi);border-radius:7px;cursor:pointer}button:disabled{opacity:.45}.visible{display:flex;gap:6px;align-items:center;white-space:nowrap;font-size:12px}@media(max-width:600px){.nav-row{gap:7px;flex-wrap:wrap}.nav-row>input{flex:1 0 calc(100% - 40px)}.nav-row :deep(.dd-btn){min-width:110px}.nav-settings{padding:14px}}</style>
