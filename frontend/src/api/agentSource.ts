import {ApiError} from './client';
import {auth,refreshAccess} from '../modules/home/auth';
export interface AgentSource {text:string;bytes:Uint8Array<ArrayBuffer>;sha256:string;version:string;size:number}
// Stop this caller's wait, not the shared refresh. Observe late rejection and
// dispose late fetch bodies without letting a timed-out continuation retry.
function abortable<T>(pending:Promise<T>,signal:AbortSignal,discard?:(value:T)=>void):Promise<T>{
 return new Promise((resolve,reject)=>{
  let settled=false;
  const abort=()=>{if(settled)return;settled=true;signal.removeEventListener('abort',abort);reject(new DOMException('读取已取消','AbortError'));};
  signal.addEventListener('abort',abort,{once:true});
  if(signal.aborted)abort();
  pending.then(value=>{if(settled){discard?.(value);return;}settled=true;signal.removeEventListener('abort',abort);resolve(value);},error=>{if(settled)return;settled=true;signal.removeEventListener('abort',abort);reject(error);});
 });
}
function discardResponse(response:Response){void response.body?.cancel().catch(()=>{});}
// This is the existing credential-free installer artifact, never an install command.
export async function readAgentSource(signal:AbortSignal):Promise<AgentSource>{
 const owner=auth.me?.id,generation=auth.sessionGeneration,epoch=auth.requestEpoch;
 const current=()=>{if(signal.aborted||!owner||auth.suspended||auth.sessionClosing||owner!==auth.me?.id||generation!==auth.sessionGeneration||epoch!==auth.requestEpoch)throw new DOMException('读取已取消','AbortError');};
 current();
 const request=async()=>{current();const response=await abortable(fetch('/agent/script',{signal,credentials:'same-origin',cache:'no-store',redirect:'error'}),signal,discardResponse);try{current();}catch(error){discardResponse(response);throw error;}return response;};
 let response=await request();
 if(response.status===401){discardResponse(response);if(await abortable(refreshAccess(),signal)){current();response=await request();}}
 current();if(!response.ok)throw new ApiError(response.status,null);
 const limit=1024*1024;
 if(Number(response.headers.get('content-length'))>limit){discardResponse(response);throw new Error('源码超过 1 MiB，无法在此查看。');}
 const reader=response.body?.getReader();if(!reader)throw new Error('源码响应为空。');
 const chunks:Uint8Array[]=[];let size=0;
 try{
  for(;;){const {done,value}=await abortable(reader.read(),signal);current();if(done)break;size+=value.byteLength;if(size>limit)throw new Error('源码超过 1 MiB，无法在此查看。');chunks.push(value);}
 }catch(error){void reader.cancel().catch(()=>{});throw error;}finally{reader.releaseLock();}
 const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
 const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
 const version=text.match(/^AGENT_VERSION\s*=\s*["']([^"']+)["']/m)?.[1];if(!version)throw new Error('响应不是有效的 Agent 源码。');
 const sha256=Array.from(new Uint8Array(await abortable(crypto.subtle.digest('SHA-256',bytes),signal)),n=>n.toString(16).padStart(2,'0')).join('');current();
 return {text,bytes,sha256,version,size};
}
