<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {marked} from 'marked';
import Icon from '../../shell/Icon.vue';
import {sanitizeNoteHtml} from '../notes/noteHtml';
import {pages,type DocPage} from './catalog';
const route=useRoute(),router=useRouter();
const storageKey='stella_doc_center_reading_v1';
interface Reading {page?:string;query?:string;scroll?:Record<string,number>}
let saved:Reading={};try{const value=JSON.parse(localStorage.getItem(storageKey)||'{}');if(value&&typeof value==='object'&&!Array.isArray(value))saved={page:typeof value.page==='string'?value.page:undefined,query:typeof value.query==='string'?value.query:undefined,scroll:value.scroll&&typeof value.scroll==='object'?Object.fromEntries(Object.entries(value.scroll).filter((entry):entry is [string,number]=>typeof entry[1]==='number'&&Number.isFinite(entry[1])&&entry[1]>=0)):undefined};}catch{/* Restricted storage still permits reading. */}
const query=ref(typeof route.query.q==='string'?route.query.q:saved.query||'');
const section=ref<'guide'|'api'>(route.query.section==='api'?'api':route.query.section==='guide'?'guide':pages.find(p=>p.id===saved.page)?.section||'guide');
const selectedId=ref(String(route.query.page||saved.page||'start'));
const selected=computed(()=>pages.find(p=>p.id===selectedId.value&&p.section===section.value)||pages.find(p=>p.section===section.value)!);
const matches=computed(()=>pages.filter(p=>p.section===section.value&&`${p.title} ${p.group} ${p.body}`.toLowerCase().includes(query.value.trim().toLowerCase())));
const groups=computed(()=>[...new Set(matches.value.map(p=>p.group))].map(name=>({name,items:matches.value.filter(p=>p.group===name)})));
const directoryOpen=ref(false),directoryButton=ref<HTMLButtonElement|null>(null),compact=ref(window.innerWidth<=600),article=ref<HTMLElement|null>(null),scroller=ref<HTMLElement|null>(null),status=ref('');
function resized(){compact.value=window.innerWidth<=600;}
async function toggleDirectory(){directoryOpen.value=!directoryOpen.value;await nextTick();if(directoryOpen.value)document.getElementById('doc-search')?.focus();else directoryButton.value?.focus();}
function closeDirectory(){directoryOpen.value=false;directoryButton.value?.focus();}
const imageDialog=ref<HTMLDialogElement|null>(null),image=ref<{src:string;alt:string}|null>(null),zoom=ref(1);
let imageTrigger:HTMLElement|null=null;
const images=import.meta.glob('./images/*.png',{eager:true,query:'?url',import:'default'}) as Record<string,string>;
const rendered=computed(()=>{
 const template=document.createElement('template');template.innerHTML=sanitizeNoteHtml(marked.parse(selected.value.body,{async:false}));
 let index=0;
 for(const h of template.content.querySelectorAll('h2,h3'))h.id=`chapter-${++index}`;
 for(const pre of template.content.querySelectorAll('pre')){const button=document.createElement('button');button.type='button';button.className='doc-copy';button.textContent='复制代码';pre.prepend(button);}
 for(const img of template.content.querySelectorAll('img')){
  const filename=img.getAttribute('src')?.split('/').at(-1);const url=images[`./images/${filename}`];
  if(!url){img.remove();continue;}
  img.src=url;const button=document.createElement('button');button.type='button';button.className='doc-image';button.setAttribute('aria-label','放大图片：'+img.alt);img.replaceWith(button);button.append(img);
 }
 for(const a of template.content.querySelectorAll('a')){a.rel='noopener noreferrer';if(/^https?:/.test(a.href))a.target='_blank';}
 return template.innerHTML;
});
const toc=computed(()=>{const t=document.createElement('template');t.innerHTML=rendered.value;return [...t.content.querySelectorAll('h2,h3')].map(h=>({id:h.id,title:h.textContent,sub:h.tagName==='H3'}));});
function persist(){try{localStorage.setItem(storageKey,JSON.stringify({page:selected.value.id,query:query.value,scroll:saved.scroll||{}}));}catch{/* No private data or server writes. */}}
function recordScroll(){saved.scroll||={};saved.scroll[selected.value.id]=scroller.value?.scrollTop||0;persist();}
async function choose(page:DocPage){recordScroll();section.value=page.section;selectedId.value=page.id;directoryOpen.value=false;status.value='';persist();await router.push({path:'/help',query:{section:page.section,page:page.id,...(query.value?{q:query.value}:{})},hash:''});await nextTick();if(compact.value)article.value?.focus({preventScroll:true});}
function chooseSection(value:'guide'|'api'){void choose(pages.find(p=>p.section===value)!);}
async function position(){await nextTick();if(route.hash){article.value?.querySelector<HTMLElement>(`[id="${route.hash.slice(1).replace(/[^\w-]/g,'')}"]`)?.scrollIntoView({block:'start'});}else if(scroller.value)scroller.value.scrollTop=saved.scroll?.[selected.value.id]||0;}
watch(()=>[route.query.section,route.query.page],()=>{if(route.query.section==='api'||route.query.section==='guide')section.value=route.query.section;if(typeof route.query.page==='string')selectedId.value=route.query.page;persist();void position();});
watch(()=>route.hash,()=>void position());
watch(query,()=>{persist();});
async function contentClick(event:MouseEvent){
 const target=event.target as HTMLElement,copy=target.closest<HTMLButtonElement>('.doc-copy'),picture=target.closest<HTMLButtonElement>('.doc-image');
 if(copy){try{await navigator.clipboard.writeText(copy.parentElement?.querySelector('code')?.textContent||'');status.value='代码已复制喵~';}catch{status.value='复制未完成，请选中代码手动复制喵~';}}
 if(picture){const img=picture.querySelector('img')!;imageTrigger=picture;image.value={src:img.src,alt:img.alt};zoom.value=1;await nextTick();imageDialog.value?.showModal();}
}
function imageKeys(event:KeyboardEvent){
 if(event.key!=='Tab')return;
 const controls=[...imageDialog.value!.querySelectorAll<HTMLButtonElement>('button')],first=controls[0],last=controls.at(-1);
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
 else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
}
function closeImage(){imageDialog.value?.close();image.value=null;imageTrigger?.focus();}
function navigateHash(event:MouseEvent,id:string){event.preventDefault();void router.replace({path:'/help',query:{section:section.value,page:selected.value.id,...(query.value?{q:query.value}:{})},hash:'#'+id});}
onMounted(()=>{window.addEventListener('resize',resized);void position();});onBeforeUnmount(()=>{window.removeEventListener('resize',resized);recordScroll();imageDialog.value?.close();});
</script>
<template>
 <section class="documentation" aria-label="文档中心">
  <header class="doc-header"><h1><Icon name="note" :size="21"/>文档中心</h1><div class="doc-sections" aria-label="文档栏目"><button :aria-pressed="section==='guide'" @click="chooseSection('guide')">使用指南</button><button :aria-pressed="section==='api'" @click="chooseSection('api')">API 参考</button></div><button ref="directoryButton" class="directory-toggle" :aria-expanded="directoryOpen" aria-controls="doc-directory" @click="toggleDirectory">文档目录</button></header>
  <div class="doc-layout">
   <aside id="doc-directory" class="doc-directory" :class="{open:directoryOpen}" @keydown.esc.prevent="closeDirectory">
    <label for="doc-search">搜索{{section==='guide'?'使用指南':'API 参考'}}</label><div class="search-row"><input id="doc-search" v-model="query" type="search" placeholder="标题、正文或接口路径"/><button v-if="query" aria-label="清除搜索" @click="query=''">清除</button></div>
    <p class="search-count" role="status">{{matches.length}} 篇{{query?'匹配文档':''}}</p>
    <p v-if="!matches.length" class="no-results">没有找到相关文档，换个关键词试试喵~</p>
    <nav aria-label="文章目录"><section v-for="group in groups" :key="group.name"><h2>{{group.name}}</h2><a v-for="page in group.items" :key="page.id" :href="router.resolve({path:'/help',query:{section:page.section,page:page.id}}).href" :aria-current="selected.id===page.id?'page':undefined" @click.prevent="choose(page)">{{page.title}}</a></section></nav><RouterLink class="first-use-return" to="/settings?section=first-use">返回首次使用清单</RouterLink>
   </aside>
   <div ref="scroller" class="doc-reading" :inert="compact&&directoryOpen||undefined" :aria-hidden="compact&&directoryOpen||undefined" @scroll.passive="recordScroll">
    <article ref="article" tabindex="-1"><div class="doc-breadcrumb">{{section==='guide'?'使用指南':'API 参考'}} / {{selected.group}}</div><h1>{{selected.title}}</h1><nav class="doc-toc" aria-label="本页目录"><a v-for="item in toc" :key="item.id" :href="'#'+item.id" :class="{sub:item.sub}" @click="navigateHash($event,item.id)">{{item.title}}</a></nav><div class="doc-prose" @click="contentClick" v-html="rendered" /></article>
   </div>
  </div>
  <p v-if="status" class="doc-status" role="status">{{status}}</p>
  <dialog ref="imageDialog" class="doc-image-dialog" aria-label="文档图片查看" @keydown="imageKeys" @cancel.prevent="closeImage" @click.self="closeImage"><template v-if="image"><div class="image-toolbar"><button aria-label="缩小图片" @click="zoom=Math.max(.5,zoom-.25)">−</button><button @click="zoom=1">复位</button><button aria-label="放大图片" @click="zoom=Math.min(3,zoom+.25)">+</button><button @click="closeImage">关闭图片</button></div><div class="image-pan"><img :src="image.src" :alt="image.alt" :style="{width:`${zoom*100}%`,maxWidth:'none'}"/></div></template></dialog>
 </section>
