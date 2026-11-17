<script setup lang="ts">
import { ref, computed, nextTick, watch, useId } from 'vue';
import Icon from '../../shell/Icon.vue';
import { iconCatalog, iconCategories, navigationIcon } from '../../icons/navigationIcons';

const props = defineProps<{ modelValue: string; name: string }>();
const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const panelId = useId();
const opened = ref(false);
const trigger = ref<HTMLButtonElement>();
const searchInput = ref<HTMLInputElement>();
const grid = ref<HTMLElement>();
const query = ref('');
const category = ref('');
const focused = ref(0);
const current = computed(() => navigationIcon(props.modelValue));
const currentLabel = computed(() => current.value?.label ?? `未知图标：${props.modelValue}（保留原值）`);
const filtered = computed(() => {
  const words = query.value.normalize('NFKC').trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return iconCatalog.filter(icon => (!category.value || icon.category === category.value) &&
    words.every(word => `${icon.key} ${icon.label} ${icon.keywords} ${iconCategories[icon.category]}`.toLocaleLowerCase().includes(word)));
});
watch(filtered, () => { focused.value = Math.max(0, filtered.value.findIndex(icon => icon.key === current.value?.key)); });
async function toggle() {
  opened.value = !opened.value;
  if (opened.value) {
    focused.value = Math.max(0, filtered.value.findIndex(icon => icon.key === current.value?.key));
    await nextTick(); searchInput.value?.focus();
  }
}
async function close() { opened.value = false; await nextTick(); trigger.value?.focus(); }
function pick(id: string) { emit('update:modelValue', id); void close(); }
function clearFilters() { query.value = ''; category.value = ''; searchInput.value?.focus(); }
function panelKey(event: KeyboardEvent) {
  if (event.isComposing || event.key !== 'Escape') return;
  event.preventDefault(); event.stopPropagation(); void close();
}
function key(event: KeyboardEvent, index: number) {
  if (event.isComposing) return;
  const buttons = [...(grid.value?.querySelectorAll<HTMLButtonElement>('button') ?? [])];
  if (!buttons.length) return;
  // Measure the actual wrapped row: responsive widths and zoom change column count.
  const columns = buttons.filter(button => button.offsetTop === buttons[0]!.offsetTop).length;
  const delta: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -columns, ArrowDown: columns };
  let next: number;
  if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = buttons.length - 1;
  else if (event.key in delta) next = (index + delta[event.key]! + buttons.length) % buttons.length;
  else return;
  event.preventDefault(); event.stopPropagation(); buttons[next]?.focus();
}
</script>

<template>
  <div class="icon-picker">
    <button ref="trigger" class="picker-trigger" type="button" :aria-expanded="opened" :aria-controls="panelId"
      :aria-label="'选择图标，当前' + currentLabel" @click="toggle">
      <Icon :name="modelValue" :size="18" /><span>{{ currentLabel }}</span><Icon name="chevron-down" />
    </button>
    <div class="preview-row">
      <span class="preview-label">侧栏效果</span>
      <div class="sidebar-preview" aria-label="侧栏效果"><Icon :name="modelValue" :size="18" /><span>{{ name || '网站名称' }}</span></div>
    </div>
    <div v-if="opened" :id="panelId" class="picker-panel" role="region" aria-label="选择导航图标" @keydown="panelKey">
      <label class="search-field"><Icon name="search" :size="18" />
        <input ref="searchInput" v-model="query" type="search" aria-label="搜索图标" placeholder="搜索图标，如：相册、cloud、待办" autocomplete="off" />
      </label>
      <div class="categories" aria-label="图标分类">
        <button type="button" :aria-pressed="category === ''" @click="category = ''">全部</button>
        <button v-for="(label, id) in iconCategories" :key="id" type="button" :aria-pressed="category === id" @click="category = id">{{ label }}</button>
      </div>
      <div class="result-summary"><span role="status">{{ filtered.length }} 个图标</span><span>方向键浏览 · Enter 选择</span></div>
      <div v-if="filtered.length" ref="grid" class="icon-grid" role="radiogroup" aria-label="图标选择">
        <button v-for="(icon, index) in filtered" :key="icon.key" type="button" role="radio" :aria-label="icon.label"
          :aria-checked="current?.key === icon.key" :tabindex="focused === index ? 0 : -1" :title="icon.label + ' · ' + icon.key"
          @focus="focused = index" @click="pick(icon.key)" @keydown="key($event, index)">
          <Icon :name="icon.key" :size="23" /><span>{{ icon.label }}</span>
        </button>
      </div>
      <div v-else class="empty-results"><Icon name="search" :size="26" /><p>没有找到图标</p><span>试试其他关键词，或查看全部分类。</span><button type="button" @click="clearFilters">清除筛选</button></div>
    </div>
  </div>
