import {computed,ref,watch,onBeforeUnmount} from 'vue';
import {auth} from '../modules/home/auth';
import {navigation,navigationRows,saveNavigation,loadNavigation,type NavRow} from '../stores/navigation';

const copy=(rows:NavRow[])=>rows.map(row=>({...row}));
const signature=(rows:NavRow[])=>JSON.stringify(rows.map(({id,label,icon,visible})=>({id,label,icon,visible})));
/** One bounded latest-intent slot; no write is replayed after an uncertain result. */
export function createNavigationOrder(save:(rows:NavRow[],reset?:boolean)=>Promise<void>,read:()=>NavRow[],reload:()=>Promise<boolean>){
 const rows=ref<NavRow[]>(copy(read())),saving=ref(false),error=ref(''),blocked=ref(false),dragging=ref<string|null>(null),checking=ref(false),hold=ref(false);
 let baseline=signature(rows.value),epoch=0,version=0,flight:Promise<boolean>|null=null,dragStart:NavRow[]=[];
 const dirty=computed(()=>signature(rows.value)!==baseline);
 function accept(value:NavRow[]){if(!dirty.value&&!saving.value&&!dragging.value&&!hold.value) {rows.value=copy(value);baseline=signature(value);}}
 function reset(){epoch++;version++;flight=null;saving.value=false;checking.value=false;hold.value=false;error.value='';blocked.value=false;dragging.value=null;rows.value=copy(read());baseline=signature(rows.value);}
 async function saveNow(resetDefaults=false):Promise<boolean>{
  if(blocked.value)return false;
  version++;
  if(flight)return flight;
  if(!resetDefaults&&!dirty.value)return true;
  const own=epoch; saving.value=true;
  const task=(async()=>{let resetFlag=resetDefaults;
   try {do {
    const snapshot=copy(rows.value),v=version;await save(snapshot,resetFlag);
    if(own!==epoch)return false;
    const canonical=copy(read());
    if(!resetFlag&&signature(canonical)!==signature(snapshot))throw new Error('导航回读不一致');
    baseline=signature(canonical);
    if(v===version&&!dragging.value)rows.value=canonical;
    resetFlag=false;
   }while(dirty.value&&!dragging.value);
   error.value='';return true;
   }catch(e){if(own===epoch){const status=(e as {status?:number})?.status;blocked.value=!(status&&status>=400&&status<500&&![408,409].includes(status));error.value='导航未保存，保留修改，请重试';}return false;}
   finally{if(own===epoch){saving.value=false;flight=null;}}
  })();flight=task;return task;
 }
 function move(id:string,delta:number){const i=rows.value.findIndex(x=>x.id===id),j=i+delta;if(i<0||j<0||j>=rows.value.length)return;const next=copy(rows.value),row=next.splice(i,1)[0]!;next.splice(j,0,row);rows.value=next;version++;void saveNow();}
 async function confirm(){if(checking.value||saving.value)return;const own=epoch;checking.value=true;try{if(await reload()&&own===epoch){baseline=signature(read());blocked.value=false;if(!dirty.value){rows.value=copy(read());error.value='';}}}finally{if(own===epoch)checking.value=false;}}
 return {rows,saving,error,blocked,checking,hold,dirty,dragging,accept,reset,save:saveNow,move,confirm,
  begin(id:string){dragStart=copy(rows.value);dragging.value=id;version++;},
  preview(id:string){const from=rows.value.findIndex(x=>x.id===dragging.value),to=rows.value.findIndex(x=>x.id===id);if(from<0||to<0||from===to)return;const next=copy(rows.value),row=next.splice(from,1)[0]!;next.splice(to,0,row);rows.value=next;version++;},
  drop(){dragging.value=null;if(signature(dragStart)!==signature(rows.value))void saveNow();},
  cancel(){if(dragging.value){rows.value=copy(dragStart);version++;dragging.value=null;}},
  discard(){if(!saving.value&&!blocked.value){rows.value=copy(read());baseline=signature(rows.value);error.value='';version++;}},
 };
}
export function useNavigationOrderPointer(enabled:()=>boolean=()=>true){
 let cleanup=()=>{};
 onBeforeUnmount(()=>{cleanup();navigationOrder.cancel();});
 function down(event:PointerEvent,id:string){
  if(!enabled()||event.button!==0||!event.isPrimary)return;
  event.preventDefault();event.stopPropagation();cleanup();
  const handle=event.currentTarget as HTMLElement,list=handle.closest('[data-order-list]');
  if(!list)return;
  const pointer=event.pointerId;navigationOrder.begin(id);
  const move=(e:PointerEvent)=>{if(e.pointerId!==pointer)return;e.preventDefault();
   const elements=Array.from(list.querySelectorAll<HTMLElement>('[data-row-id]'));
   const target=elements.find(el=>{const box=el.getBoundingClientRect();return e.clientY>=box.top&&e.clientY<=box.bottom;});
   if(target?.dataset.rowId)navigationOrder.preview(target.dataset.rowId);
   const box=list.getBoundingClientRect();if(e.clientY<box.top+25)list.scrollTop-=16;else if(e.clientY>box.bottom-25)list.scrollTop+=16;
  };
  const end=(e:PointerEvent)=>{if(e.pointerId!==pointer)return;cleanup();navigationOrder.drop();};
  const cancel=()=>{cleanup();navigationOrder.cancel();};
  const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();cancel();}};
  cleanup=()=>{document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',end);document.removeEventListener('pointercancel',cancel);document.removeEventListener('keydown',key,true);cleanup=()=>{};};
  document.addEventListener('pointermove',move,{passive:false});document.addEventListener('pointerup',end);document.addEventListener('pointercancel',cancel);document.addEventListener('keydown',key,true);
 }
 function key(event:KeyboardEvent,id:string){if(!enabled())return;if(event.key==='ArrowUp'||event.key==='ArrowDown'){event.preventDefault();event.stopPropagation();navigationOrder.move(id,event.key==='ArrowUp'?-1:1);}}
 return {down,key};
}
export const navigationOrder=createNavigationOrder(saveNavigation,()=>navigationRows.value,()=>loadNavigation({force:true}));
watch(()=>[auth.me?.id,auth.sessionClosing,auth.checked,auth.sessionGeneration,auth.requestEpoch],()=>navigationOrder.reset(),{flush:'sync'});
// A rejected write invalidates the remote cache, not the same owner's local
// draft or its error. Identity/epoch changes above still destroy both immediately.
watch([navigationRows,()=>navigation.loaded],([rows,loaded])=>{if(loaded)navigationOrder.accept(rows);},{flush:'sync'});
