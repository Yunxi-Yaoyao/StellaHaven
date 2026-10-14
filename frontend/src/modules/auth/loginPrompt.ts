import {reactive} from 'vue';
/** A login request is UI state, never a route or administrator elevation. */
export const loginPrompt=reactive({requested:false});
let returnFocus:HTMLElement|null=null;
export function openLogin(){returnFocus=document.activeElement as HTMLElement;loginPrompt.requested=true;}
export function consumeLoginFocus(){const element=returnFocus;returnFocus=null;return element;}
export function safeLoginTarget(value:unknown):string {
 if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.includes('\\')||/^\/login(?:[/?#]|$)/.test(value))return '/';
 return value;
}
