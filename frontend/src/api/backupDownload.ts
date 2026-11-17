// Native same-origin authenticated downloads: never buffer the ZIP in JS.
import {auth} from '../modules/home/auth';
import {ApiError} from './client';
export interface NativeBackupDownload {filename:string;bytes:number}

export async function startNativeBackupDownload(id:string,signal?:AbortSignal):Promise<NativeBackupDownload> {
  const url=`/operations/backups/${encodeURIComponent(id)}/download`;
  const owner=auth.me?.id,epoch=auth.requestEpoch,generation=auth.sessionGeneration;
  const control=new AbortController();
  const abort=()=>control.abort(signal?.reason || new DOMException('已停止下载预检','AbortError'));
  signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  const timer=setTimeout(()=>control.abort(new DOMException('下载预检超时，请确认登录与网络后重试','TimeoutError')),30000);
  const check=()=>{
    if(control.signal.aborted)throw control.signal.reason;
    if(!owner || auth.me?.id!==owner || auth.requestEpoch!==epoch || auth.sessionGeneration!==generation || auth.suspended || auth.sessionClosing)throw new DOMException('会话已变更','AbortError');
  };
  let rejectAbort:()=>void=()=>{};
  const cancellation=new Promise<never>((_,reject)=>{rejectAbort=()=>reject(control.signal.reason);control.signal.addEventListener('abort',rejectAbort,{once:true});if(control.signal.aborted)rejectAbort();});
  const execute=async()=>{
    check();
    const response=await fetch(url,{method:'HEAD',credentials:'same-origin',cache:'no-store',redirect:'error',signal:control.signal});
    check();
    if(!response.ok)throw new ApiError(response.status,{code:'backup_download_unavailable',message:response.status===401?'登录已过期，请重新登录':response.status===403?'当前会话无权下载此备份（403）':response.status===404?'此备份已不存在，请刷新记录':'下载预检失败，请刷新状态后重试'});
    const name=/^attachment;\s*filename="([A-Za-z0-9][A-Za-z0-9_.-]{0,195}\.zip)"$/i.exec(response.headers.get('Content-Disposition') || '')?.[1];
    const length=response.headers.get('Content-Length') || '';
    const bytes=Number(length);
    if(!name || name.includes('..') || !/^\d+$/.test(length) || !Number.isSafeInteger(bytes) || bytes<=0 || response.headers.get('Content-Type')?.split(';')[0]!== 'application/zip')throw new Error('下载元信息无效，请刷新记录；未启动传输');
    check();
    const anchor=document.createElement('a');
    anchor.href=url;anchor.download=name;anchor.referrerPolicy='no-referrer';
    document.body.append(anchor);
    try{anchor.click();}finally{anchor.remove();}
    // Browser owns the long transfer and its native progress/cancel UI. Returning
    // confirms dispatch only, not that bytes have been fully saved by the user.
    return {filename:name,bytes};
  };
  try{return await Promise.race([execute(),cancellation]);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);control.signal.removeEventListener('abort',rejectAbort);}
}
