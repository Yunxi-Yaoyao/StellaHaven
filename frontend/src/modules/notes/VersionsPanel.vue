<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount} from 'vue';
import {listVersions,versionDiff,restoreVersion,type Doc,type NoteVersion} from '../../api/notes';
import {ApiError} from '../../api/client';
const props=defineProps<{doc:Doc;dirty:boolean}>();
const emit=defineEmits<{close:[];restored:[doc:Doc]}>();
const versions=ref<NoteVersion[]>([]),diff=ref(''),error=ref(''),loading=ref(true),busy=ref(false),confirm=ref<NoteVersion|null>(null);
const controller=new AbortController();let sequence=0;
onBeforeUnmount(()=>{controller.abort();++sequence;});
onMounted(async()=>{try{versions.value=await listVersions(props.doc.id,controller.signal);}catch{if(!controller.signal.aborted)error.value='版本列表加载失败，请重试';}finally{loading.value=false;}});
async function showDiff(version:NoteVersion){const seq=++sequence;error.value='';try{const r=await versionDiff(version.id,controller.signal);if(seq===sequence)diff.value=r.diff||'正文没有差异';}catch{if(!controller.signal.aborted)error.value='差异加载失败';}}
async function restore(){if(!confirm.value||busy.value||props.dirty)return;busy.value=true;error.value='';try{const result=await restoreVersion(confirm.value.id,props.doc.updated_at,controller.signal);if(!controller.signal.aborted){emit('restored',result);emit('close');}}catch(e){if(!controller.signal.aborted)error.value=e instanceof ApiError&&e.status===409?'笔记已被修改，请关闭历史并重新载入后再恢复':e instanceof ApiError&&e.status===403?'管理权限未解锁，未恢复正文':'恢复失败，原正文未替换';}finally{busy.value=false;confirm.value=null;}}
</script>
<template>
 <Teleport to="body"><div class="notes-modal-mask" @click.self="!busy&&emit('close')"><section class="notes-modal version-modal" role="dialog" aria-modal="true" aria-label="版本历史">
 <header><h2>版本历史</h2><button :disabled="busy" aria-label="关闭版本历史" @click="emit('close')">×</button></header>
 <p>正常保存自动保留版本；小改动合并，满 5 分钟或变化达 500 字符建立检查点。草稿不进入历史。</p>
 <p v-if="props.dirty" role="status">有未保存修改。可查看差异，请先保存当前编辑再恢复。</p>
 <p v-if="error" role="alert">{{error}}</p><p v-if="loading">正在载入…</p><p v-else-if="!versions.length">尚无版本；第一次正文保存会保留修改前与修改后正文。</p>
 <ul><li v-for="v in versions" :key="v.id"><span>v{{v.version_no}} · {{new Date(v.created_at).toLocaleString()}}</span><button :disabled="busy" :aria-label="`查看差异 v${v.version_no}`" @click="showDiff(v)">差异</button><button :disabled="busy||props.dirty" :aria-label="`恢复 v${v.version_no}`" @click="confirm=v">恢复</button></li></ul>
 <pre v-if="diff" class="version-diff">{{diff}}</pre>
 <div v-if="confirm" class="version-confirm"><p>恢复 v{{confirm.version_no}} 会替换当前正文；恢复前正文会保留为版本。需要管理权限。</p><button class="danger" :disabled="busy||props.dirty" @click="restore">{{busy?'恢复中…':'确认恢复版本'}}</button><button :disabled="busy" @click="confirm=null">取消恢复</button></div>
 </section></div></Teleport>
</template>
<style>
.notes-modal-mask{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:150;display:grid;place-items:center;padding:20px}
.notes-modal{background:var(--bg-panel);color:var(--text-hi);border:1px solid var(--bg-raised);border-radius:var(--radius);padding:20px;width:min(680px,95vw);max-height:85vh;overflow:auto;box-shadow:0 16px 60px #0008}
.notes-modal header{display:flex;align-items:center;justify-content:space-between;gap:12px}.notes-modal h2{font-size:18px;margin:0}.notes-modal p{color:var(--text-lo);font-size:13px;line-height:1.6}.notes-modal button{border:1px solid var(--accent-dim);background:var(--bg-raised);color:var(--text-hi);padding:6px 10px;border-radius:var(--radius-sm);cursor:pointer}.notes-modal button:disabled{opacity:.5;cursor:not-allowed}.notes-modal button.danger{color:var(--pink);border-color:var(--pink)}
.version-modal ul{padding:0;list-style:none;max-height:220px;overflow:auto}.version-modal li{display:flex;align-items:center;gap:8px;padding:8px 0}.version-modal li span{flex:1;font-size:13px}.version-diff{white-space:pre-wrap;background:var(--bg-raised);padding:12px;font-size:13px;overflow-wrap:anywhere}.version-confirm{border-top:1px solid var(--pink);padding-top:8px}.version-confirm button+button{margin-left:8px}
</style>
