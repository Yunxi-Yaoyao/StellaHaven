import {ApiError} from './client';
import {startNativeBackupDownload} from './backupDownload';
import {auth} from '../modules/home/auth';
import {validateClientPreferences,type ClientPreferencesWrite} from '../modules/settings/clientPreferenceContract';

export type BackupScope = 'settings' | 'all';
export interface BackupConfig {
  revision:number; enabled:boolean; scope:BackupScope; directory:string;
  frequency:'daily'|'weekly'; time:string; timezone:string; weekday:number;
}
export interface BackupRecord {id:string; filename:string; scope:BackupScope; created_at:string; bytes:number; sha256:string; verified:boolean}
export interface BackupJob {id:string; kind:'backup'|'verify'|'restore'; scope:BackupScope; state:'queued'|'running'|'succeeded'|'failed'|'interrupted'; stage:string; error:string|null; record_id:string|null; reason_code?:string|null; failed_stage?:string|null}
export interface BackupSnapshot {
  config:BackupConfig; records:BackupRecord[]; job:BackupJob|null;
  storage:{node:string; available:boolean; can_initialize_default?:boolean; free_bytes:number|null; error:string|null};
  next_run:string|null; capabilities:{settings_restore:boolean; full_restore:'maintenance_cli'};
}
export type BackupConfigInput = Omit<BackupConfig,'revision'> & {expected_revision:number};
async function request<T>(suffix:string, options:RequestInit={}):Promise<T> {
  // Deliberately no automatic elevation/replay of backup or destructive writes.
  const controller=new AbortController(), generation=auth.sessionGeneration, epoch=auth.requestEpoch, owner=auth.me?.id;
  const abort=()=>controller.abort(new DOMException('已停止等待','AbortError'));
  options.signal?.addEventListener('abort',abort,{once:true});
  if(options.signal?.aborted)abort();
  const timer=setTimeout(()=>controller.abort(new DOMException('请求超时，请先刷新确认服务器状态','TimeoutError')),30000);
  const check=()=>{if(controller.signal.aborted)throw controller.signal.reason;if(auth.suspended || auth.sessionClosing || auth.sessionGeneration!==generation || auth.requestEpoch!==epoch || auth.me?.id!==owner)throw new DOMException('会话已变更','AbortError');};
  let rejectAborted:()=>void=()=>{};
  const cancelled=new Promise<never>((_resolve,reject)=>{rejectAborted=()=>reject(controller.signal.reason);controller.signal.addEventListener('abort',rejectAborted,{once:true});if(controller.signal.aborted)rejectAborted();});
  const execute=async()=>{
    check();
    const response=await fetch(`/operations/backups${suffix}`,{method:'GET',...options,signal:controller.signal,credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'}});
    check();
    if(!response.ok){const detail=await response.json().then(body=>body.detail).catch(()=>null);check();throw new ApiError(response.status,detail);}
    const value=response.status===204?undefined:await response.json();check();return value as T;
  };
  try{return await Promise.race([execute(),cancelled]);}
  finally{clearTimeout(timer);options.signal?.removeEventListener('abort',abort);controller.signal.removeEventListener('abort',rejectAborted);}
}
export const getBackups=(signal?:AbortSignal)=>request<BackupSnapshot>('',{signal});
export const getClientPreferences=async(signal?:AbortSignal)=>validateClientPreferences(await request<unknown>('/client-preferences',{signal}));
export const putClientPreferences=async(value:ClientPreferencesWrite,signal?:AbortSignal)=>validateClientPreferences(await request<unknown>('/client-preferences',{method:'PUT',body:JSON.stringify(value),signal}));
export const patchBackupConfig=(value:BackupConfigInput,signal?:AbortSignal)=>request<BackupConfig>('/config',{method:'PATCH',body:JSON.stringify(value),signal});
export const createBackup=(scope:BackupScope,signal?:AbortSignal)=>request<BackupJob>('',{method:'POST',body:JSON.stringify({scope}),signal});
export const verifyBackup=(id:string,signal?:AbortSignal)=>request<BackupJob>(`/${encodeURIComponent(id)}/verify`,{method:'POST',signal});
export const restoreBackup=(record:BackupRecord,signal?:AbortSignal)=>request<BackupJob>(`/${encodeURIComponent(record.id)}/restore`,{method:'POST',body:JSON.stringify({confirm:record.filename}),signal});
export const deleteBackup=(record:BackupRecord,signal?:AbortSignal)=>request<void>(`/${encodeURIComponent(record.id)}`,{method:'DELETE',body:JSON.stringify({confirm:record.filename}),signal});
export const downloadBackup=startNativeBackupDownload;
