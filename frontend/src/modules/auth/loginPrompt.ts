import {reactive} from 'vue';
/** A login request is UI state, never a route or administrator elevation. */
export const loginPrompt=reactive({requested:false});
let returnFocus:HTMLElement|null=null;
let loginTarget:string|null=null;
/** Only resume our native authorization endpoint, never an arbitrary redirect. */
export function oidcLoginTarget(value:unknown):string|null {
 if(typeof value!=='string'||/[\\\x00-\x20\x7f]/.test(value)||value.startsWith('//'))return null;
 try{
  const url=new URL(value,location.origin);
  if(url.origin!==location.origin||url.username||url.password||url.pathname!=='/oauth/authorize'||url.hash)return null;
  // Reject normalized/encoded paths: only the literal native endpoint is valid.
  if(value!==url.href&&value!==url.pathname+url.search)return null;
  return url.pathname+url.search;
 }catch{return null;}
}
export function consumeLoginTarget(){const target=loginTarget;loginTarget=null;return target;}
export function openLogin(next?:unknown){returnFocus=document.activeElement as HTMLElement;loginTarget=oidcLoginTarget(next);loginPrompt.requested=true;}
export function consumeLoginFocus(){const element=returnFocus;returnFocus=null;return element;}
export function safeLoginTarget(value:unknown):string {
 if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.includes('\\')||/^\/login(?:[/?#]|$)/.test(value))return '/';
 return value;
}