</template>

<style scoped>
.icon-picker { min-width:0; width:100%; display:flex; flex-wrap:wrap; align-items:center; gap:10px 16px; }
.picker-panel { flex-basis:100%; }
button, input { font:inherit; }
button { display:inline-flex; align-items:center; justify-content:center; gap:8px; min-height:40px; padding:8px 11px; background:var(--bg-raised, #25272b); color:var(--text-hi, #eeeeef); border:1px solid #ffffff24; border-radius:8px; cursor:pointer; }
button:hover { background:var(--bg-hover, #303238); }
.picker-trigger { max-width:100%; justify-content:flex-start; }
.picker-trigger span { overflow-wrap:anywhere; text-align:left; }
.preview-row { display:flex; align-items:center; gap:12px; margin:10px 0; }
.preview-label { flex-shrink:0; font-size:12px; color:var(--text-lo, #bfc0c6); }
.sidebar-preview { display:flex; align-items:center; gap:8px; min-width:0; max-width:280px; font-size:14px; padding:9px 12px; background:var(--bg-panel, #202126); border-radius:8px; }
.sidebar-preview span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.picker-panel { width:min(100%, 560px); box-sizing:border-box; padding:14px; border:1px solid #ffffff24; border-radius:12px; background:var(--bg-panel, #202126); }
.search-field { display:flex; align-items:center; gap:9px; padding:0 12px; background:var(--bg-input, #191a1e); color:var(--text-lo, #bfc0c6); border:1px solid #ffffff30; border-radius:8px; }
.search-field input { width:100%; min-width:0; min-height:44px; border:0; background:transparent; color:var(--text-hi, #eeeeef); outline:none; font-size:14px; }
.search-field input::placeholder { color:var(--text-lo, #bfc0c6); opacity:1; }
.search-field:focus-within { outline:2px solid var(--accent, #b3a1e6); outline-offset:2px; }
.categories { display:flex; flex-wrap:wrap; gap:6px; margin:12px 0; }
.categories button { padding:6px 10px; font-size:13px; min-height:36px; background:transparent; border-color:transparent; }
.categories [aria-pressed=true] { color:var(--text-hi, #eeeeef); border-color:var(--accent, #b3a1e6); background:#a99bc01a; }
.result-summary { display:flex; justify-content:space-between; gap:8px; margin:8px 0; font-size:12px; color:var(--text-lo, #bfc0c6); }
.icon-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(76px, 1fr)); gap:6px; max-height:310px; overflow-y:auto; padding:3px; scrollbar-gutter:stable; }
.icon-grid button { flex-direction:column; padding:11px 3px; min-width:0; min-height:72px; font-size:12px; line-height:1.4; background:transparent; border-color:transparent; }
.icon-grid button:hover { background:#ffffff0c; }
.icon-grid [aria-checked=true] { border-color:var(--accent, #b3a1e6); background:#a99bc024; }
button:focus-visible { outline:2px solid var(--accent, #b3a1e6); outline-offset:1px; }
.empty-results { display:flex; flex-direction:column; align-items:center; gap:10px; padding:26px 8px; text-align:center; color:var(--text-lo, #bfc0c6); font-size:13px; }
.empty-results p { margin:0; font-size:15px; color:var(--text-hi, #eeeeef); }
@media (max-width:600px) {
  .picker-panel { padding:10px; }
  .categories button, .picker-trigger { min-height:44px; }
  .result-summary { flex-wrap:wrap; }
  .icon-grid { max-height:300px; grid-template-columns:repeat(auto-fill, minmax(70px, 1fr)); }
}
</style>
