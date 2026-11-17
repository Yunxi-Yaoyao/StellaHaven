<script setup lang="ts">
import type {ThemePart} from './appearanceParts';
defineProps<{part:ThemePart;editing:boolean;selected?:boolean}>();
const emit=defineEmits<{select:[part:ThemePart,element:HTMLElement]}>();
function select(event:Event,part:ThemePart,editing:boolean){if(!editing)return;event.preventDefault();event.stopPropagation();emit('select',part,event.currentTarget as HTMLElement);}
</script>
<template>
 <div class="theme-part" :class="{'is-editable':editing,'is-selected':selected}" :data-theme-part="part.id" :role="editing?'button':undefined" :tabindex="editing?0:undefined" :aria-label="editing?`调色：${part.name}`:undefined" :aria-pressed="editing?!!selected:undefined" @click.capture="select($event,part,editing)" @keydown.capture="($event.key==='Enter'||$event.key===' ')&&select($event,part,editing)">
  <span v-if="editing" class="part-name" aria-hidden="true">{{part.name}}</span><div :inert="editing||undefined"><slot/></div>
 </div>
</template>
<style scoped>
.theme-part{position:relative;min-width:0;border-radius:8px}.is-editable{cursor:crosshair}.is-editable:hover,.is-editable:focus-visible{outline:1px dashed var(--accent);outline-offset:4px}.is-selected{outline:2px solid var(--accent);outline-offset:4px}.part-name{position:absolute;right:4px;top:-13px;z-index:2;background:var(--bg-raised);color:var(--text-hi);padding:0 5px;font-size:11px;opacity:0;pointer-events:none}.is-editable:hover>.part-name,.is-editable:focus-visible>.part-name,.is-selected>.part-name{opacity:1}
</style>
