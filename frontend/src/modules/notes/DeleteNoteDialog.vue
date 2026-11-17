<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount,onDeactivated,nextTick,watch} from 'vue';
import {useNotesStore} from '../../stores/notes';
import {useNotesPreferencesStore} from '../../stores/notesPreferences';
import {deleteDoc,permanentDeleteDoc,emptyTrash,previewDelete,listDocs,listTrash,getDoc,type DeletePreview} from '../../api/notes';
import {ApiError} from '../../api/client';
import {auth} from '../home/auth';
import {toast} from '../../composables/useToast';
import './notesModal.css';

const props=defineProps<{beforeTrash?:(ids:readonly string[])=>Promise<boolean>}>();
const emit=defineEmits<{deleted:[]}>();
const store=useNotesStore(), preferences=useNotesPreferencesStore();
const target=store.pendingDelete!;
const ordinary=target.kind==='note'||target.kind==='batch';
const action=ref<'trash'|'permanent'>(ordinary?'trash':'permanent');
const scope=ref<'cascade'|'keep'|''>(''), remember=ref(false), busy=ref(false);
const error=ref(''), deleted=ref(false), refreshed=ref(false), uncertain=ref(false), visible=ref(false);
const preview=ref<DeletePreview|null>(null), previewBusy=ref(false), initialized=ref(false), checked=ref(false);
const childCount=ref<number|null>(null);
const plans=ref<DeletePreview[]>([]), receipts=ref<{id:string;status:string}[]>([]);
const panel=ref<HTMLElement|null>(null);
const count=computed(()=>preview.value?.target_ids.length??0);
const needsScope=computed(()=>target.kind!=='empty'&&(childCount.value??0)>0);
const canRemember=computed(()=>ordinary&&!!preferences.saved&&!preferences.busy&&preferences.status==='saved');
let active=true, preferenceAttempted=false, previewEpoch=0, batchComplete=false;
let operation:DeletePreview|null=null;
const owner=auth.me?.id, generation=auth.sessionGeneration, requestEpoch=auth.requestEpoch;
const previous=document.activeElement as HTMLElement|null;
const alive=()=>active&&owner===auth.me?.id&&generation===auth.sessionGeneration&&requestEpoch===auth.requestEpoch&&!auth.suspended&&!auth.sessionClosing&&target.workspaceId===store.workspaceId&&store.pendingDelete===target;
function close(){if(refreshed.value&&alive())emit('deleted');active=false;store.pendingDelete=null;}
function hide(){visible.value=false;active=false;++previewEpoch;store.pendingDelete=null;}
onDeactivated(hide);
onBeforeUnmount(()=>{active=false;++previewEpoch;if(previous?.isConnected)previous.focus();});
watch(()=>[auth.me?.id,auth.suspended,auth.sessionClosing,auth.sessionGeneration,auth.requestEpoch,store.workspaceId],()=>{if(!alive())hide();},{flush:'sync'});
async function show(){visible.value=true;await nextTick();if(alive())panel.value?.focus();}
async function readPlan(request:Parameters<typeof previewDelete>[0]){
 const result=await previewDelete(request);
 // A missing/partial/budget-limited inventory is never evidence of a leaf.
 if(!result||typeof result.scope_token!=='string'||!result.scope_token||result.workspace_id!==request.workspace_id||result.mode!==request.mode||result.cascade!==request.cascade||(result.doc_id??undefined)!==request.doc_id||!Number.isSafeInteger(result.descendant_count)||result.descendant_count<0||!Array.isArray(result.target_ids)||result.target_ids.some(id=>typeof id!=='string'||!id)||new Set(result.target_ids).size!==result.target_ids.length||(request.doc_id&&(!result.target_ids.includes(request.doc_id)||result.target_ids.length!==(request.cascade?result.descendant_count+1:1))))throw new Error('Incomplete deletion scope');
 return {...result,target_ids:[...result.target_ids]};
}
async function loadPreview(){
 const epoch=++previewEpoch;
 preview.value=null;previewBusy.value=true;
 try{
  const docs=target.kind==='batch'?target.docs!:[target.doc];
  const rows:DeletePreview[]=[];
  for(const doc of docs){
   if(!alive()||epoch!==previewEpoch)return false;
   rows.push(await readPlan({workspace_id:target.workspaceId,...(doc?{doc_id:doc.id}:{}),mode:target.kind==='empty'?'empty-trash':action.value,cascade:target.kind==='empty'||scope.value==='cascade'}));
  }
  if(!alive()||epoch!==previewEpoch)return false;
  // A cascade deletes covering roots once; keep mode retains every selection.
  plans.value=rows.filter(row=>!row.cascade||!rows.some(other=>other!==row&&other.target_ids.includes(row.doc_id!)));
  childCount.value=rows.reduce((n,row)=>n+row.descendant_count,0);
  preview.value={...rows[0]!,target_ids:[...new Set(rows.flatMap(row=>row.target_ids))]};
  return true;
 }catch(e){if(alive()&&epoch===previewEpoch)error.value=e instanceof ApiError&&e.status===409?conflictMessage(e):'删除范围读取失败，无法确认子页。请重新读取范围；不会执行删除。';return false;}
 finally{if(alive()&&epoch===previewEpoch)previewBusy.value=false;}
}
watch([action,scope],()=>{if(initialized.value&&!busy.value&&!deleted.value&&!uncertain.value){error.value='';void loadPreview();}},{flush:'sync'});
onMounted(async()=>{
 preferences.bindOwner(auth.me?.id??'');
 const loaded=ordinary?await preferences.load():true;
 if(!alive())return;
 if(ordinary&&loaded)action.value=preferences.saved!.delete_action;
 initialized.value=loaded;
 const ready=loaded&&await loadPreview();
 if(!alive())return;
 if(ready&&ordinary&&!preferences.saved!.ask_before_delete&&!needsScope.value)await submit();
 else await show();
});
function keydown(event:KeyboardEvent){
 if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(!busy.value)close();}
 if(event.key!=='Tab'||!panel.value)return;
 const elements=Array.from(panel.value.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),a[href]')).filter(e=>!e.closest('fieldset:disabled'));
 const first=elements[0],last=elements.at(-1);
 if(event.shiftKey&&(document.activeElement===first||document.activeElement===panel.value)){event.preventDefault();last?.focus();}
 else if(!event.shiftKey&&(document.activeElement===last||document.activeElement===panel.value)){event.preventDefault();first?.focus();}
}
async function retryPreference(){
 if(busy.value||!alive())return;busy.value=true;
 const ok=await preferences.load();busy.value=false;
 if(!alive())return;
 if(ok&&deleted.value&&refreshed.value)close();
 else if(ok&&!initialized.value){initialized.value=true;error.value='';await loadPreview();}
 else error.value=preferences.error;
}
async function reconcile(){
 const op=operation;
 if(!op)return false;
 // Compare these exact responses, never potentially stale/superseded UI caches.
 const [inventory,trash]=await Promise.all([listDocs(op.workspace_id),listTrash(op.workspace_id)]);
 if(!alive())return false;
 if(!Array.isArray(inventory)||!Array.isArray(trash))throw new Error('Invalid inventory');
 const activeIds=new Set(inventory.map(d=>d.id)),trashIds=new Set(trash.map(d=>d.id));
 const done=op.target_ids.every(id=>!activeIds.has(id)&&(op.mode==='trash'?trashIds.has(id):!trashIds.has(id)));
 if(!done)return false;
 // Paginated inventories can drift while being read. Verify each frozen target
 // directly as well; only 404 means no active document, never 401/403/5xx.
 for(let offset=0;offset<op.target_ids.length;offset+=8){
  if(!alive())return false;
  const absent=await Promise.all(op.target_ids.slice(offset,offset+8).map(async id=>{
   try{await getDoc(id);return false;}
   catch(e){if(e instanceof ApiError&&e.status===404)return true;throw e;}
  }));
  if(!alive()||absent.some(value=>!value))return false;
 }
 // Only the verified snapshot may reconcile the editor; newer unrelated trash is preserved.
 store.acceptDeletionReadback(op.workspace_id,inventory,trash);
 refreshed.value=true;deleted.value=true;uncertain.value=false;
 return true;
}
function rememberPreference(){
 if(remember.value&&ordinary&&!preferenceAttempted&&(target.kind!=='batch'||batchComplete)){
  preferenceAttempted=true;
  // The owner-scoped store owns preference verification/retry, not this dialog.
  // A completed deletion must release its action even if preference I/O is slow.
  void preferences.save({delete_action:action.value,ask_before_delete:false}).then(ok=>{
   // This notification intentionally survives the completed dialog, not a session.
   if(!ok&&owner===auth.me?.id&&generation===auth.sessionGeneration&&requestEpoch===auth.requestEpoch&&!auth.suspended&&!auth.sessionClosing)
    toast('删除偏好尚未同步，请到「设置 → 笔记」重新读取或应用。',6000);
  });
 }
}
function finishPreference(){
 rememberPreference();
 close();
}
async function submit(){
 if(busy.value||!alive()||uncertain.value||(!deleted.value&&(!initialized.value||previewBusy.value||!preview.value||(needsScope.value&&!scope.value))))return;
 busy.value=true;error.value='';
 let writeStarted=false;
 try{
  if(!deleted.value){
   const op={...preview.value!,target_ids:[...preview.value!.target_ids]};
   if(op.mode==='trash'&&props.beforeTrash){
    if(!await props.beforeTrash(op.target_ids)){if(alive()){error.value='保存未完成，已阻止删除。编辑内容仍保留，请关闭此窗口后重试保存。';await show();}return;}
    if(!alive())return;
   }
   if(target.kind==='batch'){
    operation={...op,target_ids:[]};
    for(const [index,frozen] of plans.value.entries()){
     if(!alive())return;
     // Own earlier writes invalidate whole-tree tokens. Re-preview but never
     // silently expand the confirmed IDs. The server still fences the write.
     const fresh=index===0?frozen:await readPlan({workspace_id:frozen.workspace_id,doc_id:frozen.doc_id!,mode:frozen.mode,cascade:frozen.cascade});
     if(!alive())return;
     if(fresh.target_ids.length!==frozen.target_ids.length||fresh.target_ids.some(id=>!frozen.target_ids.includes(id)))throw new ApiError(409,{code:'delete_scope_changed'});
     operation.target_ids.push(...fresh.target_ids);
     writeStarted=true;
     receipts.value.push({id:fresh.doc_id!,status:'结果尚未确认'});
     await (fresh.mode==='permanent'?permanentDeleteDoc:deleteDoc)(fresh.doc_id!,fresh.cascade,fresh.scope_token,alive);
     if(!alive())return;
     receipts.value[receipts.value.length-1]!.status='请求已完成';
    }
   }else{
    operation=op;writeStarted=true;
    if(op.mode==='empty-trash')await emptyTrash(op.workspace_id,op.scope_token);
    else await (op.mode==='permanent'?permanentDeleteDoc:deleteDoc)(op.doc_id!,op.cascade,op.scope_token);
   }
   if(!alive())return;
   deleted.value=true;batchComplete=true;
   rememberPreference();
  }
  if(!refreshed.value&&!await reconcile())throw new Error('Deletion readback not yet reconciled');
  if(alive())await finishPreference();
 }catch(e){
  if(!alive())return;
  if(deleted.value)error.value='删除已完成，列表刷新失败或目标状态尚未核对。重试只刷新列表，不会再次删除。';
  else if(target.kind==='batch'&&writeStarted){uncertain.value=true;checked.value=false;error.value='批量删除已停止，部分请求结果尚未确认。请刷新列表核对；已处理项不会自动重发，未执行项请关闭后重新选择。';}
  else if(!writeStarted)error.value='保存未完成，已阻止删除。编辑内容仍保留，请关闭此窗口后重试保存。';
  else if(e instanceof ApiError&&e.status<500&&e.status!==408){
   preview.value=null;
   error.value=e.status===409?conflictMessage(e):e.status===403?'当前会话无法执行笔记删除，请检查权限或服务端版本。不会要求管理密码。':`删除被拒绝（${e.status}）。选择已保留，请重新读取范围后确认。`;
  }else{uncertain.value=true;checked.value=false;error.value='删除结果尚未确认。请刷新列表核对，不要重复删除。';}
  await show();
 }finally{busy.value=false;}
}

