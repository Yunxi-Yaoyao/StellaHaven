import {onBeforeUnmount,watch,type Ref} from 'vue';
import type {Application} from 'pixi.js';

export function syncOwnedLive2dPlayback(app:Application,model:{autoUpdate:boolean},active:boolean) {
  model.autoUpdate=active;
  app.ticker.remove(app.render,app);
  if(active)app.ticker.add(app.render,app,-25); // PIXI.UPDATE_PRIORITY.LOW
}

/** Business is never a waiter on decoration. One owner schedules one idle start. */
export function useLive2dAdmission(ready:Ref<boolean>,active:Ref<boolean>,start:()=>void) {
  let started=false,cancel:(()=>void)|undefined;
  const stop=watch([ready,active],([business,visible])=>{
    cancel?.();cancel=undefined;
    if(started||!business||!visible)return;
    const run=()=>{cancel=undefined;if(!started&&ready.value&&active.value){started=true;start();}};
    if(typeof window.requestIdleCallback==='function'){
      const id=window.requestIdleCallback(run,{timeout:1000});
      cancel=()=>window.cancelIdleCallback(id);
    }else{
      const id=window.setTimeout(run,0);cancel=()=>window.clearTimeout(id);
    }
  },{immediate:true});
  onBeforeUnmount(()=>{stop();cancel?.();});
}
