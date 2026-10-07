<script setup lang="ts">
import {ref,watch,onMounted,onBeforeUnmount,nextTick} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {navigation,navigationRows,loadNavigation,saveNavigation,type NavRow} from '../../stores/navigation';
import ServiceSettings from './ServiceSettings.vue';
import WebsiteSettings from './WebsiteSettings.vue';
import IconPicker from './IconPicker.vue';
import Icon from '../../shell/Icon.vue';
const route=useRoute(),router=useRouter();
const rows=ref<NavRow[]>([]),busy=ref(false),message=ref(''),editing=ref<string|null>(null),dirty=ref(false);
const pending=ref<{id:string|null;leave?:(allowed:boolean)=>void}|null>(null);
function continueEditing(){pending.value?.leave?.(false);pending.value=null;}
function discard(){const current=pending.value;pending.value=null;dirty.value=false;if(current?.leave)current.leave(true);else void open(current?.id??null);}
const removeGuard=router.beforeEach(to=>{
 if(to.path==='/settings'&&to.query.section==='navigation')return true;
 if(editorBusy.value){message.value='操作结果尚未确认，请先完成回读后再离开。';return false;}
 if(!dirty.value)return true;
 pending.value?.leave?.(false);return new Promise<boolean>(resolve=>{pending.value={id:null,leave:resolve};});
});
onBeforeUnmount(()=>{removeGuard();pending.value?.leave?.(false);});
const builtinDraft=ref({name:'',icon:'globe'}),builtinOriginal=ref('');
const editorBusy=ref(false),serviceDirty=ref(false);
function markServiceDirty(){serviceDirty.value=true;dirty.value=true;}
watch(builtinDraft,()=>{if(editing.value&&rows.value.find(x=>x.id===editing.value)?.builtin)dirty.value=serviceDirty.value||JSON.stringify(builtinDraft.value)!==builtinOriginal.value;},{deep:true});
async function saveBuiltin(){const row=rows.value.find(x=>x.id===editing.value);if(!row)return;row.label=builtinDraft.value.name||row.label;row.icon=builtinDraft.value.icon;await persist();if(message.value==='导航已同步'){if(serviceDirty.value){builtinOriginal.value=JSON.stringify(builtinDraft.value);dirty.value=true;}else void open(null);}}
watch(navigationRows,value=>{if(!busy.value)rows.value=value.map(row=>({...row}));},{immediate:true});
onMounted(()=>{if(!navigation.loaded)void loadNavigation();});
async function open(id:string|null){editing.value=id;dirty.value=false;serviceDirty.value=false;editorBusy.value=false;const row=rows.value.find(x=>x.id===id);if(row?.builtin){builtinDraft.value={name:row.label,icon:row.icon};builtinOriginal.value=JSON.stringify(builtinDraft.value);}await nextTick();document.querySelector('.inline-editor input')?.scrollIntoView({block:'nearest'});(document.querySelector('.inline-editor input') as HTMLInputElement|null)?.focus();}
function saved(){message.value='条目已更新并回读';void open(null);}
function choose(id:string|null){if(id===editing.value||editorBusy.value)return;if(dirty.value){pending.value={id};return;}void open(id);}
watch(()=>route.query.module,id=>{if(typeof id==='string')choose(id);},{immediate:true});
async function persist(reset=false){if(busy.value||editorBusy.value)return;busy.value=true;message.value='';try{await saveNavigation(rows.value,reset);rows.value=navigationRows.value.map(row=>({...row}));message.value='导航已同步';}catch{message.value='导航未保存，保留修改，请重试';}finally{busy.value=false;}}
function move(index:number,delta:number){if(busy.value||editorBusy.value)return;const next=index+delta;if(next<0||next>=rows.value.length)return;const row=rows.value.splice(index,1)[0];if(row)rows.value.splice(next,0,row);void persist();}
</script>
<template><section class="nav-settings"><header><h2>导航与网站</h2><button :disabled="busy||editorBusy" @click="choose('new')">＋ 添加网站</button></header><p>所有条目在一处管理；点击对应行就地编辑。隐藏设置后仍可从账号入口找回。</p><p v-if="navigation.error" role="alert">{{navigation.error}} <button @click="loadNavigation">重试加载</button></p>
<WebsiteSettings v-if="editing==='new'" key="new" @busy="editorBusy=$event" @dirty="dirty=$event" @cancel="choose(null)" @saved="saved" />
<div v-for="(row,index) in rows" :key="row.id" :data-row-id="row.id" class="nav-item"><div class="nav-row"><Icon :name="row.icon" :size="18"/><div class="identity"><span>{{row.label}}</span><small>{{row.kind==='service'?(row.id==='drive'?'OpenList':'Immich')+' · 接入服务':row.builtin?'内置页面':'接入网站 · '+(navigation.modules.find(x=>x.id===row.id)?.browser_url||'')}}</small></div><button :aria-label="'编辑 '+row.label" :disabled="busy||editorBusy" @click="choose(row.id)">编辑</button><label class="visible"><input v-model="row.visible" type="checkbox" :aria-label="'显示导航 '+row.label" :disabled="busy||editorBusy" @change="persist()"/>显示</label><button :disabled="busy||editorBusy||index===0" :aria-label="'上移 '+row.label" @click="move(index,-1)">↑</button><button :disabled="busy||editorBusy||index===rows.length-1" :aria-label="'下移 '+row.label" @click="move(index,1)">↓</button></div><template v-if="editing===row.id"><ServiceSettings v-if="row.kind==='service'" :key="row.id" :site="row.id==='drive'?'drive':'gallery'" @busy="editorBusy=$event" @dirty="dirty=$event" @cancel="choose(null)" @saved="saved"/><section v-else-if="row.builtin" class="inline-editor"><form @submit.prevent="saveBuiltin"><fieldset :disabled="busy||editorBusy"><label class="name-field">显示名称<input v-model="builtinDraft.name" aria-label="显示名称" maxlength="80"/></label><IconPicker v-model="builtinDraft.icon" :name="builtinDraft.name"/><div class="actions"><button type="button" @click="choose(null)">取消</button><button type="submit">保存</button></div></fieldset></form><div @input="markServiceDirty" @change="markServiceDirty"><slot name="builtin" :id="row.id"/></div></section><WebsiteSettings v-else :key="row.id" :id="row.id" @busy="editorBusy=$event" @dirty="dirty=$event" @cancel="choose(null)" @saved="saved" /></template></div>
<p v-if="message" role="status">{{message}} <button v-if="message.includes('未保存')" @click="persist()">重试保存</button></p><button :disabled="busy||editorBusy" @click="persist(true)">恢复默认导航</button>
<Teleport to="body"><div v-if="pending" class="mask"><section role="dialog" aria-modal="true" aria-label="未保存的修改" class="dialog"><h3>未保存的修改</h3><p>继续编辑可保留当前草稿；放弃后切换条目或页面。</p><button @click="continueEditing">继续编辑</button><button @click="discard">放弃修改</button></section></div></Teleport></section></template>
<style scoped>.nav-settings{background:var(--bg-panel);padding:20px;border-radius:14px;border:1px solid #ffffff12}header{display:flex;align-items:center;justify-content:space-between;gap:12px}h2{font-size:15px}p{font-size:12px;color:var(--text-lo);line-height:1.7;margin:12px 0}.nav-row{display:flex;align-items:center;gap:10px;padding:11px 0;border-top:1px solid #ffffff09}.identity{flex:1;min-width:0}.identity small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-lo);font-size:12px}button{white-space:nowrap;flex-shrink:0;padding:7px 10px;background:var(--bg-raised);border:1px solid #ffffff20;color:var(--text-hi);border-radius:7px;cursor:pointer}button:disabled{opacity:.45}fieldset{border:0;padding:0;margin:0;min-width:0}.name-field{display:block;width:220px;max-width:100%;font-size:12px;margin-bottom:14px}.name-field input{display:block;box-sizing:border-box;width:100%;margin-top:5px;background:var(--bg-base);color:var(--text-hi);border:1px solid #ffffff20;border-radius:7px;padding:8px}.actions{display:flex;gap:10px;justify-content:flex-end;margin:14px 0}.visible{display:flex;gap:6px;align-items:center;white-space:nowrap;font-size:12px}.mask{position:fixed;inset:0;z-index:1000;background:#080c16b8;display:grid;place-items:center;padding:18px}.dialog{background:var(--bg-panel);padding:24px;width:min(460px,100%);border-radius:14px}.inline-editor{padding:18px;border:1px solid #ffffff20;border-radius:10px}@media(max-width:600px){.nav-row{gap:7px;flex-wrap:wrap}.identity{flex-basis:calc(100% - 36px)}.nav-settings{padding:14px}}</style>
