<script setup lang="ts">
import HelpHint from "../settings/HelpHint.vue";
import Dropdown from '../../shell/Dropdown.vue';
import {computed,onActivated,onDeactivated,onBeforeUnmount,ref,watch} from 'vue';
import {auth} from '../home/auth';
import {useNotesPreferencesStore} from '../../stores/notesPreferences';
import {ensureWorkspace,listDocs,type Doc,type NotesPreferenceFields} from '../../api/notes';
import {useNotesStore} from '../../stores/notes';
import {importTreeRows} from './import-helpers';
const notes=useNotesStore();
const props=defineProps<{loadWorkspace?:boolean}>();
const directoryDocs=ref<Doc[]>([]),directoryStatus=ref<'idle'|'loading'|'ready'|'error'>('idle');
const contextActive=ref(true);let directorySequence=0;
const directoryScope=computed(()=>JSON.stringify([auth.me?.id,auth.sessionGeneration,auth.requestEpoch,auth.suspended,auth.sessionClosing,notes.userId,notes.workspaceId,contextActive.value]));
async function loadDirectories(){
 const seq=++directorySequence, scope=directoryScope.value,owner=auth.me?.id;
 directoryDocs.value=[];directoryStatus.value='idle';
 if(!props.loadWorkspace||!owner||auth.suspended||auth.sessionClosing||!contextActive.value)return;
 const current=()=>seq===directorySequence&&scope===directoryScope.value;
 directoryStatus.value='loading';
 try {
  const context=notes.userId===owner&&notes.workspaceId?{userId:owner,workspaceId:notes.workspaceId}:await ensureWorkspace();
  if(!current())return;
  if(context.userId!==owner)throw Error('工作区身份不匹配');
  const docs=await listDocs(context.workspaceId);
  if(!current())return;
  if(docs.some(doc=>doc.workspace_id!==context.workspaceId))throw Error('目录归属不匹配');
  directoryDocs.value=docs;directoryStatus.value='ready';
 }catch{if(current())directoryStatus.value='error';}
}
watch(directoryScope,()=>{void loadDirectories();},{immediate:true,flush:'sync'});
onActivated(()=>{if(!contextActive.value)contextActive.value=true;});
onDeactivated(()=>{contextActive.value=false;});
onBeforeUnmount(()=>{++directorySequence;});
const folders=computed(()=>importTreeRows((props.loadWorkspace?directoryDocs.value:notes.allDocs).filter(d=>d.is_folder)));
function hide(id:string, checked:boolean){
 const ids=new Set(preferences.draft.hidden_folders??[]);
 if(checked)ids.add(id);else ids.delete(id);
 change({hidden_folders:[...ids]});
}
const preferences=useNotesPreferencesStore();
const available=computed(()=>!!auth.me&&!auth.suspended&&!auth.sessionClosing);
const editable=computed(()=>available.value&&!!preferences.saved&&!preferences.busy&&!['verify','conflict'].includes(preferences.status));
function load(){if(available.value){preferences.bindOwner(auth.me!.id);void preferences.load();}else preferences.bindOwner('');}
watch(()=>[auth.me?.id,auth.suspended,auth.sessionClosing,auth.sessionGeneration,auth.requestEpoch],load,{immediate:true,flush:'sync'});
onActivated(load);
function change(fields:Partial<NotesPreferenceFields>){if(editable.value)void preferences.save(fields);}
</script>
<template>
 <section class="notes-settings" aria-labelledby="notes-settings-title">
  <header><h2 id="notes-settings-title">笔记</h2><span role="status">{{preferences.busy?(preferences.status==='saving'?'正在保存…':'正在读取…'):preferences.status==='saved'?'已同步':preferences.status==='idle'?'等待登录':'尚未同步'}}</span></header>
  <p class="intro">按账号自动同步，修改立即生效。</p>
  <fieldset :disabled="!editable" class="reading-settings"><legend>阅读与编辑</legend>
   <label>字号<input aria-label="字号" type="number" min="12" max="28" :value="preferences.draft.font_size??16" @change="change({font_size:Number(($event.target as HTMLInputElement).value)})" /></label>
   <label>行距<input aria-label="行距" type="number" min="1.2" max="2.5" step="0.1" :value="preferences.draft.line_height??1.8" @change="change({line_height:Number(($event.target as HTMLInputElement).value)})" /></label>
   <label>阅读宽度<input aria-label="阅读宽度" type="number" min="480" max="1400" step="40" :value="preferences.draft.read_width??800" @change="change({read_width:Number(($event.target as HTMLInputElement).value)})" /></label>
   <label><input type="checkbox" :checked="preferences.draft.code_line_numbers??false" @change="change({code_line_numbers:($event.target as HTMLInputElement).checked})" />代码行号</label>
   <label><input type="checkbox" :checked="preferences.draft.code_wrap??true" @change="change({code_wrap:($event.target as HTMLInputElement).checked})" />代码自动换行</label>
   <div class="sort-row"><span>目录排序</span><Dropdown :model-value="preferences.draft.directory_sort??'updated'" :options="[{value:'updated',label:'最近更新'},{value:'title',label:'标题'},{value:'created',label:'创建时间'}]" @update:model-value="change({directory_sort:$event as 'updated'|'title'|'created'})" /></div>
  </fieldset>
  <details id="notes-hidden-folders" open><summary>隐藏目录</summary><p v-if="loadWorkspace&&directoryStatus==='loading'" role="status">正在读取工作区目录…</p><p v-if="loadWorkspace&&directoryStatus==='error'" role="alert">目录读取失败，未改变隐藏设置。<button class="ghost-btn" @click="loadDirectories">重试目录</button></p><fieldset :disabled="!editable||(loadWorkspace&&directoryStatus!=='ready')"><label v-for="folder in folders" :key="folder.id" :style="{paddingLeft:`${folder.depth*16}px`}"><input type="checkbox" :checked="preferences.draft.hidden_folders?.includes(folder.id)??false" @change="hide(folder.id,($event.target as HTMLInputElement).checked)" />{{folder.title}}</label><p v-if="!folders.length&&(!loadWorkspace||directoryStatus==='ready')">当前工作区没有目录</p></fieldset></details>
  <fieldset :disabled="!editable">
   <legend>默认删除方式<HelpHint label="笔记数据保护说明"><p>附件引用与草稿保护是固定安全规则，不提供关闭开关。被其他笔记、回收站、草稿或历史版本引用的附件，会阻止破坏引用的永久删除。</p><p>回收站单篇删除和清空会展示明确范围。工作区与全局管理权限不受这些偏好影响。</p></HelpHint></legend>
   <div class="options">
    <label :class="{selected:preferences.draft.delete_action==='trash'}"><input :checked="preferences.draft.delete_action==='trash'" type="radio" name="notes-default-delete" value="trash" @change="change({delete_action:'trash'})" /><span>移入回收站<small>可在回收站还原</small></span></label>
    <label :class="{selected:preferences.draft.delete_action==='permanent'}"><input :checked="preferences.draft.delete_action==='permanent'" type="radio" name="notes-default-delete" value="permanent" @change="change({delete_action:'permanent'})" /><span>永久删除<small>删除后不可恢复</small></span></label>
   </div>
   <label class="ask"><input :checked="preferences.draft.ask_before_delete" type="checkbox" aria-label="删除前询问" @change="change({ask_before_delete:($event.target as HTMLInputElement).checked})" /><span>删除前询问<small>重新开启后，每次可以选择删除方式；取消不改变偏好。</small></span></label>
  </fieldset>
  <p v-if="preferences.draft.delete_action==='permanent'&&!preferences.draft.ask_before_delete" class="warning">已选择直接永久删除。普通笔记不会再弹确认；有子页面时仍需明确选择一起删除或保留上移。</p>
  <p v-if="preferences.error" class="error" role="alert">{{preferences.error}}</p>
  <div v-if="preferences.error" class="retry">
   <template v-if="preferences.status==='conflict'"><button :disabled="preferences.busy||!available" @click="preferences.save(preferences.draft)">重新应用我的选择</button><button :disabled="preferences.busy||!available" @click="preferences.useServer()">使用服务器设置</button></template>
   <button v-else :disabled="preferences.busy||!available" @click="preferences.load()">重新读取偏好</button>
  </div>
 </section>
