<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount,useId} from 'vue';
import {notificationMotion,type NotificationOrigin} from './notificationMotion';
const props=defineProps<{title:string;origin?:NotificationOrigin}>();
const emit=defineEmits<{close:[]}>();
const root=ref<HTMLElement>(),mask=ref<HTMLElement>(),content=ref<HTMLElement>(),titleId=useId();
let previous:HTMLElement|null=null, motion:ReturnType<typeof notificationMotion>|undefined;
let closing=false;
onMounted(()=>{
 previous=document.activeElement as HTMLElement;root.value?.focus();
 if(props.origin&&root.value&&mask.value&&content.value){motion=notificationMotion(root.value,mask.value,content.value,props.origin);motion.open();}
 window.addEventListener('resize',resize);
});
function resize(){motion?.settle();}
onBeforeUnmount(()=>{window.removeEventListener('resize',resize);motion?.dispose();if(previous?.isConnected&&!previous.closest('[inert]'))previous.focus();});
async function close(){if(closing)return;closing=true;if(!motion||await motion.close())emit('close');}
function keys(e:KeyboardEvent){
 if(e.isComposing)return;
 if(e.key==='Escape'){e.preventDefault();e.stopPropagation();void close();}
 if(e.key!=='Tab')return;
 const controls=[...root.value?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),[tabindex="0"]')||[]];
 const first=controls[0],last=controls.at(-1);
 if(e.shiftKey&&(document.activeElement===first||document.activeElement===root.value)){e.preventDefault();last?.focus();}
 else if(!e.shiftKey&&(document.activeElement===last||document.activeElement===root.value)){e.preventDefault();first?.focus();}
}
</script>
<template><Teleport to="body"><div ref="mask" class="detail-mask" @click.self="close"><section ref="root" class="detail-dialog" :class="{'notification-surface':origin}" role="dialog" aria-modal="true" :aria-labelledby="titleId" tabindex="-1" @keydown="keys"><div ref="content"><header><h2 :id="titleId">{{title}}</h2><button aria-label="关闭详情" @click="close">关闭</button></header><slot /></div></section></div></Teleport></template>
<style scoped>
.detail-mask{position:fixed;inset:0;z-index:500;background:#0d101bb8;display:grid;place-items:center;padding:18px;color:var(--text-hi,#ede8e1)}.detail-dialog{box-sizing:border-box;width:min(700px,100%);max-height:calc(100dvh - 36px);overflow:auto;overflow-wrap:anywhere;background:var(--bg-panel,#252321);border:1px solid #ffffff25;border-radius:14px;padding:22px;box-shadow:0 22px 80px #0006;font-size:14px;line-height:1.7}.detail-dialog:focus{outline:none}.notification-surface{width:min(620px,100%);transform-origin:top left;will-change:transform;overflow:hidden}.notification-surface>div{max-height:calc(100dvh - 82px);overflow:auto}header{display:flex;justify-content:space-between;gap:16px;align-items:start;margin-bottom:18px}h2{font-size:21px;font-weight:550;margin:0}.notification-surface header{align-items:center;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid #ffffff14}.notification-surface h2{font-size:14px;font-weight:500;color:var(--text-lo,#bdb6ac)}button{font:inherit;min-height:40px;padding:6px 12px;border:1px solid #ffffff30;border-radius:7px;color:inherit;background:#ffffff08;cursor:pointer}button:focus-visible{outline:2px solid #9bcbb6;outline-offset:2px}@media(max-width:600px){.detail-mask{padding:10px}.detail-dialog{padding:16px;max-height:calc(100dvh - 20px)}.notification-surface>div{max-height:calc(100dvh - 54px)}button{min-height:44px}}
</style>