function conflictMessage(e:ApiError){
 const code=(e.detail as {code?:string}|null)?.code;
 const messages:Record<string,string>={
  attachment_in_use:'附件仍被集合外的笔记、回收站、草稿或历史引用。请先处理引用，再重新确认。',
  attachment_reference_conflict:'附件仍被集合外的笔记、回收站、草稿或历史引用。请先处理引用，再重新确认。',
  reference_check_incomplete:'附件引用检查未完成。请稍后重试预检，或联系管理员检查扫描限制。',
  document_has_children:'删除范围外仍有子页。请处理子页或重新选择级联／保留上移，再确认范围。',
  document_tree_invalid:'笔记树结构异常。请先修复父子关系，再重新预检；本次未删除。',
  document_tree_check_incomplete:'笔记树检查未完成，不能判断子页范围。请处理检查限制后重新预检。',
  delete_scope_changed:'删除范围已变化。请重新读取范围并确认；不会自动重发删除。',
 };
 const aliases:Record<string,string>={attachment_reference_check_incomplete:'reference_check_incomplete',tree_invalid:'document_tree_invalid',tree_check_incomplete:'document_tree_check_incomplete'};
 return messages[aliases[code??'']??code??'']??'删除被服务器拒绝。请核对笔记状态后重新预检；本次未完成删除。';
}
async function checkUncertain(){
 if(busy.value||!alive())return;busy.value=true;
 try{
  if(await reconcile()){if(alive())await finishPreference();}
  else if(alive()){checked.value=true;error.value='目标尚未达到所选删除状态。选择已保留；可继续只读核对，或重新读取范围后再次确认。不会自动重发。';}
 }catch{if(alive())error.value='列表仍未读取成功，请稍后重试。不会重新发送删除请求。';}
 finally{busy.value=false;}
}
async function reconfirm(){
 if(busy.value||previewBusy.value||!alive()||!initialized.value)return;
 if(target.kind==='batch'&&receipts.value.length)return;
 uncertain.value=false;checked.value=false;operation=null;error.value='';
 // New scope always requires an explicit confirmation, never the remembered auto path.
 scope.value='';await loadPreview();
}
</script>
<template>
 <Teleport to="body">
  <div v-if="visible&&store.pendingDelete" class="notes-modal-mask" @click.self="!busy&&close()">
   <section ref="panel" tabindex="-1" class="notes-modal delete-note-modal" role="dialog" aria-modal="true" aria-labelledby="delete-note-heading" aria-describedby="delete-note-scope" @keydown="keydown">
    <h2 id="delete-note-heading">{{target.kind==='batch'?`批量删除 ${target.docs!.length} 篇笔记`:target.kind==='empty'?'清空回收站':`删除「${target.doc?.title}」`}}</h2>
    <ul v-if="target.kind==='batch'"><li v-for="doc in target.docs" :key="doc.id">{{doc.title}}：{{receipts.find(r=>r.id===doc.id)?.status??'尚未执行'}}</li></ul>
    <p id="delete-note-scope">{{target.kind==='empty'?`当前工作区回收站中的 ${count} 篇笔记将永久删除；不影响其他工作区。`:target.kind==='trash'?'此笔记已在回收站。此次操作会永久删除所选范围。':'请选择这次的删除方式。'}}</p>
    <fieldset :disabled="busy||deleted||uncertain||!initialized">
     <template v-if="ordinary">
      <legend>删除方式</legend>
      <label class="choice"><input v-model="action" type="radio" value="trash" name="delete-action" /><span>移入回收站<small>之后仍可还原</small></span></label>
      <label class="choice"><input v-model="action" type="radio" value="permanent" name="delete-action" /><span>永久删除<small>不可恢复</small></span></label>
     </template>
     <p v-if="action==='permanent'" class="warning">永久删除后无法恢复，包括所选笔记的历史与草稿。外部附件引用仍受保护。</p>
     <div v-if="needsScope" class="scope">
      <p>{{target.kind==='batch'?'所选笔记包含子页面':`包含 ${childCount} 篇子页面`}}，请明确选择范围：</p>
      <label><input v-model="scope" type="radio" value="cascade" name="delete-scope" />一起删除{{target.kind==='batch'?'（包括所选笔记的全部子页）':`（共 ${(childCount??0)+1} 篇）`}}</label>
      <label><input v-model="scope" type="radio" value="keep" name="delete-scope" />{{target.kind==='batch'?'仅删所选笔记':'仅删此篇'}} · 子页保留并上移一级</label>
      <p>子页处理方式不会记住，下次仍需选择。</p>
     </div>
     <template v-if="ordinary">
      <label><input v-model="remember" data-remember type="checkbox" :disabled="!canRemember" />下次不再询问</label>
      <p>仅确认删除并勾选后记住方式。可在「设置 → 笔记」修改或重新开启询问。</p>
     </template>
    </fieldset>
    <p v-if="ordinary&&preferences.error&&!deleted" role="alert">{{preferences.error}} <button :disabled="busy||preferences.busy" @click="retryPreference">重新读取偏好</button></p>
    <p v-if="deleted" role="status">{{refreshed?'笔记删除已完成，列表已刷新。':'删除请求已完成，正在核对删除结果并刷新列表。'}}</p>
    <p v-if="error" class="error" role="alert">{{error}}</p>
    <footer>
     <button :disabled="busy" @click="close()">{{deleted||uncertain?'关闭':'取消'}}</button>
     <button v-if="uncertain" :disabled="busy" @click="checkUncertain">刷新列表核对</button>
     <button v-else :disabled="busy||(!deleted&&(!initialized||previewBusy||!preview||(needsScope&&!scope)))" :class="{danger:action==='permanent'&&!deleted}" @click="submit">{{busy?(deleted?'正在核对删除结果…':'处理中…'):deleted?'重试刷新列表':target.kind==='empty'?'确认永久清空':action==='permanent'?'确认永久删除':'确认移入回收站'}}</button>
     <button v-if="!deleted&&initialized&&!(target.kind==='batch'&&receipts.length)&&((!preview&&!uncertain)||(uncertain&&checked))" :disabled="busy||previewBusy" @click="reconfirm">重新读取范围</button>
    </footer>
    <p v-if="previewBusy" role="status">正在读取删除范围…</p>
    <p v-if="!deleted" class="range">{{!preview?'范围尚未确认':needsScope&&!scope?'尚未选择子页范围':`本次范围：${count} 篇笔记`}}</p>
   </section>
  </div>
 </Teleport>
