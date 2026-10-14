import {watch} from 'vue';
import {auth} from '../home/auth';
const privatePrefixes=/^\/(?:auth|workspaces|documents|doc-tags|tags|document-links|document-versions|attachments|homebg|navigation|notifications|servers|monitor|drive|gallery|users|config|services|websites|operations|nodes|monitors|tasks|notes-tools|service-settings|website-settings|integration-targets|integration-presets|external-modules|builtin-injections|admin|search|alerts)(?:\/|$)/;
const entryPaths=new Set(['/auth/status','/auth/login','/auth/register','/auth/refresh','/auth/logout','/auth/forgot','/auth/reset','/auth/login-code','/auth/login-code/send','/auth/email/resend','/auth/register-invite']);
export function privateRequest(path:string,method='GET'){
 const url=new URL(path,location.href);
 if(url.origin!==location.origin)return false;
 if(entryPaths.has(url.pathname)||method==='GET'&&['/auth/me','/config/site-background','/homebg/media'].includes(url.pathname))return false;
 return privatePrefixes.test(url.pathname);
}
export function sessionBlocked(){return auth.suspended||auth.sessionClosing||auth.checked&&!auth.me;}
export function assertSession(generation:number,owner:string|undefined,epoch=auth.requestEpoch){
 if(sessionBlocked()||generation!==auth.sessionGeneration||epoch!==auth.requestEpoch||owner!==auth.me?.id)throw new DOMException('登录后继续','AbortError');
}
/** Fence native fetch and live sockets too: a modal must not consume late private data. */
export function installSessionFence(){
 const original=window.fetch.bind(window);
 window.fetch=async(input,init)=>{
  const path=typeof input==='string'?input:input instanceof URL?input.href:input.url;
  const method=init?.method||(typeof input==='object'&&'method' in input?input.method:'GET');
  const url=new URL(path,location.href);
  // Serialize cookie-changing responses, not just local identity assignments.
  if(auth.sessionClosing && url.origin===location.origin && /^\/auth\/(?:login|register|login-code|register-invite|refresh)(?:\/|$)/.test(url.pathname))throw new DOMException('正在退出登录，请稍候','AbortError');
  const privateCall=privateRequest(path,method.toUpperCase());
  const generation=auth.sessionGeneration,owner=auth.me?.id,epoch=auth.requestEpoch;
  if(privateCall)assertSession(generation,owner,epoch);
  const response=await original(input,init);
  if(privateCall){
   assertSession(generation,owner,epoch);
   for(const name of ['json','text','blob','arrayBuffer','formData'] as const){
    const read=response[name].bind(response);
    Object.defineProperty(response,name,{value:async()=>{const value=await read();assertSession(generation,owner,epoch);return value;}});
   }
  }
  return response;
 };
 const NativeSocket=window.WebSocket,sockets=new Set<WebSocket>();
 class SessionSocket extends NativeSocket{
  constructor(url:string|URL,protocols?:string|string[]){
   if(sessionBlocked())throw new DOMException('登录后继续','AbortError');
   super(url,protocols);sockets.add(this);
   const generation=auth.sessionGeneration,owner=auth.me?.id,epoch=auth.requestEpoch;
   this.addEventListener('message',event=>{if(sessionBlocked()||generation!==auth.sessionGeneration||epoch!==auth.requestEpoch||owner!==auth.me?.id)event.stopImmediatePropagation();});
   this.addEventListener('close',()=>sockets.delete(this));
  }
 }
 window.WebSocket=SessionSocket;
 const stop=watch(()=>[auth.suspended,auth.sessionClosing,auth.sessionGeneration,auth.me?.id],()=>{for(const socket of sockets)socket.close();sockets.clear();},{flush:'sync'});
 return ()=>{stop();window.fetch=original;window.WebSocket=NativeSocket;for(const socket of sockets)socket.close();};
}
