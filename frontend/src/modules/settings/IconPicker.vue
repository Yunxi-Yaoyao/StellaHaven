<script setup lang="ts">
import {ref,computed,nextTick} from 'vue';
import Icon from '../../shell/Icon.vue';
import {navigationIcons,legacyNavigationIcons} from '../../stores/navigation';
const props=defineProps<{modelValue:string;name:string}>();
const emit=defineEmits<{'update:modelValue':[value:string]}>();
const labels:Record<string,string>={home:'首页',note:'笔记',image:'图片',drive:'网盘',server:'服务器',settings:'设置',globe:'网站',link:'链接',book:'书籍',folder:'文件夹',terminal:'终端',star:'收藏',activity:'监测',box:'应用'};
const opened=ref(false),trigger=ref<HTMLButtonElement>(),grid=ref<HTMLElement>();
const legacyLabels:Record<string,string>={heart:'爱心（旧图标）','file-text':'笔记（旧图标）','hard-drive':'网盘（旧图标）'};
const current=computed(()=>[...navigationIcons,...legacyNavigationIcons].includes(props.modelValue)?props.modelValue:'globe');
const currentLabel=computed(()=>labels[props.modelValue]||legacyLabels[props.modelValue]||(legacyNavigationIcons.includes(props.modelValue)?'旧图标：'+props.modelValue+'（网站预览，保存时保留）':'网站（未知图标：'+props.modelValue+'，保存时保留）'));
async function toggle(){opened.value=!opened.value;if(opened.value){await nextTick();(grid.value?.querySelector<HTMLButtonElement>('[aria-checked=true]')||grid.value?.querySelector<HTMLButtonElement>('button'))?.focus();}}
async function close(){opened.value=false;await nextTick();trigger.value?.focus();}
function pick(id:string){emit('update:modelValue',id);void close();}
function key(event:KeyboardEvent,index:number){
 if(event.key==='Escape'){event.preventDefault();void close();return;}
 const delta:Record<string,number>={ArrowLeft:-1,ArrowRight:1,ArrowUp:-4,ArrowDown:4};
 if(event.key in delta){event.preventDefault();const next=(index+delta[event.key]!+navigationIcons.length)%navigationIcons.length;grid.value?.querySelectorAll<HTMLButtonElement>('button')[next]?.focus();}
}
</script>
<template><div class="icon-picker"><button ref="trigger" type="button" :aria-expanded="opened" :aria-label="'选择图标，当前'+currentLabel" @click="toggle"><Icon :name="current" :size="18"/>{{currentLabel}}<Icon name="chevron-down"/></button><div v-if="opened" ref="grid" class="icon-grid" role="radiogroup" aria-label="图标选择"><button v-for="(id,index) in navigationIcons" :key="id" type="button" role="radio" :aria-label="labels[id]" :aria-checked="current===id" :tabindex="current===id||(!navigationIcons.includes(current)&&index===0)?0:-1" @click="pick(id)" @keydown="key($event,index)"><Icon :name="id" :size="22"/><span>{{labels[id]}}</span></button></div><p>侧栏效果</p><div class="sidebar-preview" aria-label="侧栏效果"><Icon :name="current" :size="18"/><span>{{name||'网站名称'}}</span></div></div></template>
<style scoped>.icon-picker{min-width:0}button{font:inherit;display:inline-flex;align-items:center;gap:8px;padding:8px 11px;background:var(--bg-raised);color:var(--text-hi);border:1px solid #ffffff20;border-radius:7px;cursor:pointer}.icon-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;padding:10px;margin-top:10px;border:1px solid #ffffff20;border-radius:8px;width:300px;max-width:100%;box-sizing:border-box}.icon-grid button{flex-direction:column;padding:9px 2px;font-size:12px;min-width:0}.icon-grid [aria-checked=true]{border-color:var(--accent);background:#7085a930}button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}p{font-size:12px;color:var(--text-lo);margin:12px 0 6px}.sidebar-preview{display:flex;align-items:center;gap:8px;font-size:14px;padding:10px;background:var(--bg-panel);border-radius:8px}.sidebar-preview span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}</style>
