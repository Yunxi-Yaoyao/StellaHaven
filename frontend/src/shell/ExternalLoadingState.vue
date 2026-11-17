<script setup lang="ts">
import Icon from './Icon.vue';
withDefaults(defineProps<{name?:string;icon?:string;stage:string;compact?:boolean}>(),{name:'网站',icon:'globe',compact:false});
</script>
<template>
 <div class="external-loading" :class="compact?'external-loading--compact':'external-loading--center'" role="status" aria-live="polite" aria-atomic="true">
  <span class="site-mark" aria-hidden="true"><Icon :name="icon" :size="compact?18:28"/></span>
  <div><strong v-if="!compact">{{name}}</strong><p><span class="activity" aria-hidden="true"/>{{stage}}</p><small v-if="!compact">原站登录与内容状态由网站自身显示</small></div>
 </div>
</template>
<style scoped>
.external-loading{z-index:2;color:var(--text-hi,#e8e8ed);pointer-events:none}
.external-loading--center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;text-align:center;background:var(--bg-base,#17191f)}
.site-mark{display:grid;place-items:center;width:64px;height:64px;border:1px solid #9898a52e;border-radius:20px;background:var(--bg-raised,#25272e);color:var(--accent,#9cd5c7)}
strong{display:block;font-size:18px;font-weight:500;line-height:1.5}p{display:flex;align-items:center;justify-content:center;gap:8px;margin:10px 0;color:var(--text-hi,#e8e8ed);font-size:14px;line-height:1.6}small{color:var(--text-lo,#b6b6c1);font-size:12px;line-height:1.6}
.activity{width:6px;height:6px;border-radius:50%;background:currentColor;animation:external-pulse 1.4s ease-in-out infinite}
.external-loading--compact{position:absolute;top:12px;right:16px;display:flex;gap:8px;align-items:center;padding:4px 12px;border:1px solid #9898a52e;border-radius:10px;background:var(--bg-panel,#25272e)}
.external-loading--compact .site-mark{width:auto;height:auto;border:0;background:none}.external-loading--compact p{margin:4px 0;font-size:12px}
@keyframes external-pulse{50%{opacity:.35}}
@media(prefers-reduced-motion:reduce){.activity{animation:none}}
</style>
