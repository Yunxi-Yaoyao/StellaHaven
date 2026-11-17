<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { importTreeRows } from './import-helpers';
const props = defineProps<{ docs: { id: string; title: string; parent_id: string | null }[]; modelValue: string; disabled?: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const open = ref(false), query = ref(''), expanded = ref(new Set<string>());
const trigger = ref<HTMLButtonElement|null>(null), search = ref<HTMLInputElement|null>(null);
const rows = computed(() => importTreeRows(props.docs));
const byId = computed(() => new Map(props.docs.map(doc => [doc.id, doc])));
function ancestors(id:string) {
  const path:string[] = [], seen = new Set<string>();
  for(let doc = byId.value.get(id); doc && !seen.has(doc.id); doc = byId.value.get(doc.parent_id ?? '')) { seen.add(doc.id); path.unshift(doc.id); }
  return path;
}
function path(id:string) { return ['工作区根目录', ...ancestors(id).map(key => byId.value.get(key)?.title || '未命名笔记')].join(' / '); }
const duplicateTitles=computed(()=>{const seen=new Set<string>(),duplicates=new Set<string>();for(const doc of props.docs){if(seen.has(doc.title))duplicates.add(doc.title);seen.add(doc.title);}return duplicates;});
const children = computed(() => new Set(props.docs.map(doc => doc.parent_id).filter(Boolean)));
const visible = computed(() => {
  const q=query.value.trim().toLocaleLowerCase();
  if(!q)return rows.value.filter(row=>ancestors(row.id).slice(0,-1).every(id=>expanded.value.has(id)));
  const retained=new Set<string>();
  for(const row of rows.value)if(path(row.id).toLocaleLowerCase().includes(q))for(const id of ancestors(row.id))retained.add(id);
  return rows.value.filter(row=>retained.has(row.id));
});
const focusId=ref('');
const tree=ref<HTMLElement|null>(null);
const visibleIds=computed(()=>['',...visible.value.map(row=>row.id)]);
watch(visibleIds,ids=>{if(!ids.includes(focusId.value))focusId.value='';});
async function focus(id:string) { focusId.value=id;await nextTick();[...tree.value?.querySelectorAll<HTMLButtonElement>('[role=treeitem]')??[]].find(el=>el.dataset.id===id)?.focus(); }
function expandedRow(id:string) { return !!query.value.trim() || expanded.value.has(id); }
function keyboard(event:KeyboardEvent,id:string) {
  const ids=visibleIds.value,index=ids.indexOf(id);let next:string|undefined;
  if(event.key==='ArrowDown')next=ids[Math.min(index+1,ids.length-1)];
  else if(event.key==='ArrowUp')next=ids[Math.max(index-1,0)];
  else if(event.key==='Home')next=ids[0];
  else if(event.key==='End')next=ids.at(-1);
  else if(event.key==='ArrowRight') {
    if(!id)next=ids[1];
    else if(children.value.has(id)) {if(!expandedRow(id))branch(id);else next=visible.value.find(row=>byId.value.get(row.id)?.parent_id===id)?.id;}
  } else if(event.key==='ArrowLeft') {
    if(id&&children.value.has(id)&&expandedRow(id)&&!query.value.trim())branch(id);
    else next=byId.value.get(id)?.parent_id??'';
  } else return;
  event.preventDefault();if(next!==undefined)void focus(next);
}
async function toggle() {
  open.value = !open.value;
  if(open.value) { focusId.value=byId.value.has(props.modelValue)?props.modelValue:'';expanded.value = new Set([...expanded.value,...ancestors(props.modelValue)]); await nextTick(); search.value?.focus(); }
}
function branch(id:string) { const next = new Set(expanded.value); if(next.has(id))next.delete(id);else next.add(id);expanded.value=next; }
function close() { open.value=false;trigger.value?.focus(); }
function choose(id:string) { emit('update:modelValue',id);close(); }
</script>
<template>
  <div class="target-picker" @keydown.esc.stop="close">
    <button ref="trigger" class="target-summary" :title="path(modelValue)" :disabled="disabled" :aria-expanded="open" @click="toggle">{{path(modelValue)}} · 更改</button>
    <div v-if="open" class="target-options">
      <input ref="search" v-model="query" @keydown.down.prevent="focus(visibleIds.includes(focusId)?focusId:'')" aria-label="搜索导入目标" placeholder="搜索页面或路径" :disabled="disabled" />
      <div ref="tree" class="target-tree" role="tree" aria-label="导入目标页面层级">
        <button role="treeitem" data-id="" :aria-level="1" :aria-selected="!modelValue" :aria-pressed="!modelValue" :tabindex="focusId===''?0:-1" :disabled="disabled" @focus="focusId=''" @keydown="keyboard($event,'')" @click="choose('')">工作区根目录</button>
        <div v-for="row in visible" :key="row.id" class="target-row" :style="{paddingLeft:`${Math.min(row.depth,8)*16}px`}">
          <button v-if="children.has(row.id)" class="branch" :aria-label="`${expandedRow(row.id)?'收起':'展开'} ${row.title}`" :aria-expanded="expandedRow(row.id)" tabindex="-1" :disabled="disabled" @click="branch(row.id);focus(row.id)">{{expandedRow(row.id)?'−':'+'}}</button><span v-else class="leaf" aria-hidden="true">·</span>
          <button class="target-choice" role="treeitem" :data-id="row.id" :aria-level="row.depth+2" :aria-selected="modelValue===row.id" :aria-expanded="children.has(row.id)?expandedRow(row.id):undefined" :tabindex="focusId===row.id?0:-1" :aria-pressed="modelValue===row.id" :title="path(row.id)" :disabled="disabled" @focus="focusId=row.id" @keydown="keyboard($event,row.id)" @click="choose(row.id)">{{row.title || '未命名笔记'}}<small v-if="query.trim()||duplicateTitles.has(row.title)">{{path(row.id)}}</small></button>
        </div>
        <p v-if="!visible.length">没有匹配的页面</p>
      </div>
    </div>
  </div>
</template>
<style scoped>
.target-choice small{display:block;font-size:11px;line-height:1.5;color:var(--text-lo);overflow-wrap:anywhere}.target-picker{min-width:0}.target-summary{width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.target-options{margin-top:8px;display:grid;gap:8px}.target-tree{max-height:210px;overflow:auto;border:1px solid var(--accent-dim);border-radius:var(--radius-sm);min-width:0}button,input{font:inherit;font-size:13px;color:var(--text-hi);background:var(--bg-raised);border:1px solid var(--accent-dim);border-radius:var(--radius-sm);padding:9px 12px;text-align:left}button{cursor:pointer;min-height:36px}input{width:100%;box-sizing:border-box}button:disabled{opacity:.5;cursor:default}.target-tree>button{width:100%}.target-row{display:flex;align-items:center}.target-choice{flex:1;min-width:0;overflow-wrap:anywhere;border:0;background:transparent}.branch,.leaf{width:36px;flex-shrink:0;text-align:center;padding:6px;border:0}.leaf{color:var(--text-lo)}button[aria-pressed=true]{color:var(--accent);background:var(--bg-raised)}button:hover{background:var(--bg-base)}p{padding:8px;color:var(--text-lo)}button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
</style>
