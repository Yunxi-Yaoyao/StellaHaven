<script setup lang="ts">
defineProps<{label:string;checked:boolean}>();
const emit=defineEmits<{change:[checked:boolean]}>();
</script>
<template><button class="theme-switch" type="button" role="switch" :aria-label="label" :aria-checked="checked" @click="emit('change',!checked)"><span/></button></template>
<style scoped>
.theme-switch{box-sizing:border-box;position:relative;display:inline-flex;align-items:center;flex:none;width:34px;height:20px;padding:2px;border:1px solid var(--control-border);border-radius:20px;background:var(--control-bg);cursor:pointer;vertical-align:middle}.theme-switch span{width:14px;height:14px;display:block;flex:none;border-radius:50%;background:var(--text-lo);transition:transform .15s}.theme-switch[aria-checked=true]{background:var(--accent-dim);border-color:var(--accent)}.theme-switch[aria-checked=true] span{transform:translateX(14px);background:var(--accent)}.theme-switch:focus-visible{outline:2px solid var(--accent);outline-offset:4px}@media(max-width:640px){.theme-switch:before{content:'';position:absolute;inset:-10px -5px}}@media(prefers-reduced-motion:reduce){.theme-switch span{transition:none}}
</style>
