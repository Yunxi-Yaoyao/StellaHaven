<script setup lang="ts">
import {metricColors} from '../../stores/appearance';
defineProps<{kind:'cpu'|'memory'|'disk';label:string}>();
const values={cpu:[18,32,28,51,38,62,45,57],memory:[42,43,46,44,51,50,54,52],disk:[11,24,15,34,17,28,21,19]};
const path=(series:number[])=>series.map((v,i)=>`${i?'L':'M'}${i*28+2},${78-v}`).join(' ');
</script>
<template>
 <div class="metric-example"><span class="legend"><i :style="{background:metricColors[kind]}"/>{{label}}</span><svg viewBox="0 0 200 80" role="img" :aria-label="`${label}示例趋势`"><path d="M0,77 H200" :stroke="metricColors[kind+'Start' as 'cpuStart']"/><path :d="path(values[kind])" fill="none" :stroke="metricColors[kind]" stroke-width="2.5" stroke-linejoin="round"/><circle cx="198" :cy="78-values[kind][7]!" r="3" :fill="metricColors[kind]"/></svg></div>
</template>
<style scoped>
.metric-example{padding:10px;background:var(--bg-panel);border:1px solid var(--control-border);border-radius:8px}.legend{display:flex;align-items:center;gap:6px;font-size:13px}.legend i{width:9px;height:9px;border-radius:3px}svg{width:100%;height:70px;display:block}
</style>
