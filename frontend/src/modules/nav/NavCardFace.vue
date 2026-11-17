<script setup lang="ts">
import {computed} from 'vue';
import Icon from '../../shell/Icon.vue';
import {effectiveStyle,type Card,type Preferences,type Style} from './types';
const props=defineProps<{card:Card;preferences:Preferences;groupStyle?:Style|null}>();
const style=computed(()=>effectiveStyle(props.groupStyle,props.preferences));
const iconSrc=computed(()=>props.card.icon?.itemType===3&&/^[\w-]+:[\w-]+$/.test(props.card.icon.text)?`https://api.iconify.design/${props.card.icon.text.replace(':','/')}.svg`:props.card.icon?.src);
</script>
<template>
 <span class="nav-card-face" :class="style.layout" :style="{color:style.textColor||undefined,'--card-bg':card.icon?.backgroundColor||'var(--bg-raised)'}">
  <span class="nav-site-icon">
   <img v-if="iconSrc&&card.icon?.itemType!==1" :src="iconSrc" alt="" loading="lazy" referrerpolicy="no-referrer" @error="($event.target as HTMLImageElement).style.visibility='hidden'">
   <span v-else-if="card.icon?.text">{{card.icon.text.slice(0,4)}}</span><Icon v-else name="globe" :size="28"/>
  </span>
  <span v-if="style.layout==='info'||!style.hideTitle" class="nav-card-copy"><strong>{{card.title||'网站名称'}}</strong><small v-if="style.layout==='info'&&!style.hideDescription">{{card.description||' '}}</small></span>
 </span>
</template>
<style scoped>
.nav-card-face{display:flex;gap:12px;align-items:center;min-width:0;color:var(--text-hi)}.nav-card-face.info{background:var(--card-bg);border:1px solid var(--control-border,var(--selected-border));border-radius:12px;padding:12px;min-height:82px}.nav-card-face.icon{flex-direction:column;gap:10px;text-align:center;padding:10px 4px}.nav-site-icon{display:grid;place-items:center;flex:none;width:58px;height:58px;border-radius:14px;background:var(--card-bg);font-size:23px;overflow:hidden}.info .nav-site-icon{width:48px;height:48px;background:transparent}.nav-site-icon img{width:100%;height:100%;object-fit:contain}.nav-card-copy{min-width:0;max-width:100%;display:grid;gap:4px}.nav-card-copy strong{font-size:15px;font-weight:550;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.nav-card-copy small{font-size:13px;color:inherit;opacity:.78;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;line-height:1.5}.icon .nav-card-copy strong{max-width:120px}
</style>
