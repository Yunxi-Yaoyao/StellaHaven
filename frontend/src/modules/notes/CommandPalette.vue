<script setup lang="ts">
import {ref,computed,watch,onMounted,onBeforeUnmount,nextTick} from 'vue';
import {useRouter} from 'vue-router';
import {useNotesStore} from '../../stores/notes';
import {auth} from '../home/auth';
import {unifiedSearch,type SearchItem,type Doc} from '../../api/notes';
import QuickRecordDialog from './QuickRecordDialog.vue';
import {toast} from '../../composables/useToast';
import './notesModal.css';
const props=defineProps<{modules?:{label:string;path:string}[];workspaceId?:string}>();
const store=useNotesStore(),router=useRouter();
const open=ref(false),query=ref(''),remote=ref<SearchItem[]>([]),busy=ref(false),error=ref(''),cursor=ref(0),capture=ref(false),input=ref<HTMLInputElement|null>(null);
const captureWorkspace=ref('');
let previousFocus:HTMLElement|null=null,timer:ReturnType<typeof setTimeout>|undefined,controller:AbortController|undefined,sequence=0;
const workspace=computed(()=>{
 if(props.workspaceId)return props.workspaceId;
 if(store.userId===auth.me?.id&&store.workspaceId)return store.workspaceId;
 try{const cache=JSON.parse(localStorage.getItem('stella_bootstrap')||'{}');return cache.userId===auth.me?.id?cache.workspaceId||'':'';}catch{return '';}
});
const defaults=[{label:'主页',path:'/'},{label:'服务器',path:'/status'},{label:'笔记',path:'/notes'},{label:'网盘',path:'/drive'},{label:'图库',path:'/gallery'},{label:'设置',path:'/settings'}];
const results=computed<SearchItem[]>(()=>{
 const q=query.value.trim().toLocaleLowerCase();
 const modules=(props.modules??defaults).filter(m=>!q||m.label.toLocaleLowerCase().includes(q)).map(m=>({kind:'module',id:m.path,label:m.label,path:m.path}));
 return [...modules,...remote.value].slice(0,30);
});
function cancel(){if(timer)clearTimeout(timer);timer=undefined;controller?.abort();controller=undefined;++sequence;busy.value=false;}
function close(){cancel();open.value=false;remote.value=[];void nextTick(()=>previousFocus?.focus());}
function show(){if(!auth.me)return;previousFocus=document.activeElement as HTMLElement;open.value=true;query.value='';remote.value=[];error.value='';cursor.value=0;void nextTick(()=>input.value?.focus());}
watch(query,()=>{cancel();remote.value=[];error.value='';cursor.value=0;if(!open.value||!query.value.trim())return;const seq=sequence;busy.value=true;timer=setTimeout(async()=>{controller=new AbortController();const signal=controller.signal;try{const r=await unifiedSearch(query.value.trim(),workspace.value||undefined,signal);if(seq===sequence&&open.value)remote.value=r.items;}catch{if(seq===sequence&&!signal.aborted)error.value='搜索失败，本地模块仍可打开。请重试';}finally{if(seq===sequence)busy.value=false;}},180);});
watch(()=>auth.me?.id,()=>{close();capture.value=false;});
async function choose(item:SearchItem){close();await router.push(item.path);}
function quick(){if(!workspace.value)return;captureWorkspace.value=workspace.value;close();capture.value=true;}
async function captured(doc:Doc){const owner=auth.me?.id;capture.value=false;if(store.workspaceId===doc.workspace_id&&store.userId===owner){try{await store.refreshList();}catch{toast('记录已保存，列表刷新失败；正在打开笔记');}}if(owner&&owner===auth.me?.id)await router.push('/notes?doc='+encodeURIComponent(doc.id));}
function key(event:KeyboardEvent){if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'&&!event.altKey){event.preventDefault();if(open.value)close();else show();return;}if(!open.value)return;if(event.key==='Escape'){event.preventDefault();close();}else if(event.key==='ArrowDown'){event.preventDefault();cursor.value=Math.min(cursor.value+1,results.value.length-1);}else if(event.key==='ArrowUp'){event.preventDefault();cursor.value=Math.max(0,cursor.value-1);}else if(event.key==='Enter'&&results.value[cursor.value]){event.preventDefault();void choose(results.value[cursor.value]!);}}
defineExpose({show,close});
function openEvent(){show();}
onMounted(()=>{window.addEventListener('keydown',key);window.addEventListener('stella:command-palette',openEvent);});
onBeforeUnmount(()=>{cancel();window.removeEventListener('keydown',key);window.removeEventListener('stella:command-palette',openEvent);});
const kinds:Record<string,string>={module:'模块',note:'笔记',node:'节点',node_status:'节点历史',alert:'告警历史',mtr_task:'MTR记录',iperf_task:'打流记录',command_task:'命令记录',component_task:'组件记录',net_task:'网络记录'};
</script>
<template><span class="command-palette-root" hidden></span><Teleport to="body"><div v-if="open" class="notes-modal-mask" @click.self="close"><section class="notes-modal command-palette" role="dialog" aria-modal="true" aria-label="统一搜索与快捷命令">
<header><h2>搜索与快捷命令</h2><button aria-label="关闭统一搜索" @click="close">×</button></header>
<input ref="input" v-model="query" aria-label="统一搜索" placeholder="搜索模块、笔记标题、节点与已有历史…" autocomplete="off" :aria-activedescendant="`command-result-${cursor}`" />
<div class="command-bar"><button :disabled="!workspace" @click="quick">快捷记录</button><small>{{workspace?'保存到当前工作区收件箱':'先打开笔记选择工作区，才能快捷记录'}}</small></div>
<p v-if="error" role="alert">{{error}}</p><p v-if="busy" role="status">搜索中…</p><p v-if="!busy&&!results.length">没有命中；仅搜索已保存的标题与事件元信息，不读取草稿或正文。</p>
<ul role="listbox"><li v-for="(item,index) in results" :key="item.kind+item.id"><button :id="`command-result-${index}`" role="option" :aria-selected="cursor===index" :class="{selected:cursor===index}" @mousemove="cursor=index" @click="choose(item)"><small>{{kinds[item.kind]||item.kind}}</small><span>{{item.label}}</span><time v-if="item.ts">{{new Date(item.ts).toLocaleDateString()}}</time></button></li></ul>
<footer>↑↓ 选择 · Enter 打开 · Esc 关闭 · Ctrl / ⌘ K</footer>
</section></div></Teleport><QuickRecordDialog v-if="capture" :workspace-id="captureWorkspace" @close="capture=false" @created="captured" /></template>
<style scoped>.command-palette>input{box-sizing:border-box;width:100%;margin:16px 0 10px;border:1px solid var(--accent-dim);background:var(--bg-raised);color:var(--text-hi);padding:12px;font:inherit;border-radius:var(--radius-sm)}.command-bar{display:flex;align-items:center;gap:10px}.command-bar small{font-size:12px;color:var(--text-lo)}.command-palette ul{padding:0;list-style:none;max-height:46vh;overflow:auto}.command-palette li button{display:flex;align-items:center;gap:12px;width:100%;text-align:left;margin:3px 0;background:transparent;border-color:transparent}.command-palette li button.selected{border-color:var(--accent-dim);background:var(--bg-raised)}.command-palette li small{min-width:58px;color:var(--text-faint)}.command-palette li span{flex:1;overflow-wrap:anywhere}.command-palette li time,.command-palette footer{color:var(--text-faint);font-size:12px}</style>
