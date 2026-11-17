<script setup lang="ts">
import {computed} from 'vue';
import Dropdown from '../../shell/Dropdown.vue';
const props=defineProps<{modelValue:any;options:{value:string|number|boolean|null;label:string}[];label:string;disabled?:boolean}>();
const emit=defineEmits<{ 'update:modelValue':[value:any];change:[] }>();
const options=computed(()=>props.options.map(o=>({...o,value:o.value===null?'__nav_inherit__':o.value})));
function update(value:string|number|boolean){emit('update:modelValue',value==='__nav_inherit__'?null:value);emit('change');}
</script>
<template><Dropdown class="nav-select" :label="label" :disabled="disabled" :model-value="modelValue??'__nav_inherit__'" :options="options" @update:model-value="update"/></template>