</template>
<style scoped>
.documentation{height:100%;min-height:0;min-width:0;display:flex;flex-direction:column;background:var(--bg-panel);color:var(--text-hi);font-family:Inter,"Noto Sans SC",sans-serif}
.doc-header{display:flex;align-items:center;flex-wrap:wrap;gap:16px;padding:16px 24px;border-bottom:1px solid var(--accent-dim);flex-shrink:0}.doc-header h1{display:flex;gap:10px;align-items:center;font-size:20px;margin:0;font-weight:550}.doc-sections{display:flex;gap:6px;margin-left:auto}button{font:inherit;color:var(--text-hi);background:var(--bg-raised);border:1px solid var(--accent-dim);border-radius:7px;min-height:38px;padding:7px 12px;cursor:pointer}button[aria-pressed=true]{background:var(--selected-bg);border-color:var(--selected-border);color:var(--accent)}button:focus-visible,a:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.doc-layout{display:grid;grid-template-columns:280px minmax(0,1fr);min-height:0;flex:1}.doc-directory{padding:20px 14px;overflow:auto;border-right:1px solid var(--accent-dim);font-size:14px}.doc-directory label{display:block;margin:0 6px 9px;color:var(--text-hi)}.search-row{display:flex;gap:4px}.search-row input{width:100%;min-width:0;background:var(--bg-base);border:1px solid var(--accent-dim);border-radius:7px;padding:10px;color:var(--text-hi);font:inherit}.search-row input::placeholder{color:var(--text-lo)}.search-count{font-size:12px;color:var(--text-lo);margin:10px 6px 18px}.no-results{line-height:1.8;color:var(--text-lo)}.doc-directory h2{font-size:12px;font-weight:500;color:var(--text-lo);margin:20px 8px 7px}.doc-directory a{display:block;padding:9px 10px;border-radius:6px;color:var(--text-hi);text-decoration:none;overflow-wrap:anywhere;line-height:1.55}.doc-directory a[aria-current]{background:var(--selected-bg);color:var(--accent);box-shadow:inset 2px 0 var(--accent)}.doc-directory a:hover{background:var(--bg-raised)}.doc-reading{overflow:auto;min-width:0;scroll-behavior:auto;scroll-padding-top:24px}.doc-reading article{max-width:940px;margin:0 auto;padding:30px 38px 80px;outline:none}.doc-breadcrumb{color:var(--text-lo);font-size:13px;margin-bottom:12px}.doc-reading h1{font-size:27px;font-weight:550;margin:0 0 22px;overflow-wrap:anywhere}.doc-toc{display:flex;flex-wrap:wrap;gap:8px 18px;border-bottom:1px solid var(--accent-dim);padding-bottom:20px;margin-bottom:26px}.doc-toc a{font-size:13px;color:var(--text-lo);text-decoration:none}.doc-toc .sub{font-size:12px}.doc-prose{font-size:16px;line-height:1.85;overflow-wrap:anywhere;user-select:text}.doc-prose :deep(h2){font-size:22px;font-weight:550;line-height:1.5;margin:30px 0 12px}.doc-prose :deep(h3){font-size:17px;margin:24px 0 10px}.doc-prose :deep(p){margin:12px 0}.doc-prose :deep(ul),.doc-prose :deep(ol){padding-left:25px}.doc-prose :deep(a){color:var(--accent)}.doc-prose :deep(pre){position:relative;background:var(--bg-base);padding:54px 18px 18px;border:1px solid var(--accent-dim);border-radius:10px;overflow:auto;font-size:13px;line-height:1.7;max-height:560px;white-space:pre}.doc-prose :deep(code){font-family:ui-monospace,monospace}.doc-prose :deep(.doc-copy){position:absolute;right:9px;top:9px;font:inherit;background:var(--bg-raised);border:1px solid var(--accent-dim);color:var(--text-hi);border-radius:6px;padding:6px 10px;cursor:pointer;min-height:36px}.doc-prose :deep(table){display:block;width:100%;max-width:100%;overflow-x:auto;border-collapse:collapse;font-size:14px}.doc-prose :deep(th),.doc-prose :deep(td){padding:10px 12px;border:1px solid var(--accent-dim);text-align:left;min-width:80px}.doc-prose :deep(.doc-image){display:block;width:100%;padding:0;border:1px solid var(--accent-dim);border-radius:10px;overflow:hidden;cursor:zoom-in;background:var(--bg-base)}.doc-prose :deep(img){display:block;width:100%;height:auto}.doc-prose :deep(button:focus-visible){outline:2px solid var(--accent);outline-offset:3px}.directory-toggle{display:none}.doc-status{margin:0;padding:10px 24px;font-size:13px;background:var(--bg-raised);border-top:1px solid var(--accent-dim)}.doc-image-dialog{width:min(1100px,94vw);max-height:92dvh;padding:12px;background:var(--bg-panel);color:var(--text-hi);border:1px solid var(--accent-dim);border-radius:12px}.doc-image-dialog::backdrop{background:#000b}.image-toolbar{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;margin-bottom:12px}.image-pan{max-height:75dvh;overflow:auto}.image-pan img{display:block;height:auto}
/* The directory owns its full-height border; the reading column owns its inset. */
@media(min-width:769px){
 .documentation{display:grid;grid-template-columns:280px minmax(0,1fr);grid-template-rows:auto minmax(0,1fr)}
 .doc-layout{display:contents}.doc-header{grid-column:2;grid-row:1;padding-top:44px}
 .doc-directory{grid-column:1;grid-row:1 / span 2;padding-top:121px}
 .doc-reading{grid-column:2;grid-row:2}
}
@media(min-width:769px) and (max-width:900px){.documentation{grid-template-columns:235px minmax(0,1fr)}}
@media(max-width:900px){.doc-layout{grid-template-columns:235px minmax(0,1fr)}.doc-reading article{padding:26px 24px 64px}}
@media(max-width:600px){.doc-header{padding:15px 16px;gap:12px}.doc-header h1{font-size:19px}.doc-sections{margin-left:0}.doc-sections button,.directory-toggle{min-height:44px}.directory-toggle{display:block;margin-left:auto}.doc-layout{display:flex;flex-direction:column;position:relative}.doc-directory{display:none}.doc-directory.open{display:block;position:absolute;inset:0;z-index:2;background:var(--bg-panel);border:0}.doc-directory a{min-height:44px}.search-row input{font-size:16px}.doc-reading{height:100%;flex:1}.doc-reading article{padding:24px 18px 60px}.doc-reading h1{font-size:24px}.doc-prose{font-size:16px}.doc-prose :deep(h2){font-size:21px}.doc-toc{gap:10px 16px}.doc-toc a{line-height:1.8}.image-toolbar button{min-height:44px}.doc-prose :deep(.doc-copy){min-height:44px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style>
