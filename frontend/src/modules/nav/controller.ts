import {ref} from 'vue';
import {copy,defaultPreferences,type Data,type Snapshot} from './types';
export function defaults():Data{return {groups:[],preferences:defaultPreferences()};}
type Transport=<T>(path:string,options?:RequestInit,admitted?:()=>boolean)=>Promise<T>;
export function createNavController(transport:Transport,owner:()=>string){
 const state=ref<Snapshot|null>(null),loading=ref(false),saving=ref(false),error=ref(''),uncertain=ref(false),conflict=ref(false);
 let generation=0,controller:AbortController|undefined;
 const message=(e:unknown)=>{
  const d=(e as {detail?:unknown})?.detail;
  return typeof d==='string'?d:'保存未确认，请重新读取；草稿已保留。';
 };
 function cancel(){generation++;controller?.abort();loading.value=false;saving.value=false;}
 function reset(){cancel();state.value=null;error.value='';uncertain.value=false;conflict.value=false;}
 async function load(){
  if(saving.value)return false;
  const current=++generation,identity=owner();controller?.abort();const request=new AbortController();controller=request;
  const valid=()=>generation===current&&owner()===identity;
  loading.value=true;error.value='';
  const timer=setTimeout(()=>request.abort(),15000);
  try{const r=await transport<Snapshot>('/nav-data',{signal:request.signal},valid);if(!valid())return false;state.value={...r,data:{...r.data,preferences:{...defaultPreferences(),...r.data.preferences}}};uncertain.value=false;return true;}
  catch(e){if(valid())error.value='导航读取失败，请重试。';return false;}
  finally{clearTimeout(timer);if(valid())loading.value=false;}
 }
 async function save(data:Data,revision:number,pack?:{source:string;digest:string;confirmed:boolean;module_bindings?:Record<string,string|null>}){
  if(saving.value||loading.value||uncertain.value)return false;
  const current=++generation,identity=owner();controller?.abort();const request=new AbortController();controller=request;
  const valid=()=>generation===current&&owner()===identity;
  saving.value=true;error.value='';conflict.value=false;
  let acknowledgedWrite=false;
  const timer=setTimeout(()=>request.abort(),15000);
  try{
   const acknowledged=await transport<Snapshot>(pack?'/nav-package-import':'/nav-data',{method:pack?'POST':'PUT',signal:request.signal,body:JSON.stringify({...pack,...(!pack?{data:copy(data)}:{}),revision,mutation_id:crypto.randomUUID()})},valid);
   acknowledgedWrite=true;
   if(!valid())return false;
   const actual=await transport<Snapshot>('/nav-data',{signal:request.signal},valid);
   if(!valid())return false;
   state.value=actual;
   if(JSON.stringify(actual.data)!==JSON.stringify(acknowledged.data)){
    // Server fills defaults; compare by value rather than key insertion order.
    const canonical=(v:any):any=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;
    if(JSON.stringify(canonical(actual.data))!==JSON.stringify(canonical(acknowledged.data))){conflict.value=true;error.value='服务端已有更新，草稿保留，请比较后重新应用。';return false;}
   }
   return true;
  }catch(e){if(valid()){
   const status=(e as {status?:number})?.status;
   // Only a definite pre-ACK 4xx rejection proves no commit. A response can
   // fail after the durable write; failed readback must stay GET-only too.
   const rejected=!acknowledgedWrite&&typeof status==='number'&&status>=400&&status<500&&status!==408;
   conflict.value=rejected&&status===409;uncertain.value=!rejected;
   error.value=uncertain.value?'保存结果未知，请先读取服务端版本；草稿已保留。':message(e);
  }return false;}
  finally{clearTimeout(timer);if(valid())saving.value=false;}
 }
 return {state,loading,saving,error,uncertain,conflict,load,save,cancel,reset};
}
