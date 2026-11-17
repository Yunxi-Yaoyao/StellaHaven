<script setup lang="ts">
import {computed, ref, watch} from 'vue';
import {marked} from 'marked';
import {sanitizeNoteHtml} from './noteHtml';
import {guardPrivateMediaHtml} from '../auth/privateMedia';
const props = defineProps<{markdown:string; summary?:string}>();
const source = ref(false);
const cap = 256 * 1024;
const snippet = computed(() => props.markdown.slice(0,cap));
watch(()=>props.markdown,()=>{source.value=false;});
// Same Markdown → note sanitizer → private-media guard boundary as note reading.
// No editor, draft, upload, remote image fetch or project runtime is mounted here.
const rendered = computed(()=>{
  const html=guardPrivateMediaHtml(sanitizeNoteHtml(marked.parse(snippet.value,{breaks:true,async:false}) as string));
  const template=document.createElement('template');template.innerHTML=html;
  // Rebuild only inert task indicators; never retain source input attributes.
  for(const el of template.content.querySelectorAll('input')) {
    if(el instanceof HTMLInputElement && el.type==='checkbox') {
      const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.disabled=true;
      if(el.checked)checkbox.setAttribute('checked','');
      el.replaceWith(checkbox);
    } else el.remove();
  }
  for(const el of template.content.querySelectorAll('img,video,audio,picture,source,track,svg,image,[background]')) {
    if(!template.content.contains(el))continue;
    const placeholder=document.createElement('span');placeholder.className='preview-media-missing';placeholder.textContent=`图片未加载${el.getAttribute('alt')?'：'+el.getAttribute('alt'): '（预览不读取资源）'}`;el.replaceWith(placeholder);
  }
  for(const el of template.content.querySelectorAll('[contenteditable],[tabindex]')) {el.removeAttribute('contenteditable');el.removeAttribute('tabindex');}
  for(const el of template.content.querySelectorAll('textarea,select,button')) {const text=document.createElement('span');text.textContent=el.textContent;el.replaceWith(text);}
  for(const link of template.content.querySelectorAll('a')) {link.removeAttribute('href');link.removeAttribute('target');}
  return template.innerHTML;
});
</script>
<template>
  <section class="import-read-preview" aria-label="导入后阅读效果">
    <header><strong>阅读效果</strong><div><button :aria-pressed="!source" @click="source=false">阅读</button><button :aria-pressed="source" @click="source=true">源码</button></div></header>
    <p class="preview-notice">{{summary || '只读正文预览，不加载图片、音视频或外链；图表代码在此保留为源码。'}}<template v-if="summary"> 图片与外链资源未加载；图表在此显示源码。</template></p>
    <p v-if="markdown.length > cap" class="preview-notice">正文预览已截断至前 {{cap}} 字符；导入仍保留完整原文。</p>
    <pre v-if="source" class="preview-source">{{snippet}}</pre>
    <article v-else class="preview-body" @click.prevent v-html="rendered" />
  </section>
</template>
<style scoped>
.import-read-preview{border:1px solid var(--accent-dim);border-radius:var(--radius-sm);margin-top:8px;min-width:0;background:var(--bg-base)}header{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:9px 12px;border-bottom:1px solid var(--accent-dim);font-size:13px}header div{display:flex;gap:4px}button{background:transparent;color:var(--text-lo);border:1px solid transparent;border-radius:5px;padding:6px 10px;min-height:32px;cursor:pointer;font:inherit}button[aria-pressed=true]{color:var(--accent);background:var(--bg-raised);border-color:var(--accent-dim)}.preview-notice{font-size:12px;line-height:1.6;color:var(--text-lo);padding:9px 14px;margin:0}.preview-body,.preview-source{padding:4px 20px 20px;font-size:16px;line-height:1.8;overflow-wrap:anywhere;min-width:0;margin:0}.preview-source{white-space:pre-wrap;font-size:13px}.preview-body :deep(h1){font-size:26px}.preview-body :deep(h2){font-size:22px}.preview-body :deep(h3){font-size:18px}.preview-body :deep(p){margin:10px 0}.preview-body :deep(pre){white-space:pre-wrap;background:var(--bg-raised);padding:12px;border-radius:6px;font-size:13px}.preview-body :deep(table){border-collapse:collapse;display:block;max-width:100%;overflow:auto;font-size:14px}.preview-body :deep(th),.preview-body :deep(td){border:1px solid var(--accent-dim);padding:7px 10px}.preview-body :deep(blockquote){border-left:3px solid var(--accent);margin-left:0;padding-left:15px;color:var(--text-lo)}.preview-body :deep(a){color:var(--accent)}.preview-body :deep(.preview-media-missing){display:block;color:var(--text-lo);font-size:13px;border:1px dashed var(--accent-dim);padding:8px;margin:8px 0}button:focus-visible{outline:2px solid var(--accent)}
</style>
