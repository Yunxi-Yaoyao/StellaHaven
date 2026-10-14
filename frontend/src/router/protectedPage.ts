import {defineComponent,defineAsyncComponent,h} from 'vue';
import type {Component} from 'vue';
import {loggedIn,auth} from '../modules/home/auth';
/** The route resolves without importing or mounting a private business page for guests. */
export function protectedPage(name:string,loader:()=>Promise<{default:Component}>){
 const Page=defineAsyncComponent(loader);
 return defineComponent({name,setup(){
  let mounted=false;
  return ()=>{
   if(loggedIn.value)mounted=true;
   if(loggedIn.value||(mounted&&(auth.suspended||auth.sessionClosing)))return h(Page);
   return h('div',{class:'protected-placeholder',role:'status'},'登录后继续');
  };
 }});
}