</template>
<style scoped>
.delete-note-modal{width:min(520px,100%);box-sizing:border-box}.delete-note-modal h2{font-size:20px;overflow-wrap:anywhere;line-height:1.5}.delete-note-modal p{font-size:14px}.delete-note-modal fieldset{border:0;padding:0;margin:18px 0}.delete-note-modal legend{margin-bottom:10px;font-size:14px}.delete-note-modal label{display:flex;align-items:center;gap:10px;min-height:44px;font-size:14px;cursor:pointer}.delete-note-modal input{accent-color:var(--accent);width:18px;height:18px;flex-shrink:0}.choice{border:1px solid var(--accent-dim);border-radius:10px;padding:10px 12px;margin:8px 0}.choice:has(input:checked){background:var(--bg-raised);border-color:var(--accent)}.choice small{display:block;font-size:12px;color:var(--text-lo);margin-top:4px}.scope{border-top:1px solid var(--accent-dim);border-bottom:1px solid var(--accent-dim);margin:16px 0;padding:0 0 8px}.delete-note-modal .warning,.delete-note-modal .error{color:#f1b7c1}.delete-note-modal .success{color:#a8d8b0}.delete-note-modal footer{display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap}.delete-note-modal button{min-height:40px;font:inherit;font-size:14px}.delete-note-modal :focus-visible{outline:2px solid var(--accent);outline-offset:3px}.delete-note-modal .range{font-size:12px;text-align:right;margin-bottom:0}@media(max-width:540px){.delete-note-modal{padding:18px}.delete-note-modal button{min-height:44px}}
</style>
