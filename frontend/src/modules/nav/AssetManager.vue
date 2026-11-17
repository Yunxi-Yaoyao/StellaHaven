<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue';
import {api} from '../../api/client';
import {auth} from '../home/auth';
import NavSelect from './NavSelect.vue';
import type {Asset} from './types';
const props=defineProps<{assets:Asset[];busy:boolean}>();
const emit=defineEmits<{refresh:[];busy:[value:boolean]}>();
const purposes=[{value:'uncategorized',label:'未分类'},{value:'icon',label:'图标'},{value:'background',label:'背景'},{value:'logo',label:'标识'},{value:'other',label:'其他'}];
const filter=ref(''),category=ref('icon'),selected=ref<string[]>([]),error=ref('');
const visible=computed(()=>props.assets.filter(a=>!filter.value||a.category===filter.value));
let epoch=0;
const identity=()=>`${auth.me?.id}:${auth.sessionGeneration}:${auth.requestEpoch}`;
watch(identity,()=>{epoch++;selected.value=[];error.value='';},{flush:'sync'});
watch(()=>props.assets,()=>selected.value=selected.value.filter(id=>props.assets.some(a=>a.id===id)));
onBeforeUnmount(()=>epoch++);
async function mutate(kind:'category'|'delete'){
 if(props.busy||!selected.value.length)return;
 const ids=[...selected.value],id=identity(),generation=epoch;
 if(kind==='delete'&&!window.confirm(`确认删除所选 ${ids.length} 项素材？整批有任一引用或无权项将全部拒绝。`))return;
 emit('busy',true);error.value='';
 try{await api(kind==='delete'?'/nav-assets-batch-delete':'/nav-assets-category',{method:'POST',body:JSON.stringify({ids,...(kind==='category'?{category:category.value}:{})})},()=>generation===epoch&&id===identity());if(generation===epoch&&id===identity()){selected.value=[];emit('refresh');}}
 catch(e){if(generation===epoch&&id===identity())error.value=typeof (e as any)?.detail==='string'?(e as any).detail:'结果未确认，请重读素材；不会自动重放操作。';}
 finally{if(generation===epoch&&id===identity())emit('busy',false);}
}
</script>
<template><section aria-label="素材分类与批量管理"><div class="nav-actions"><NavSelect label="素材分类筛选" v-model="filter" :options="[{value:'',label:'全部分类'},...purposes]"/><button type="button" class="st-button" :disabled="busy" @click="selected=visible.map(a=>a.id)">选择当前分类</button><button type="button" class="st-button is-ghost" @click="selected=[]">清除选择</button></div><div v-if="selected.length" class="nav-actions"><span>已选 {{selected.length}} 项</span><NavSelect label="批量用途分类" v-model="category" :options="purposes"/><button type="button" class="st-button" :disabled="busy" @click="mutate('category')">应用分类</button><button type="button" class="st-button is-danger" :disabled="busy" @click="mutate('delete')">删除所选</button></div><p v-if="error" role="alert" class="nav-error">{{error}}</p><div class="nav-material-grid"><article v-for="a in visible" :key="a.id"><label class="nav-check"><input type="checkbox" :value="a.id" v-model="selected" :aria-label="'选择素材 '+a.name" :disabled="busy">选择</label><img :src="a.url" :alt="a.name"><strong>{{a.name}}</strong><span>{{purposes.find(p=>p.value===a.category)?.label||'未分类'}} · {{a.width??'?'}} × {{a.height??'?'}} · {{a.size}} bytes</span><details><summary>素材详情</summary><p>{{a.mime}}</p><p class="nav-asset-hash">SHA-256 {{a.sha256}}</p><input :value="a.url" readonly :aria-label="a.name+' 素材地址'"></details></article></div><p v-if="!visible.length" class="nav-empty">此分类暂无素材。</p></section></template>
