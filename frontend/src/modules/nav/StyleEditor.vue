<script setup lang="ts">
import type {Style} from './types';
import NavSelect from './NavSelect.vue';
import NavColor from './NavColor.vue';
const props=defineProps<{value:Style;inherit?:boolean}>();
const emit=defineEmits<{change:[value:Style]}>();
function update(key:keyof Style,value:unknown){emit('change',{...props.value,[key]:value});}
const bools=[{value:false,label:'显示'},{value:true,label:'隐藏'}];
</script>
<template>
 <div class="nav-fields">
  <label>卡片布局<NavSelect label="卡片布局" :model-value="value.layout??null" :options="[...(inherit?[{value:null,label:'继承全局'}]:[]),{value:'icon',label:'图标'},{value:'info',label:'详情'}]" @update:model-value="update('layout',$event)"/></label>
  <label>文字颜色<NavColor label="文字颜色" :model-value="value.textColor??null" @update:model-value="update('textColor',$event)"/></label>
  <label>图标标题<NavSelect label="图标标题" :model-value="value.hideTitle??null" :options="[...(inherit?[{value:null,label:'继承全局'}]:[]),...bools]" @update:model-value="update('hideTitle',$event)"/></label>
  <label>详情描述<NavSelect label="详情描述" :model-value="value.hideDescription??null" :options="[...(inherit?[{value:null,label:'继承全局'}]:[]),...bools]" @update:model-value="update('hideDescription',$event)"/></label>
 </div>
</template>
