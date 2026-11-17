<script setup lang="ts">
import {nextTick,onBeforeUnmount,onMounted,ref,useId,watch} from 'vue';
const props=defineProps<{state:'unavailable'|'pending'|'verified'|'loading'|'error'|'unknown';label:string;disabled?:boolean}>();
const emit=defineEmits<{open:[]}>();
const id=`email-state-${useId()}`,open=ref(false),trigger=ref<HTMLButtonElement>(),panel=ref<HTMLElement>();
const position=ref({left:'8px',top:'8px'});
let closeTimer:ReturnType<typeof setTimeout>|undefined;
let pointerInside=false,pinned=false,restoringFocus=false;
function contains(target:EventTarget|null){return target instanceof Node&&(!!trigger.value?.contains(target)||!!panel.value?.contains(target));}
function cancelClose(){clearTimeout(closeTimer);closeTimer=undefined;}
async function show(){
 if(props.disabled)return;
 cancelClose();
 if(open.value)return;
 open.value=true;emit('open');await nextTick();place();
}
function enter(e:MouseEvent & {sourceCapabilities?:{firesTouchEvents:boolean}}){if(e.sourceCapabilities?.firesTouchEvents)return;pointerInside=true;void show();}
function leave(){pointerInside=false;scheduleClose();}
function scheduleClose(){
 cancelClose();
 // A short grace period joins the trigger and teleported panel across their 6px gap.
 closeTimer=setTimeout(()=>{if(!pointerInside&&!pinned&&!contains(document.activeElement))close();},160);
}
function close(restore=false){
 cancelClose();open.value=false;pinned=false;pointerInside=false;
 if(restore){restoringFocus=true;trigger.value?.focus();restoringFocus=false;}
}
function focus(){if(!restoringFocus)void show();}
function click(){if(pinned){close();return;}pinned=true;void show();}
function outside(e:Event){if(open.value&&!contains(e.target))close();}
function focusChanged(e:FocusEvent){if(!open.value)return;if(contains(e.target))cancelClose();else close();}
function items(){return [...panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled)')??[]];}
function key(e:KeyboardEvent){
 if(!open.value)return;
 if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(contains(document.activeElement));return;}
 if(e.key!=='Tab'||!contains(e.target))return;
 const controls=items(),first=controls[0],last=controls.at(-1);
 // Teleport changes DOM order. Bridge only the two edges, never wrap or trap Tab.
 if(e.target===trigger.value){if(e.shiftKey){close();}else if(first){e.preventDefault();first.focus();}}
 else if(e.shiftKey&&e.target===first){e.preventDefault();trigger.value?.focus();}
 else if(!e.shiftKey&&e.target===last){close(true);/* native Tab continues after the trigger */}
}
function place(){
 if(!trigger.value||!panel.value)return;
 const t=trigger.value.getBoundingClientRect(),p=panel.value.getBoundingClientRect();
 // DOMRect is already scaled by CSS UI zoom; fixed-position CSS coordinates are not.
 const zoom=p.width/panel.value.offsetWidth||1;
 panel.value.style.maxWidth=`${(innerWidth-16)/zoom}px`;
 panel.value.style.maxHeight=`${(innerHeight-16)/zoom}px`;
 const bounded=panel.value.getBoundingClientRect();
 position.value={left:`${Math.max(8,Math.min(t.left,innerWidth-bounded.width-8))/zoom}px`,top:`${Math.max(8,Math.min(t.bottom+6,innerHeight-bounded.height-8))/zoom}px`};
}
let observer:ResizeObserver|undefined;
watch(panel,value=>{observer?.disconnect();if(value&&typeof ResizeObserver!=='undefined'){observer=new ResizeObserver(place);observer.observe(value);}},{flush:'post'});
watch(()=>props.state,async()=>{await nextTick();place();});
watch(()=>props.disabled,value=>{if(value)close();});
onMounted(()=>{document.addEventListener('pointerdown',outside);document.addEventListener('focusin',focusChanged);document.addEventListener('keydown',key);window.addEventListener('resize',place);window.addEventListener('scroll',place,true);});
onBeforeUnmount(()=>{cancelClose();observer?.disconnect();document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',focusChanged);document.removeEventListener('keydown',key);window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);});
defineExpose({close});
</script>
<template>
 <div class="email-state-control">
  <button ref="trigger" type="button" class="email-state-trigger" :data-state="state" :disabled="disabled" :aria-label="label" aria-haspopup="dialog" :aria-expanded="open" :aria-controls="open?id:undefined" @mouseenter="enter" @mouseleave="leave" @focus="focus" @click="click">
   <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
    <template v-if="state==='verified'"><path d="m8 12 3 3 5-6"/><circle cx="12" cy="12" r="9"/></template>
    <template v-else-if="state==='unavailable'"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7M3 3l18 18"/></template>
    <template v-else-if="state==='pending'"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/></template>
    <template v-else-if="state==='loading'"><circle cx="12" cy="12" r="9" stroke-dasharray="4 3"/><path d="M12 6v6l3 2"/></template>
    <template v-else><circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 4h.01"/></template>
   </svg>
  </button>
  <Teleport to="body"><div v-if="open" :id="id" ref="panel" role="dialog" :aria-label="label" class="email-state-popover" :style="position" @mouseenter="enter" @mouseleave="leave"><header><strong>{{label}}</strong><button type="button" aria-label="关闭邮箱状态" @click="close(true)">×</button></header><slot /></div></Teleport>
 </div>
</template>
<style scoped>
.email-state-control{width:36px;min-width:36px;height:38px;display:grid;place-items:center;}
.email-state-trigger{display:grid;place-items:center;width:36px;height:36px;padding:0;border:0;border-radius:6px;background:transparent;color:var(--text-lo);cursor:pointer;}
.email-state-trigger svg{width:18px;height:18px;stroke-linecap:round;stroke-linejoin:round;}
.email-state-trigger[data-state=unavailable],.email-state-trigger[data-state=pending]{color:var(--warning);}
.email-state-trigger[data-state=verified]{color:var(--success);}
.email-state-trigger[data-state=error]{color:var(--danger);}
.email-state-trigger:hover{background:var(--control-hover);}
.email-state-trigger:focus-visible,.email-state-popover :focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
.email-state-popover{position:fixed;z-index:310;box-sizing:border-box;width:320px;max-width:calc(100vw - 16px);max-height:calc(100dvh - 16px);overflow:auto;padding:12px 14px;border:1px solid var(--control-border);border-radius:8px;background:var(--bg-raised);color:var(--text-hi);box-shadow:0 8px 30px #0006;font-size:14px;line-height:1.6;font-family:inherit;overflow-wrap:anywhere;}
.email-state-popover header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px;}
.email-state-popover header button{width:32px;height:32px;flex:none;border:0;border-radius:4px;background:transparent;color:var(--text-lo);font-size:20px;cursor:pointer;}
@media(max-width:768px){.email-state-control{height:44px;width:44px;min-width:44px;}.email-state-trigger,.email-state-popover header button{height:44px;width:44px;}}
</style>
