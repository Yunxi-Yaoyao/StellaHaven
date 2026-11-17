<script setup lang="ts">
import {computed} from 'vue';
const value=defineModel<string|null>({required:true});
defineProps<{label:string}>();
const palette=['#ffffff','#202020','#a5decb','#60a5fa','#c084fc','#fb7185','#fbbf24'];
const picker=computed(()=>/^#[\da-f]{6}$/i.test(value.value||'')?value.value!:'#a5decb');
</script>
<template><div class="nav-color"><div class="nav-color-swatches"><button v-for="c in palette" :key="c" type="button" :aria-label="label+' '+c" :aria-pressed="value===c" :style="{background:c}" @click="value=c"></button><input type="color" :aria-label="label+' 自选色板'" :value="picker" @input="value=($event.target as HTMLInputElement).value"><button type="button" class="st-button is-ghost" @click="value=null">跟随主题</button></div><input :aria-label="label" :value="value||''" placeholder="可选 HEX / alpha" maxlength="9" @input="value=($event.target as HTMLInputElement).value||null"></div></template>
