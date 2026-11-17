<script setup lang="ts">
import {toast} from "../../composables/useToast";
import HelpHint from "./HelpHint.vue";
import {computed, nextTick, onMounted, onBeforeUnmount, onActivated, onDeactivated, ref, watch} from 'vue';
import {auth,isAdmin} from '../home/auth';
import Icon from '../../shell/Icon.vue';
import {ApiError} from '../../api/client';
import {clientPreferenceSync} from './clientPreferenceSync';
import ClientPreferenceStatus from './ClientPreferenceStatus.vue';

import {getBackups, patchBackupConfig, createBackup, verifyBackup, restoreBackup, deleteBackup, downloadBackup, type BackupRecord, type BackupJob, type BackupScope, type BackupSnapshot, type BackupConfig} from '../../api/backups';

const weekdays=['周一','周二','周三','周四','周五','周六','周日'];
function formatBytes(value:number){
  const units=['B','KiB','MiB','GiB','TiB'];let size=value,index=0;
  while(size>=1024 && index<units.length-1){size/=1024;index++;}
  return `${Number(size.toFixed(1))} ${units[index]}`;
}
function formatTime(value:string){
  try{return new Intl.DateTimeFormat('zh-CN',{timeZone:state.value?.config.timezone || 'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value));}
  catch{return '时间不可读';}
}
const state=ref<BackupSnapshot|null>(null), draft=ref<BackupConfig|null>(null), error=ref(''), notice=ref(''), busy=ref(false);
let controller=new AbortController(), readController=new AbortController(), generation=0, readId=0, alive=true;
const loading=ref(false), readback=ref(false), conflict=ref(false);
const active=ref(true);
let savedConfig:{config:BackupConfig;source:string}|null=null;
let pendingDelete:BackupRecord|null=null;
let acceptedJob:BackupJob|null=null;
let preferenceRestore:{id:string|null;previousId:string|undefined}|null=null;
const current=(token:number)=>alive && active.value && token===generation && !controller.signal.aborted;
function invalidate(){generation++;readId++;clearTimeout(poll);controller.abort();readController.abort();controller=new AbortController();busy.value=false;loading.value=false;}
function begin(){invalidate();busy.value=true;error.value='';notice.value='';return generation;}
function stopWaiting(){const writing=busy.value;invalidate();if(writing)readback.value=true;error.value=writing?'已停止等待；服务器操作可能仍在执行，请先重新读取状态。':'已停止读取，可重新刷新。';}
const permissionRequired=ref(false);
const jobActive=computed(()=>!!state.value?.job && ['queued','running'].includes(state.value.job.state));
const directoryDirty=computed(()=>draft.value?.directory!==state.value?.config.directory);
const operationBlocked=computed(()=>busy.value || readback.value || permissionRequired.value || jobActive.value);
const defaultCanInitialize=computed(()=>!!state.value && state.value.config.directory==='' && state.value.storage.can_initialize_default===true);
const blocked=computed(()=>operationBlocked.value || !state.value?.storage.available);
const manualBlocked=computed(()=>operationBlocked.value || !(state.value?.storage.available || defaultCanInitialize.value));
async function download(record:BackupRecord){
  if(blocked.value)return;const token=begin();
  try{await downloadBackup(record.id,controller.signal);if(!current(token))return;notice.value='已交由浏览器下载，请在浏览器下载列表确认结果。';}catch(reason){if(current(token))fail(reason);}finally{if(current(token))busy.value=false;}
}
async function runJob(action:()=>Promise<BackupJob>, syncPreferences=false){
  if(syncPreferences?manualBlocked.value:blocked.value)return;
  const token=begin();
  let submitted=false;
  try{
    if(syncPreferences){await clientPreferenceSync.ensureConfirmed();if(!current(token))return;}
    submitted=true;const job=await action();if(!current(token))return;
    if(job.kind==='restore' && preferenceRestore){preferenceRestore.id=job.id;clientPreferenceSync.beginRestore(job.id);}
    acceptedJob=job;if(state.value)state.value.job=job;readback.value=true;await load();
  }catch(reason){if(current(token)){
    readback.value=submitted && !(reason instanceof ApiError && [400,403,422].includes(reason.status));
    if(!submitted)error.value='账号偏好尚未由服务器确认，未创建备份。请先处理下方同步状态，本机输入已保留。';else fail(reason);
    if(preferenceRestore && reason instanceof ApiError && [400,401,403,409,422].includes(reason.status)){preferenceRestore=null;await clientPreferenceSync.refreshAfterRestore();}
  }}finally{if(current(token))busy.value=false;}
}
function backup(scope:BackupScope){if(!directoryDirty.value)return runJob(()=>createBackup(scope,controller.signal),true);}
function verify(id:string){return runJob(()=>verifyBackup(id,controller.signal));}
const target=ref<{kind:'delete'|'restore';record:BackupRecord}|null>(null), confirmation=ref('');
const dialog=ref<HTMLElement|null>(null), confirmInput=ref<HTMLInputElement|null>(null);
const maintenance=ref<{message:string;command:string}|null>(null);
let previousFocus:HTMLElement|null=null;
async function openDialog(kind:'delete'|'restore',record:BackupRecord){
  previousFocus=document.activeElement as HTMLElement;target.value={kind,record:{...record}};confirmation.value='';maintenance.value=null;error.value='';
  await nextTick();confirmInput.value?.focus();
}
async function closeDialog(){if(busy.value)return;target.value=null;await nextTick();if(previousFocus?.isConnected)previousFocus.focus();}
function dialogKeys(event:KeyboardEvent){
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();void closeDialog();}
  if(event.key!=='Tab')return;
  const nodes=[...dialog.value!.querySelectorAll<HTMLElement>('input,button:not(:disabled),[tabindex="0"]')];
  const first=nodes[0],last=nodes.at(-1);
  if(event.shiftKey && document.activeElement===first){event.preventDefault();last?.focus();}
  else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus();}
}
async function confirmAction(){
  const frozen=target.value;if(!frozen || blocked.value || confirmation.value!==frozen.record.filename)return;
  confirmInput.value?.focus();
  if(frozen.kind==='restore' && frozen.record.scope==='settings'){
    await runJob(()=>{clientPreferenceSync.beginRestore(null,state.value?.job?.id ?? null);preferenceRestore={id:null,previousId:state.value?.job?.id};return restoreBackup(frozen.record,controller.signal);});if(!error.value)await closeDialog();return;
  }
  const token=begin();
  try{
    if(frozen.kind==='delete'){
      pendingDelete=frozen.record;await deleteBackup(frozen.record,controller.signal);if(!current(token))return;readback.value=true;await load();if(!current(token))return;
      if(state.value?.records.some(r=>r.id===frozen.record.id))throw Error('delete not confirmed');
      if(!error.value){busy.value=false;await closeDialog();}
    }else{
      await restoreBackup(frozen.record,controller.signal);
      error.value='服务器未返回离线维护指引；未确认任何全站恢复。';
    }
  }catch(reason){
    if(!current(token))return;
    const detail=reason instanceof ApiError?reason.detail:null;
    if(reason instanceof ApiError && reason.status===409 && detail && typeof detail==='object' && 'code' in detail && detail.code==='maintenance_required' && 'command' in detail && typeof detail.command==='string'){
      maintenance.value={message:'message' in detail?String(detail.message):'需要离线维护',command:detail.command};
      await nextTick();dialog.value?.querySelector<HTMLElement>('pre')?.focus();
    }else{readback.value=!(reason instanceof ApiError && [400,403,422].includes(reason.status));fail(reason);}
  }finally{if(current(token))busy.value=false;}
}
const jobText=computed(()=>{
  const job=state.value?.job;if(!job)return '';
  const name={backup:'备份',verify:'ZIP 校验',restore:'设置恢复'}[job.kind];
  return name+({queued:'等待执行',running:'进行中',succeeded:'已完成',failed:'失败',interrupted:'已中断'}[job.state]);
});
let poll:ReturnType<typeof setTimeout>|undefined;
function schedulePoll(){clearTimeout(poll);if(jobActive.value && active.value && !!auth.me && !auth.suspended && !auth.sessionClosing && !controller.signal.aborted)poll=setTimeout(()=>{void load();},1500);}
function fail(reason:unknown){
  const detail=reason instanceof ApiError?reason.detail:null;
  if(reason instanceof ApiError && reason.status===403){
    permissionRequired.value=true;clearTimeout(poll);

  }
  error.value=reason instanceof ApiError && reason.status===401?'登录已过期，请重新登录后读取状态；不会自动重做刚才的操作。':reason instanceof ApiError && reason.status===403?'当前会话无权执行此操作（403）；不会自动重做，输入已保留。':typeof detail==='string'?detail:detail && typeof detail==='object' && 'message' in detail?String(detail.message):'操作未完成，请检查网络后重试';
}
function sameConfig(a:BackupConfig,b:BackupConfig){return (['enabled','scope','directory','frequency','time','timezone','weekday'] as const).every(key=>a[key]===b[key]);}
async function load(){
  if(!alive || !active.value)return false;
  const token=generation, id=++readId;readController.abort();readController=new AbortController();loading.value=true;
  try{
    const value=await getBackups(readController.signal);if(!current(token) || id!==readId)return false;
    if(acceptedJob && value.job?.id!==acceptedJob.id){
      value.job=acceptedJob;state.value={...value};readback.value=true;notice.value='任务已受理，等待服务器确认进度';error.value='';schedulePoll();return true;
    }
    acceptedJob=null;
    const dirty=draft.value && !sameConfig(draft.value,state.value!.config), pending=savedConfig;
    if(pending && sameConfig(value.config,pending.config)){
      if(JSON.stringify(draft.value)===pending.source)draft.value={...value.config};
      toast('目录与计划已确认');notice.value=draft.value && !sameConfig(draft.value,value.config)?'仍有未应用的输入':'';
    }else if(!draft.value || !dirty)draft.value={...value.config};
    state.value=value;savedConfig=null;readback.value=false;error.value='';permissionRequired.value=!isAdmin.value;
    if(pendingDelete && !value.records.some(record=>record.id===pendingDelete!.id)){
      pendingDelete=null;toast('ZIP 删除已确认');busy.value=false;await closeDialog();
    }
    conflict.value=!!draft.value && draft.value.revision!==value.config.revision && !sameConfig(draft.value,value.config);
    // The App-owned admitted identity survives this view's unmount. Only that
    // known job may reconcile a terminal result; unrelated history is ignored.
    if(!preferenceRestore && clientPreferenceSync.state.restoreWaiting){
      preferenceRestore={id:clientPreferenceSync.state.restoreJobId,previousId:clientPreferenceSync.state.restorePreviousJobId ?? undefined};
    }
    // Fresh current-owner status can also discover a currently active restore.
    if(!preferenceRestore && value.job?.kind==='restore' && value.job.scope==='settings' && ['queued','running'].includes(value.job.state)){
      clientPreferenceSync.beginRestore(value.job.id);preferenceRestore={id:value.job.id,previousId:undefined};
    }
    if(preferenceRestore){
      if(!preferenceRestore.id && value.job?.kind==='restore' && value.job.scope==='settings' && value.job.id!==preferenceRestore.previousId){
        preferenceRestore.id=value.job.id;clientPreferenceSync.beginRestore(value.job.id);
      }
      if(value.job?.id===preferenceRestore.id && ['succeeded','failed','interrupted'].includes(value.job.state)){
        preferenceRestore=null;await clientPreferenceSync.refreshAfterRestore();if(!current(token) || id!==readId)return false;
      }else if(!preferenceRestore.id){readback.value=true;notice.value='恢复是否受理尚未确认，请重新读取状态；不会自动重发。';}
    }
    schedulePoll();return true;
  }catch(reason){if(current(token) && id===readId){readback.value=true;fail(reason);}return false;}
  finally{if(current(token) && id===readId)loading.value=false;}
}
function useServer(){if(state.value && !busy.value && !readback.value){draft.value={...state.value.config};conflict.value=false;notice.value='已使用服务器配置';}}
async function apply(){
  if(!draft.value || busy.value || readback.value || permissionRequired.value || jobActive.value)return;
  const {revision,...fields}=draft.value, source=JSON.stringify(draft.value), expected_revision=conflict.value?state.value!.config.revision:revision;
  const token=begin();
  try{const saved=await patchBackupConfig({...fields,expected_revision},controller.signal);if(!current(token))return;savedConfig={config:saved,source};readback.value=true;await load();}
  catch(reason){if(current(token)){readback.value=!(reason instanceof ApiError && [400,403,422].includes(reason.status));fail(reason);}}
  finally{if(current(token))busy.value=false;}
}
onMounted(()=>{void load();});
onActivated(()=>{active.value=true;if(!loading.value)void load();});
onDeactivated(()=>{active.value=false;if(busy.value)readback.value=true;invalidate();target.value=null;notice.value='';});
watch([isAdmin,()=>auth.me?.id,()=>auth.sessionGeneration,()=>auth.requestEpoch,()=>auth.suspended,()=>auth.sessionClosing],(now,old)=>{
  if(busy.value)readback.value=true;invalidate();target.value=null;notice.value='';
  if(old && (now[1]!==old[1] || now[2]!==old[2])){state.value=null;draft.value=null;savedConfig=null;pendingDelete=null;acceptedJob=null;preferenceRestore=null;readback.value=false;}
  permissionRequired.value=!isAdmin.value;
  // Reauthentication reconciles accepted work; it never replays a write.
  const authenticationChanged=!!old && now.some((value,index)=>index>0 && value!==old[index]);
  if(active.value && !!auth.me && !auth.suspended && !auth.sessionClosing &&
     (isAdmin.value || authenticationChanged || clientPreferenceSync.state.restoreWaiting))void load();
},{flush:'sync'});
onBeforeUnmount(()=>{alive=false;invalidate();});
</script>
<template>
  <section class="backup-center" aria-label="备份与恢复">
    <header class="center-header">
      <div><h2>备份范围</h2></div>
      <div class="actions"><button class="st-button" :disabled="busy || loading" @click="load()">{{readback?'重新读取状态':'刷新备份状态'}}</button><button class="st-button" v-if="busy || loading" @click="stopWaiting">停止等待</button></div>
    </header>
    <div v-if="error && !target" class="feedback error" role="alert">{{error}}</div>
    <div v-if="permissionRequired && !target" class="feedback"><span>当前会话无权执行此操作；确认登录后可重新读取状态，不会自动重做。</span><button class="st-button" :disabled="loading" @click="load()">重新读取状态</button></div>
    <p v-if="notice" class="feedback" role="status">{{notice}}</p>
    <template v-if="draft && state">
      <div class="scope-grid" aria-label="备份范围">
        <article class="scope-card" :class="{selected:draft.scope==='settings'}">
          <label class="scope-choice"><input v-model="draft.scope" type="radio" name="backup-scope" value="settings" /><span><strong><Icon name="settings" :size="19" aria-hidden="true" />所有设置<HelpHint label="备份偏好范围说明">备份保存服务器已确认的账号设置，不代表其他设备的本机设置已同步。</HelpHint></strong><span class="description">站内设置及背景、头像等配置资源。不含笔记正文、草稿、笔记附件和网页项目内容。</span></span></label>
          <button class="st-button" :disabled="manualBlocked || directoryDirty" @click="backup('settings')">备份所有设置</button>
        </article>
        <article class="scope-card" :class="{selected:draft.scope==='all'}">
          <label class="scope-choice"><input v-model="draft.scope" type="radio" name="backup-scope" value="all" /><span><strong><Icon name="box" :size="19" aria-hidden="true" />全部备份</strong><span class="description">Stella 全部持久数据、资源与历史。不含外部 Immich / OpenList 数据，也不是宿主机整盘。</span></span></label>
          <button class="st-button" :disabled="manualBlocked || directoryDirty" @click="backup('all')">备份全部数据</button>
        </article>
      </div>
      <p v-if="directoryDirty" class="feedback">请先应用目录，再创建备份。</p>
      <div v-if="state.job" class="feedback job" :class="{error:['failed','interrupted'].includes(state.job.state)}" role="status">
        <Icon :name="jobActive?'clock':state.job.state==='succeeded'?'check':'activity'" aria-hidden="true" />{{jobText}}<span v-if="state.job.error">：{{state.job.error}}</span>
        <span>任务编号：<code>{{state.job.id}}</code></span>
        <template v-if="['failed','interrupted'].includes(state.job.state)">
          <span>失败阶段：{{state.job.failed_stage || '未记录'}}</span>
          <span>原因代码：<code>{{state.job.reason_code || '原因未记录（历史任务无法追溯）'}}</code></span>
        </template>
      </div>
      <form class="panel" @submit.prevent="apply">
        <h3><Icon name="folder" :size="18" aria-hidden="true" />保存位置与计划<HelpHint label="备份保留规则">每个目录最多保留 2 份成功 ZIP；两种范围、手动与定时共用上限。新备份成功并校验后才删除最旧份，失败不删旧档。</HelpHint></h3>
        <div class="directory-field"><span><label for="backup-directory">服务器路径</label><HelpHint label="备份目录说明">目录是服务器可访问或已挂载的路径，不是这台浏览器电脑的目录。本地目录不代表主备节点共享。</HelpHint></span><input id="backup-directory" v-model="draft.directory" aria-label="备份目录" placeholder="留空使用服务器默认备份目录" maxlength="4096" /></div>
        <p class="storage-note" :class="{error:!state.storage.available && !defaultCanInitialize}" :role="state.storage.available || defaultCanInitialize?undefined:'alert'">当前节点 {{state.storage.node}} · {{state.storage.available?'目录可用':defaultCanInitialize?'默认目录尚未创建':'目录不可用'}}<span v-if="state.storage.free_bytes!==null"> · 可用 {{formatBytes(state.storage.free_bytes)}}</span><span v-if="state.storage.error && !defaultCanInitialize"> · {{state.storage.error}}</span>。</p>
        <p v-if="defaultCanInitialize && !state.storage.available" class="hint">默认目录将在首次手动备份或启用计划后的执行时创建；读取本页不会创建目录。</p>
        <div class="schedule-heading"><label class="toggle-label"><input v-model="draft.enabled" type="checkbox" aria-label="启用自动备份" />启用自动备份</label><span class="hint">{{state.config.enabled?'当前计划已开启':'自动备份已关闭'}}</span></div>
        <div class="schedule-row">
          <label>频率<select v-model="draft.frequency" aria-label="执行频率"><option value="daily">每日</option><option value="weekly">每周</option></select></label>
          <label v-if="draft.frequency==='weekly'">星期<select v-model.number="draft.weekday" aria-label="执行星期"><option v-for="(day,index) in weekdays" :key="index" :value="index">{{day}}</option></select></label>
          <label>时间<input v-model="draft.time" aria-label="执行时间" type="time" required /></label>
          <label class="zone-field">时区<input v-model="draft.timezone" aria-label="时区" placeholder="Asia/Shanghai" maxlength="128" required /></label>
        </div>
        <p v-if="state.config.enabled" class="hint">下次执行：{{state.next_run?formatTime(state.next_run):'服务器尚未提供时间'}} · {{state.config.timezone}}</p>
        <p v-if="conflict" class="feedback">服务器配置已更新。当前输入已保留，请核对后重新应用，或使用服务器配置。</p>
        <div class="actions"><button class="primary st-button is-primary" :disabled="busy || readback || permissionRequired || jobActive" type="submit">{{conflict?'重新应用当前输入':'应用目录与计划'}}</button><button class="st-button" v-if="conflict" type="button" :disabled="busy || readback" @click="useServer">使用服务器配置</button><HelpHint v-if="!draft.enabled" label="计划生效说明">时间设置仅在启用并应用后生效。</HelpHint></div>
      </form>
      <section class="panel records" aria-label="ZIP 记录">
        <header><h3><Icon name="drive" :size="18" aria-hidden="true" />ZIP 记录</h3><HelpHint label="ZIP 校验说明">校验不等于恢复验证；仅核对 ZIP 完整性与清单。</HelpHint></header>
        <p v-if="!state.capabilities.settings_restore" class="feedback">此环境暂不提供设置恢复；仍可下载 ZIP 并核对离线恢复条件。</p>
        <div v-if="!state.records.length" class="empty"><Icon name="box" :size="26" aria-hidden="true" /><p>暂无备份记录</p><span class="hint">选择范围后手动创建，或主动启用计划。</span></div>
        <article v-for="record in state.records" :key="record.id" class="record" :data-backup-id="record.id">
          <div class="record-main"><strong class="filename">{{record.filename}}</strong><div class="record-meta"><span class="scope-badge">{{record.scope==='settings'?'所有设置':'全部备份'}}</span><time :datetime="record.created_at">{{formatTime(record.created_at)}}</time><span>{{formatBytes(record.bytes)}}</span><span>{{record.verified?'ZIP 完整性已校验':'尚未校验'}}</span></div></div>
          <div class="actions record-actions"><button class="st-button" :disabled="blocked" @click="download(record)">下载 ZIP</button><button class="st-button" :disabled="blocked" @click="verify(record.id)">校验 ZIP</button><button class="st-button" :disabled="blocked || record.scope==='settings' && !state.capabilities.settings_restore" @click="openDialog('restore',record)">{{record.scope==='settings'?'恢复设置':'离线恢复'}}</button><button class="danger st-button is-danger" :disabled="blocked" @click="openDialog('delete',record)">删除 ZIP</button></div>
          <details><summary>校验信息</summary><code class="checksum">SHA-256 {{record.sha256}}</code></details>
        </article>
      </section>
      <ClientPreferenceStatus />
    </template>
    <p v-else-if="!error" role="status">正在读取备份中心…</p>
    <Teleport to="body"><div v-if="target && active" class="backup-mask" @click.self="closeDialog"><section ref="dialog" role="dialog" aria-modal="true" aria-labelledby="backup-dialog-title" class="backup-dialog" @keydown="dialogKeys">
      <h2 id="backup-dialog-title">{{target.kind==='delete'?'删除备份 ZIP':target.record.scope==='settings'?'恢复所有设置':'全站离线恢复'}}</h2>
      <p class="filename">{{target.record.filename}}</p><p class="hint">{{target.record.scope==='settings'?'所有设置':'全部备份'}} · {{formatTime(target.record.created_at)}} · {{formatBytes(target.record.bytes)}}</p>
      <p v-if="target.kind==='delete'">仅删除这份备份文件，无法撤销；不会删除站内现有数据。</p>
      <p v-else-if="target.record.scope==='settings'">将覆盖站内设置及背景、头像等配置资源。保留原笔记正文、附件及网页项目内容。请确认备份时间与范围；此操作无法自动撤销。</p>
      <p v-else>全部备份恢复需要维护模式及隔离或空白目标。此处只读取服务器提供的离线入口，不会在网页中执行全站恢复。</p>
      <form v-if="!maintenance" @submit.prevent="confirmAction"><label class="confirm-field">输入完整 ZIP 文件名确认<input ref="confirmInput" v-model="confirmation" aria-label="确认 ZIP 文件名" autocomplete="off" :readonly="busy" /></label>
        <p v-if="error" class="error" role="alert">{{error}}</p><div class="actions"><button class="st-button" v-if="readback || permissionRequired" type="button" :disabled="busy || loading" @click="load()">重新读取状态</button><button class="st-button" v-if="busy || loading" type="button" @click="stopWaiting">停止等待</button></div>
        <footer><button class="st-button" type="button" :disabled="busy" @click="closeDialog">取消</button><button class="primary st-button is-primary" type="submit" :disabled="blocked || confirmation!==target.record.filename">{{target.kind==='delete'?'确认删除':target.record.scope==='settings'?'确认恢复设置':'读取离线恢复指引'}}</button></footer>
      </form>
      <template v-else><p>{{maintenance.message}}</p><pre tabindex="0"><code>{{maintenance.command}}</code></pre><p>请由管理员核实命令、备份路径和空白目标后，在离线维护环境执行。网页未执行恢复。</p><button class="st-button" @click="closeDialog">关闭指引</button></template>
    </section></div></Teleport>
  </section>
</template>
<style scoped>
.backup-center,.backup-dialog{font-size:14px;line-height:1.65;color:var(--text-hi);min-width:0;color-scheme:dark}
h2,h3,p{margin:0}h2{font-size:22px;font-weight:600;letter-spacing:.3px}h3{display:flex;align-items:center;gap:9px;font-size:16px;font-weight:550;margin-bottom:16px}p{margin:9px 0;color:var(--text-lo)}
.center-header,.records>header{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px}.center-header p{margin:4px 0 0}.records>header h3{margin:0}
.actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.actions:empty{display:none}button:not(.st-button){display:inline-flex;align-items:center;justify-content:center;gap:7px;border:1px solid var(--control-border,var(--accent-dim));border-radius:8px;min-height:38px;padding:7px 13px;background:var(--bg-raised);color:var(--text-hi);font:inherit;font-size:13px;cursor:pointer;transition:border-color 160ms,background-color 160ms;white-space:nowrap}button:not(.st-button):hover:not(:disabled){border-color:var(--accent);background:var(--selected-bg,var(--bg-raised))}button:not(.st-button).primary:not(.st-button){background:linear-gradient(var(--button-top,#77619f),var(--button-bottom,#51416f));border-color:var(--button-border,#9781bb);color:#fff}button:not(.st-button).danger:not(.st-button){color:var(--warm,var(--pink));background:transparent}button:not(.st-button):disabled{opacity:.5;cursor:not-allowed}
:where(button:not(.st-button),input,select,summary,pre):focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.scope-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-bottom:18px}.scope-card{background:var(--bg-panel);border:1px solid var(--control-border,var(--accent-dim));padding:18px;border-radius:13px;display:flex;flex-direction:column;gap:16px;min-width:0;transition:border-color 160ms,background-color 160ms}.scope-card.selected{border-color:var(--selected-border,var(--accent-dim));background:color-mix(in srgb,var(--selected-bg,var(--bg-raised)) 50%,var(--bg-panel))}.scope-choice{display:flex;gap:11px;cursor:pointer;flex:1}.scope-choice>input{margin-top:6px;flex-shrink:0}.scope-choice strong{display:flex;align-items:center;gap:9px;font-size:16px;font-weight:550}.scope-choice strong svg{color:var(--accent)}.scope-choice .description{display:block;color:var(--text-lo);margin-top:7px;font-size:13px;line-height:1.7}.scope-card>button{align-self:flex-start;margin-left:24px}
.panel{background:var(--bg-panel);border:1px solid var(--control-border,var(--accent-dim));padding:20px;border-radius:13px;margin:0 0 18px;min-width:0}.directory-field{display:grid;grid-template-columns:200px minmax(0,1fr);align-items:center;gap:24px}input:not([type=radio]):not([type=checkbox]),select{font:inherit;font-size:14px;min-width:0;border-radius:8px;background:var(--bg-base);border:1px solid var(--control-border,var(--accent-dim));padding:8px 11px;color:var(--text-hi);min-height:40px;max-width:100%}input::placeholder{color:var(--text-faint);opacity:1}input[type=radio],input[type=checkbox]{width:17px;height:17px;accent-color:var(--accent)}
.hint,.storage-note{color:var(--text-faint);font-size:12px;line-height:1.65}.storage-note{overflow-wrap:anywhere}.retention{display:flex;align-items:flex-start;gap:8px;padding:12px 0;border-top:1px solid var(--control-border,var(--accent-dim));margin:14px 0 0;font-size:13px}.retention svg{margin-top:3px}.schedule-heading{display:flex;flex-wrap:wrap;align-items:center;gap:6px 20px;margin:14px 0 12px}.toggle-label{display:flex;align-items:center;gap:9px;min-height:36px;cursor:pointer}.schedule-row{display:flex;flex-wrap:wrap;gap:12px 18px;margin:0 0 16px}.schedule-row label{display:flex;align-items:center;gap:10px}.schedule-row select{width:90px}.schedule-row input[type=time]{width:130px}.zone-field{flex:0 1 340px;min-width:210px}.zone-field input{flex:1;width:0}
.feedback{border:1px solid var(--selected-border,var(--control-border,var(--accent-dim)));background:var(--selected-bg,var(--bg-raised));border-radius:9px;padding:10px 13px;margin:0 0 14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:13px;color:var(--text-hi);overflow-wrap:anywhere}.error{color:var(--warm,var(--pink))}.feedback.error{border-color:color-mix(in srgb,var(--warm,var(--pink)) 45%,transparent)}
.empty{display:flex;flex-direction:column;align-items:center;padding:24px 12px;color:var(--text-faint);text-align:center}.empty p{color:var(--text-lo);margin:7px 0 1px}.record{padding:16px 0;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px 16px;border-top:1px solid var(--control-border,var(--accent-dim))}.record-main{min-width:0}.filename{font-size:14px;font-weight:500;overflow-wrap:anywhere}.record-meta{display:flex;align-items:center;gap:5px 12px;flex-wrap:wrap;margin-top:6px;color:var(--text-faint);font-size:12px}.scope-badge{color:var(--accent)}.record-actions{justify-content:flex-end}.record details{grid-column:1/-1;min-width:0}.record summary{font-size:12px;color:var(--text-faint);cursor:pointer;width:fit-content;min-height:24px}.checksum{display:block;color:var(--text-lo);overflow-wrap:anywhere;font-size:12px}.local-boundary{margin:0 0 16px;overflow-wrap:anywhere}
.backup-mask{position:fixed;inset:0;z-index:900;background:color-mix(in srgb,var(--bg-base) 75%,transparent);display:grid;place-items:center;padding:20px}.backup-dialog{width:min(520px,100%);max-height:calc(100dvh - 40px);overflow:auto;background:var(--bg-panel);border:1px solid var(--control-border,var(--accent-dim));border-radius:16px;box-shadow:0 24px 80px #0008;padding:24px;animation:backup-dialog-in 150ms ease-out}.backup-dialog h2{font-size:20px}.backup-dialog .filename{margin-top:12px;color:var(--text-hi)}.confirm-field{display:grid;gap:7px;margin:18px 0}.confirm-field input{width:100%}.backup-dialog footer{display:flex;justify-content:flex-end;gap:9px;margin-top:20px;flex-wrap:wrap}.backup-dialog pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%;font-size:12px;background:var(--bg-base);border:1px solid var(--control-border,var(--accent-dim));padding:13px;border-radius:8px;color:var(--text-hi)}
@keyframes backup-dialog-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
@media(max-width:900px){.record{grid-template-columns:minmax(0,1fr)}.record-actions{justify-content:flex-start}}
@media(max-width:600px){.center-header{align-items:flex-start;flex-direction:column;gap:12px}.scope-grid{grid-template-columns:minmax(0,1fr);gap:12px}.scope-card,.panel{padding:16px}.scope-card>button:not(.st-button){align-self:stretch}.directory-field{grid-template-columns:minmax(0,1fr);gap:7px}.schedule-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}.schedule-row label{flex-direction:column;align-items:stretch;gap:5px;min-width:0}.schedule-row select,.schedule-row input[type=time]{width:100%}.zone-field{grid-column:1/-1;min-width:0}.zone-field input{width:100%}.records>header{align-items:flex-start;flex-direction:column;gap:4px}.backup-center button:not(.st-button),.backup-dialog button:not(.st-button){min-height:44px}.record-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));width:100%}.toggle-label{min-height:44px}.backup-mask{padding:14px}.backup-dialog{padding:20px;max-height:calc(100dvh - 28px)}.backup-dialog footer button:not(.st-button){flex:1}.backup-dialog .actions button:not(.st-button){width:100%}}
@media(max-width:600px){input:not([type=radio]):not([type=checkbox]),select{min-height:44px}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
</style>