</template>
<style scoped>
.sort-row{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:15px;min-height:44px}
.notes-settings .reading-settings{display:grid;gap:8px;margin-bottom:22px}.notes-settings .reading-settings input[type=number]{width:90px;height:32px;margin-left:auto;background:var(--bg-base);color:var(--text-hi);border:1px solid var(--accent-dim);border-radius:4px}.notes-settings select{min-width:0;background:var(--bg-base);color:var(--text-hi);padding:6px}.notes-settings details{margin-bottom:24px}.notes-settings summary{cursor:pointer;padding:12px 0}

.notes-settings{background:var(--bg-panel);color:var(--text-hi);border:1px solid var(--accent-dim);border-radius:16px;padding:24px;max-width:820px;box-sizing:border-box}.notes-settings header{display:flex;align-items:center;justify-content:space-between;gap:16px}.notes-settings h2{font-size:22px;margin:0;font-weight:600}.notes-settings header span{font-size:13px;color:var(--text-lo)}.notes-settings p{font-size:14px;line-height:1.7;color:var(--text-lo)}.intro{margin:10px 0 24px}.notes-settings fieldset{border:0;padding:0;margin:0}.notes-settings legend{font-size:14px;margin-bottom:12px}.options{display:grid;grid-template-columns:1fr 1fr;gap:12px}.options label{border:1px solid var(--accent-dim);border-radius:10px;padding:14px}.options .selected{background:var(--bg-raised);border-color:var(--accent)}.notes-settings label{display:flex;align-items:center;gap:12px;font-size:15px;min-height:44px;cursor:pointer}.notes-settings input{width:18px;height:18px;flex-shrink:0;accent-color:var(--accent)}.notes-settings small{display:block;font-size:13px;color:var(--text-lo);margin-top:6px;line-height:1.6}.ask{margin:20px 0}.notes-settings aside{border-top:1px solid var(--accent-dim);margin-top:24px;padding-top:18px}.notes-settings h3{font-size:15px;margin:0;font-weight:500}.notes-settings .warning,.notes-settings .error{color:#f1b7c1}.retry{display:flex;gap:10px;flex-wrap:wrap}.notes-settings button{background:var(--bg-raised);color:var(--text-hi);border:1px solid var(--accent-dim);border-radius:8px;padding:10px 14px;min-height:40px;font:inherit;cursor:pointer}.notes-settings button:disabled{opacity:.6;cursor:wait}.notes-settings :focus-visible{outline:2px solid var(--accent);outline-offset:3px}@media(max-width:540px){.notes-settings{padding:18px}.options{grid-template-columns:1fr}.notes-settings button{min-height:44px}}
</style>
