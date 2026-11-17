<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue';
import {useRouter} from 'vue-router';
import {api} from '../../api/client';
import {auth,loggedIn,displayBg} from '../home/auth';
import {navigation} from '../../stores/navigation';
import {toast} from '../../composables/useToast';
import Icon from '../../shell/Icon.vue';
import NavCardFace from './NavCardFace.vue';
import StyleEditor from './StyleEditor.vue';
import SettingsFields from './SettingsFields.vue';
import NavSelect from './NavSelect.vue';
import NavColor from './NavColor.vue';
import MaterialChoice from './MaterialChoice.vue';
import AssetManager from './AssetManager.vue';
import BgManager from '../home/BgManager.vue';
import {faviconCandidates} from './favicon';
import {useBackgroundMedia} from '../home/backgroundMedia';
import {createNavController,defaults} from './controller';
import {watchNavRevision} from './realtime';
import {keepNavDraft,readNavDraft,forgetNavDraft} from './drafts';
import {copy,newGroup,newCard,destination,effectiveStyle,videoUrl,rebaseData,type Data,type Group,type Card,type Asset,type Preferences} from './types';
import './nav.css';
const router=useRouter();
const identity=()=>`${auth.me?.id||''}:${auth.sessionGeneration}:${auth.requestEpoch}:${loggedIn.value}`;
const control=createNavController(api,identity);
const {state,loading,saving,error,uncertain,conflict}=control;
const data=computed(()=>state.value?.data||defaults());
const preferences=computed(()=>data.value.preferences);
const query=ref(''),selected=ref(''),engine=ref('');
const searchInput=ref<HTMLInputElement>();
const network=ref<'wan'|'lan'>('wan');
try{network.value=localStorage.getItem('stella-nav-device-network')==='lan'?'lan':'wan';}catch{}
watch(network,v=>{try{localStorage.setItem('stella-nav-device-network',v);}catch{}});
const shownGroups=computed(()=>data.value.groups.filter(g=>!selected.value||g.id===selected.value).map(g=>({...g,items:g.items.filter(c=>`${c.title} ${c.description} ${c.url} ${c.lanUrl}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase()))})).filter(g=>!query.value||g.items.length));
const background=computed(()=>preferences.value.background==='home'?displayBg.value:preferences.value.background==='custom'?preferences.value.backgroundUrl:'');
const backgroundPlayer=useBackgroundMedia(background);
const clock=ref(new Date());let ticker:ReturnType<typeof setInterval>|undefined;
const clockText=computed(()=>clock.value.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',...(preferences.value.seconds?{second:'2-digit'}:{})}));
const modal=ref<HTMLDialogElement>();
const mode=ref<'group'|'card'|'settings'|'delete'>('settings');
const tab=ref('display'),editor=ref<Data>(defaults()),baseRevision=ref(0),groupId=ref(''),cardId=ref(''),cardGroupId=ref('');
const baseline=ref<Data>(defaults());
const editorGroup=computed(()=>editor.value.groups.find(g=>g.id===groupId.value));
const editorCard=computed(()=>editor.value.groups.flatMap(g=>g.items).find(c=>c.id===cardId.value));
const deleteTarget=ref<{kind:'group'|'card';id:string;title:string}>();
let dialogEpoch=0,draftOwner='';
const draftAvailable=ref(false);
function checkDraft(){draftAvailable.value=!!auth.me?.id&&!!readNavDraft(auth.me.id);}
function stashDraft(){if(!draftOwner||!modalOpen.value||mode.value==='delete'||JSON.stringify(editor.value)===JSON.stringify(baseline.value))return;keepNavDraft(draftOwner,{editor:editor.value,baseline:baseline.value,revision:baseRevision.value,mode:mode.value,tab:tab.value,groupId:groupId.value,cardId:cardId.value,cardGroupId:cardGroupId.value,uncertain:uncertain.value||saving.value});}
function discardDraft(){if(auth.me?.id)forgetNavDraft(auth.me.id);checkDraft();}
async function restoreDraft(){const owner=auth.me?.id,draft=owner?readNavDraft(owner):null;if(!draft||!await open(draft.mode)||auth.me?.id!==owner)return;editor.value=draft.editor;baseline.value=draft.baseline;baseRevision.value=draft.revision;tab.value=draft.tab;groupId.value=draft.groupId;cardId.value=draft.cardId;cardGroupId.value=draft.cardGroupId;uncertain.value=draft.uncertain;draftAvailable.value=false;localError.value='已恢复本页面会话中的草稿，尚未写入。请比较当前服务端版本。';await loadAssets();}
const bgPickerOpen=ref(false);
watch(bgPickerOpen,async open=>{await nextTick();if(open)modal.value?.querySelector<HTMLButtonElement>('.bgm .x')?.focus();else if(modalOpen.value)modal.value?.querySelector<HTMLButtonElement>('[data-manage-background]')?.focus();});
const protectedBackgrounds=computed(()=>{
 const urls=new Set<string>();
 function collect(value:unknown){if(typeof value==='string'){if(value.startsWith('/assets/homebg/'))urls.add(value);}else if(value&&typeof value==='object')for(const item of Object.values(value))collect(item);}
 collect(data.value);collect(baseline.value);collect(editor.value);return [...urls];
});
function pickBackground(url:string){if(!bgPickerOpen.value||!modalOpen.value||draftOwner!==auth.me?.id)return;editor.value.preferences.background='custom';editor.value.preferences.backgroundUrl=url;}
const modalOpen=ref(false),localError=ref(''),assets=ref<Asset[]>([]),assetBusy=ref(false),previewBusy=ref(false),source=ref(''),preview=ref<any>(null);
const packageConfirmed=ref(false),moduleBindings=ref<Record<string,string|null>>({});
watch(moduleBindings,()=>packageConfirmed.value=false,{deep:true,flush:'sync'});
watch(source,()=>{preview.value=null;packageConfirmed.value=false;});
const settingsTabs=[['display','显示与布局'],['background','背景'],['search','搜索'],['assets','素材'],['data','数据工具']];
const title=computed(()=>mode.value==='group'?'编辑分组':mode.value==='card'?'编辑网站':mode.value==='delete'?`删除${deleteTarget.value?.kind==='group'?'分组':'网站'}`:'导航设置');
const editable=computed(()=>!!state.value&&!loading.value&&!saving.value&&!modalOpen.value);
async function open(kind:typeof mode.value){
 if(!state.value||saving.value||loading.value)return false;
 dialogEpoch++;draftOwner=auth.me?.id||'';baseline.value=copy(data.value);editor.value=copy(data.value);baseRevision.value=state.value.revision;mode.value=kind;localError.value='';error.value='';preview.value=null;previewBusy.value=false;source.value='';modalOpen.value=true;
 clearFavicons();faviconNotice.value='';
 await nextTick();modal.value?.showModal();return true;
}
function close(){if(bgPickerOpen.value){bgPickerOpen.value=false;return;}if(saving.value||assetBusy.value)return;discardDraft();dialogEpoch++;clearFavicons();modal.value?.close();modalOpen.value=false;localError.value='';}
async function editGroup(g?:Group){if(!await open('group'))return;const target=g?editor.value.groups.find(x=>x.id===g.id)!:newGroup();if(!g)editor.value.groups.push(target);groupId.value=target.id;}
async function editCard(g?:Group,c?:Card){if(!await open('card'))return;let target=g?editor.value.groups.find(x=>x.id===g.id):editor.value.groups[0];if(!target){close();await editGroup();return;}const card=c?target.items.find(i=>i.id===c.id)!:newCard();if(!c)target.items.push(card);if(!card.icon)card.icon={itemType:1,src:'',text:'',backgroundColor:null};groupId.value=target.id;cardId.value=card.id;cardGroupId.value=target.id;await loadAssets();}
function changeCardGroup(){const item=editorCard.value;if(!item)return;for(const g of editor.value.groups)g.items=g.items.filter(i=>i.id!==item.id);editor.value.groups.find(g=>g.id===cardGroupId.value)?.items.push(item);groupId.value=cardGroupId.value;}
async function settings(){if(await open('settings')){tab.value='display';await loadAssets();}}
async function askDelete(kind:'group'|'card',id:string,name:string){if(!await open('delete'))return;deleteTarget.value={kind,id,title:name};}
async function submit(){
 if(saving.value||!state.value)return;
 const epoch=dialogEpoch;
 if(mode.value==='delete'){
  const target=deleteTarget.value;if(!target)return;
  editor.value.groups=editor.value.groups.filter(g=>target.kind!=='group'||g.id!==target.id);
  if(target.kind==='card')for(const g of editor.value.groups)g.items=g.items.filter(c=>c.id!==target.id);
 }
 const submitted=copy(editor.value);
 const ok=await control.save(submitted,baseRevision.value);
 if(epoch!==dialogEpoch)return;
 if(ok){
  if(JSON.stringify(editor.value)!==JSON.stringify(submitted)){
   baseline.value=submitted;baseRevision.value=state.value!.revision;
   localError.value='先前快照已保存；保存期间的新修改仍保留在本窗口，请再次保存。';
  }else{close();toast('导航已保存');}
  if(selected.value&&!data.value.groups.some(g=>g.id===selected.value))selected.value='';
 }
}
async function reorder(kind:'group'|'card',g:Group,index:number,offset:number){
 if(!state.value||!editable.value)return;
 const draft=copy(data.value),list=kind==='group'?draft.groups:draft.groups.find(x=>x.id===g.id)!.items;
 const to=index+offset;if(to<0||to>=list.length)return;
 const [entry]=list.splice(index,1);if(!entry)return;list.splice(to,0,entry as Group&Card);
 if(await control.save(draft,state.value.revision))toast('顺序已保存');
}
const dragging=ref<{kind:'group'|'card';id:string}>();
function dragStart(event:DragEvent,kind:'group'|'card',id:string){if(!editable.value){event.preventDefault();return;}dragging.value={kind,id};event.dataTransfer?.setData('text/plain','stella-native-nav');if(event.dataTransfer)event.dataTransfer.effectAllowed='move';}
async function drop(event:DragEvent,group:Group,card?:Card){event.preventDefault();event.stopPropagation();const moving=dragging.value;dragging.value=undefined;if(!moving||!editable.value||!state.value)return;const draft=copy(data.value);
 if(moving.kind==='group'){if(card||moving.id===group.id)return;const at=draft.groups.findIndex(g=>g.id===moving.id),to=draft.groups.findIndex(g=>g.id===group.id);if(at<0||to<0)return;const item=draft.groups.splice(at,1)[0];if(item)draft.groups.splice(to,0,item);}
 else{if(card?.id===moving.id)return;const source=draft.groups.find(g=>g.items.some(c=>c.id===moving.id)),target=draft.groups.find(g=>g.id===group.id);if(!source||!target)return;const item=source.items.splice(source.items.findIndex(c=>c.id===moving.id),1)[0];const to=card?target.items.findIndex(c=>c.id===card.id):target.items.length;if(item)target.items.splice(Math.max(0,to),0,item);}
 await control.save(draft,state.value.revision);
}
const favicons=ref<{url:string;thumbnail:string}[]>([]),faviconBusy=ref(false),faviconNotice=ref('');let faviconGeneration=0;
function clearFavicons(){faviconGeneration++;for(const f of favicons.value)URL.revokeObjectURL(f.thumbnail);favicons.value=[];faviconBusy.value=false;}
async function discoverFavicon(){const card=editorCard.value;if(!card||faviconBusy.value)return;clearFavicons();const epoch=dialogEpoch,id=identity(),generation=faviconGeneration;faviconBusy.value=true;faviconNotice.value='';const urls=faviconCandidates(card.url);if(!urls.length){faviconNotice.value='仅允许普通公开域名的标准80/443端口；内网/测试地址请手动选素材。';faviconBusy.value=false;return;}
 const found=await Promise.all(urls.map(async url=>{const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),4000);let thumbnail='';try{const response=await fetch(url,{credentials:'omit',referrerPolicy:'no-referrer',redirect:'error',cache:'no-store',signal:controller.signal});if(!response.ok||!response.body||Number(response.headers.get('content-length')||0)>256*1024)return null;const reader=response.body.getReader(),chunks:Uint8Array[]=[];let size=0;while(true){const chunk=await reader.read();if(chunk.done)break;size+=chunk.value.byteLength;if(size>256*1024){await reader.cancel();return null;}chunks.push(chunk.value);}const bytes=new Uint8Array(size);let at=0;for(const c of chunks){bytes.set(c,at);at+=c.length;}const head=[...bytes.slice(0,12)];let mime='';if(head.slice(0,4).join()==='137,80,78,71')mime='image/png';else if(head.slice(0,3).join()==='255,216,255')mime='image/jpeg';else if(head.slice(0,3).join()==='71,73,70')mime='image/gif';else if(head.slice(0,4).join()==='0,0,1,0')mime='image/x-icon';else if(head.slice(0,4).join()==='82,73,70,70'&&head.slice(8).join()==='87,69,66,80')mime='image/webp';if(!mime)return null;thumbnail=URL.createObjectURL(new Blob([bytes],{type:mime}));const image=new Image();image.src=thumbnail;await image.decode();if(!image.naturalWidth||image.naturalWidth*image.naturalHeight>16_000_000){URL.revokeObjectURL(thumbnail);return null;}return {url,thumbnail};}catch{if(thumbnail)URL.revokeObjectURL(thumbnail);return null;}finally{clearTimeout(timer);controller.abort();}}));
 const valid=epoch===dialogEpoch&&id===identity()&&generation===faviconGeneration;
 const candidates=found.filter((x):x is {url:string;thumbnail:string}=>!!x);if(!valid){for(const f of candidates)URL.revokeObjectURL(f.thumbnail);return;}favicons.value=candidates;faviconBusy.value=false;faviconNotice.value=candidates.length?'选择一个候选；每项最多256 KiB，不自动替换图标。':'公开候选不可匿名读取，请选自有素材。';
}
async function recover(){await control.load();}
function rebase(){if(!state.value)return;try{editor.value=rebaseData(baseline.value,editor.value,state.value.data);baseline.value=copy(state.value.data);baseRevision.value=state.value.revision;conflict.value=false;error.value='';localError.value='已保留服务端其他字段；保存将应用本窗口修改。';}catch(e){localError.value=(e as Error).message;}}
function openCard(c:Card,event?:MouseEvent){if(event?.ctrlKey||event?.metaKey||event?.shiftKey)return; if(c.module_id){event?.preventDefault();void router.push(destination(c,network.value));}}
const currentEngine=computed(()=>preferences.value.engines.find(x=>x.id===(engine.value||preferences.value.defaultEngine))||preferences.value.engines[0]);
async function chooseEngine(){if(!state.value||!editable.value)return;const draft=copy(data.value);draft.preferences.defaultEngine=engine.value||null;await control.save(draft,state.value.revision);engine.value='';}
function externalSearch(e?:KeyboardEvent){if(e?.isComposing||!query.value.trim())return;const current=currentEngine.value;if(!current)return;const url=current.url.replaceAll('{query}',encodeURIComponent(query.value.trim()));if(preferences.value.newWindowOpen)window.open(url,'_blank','noopener,noreferrer');else window.location.assign(url);}
function shortcut(e:KeyboardEvent){if(e.key!=='/'||e.isComposing||e.ctrlKey||e.altKey||e.metaKey||!preferences.value.search||modalOpen.value)return;const target=e.target as HTMLElement;if(target.closest('input,textarea,select,[contenteditable="true"],dialog'))return;e.preventDefault();searchInput.value?.focus();}
async function loadAssets(){const epoch=dialogEpoch,id=identity();try{const list=await api<Asset[]>('/nav-assets');if(epoch===dialogEpoch&&identity()===id)assets.value=list;}catch{if(epoch===dialogEpoch&&identity()===id)localError.value='素材读取失败，可重试。';}}
async function upload(event:Event){const file=(event.target as HTMLInputElement).files?.[0];if(!file||assetBusy.value)return;const epoch=dialogEpoch,id=identity();assetBusy.value=true;localError.value='';try{const form=new FormData();form.append('file',file);await api('/nav-assets',{method:'POST',body:form},()=>epoch===dialogEpoch&&id===identity());if(epoch===dialogEpoch&&id===identity())await loadAssets();}catch(e){if(epoch===dialogEpoch&&id===identity())localError.value=typeof (e as any)?.detail==='string'?(e as any).detail:'上传未确认，请重读素材列表。';}finally{if(epoch===dialogEpoch&&id===identity())assetBusy.value=false;}}
async function exportData(){const epoch=dialogEpoch,id=identity();try{const value=await api('/nav-export');if(epoch!==dialogEpoch||id!==identity())return;const href=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=href;a.download='Stella-Native-Navigation.stella-nav.json';a.click();setTimeout(()=>URL.revokeObjectURL(href),1000);}catch{if(epoch===dialogEpoch&&id===identity())localError.value='导出失败，请重试。';}}
async function exportPackage(){const epoch=dialogEpoch,id=identity();try{const value=await api('/nav-package');if(epoch!==dialogEpoch||id!==identity())return;const href=URL.createObjectURL(new Blob([JSON.stringify(value)],{type:'application/json'}));const a=document.createElement('a');a.href=href;a.download='Stella-Navigation.complete.json';a.click();setTimeout(()=>URL.revokeObjectURL(href),1000);}catch{if(epoch===dialogEpoch&&id===identity())localError.value='完整包导出失败';}}
async function previewPackage(){if(previewBusy.value)return;const epoch=dialogEpoch,id=identity(),input=source.value;previewBusy.value=true;packageConfirmed.value=false;try{const result=await api<any>('/nav-package-preview',{method:'POST',body:JSON.stringify({source:input})},()=>epoch===dialogEpoch&&id===identity());if(epoch===dialogEpoch&&id===identity()&&input===source.value){moduleBindings.value={};preview.value={...result,complete:true};}}catch(e){if(epoch===dialogEpoch&&id===identity())localError.value=typeof (e as any)?.detail==='string'?(e as any).detail:'完整包解析失败';}finally{if(epoch===dialogEpoch&&id===identity())previewBusy.value=false;}}
async function importPackage(){if(!preview.value?.complete||!packageConfirmed.value||saving.value||uncertain.value)return;const epoch=dialogEpoch;const ok=await control.save(preview.value.data,preview.value.revision,{source:source.value,digest:preview.value.digest,confirmed:true,module_bindings:copy(moduleBindings.value)});if(epoch!==dialogEpoch)return;if(ok){close();toast('完整导航及素材已原子导入');}}
async function preflight(){if(previewBusy.value)return;const epoch=dialogEpoch,id=identity();previewBusy.value=true;localError.value='';try{const result=await api('/nav-import-preview',{method:'POST',body:JSON.stringify({source:source.value})},()=>epoch===dialogEpoch&&id===identity());if(epoch===dialogEpoch&&id===identity())preview.value=result;}catch(e){if(epoch===dialogEpoch&&id===identity())localError.value=(e as any)?.detail||'解析失败';}finally{if(epoch===dialogEpoch&&id===identity())previewBusy.value=false;}}
async function readImport(e:Event){const f=(e.target as HTMLInputElement).files?.[0],epoch=dialogEpoch;if(!f)return;if(f.size>44*1024*1024){localError.value='完整包超过 44 MiB';return;}const text=await f.text();if(epoch===dialogEpoch)source.value=text;}
function globalStyle(s:Preferences){return s;}
const live=ref(false);let stopLive:(()=>void)|undefined;
function startLive(){stopLive?.();stopLive=undefined;if(!loggedIn.value||typeof WebSocket==='undefined')return;const id=identity();stopLive=watchNavRevision(()=>new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws/native-nav/changes`),revision=>{if(id===identity()&&state.value&&revision!==state.value.revision&&!saving.value&&!loading.value&&!uncertain.value)void control.load();},online=>live.value=online);}
watch(identity,()=>{stashDraft();stopLive?.();control.reset();dialogEpoch++;bgPickerOpen.value=false;modal.value?.close();modalOpen.value=false;assets.value=[];editor.value=defaults();assetBusy.value=false;previewBusy.value=false;preview.value=null;source.value='';query.value='';selected.value='';checkDraft();if(loggedIn.value){void control.load();startLive();}},{flush:'sync'});
onMounted(()=>{checkDraft();if(loggedIn.value){void control.load();startLive();}window.addEventListener('keydown',shortcut);ticker=setInterval(()=>clock.value=new Date(),1000);});
onBeforeUnmount(()=>{stashDraft();stopLive?.();control.reset();dialogEpoch++;window.removeEventListener('keydown',shortcut);clearInterval(ticker);});
</script>
<template>
 <main class="native-nav" :style="{'--nav-gap':preferences.gap+'px','--nav-padding':preferences.padding+'px'}">
  <div v-if="background" class="nav-wallpaper" aria-hidden="true"><video v-if="videoUrl(background)" :src="backgroundPlayer.source.value||background" :poster="backgroundPlayer.poster.value" autoplay muted loop playsinline :style="{filter:`blur(${preferences.blur}px)`}"></video><img v-else :src="backgroundPlayer.source.value||background" alt="" :style="{filter:`blur(${preferences.blur}px)`}"><span :style="{opacity:preferences.mask}"></span></div>
  <div class="nav-body" :style="{maxWidth:preferences.width+preferences.widthUnit,marginTop:preferences.marginTop+'%',marginBottom:preferences.marginBottom+'%',paddingLeft:preferences.marginX+'px',paddingRight:preferences.marginX+'px'}">
   <header class="nav-toolbar"><h1>导航</h1><span class="nav-hint" role="status">{{live?'多窗口同步已连接':'实时连接未就绪，可手动刷新'}}</span><div class="nav-toolbar-actions">
    <label v-if="preferences.networkButton" class="nav-device"><span class="sr-only">此设备线路</span><NavSelect v-model="network" label="此设备线路" :options="[{value:'wan',label:'公网'},{value:'lan',label:'内网'}]"/></label>
    <button class="st-button is-primary" :disabled="!editable" @click="editCard()"><Icon name="plus"/>新增网站</button>
    <button class="st-button" :disabled="!editable" @click="editGroup()">新增分组</button>
    <button class="st-button is-icon" :disabled="!editable" aria-label="导航设置" @click="settings"><Icon name="settings"/></button>
    <button class="st-button is-icon" :disabled="loading||saving" aria-label="刷新导航" @click="recover"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 4v6h-6M20 10a8 8 0 1 0 0 7"/></svg></button>
   </div></header>
   <div v-if="preferences.showTitle||preferences.clock" class="nav-identity"><img v-if="preferences.showTitle&&preferences.titleImage" :src="preferences.titleImage" alt=""><h2 v-else-if="preferences.showTitle">{{preferences.title}}</h2><time v-if="preferences.clock" :style="{color:preferences.clockColor||undefined}">{{clockText}}</time></div>
   <form v-if="preferences.search" class="nav-search" :style="{background:preferences.searchBackground||undefined,borderColor:preferences.searchBorder||undefined,color:preferences.searchText||undefined}" @submit.prevent="externalSearch()">
    <img v-if="preferences.searchIcons&&currentEngine?.icon" :src="currentEngine.icon" alt="">
    <NavSelect v-if="preferences.engines.length" :model-value="engine||preferences.defaultEngine||preferences.engines[0]?.id" label="搜索引擎" :disabled="!editable" :options="preferences.engines.map(e=>({value:e.id,label:e.title}))" @update:model-value="engine=$event;chooseEngine()"/>
    <Icon v-else name="search"/><input ref="searchInput" v-model="query" aria-label="搜索网站" placeholder="搜索名称、描述、公网或内网地址 · /" @keydown.enter="($event.isComposing)&&$event.preventDefault()" @keydown.esc="query=''">
    <button v-if="query" type="button" class="st-button is-ghost" aria-label="清空搜索" @click="query=''">清空</button><button v-if="preferences.engines.length" class="st-button is-ghost" type="submit">外部搜索</button>
   </form>
   <div v-if="draftAvailable&&!modalOpen" class="nav-error" role="status">有未保存的导航草稿，仅在当前页面会话内保留；刷新或关闭标签页会清除。<button class="st-button" :disabled="!editable" @click="restoreDraft">恢复未保存导航草稿</button><button class="st-button" @click="discardDraft">丢弃草稿</button></div>
   <p v-if="loading" class="nav-empty" role="status">正在读取导航…</p>
   <div v-if="error&&!modalOpen" class="nav-error" role="alert">{{error}}<button class="st-button" :disabled="loading||saving" @click="recover">重新读取</button></div>
   <div v-if="state" class="nav-content"><nav class="nav-groups" aria-label="导航分组"><button :class="{active:!selected}" @click="selected=''">全部</button><button v-for="g in data.groups" :key="g.id" :class="{active:selected===g.id}" @click="selected=g.id">{{g.title}}</button></nav>
    <div class="nav-sections"><p v-if="!shownGroups.length" class="nav-empty">{{query?'没有匹配的网站':data.groups.length?'此分组没有网站':'还没有分组。添加一个分组，开始整理常用网站。'}}</p>
     <section v-for="g in shownGroups" :key="g.id" :data-group="g.id" class="nav-section">
      <div class="nav-section-head" @dragover.prevent @drop="drop($event,g)"><div><h2>{{g.icon}} {{g.title}}</h2><p v-if="g.description">{{g.description}}</p></div><div class="nav-actions"><button class="st-button is-icon" :draggable="editable" :disabled="!editable" :aria-label="`拖动分组 ${g.title}`" @dragstart="dragStart($event,'group',g.id)" @dragend="dragging=undefined"><Icon name="grid"/></button>
       <button class="st-button is-icon" :disabled="!editable||data.groups[0]?.id===g.id" :aria-label="`上移分组 ${g.title}`" @click="reorder('group',g,data.groups.findIndex(x=>x.id===g.id),-1)"><Icon name="chevron-down" class="nav-up"/></button>
       <button class="st-button is-icon" :disabled="!editable||data.groups.at(-1)?.id===g.id" :aria-label="`下移分组 ${g.title}`" @click="reorder('group',g,data.groups.findIndex(x=>x.id===g.id),1)"><Icon name="chevron-down"/></button>
       <button class="st-button is-icon" :disabled="!editable" :aria-label="`向 ${g.title} 新增网站`" @click="editCard(g)"><Icon name="plus"/></button><button class="st-button is-icon" :disabled="!editable" :aria-label="`编辑分组 ${g.title}`" @click="editGroup(g)"><Icon name="edit"/></button><button class="st-button is-icon" :disabled="!editable" :aria-label="`删除分组 ${g.title}`" @click="askDelete('group',g.id,g.title)"><Icon name="trash"/></button>
      </div></div>
      <div class="nav-cards" :class="effectiveStyle(g.style,preferences).layout" @dragover.prevent @drop="drop($event,g)"><article v-for="c in g.items" :key="c.id" class="nav-card" :data-card="c.id" @dragover.prevent @drop="drop($event,g,c)">
       <a :href="destination(c,network)" :target="c.openMethod===2?'_blank':undefined" rel="noopener noreferrer" :title="c.description||c.title" @click="openCard(c,$event)"><NavCardFace :card="c" :preferences="preferences" :group-style="g.style"/></a>
       <div class="nav-card-tools"><button class="st-button is-icon" :draggable="editable" :disabled="!editable" :aria-label="`拖动网站 ${c.title}`" @dragstart="dragStart($event,'card',c.id)" @dragend="dragging=undefined"><Icon name="grid"/></button><button class="st-button is-icon" :disabled="!editable" :aria-label="`编辑网站 ${c.title}`" @click="editCard(g,c)"><Icon name="edit"/></button><button class="st-button is-icon" :disabled="!editable||data.groups.find(x=>x.id===g.id)?.items[0]?.id===c.id" :aria-label="`上移网站 ${c.title}`" @click="reorder('card',g,data.groups.find(x=>x.id===g.id)!.items.findIndex(x=>x.id===c.id),-1)"><Icon name="chevron-down" class="nav-up"/></button><button class="st-button is-icon" :disabled="!editable||data.groups.find(x=>x.id===g.id)?.items.at(-1)?.id===c.id" :aria-label="`下移网站 ${c.title}`" @click="reorder('card',g,data.groups.find(x=>x.id===g.id)!.items.findIndex(x=>x.id===c.id),1)"><Icon name="chevron-down"/></button><button class="st-button is-icon" :disabled="!editable" :aria-label="`删除网站 ${c.title}`" @click="askDelete('card',c.id,c.title)"><Icon name="trash"/></button></div>
      </article><button class="nav-add" :disabled="!editable" :aria-label="`在 ${g.title} 添加网站`" @click="editCard(g)"><Icon name="plus" :size="24"/><span>添加网站</span></button></div>
     </section>
    </div>
   </div>
  </div>
  <dialog ref="modal" class="nav-dialog" aria-labelledby="nav-dialog-title" @cancel.prevent="close">
   <form :inert="bgPickerOpen" @submit.prevent="submit"><header><h2 id="nav-dialog-title">{{title}}</h2><button type="button" class="st-button is-icon" :disabled="saving||assetBusy" aria-label="关闭导航窗口" @click="close"><Icon name="x"/></button></header>
    <div class="nav-dialog-content">
     <template v-if="mode==='group'&&editorGroup">
      <div class="nav-fields"><label>分组名称<input v-model="editorGroup.title" required maxlength="100"></label><label>分组图标文字<input v-model="editorGroup.icon" maxlength="24"></label><label class="nav-wide">分组描述<textarea v-model="editorGroup.description" maxlength="500" rows="2"></textarea></label></div>
      <h3>分组外观覆盖</h3><StyleEditor :value="editorGroup.style||{}" inherit @change="editorGroup.style=$event"/>
      <button type="button" class="st-button is-ghost" @click="editorGroup.style=null">全部继承全局</button>
      <div class="nav-preview"><NavCardFace :card="editorGroup.items[0]||{...newCard(),title:'预览网站',description:'分组的布局和文字效果'}" :preferences="editor.preferences" :group-style="editorGroup.style"/></div>
     </template>
     <template v-if="mode==='card'&&editorCard">
      <div class="nav-preview is-sticky"><NavCardFace :card="editorCard" :preferences="editor.preferences" :group-style="editorGroup?.style"/></div>
      <div class="nav-fields"><label>网站名称<input v-model="editorCard.title" required maxlength="120"></label><label>所属分组<NavSelect label="所属分组" v-model="cardGroupId" @change="changeCardGroup" :options="editor.groups.map(g=>({value:g.id,label:g.title}))"/></label>
       <label class="nav-wide">公网地址<input v-model="editorCard.url" placeholder="https://example.test/path" maxlength="2048"></label><label class="nav-wide">内网地址<input v-model="editorCard.lanUrl" placeholder="http://192.0.2.1/path" maxlength="2048"></label>
       <label class="nav-wide">引用已接入网站<NavSelect label="引用已接入网站" v-model="editorCard.module_id" :options="[{value:null,label:'普通链接（不创建网站接入）'},...navigation.modules.map(m=>({value:m.id,label:m.name}))]"/></label>
       <label>打开方式<NavSelect label="打开方式" v-model="editorCard.openMethod" :options="[{value:2,label:'新标签页'},{value:1,label:'当前标签页'}]"/></label>
       <label v-if="editorCard.icon">图标类型<NavSelect label="图标类型" v-model="editorCard.icon.itemType" :options="[{value:1,label:'文字'},{value:2,label:'图片'},{value:3,label:'Iconify 图标'}]"/></label>
       <template v-if="editorCard.icon"><label v-if="editorCard.icon.itemType!==2">图标内容<input v-model="editorCard.icon.text" :placeholder="editorCard.icon.itemType===3?'mdi:home':'最多四字预览'" maxlength="24"></label><div v-else><MaterialChoice label="图片素材" v-model="editorCard.icon.src" :assets="assets"/><button type="button" class="st-button" :disabled="faviconBusy" @click="discoverFavicon">发现公开favicon（最多3候选）</button><p class="nav-hint">仅浏览器匿名请求公网原点，不发送查询/凭据到服务器。失败可选自有素材。</p><p role="status">{{faviconNotice}}</p><div class="nav-favicon-candidates"><button v-for="f in favicons" :key="f.url" type="button" :aria-label="'选择favicon '+f.url" @click="editorCard.icon.src=f.url"><img :src="f.thumbnail" alt=""></button></div></div><label>图标 / 卡片底色<NavColor label="图标 / 卡片底色" v-model="editorCard.icon.backgroundColor"/></label></template>
       <label class="nav-wide">描述<textarea v-model="editorCard.description" rows="3" maxlength="2000"></textarea></label>
      </div>
     </template>
     <template v-if="mode==='settings'">
      <nav class="nav-settings-tabs" aria-label="导航设置栏目"><button v-for="[key,label] in settingsTabs" :key="key" type="button" :class="{active:tab===key}" @click="tab=key!">{{label}}</button></nav>
      <SettingsFields v-model="editor.preferences" :tab="tab" :assets="assets" @manage-background="bgPickerOpen=true"/>
      <div v-if="tab==='display'" class="nav-preview"><NavCardFace :card="data.groups[0]?.items[0]||{...newCard(),title:'预览网站',description:'全局默认外观'}" :preferences="globalStyle(editor.preferences)"/></div>
      <template v-if="tab==='assets'"><div class="nav-actions"><label class="st-button">上传图片<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" :disabled="assetBusy" @change="upload"></label><button type="button" class="st-button" :disabled="assetBusy" @click="loadAssets">重读素材</button></div><p class="nav-hint">每张不超过 3 MiB，最多 100 张 / 30 MiB。仅当前账号可读取；分类、尺寸、哈希和批量操作在下方。</p><AssetManager :assets="assets" :busy="assetBusy" @busy="assetBusy=$event" @refresh="loadAssets"/></template>
      <template v-if="tab==='data'"><div class="nav-actions"><button type="button" class="st-button" @click="exportData">导出导航配置</button><button type="button" class="st-button" @click="exportPackage">导出完整包（含素材字节）</button><label class="st-button">读取导出文件<input type="file" accept="application/json,.json" @change="readImport"></label></div><p class="nav-hint">完整包包含分组、网站、全部导航偏好及owner素材字节、计数与SHA-256，不包含会话或凭据。完整导入替换导航聚合且保留现有素材，先比较再人工确认；旧站网站清单仍仅预览，不冒充完整包。</p><label>待解析的导航 JSON<textarea v-model="source" rows="6" maxlength="46137344"></textarea></label><div class="nav-actions"><button type="button" class="st-button" :disabled="previewBusy||!source" @click="preflight">{{previewBusy?'解析中…':'解析与差异预览'}}</button><button type="button" class="st-button" :disabled="previewBusy||!source" @click="previewPackage">完整包预览（不写入）</button></div>
       <div v-if="preview?.complete" class="nav-import-preview"><h3>{{preview.counts.groups}} 组 · {{preview.counts.items}} 网站 · {{preview.counts.assets}} 素材 / {{preview.counts.bytes}} 字节</h3><p>{{preview.boundary}}</p><p v-for="line in preview.warnings" :key="line">{{line}}</p><details open><summary>偏好字段差异 / 素材哈希与尺寸 / 完整导航内容</summary><pre>{{JSON.stringify({changes:preview.preference_changes,assets:preview.asset_mappings,groups:preview.data.groups},null,2)}}</pre></details><h4>逐项重绑定到已接入网站（可选）</h4><p class="nav-hint">不自动按名称或地址匹配。保留原设置或明确选择普通链接；不会新增接入定义。</p><div class="nav-fields"><template v-for="g in preview.data.groups" :key="g.id"><label v-for="c in g.items" :key="c.id">{{g.title}} / {{c.title}}<NavSelect :label="`迁移网站 ${c.title} 的模块绑定`" :model-value="Object.hasOwn(moduleBindings,c.id)?moduleBindings[c.id]:'__keep__'" :disabled="saving||uncertain" :options="[{value:'__keep__',label:'保留包内设置'+(c.module_id?' · '+c.module_id:' · 普通链接')},{value:null,label:'明确改为普通链接'},...navigation.modules.map(m=>({value:m.id,label:m.name}))]" @update:model-value="v=>{if(v==='__keep__')delete moduleBindings[c.id];else moduleBindings[c.id]=v;}"/></label></template></div><label class="nav-check"><input type="checkbox" v-model="packageConfirmed">我已检查差异，确认替换导航及上述打开方式映射</label><button type="button" class="st-button is-primary" :disabled="!packageConfirmed||saving||uncertain||state?.revision!==preview.revision" @click="importPackage">确认原子导入</button></div>
       <div v-else-if="preview" class="nav-import-preview"><h3>{{preview.counts.groups}} 个分组 · {{preview.counts.items}} 个网站</h3><p>当前 {{preview.current_counts.groups}} 组 / {{preview.current_counts.items}} 网站；本次无写入。</p><ul><li v-for="(g,i) in preview.groups" :key="i">{{g.title}} — {{g.children.length}} 个网站</li></ul><p v-for="line in preview.requires_decisions" :key="line">{{line}}</p><p v-if="preview.settings_missing.length">需另行迁入：{{preview.settings_missing.join('、')}}</p><details><summary>字段、排序与素材映射</summary><pre>{{JSON.stringify({mapping:preview.mapping,asset_mappings:preview.asset_mappings,settings:preview.settings},null,2)}}</pre></details></div>
      </template>
     </template>
     <template v-if="mode==='delete'"><p>删除「{{deleteTarget?.title}}」{{deleteTarget?.kind==='group'?'及该分组内全部网站卡片':''}}？</p><p class="nav-hint">不删除网站接入定义、图片素材或旧导航站数据。</p></template>
     <div v-if="error||localError||conflict||uncertain||(state&&baseRevision!==state.revision)" class="nav-error" role="alert">{{error||localError||'服务端版本已更新，草稿保留。可比较后重新应用或取消。'}}<div class="nav-actions"><button v-if="uncertain||conflict" type="button" class="st-button" :disabled="loading||saving" @click="recover">读取服务端版本（保留草稿）</button><button v-if="state&&baseRevision!==state.revision&&!uncertain" type="button" class="st-button" @click="rebase">以最新版本重新应用草稿</button></div></div>
    </div>
    <footer><button type="button" class="st-button" :disabled="saving||assetBusy" @click="close">取消</button><button v-if="mode!=='settings'||!['assets','data'].includes(tab)" type="submit" class="st-button" :class="mode==='delete'?'is-danger':'is-primary'" :disabled="saving||loading||uncertain||assetBusy||(state?.revision!==baseRevision)" :aria-busy="saving"><span class="st-button-label">{{mode==='delete'?'确认删除':'保存'}}</span></button></footer>
   </form>
   <BgManager v-if="bgPickerOpen&&modal" picker open :teleport-to="modal" :selected-url="editor.preferences.backgroundUrl" :protected-urls="protectedBackgrounds" @pick="pickBackground" @close="bgPickerOpen=false"/>
  </dialog>
 </main>
</template>
