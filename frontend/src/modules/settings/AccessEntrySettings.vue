<script setup lang="ts">
import {ref,computed,watch,onBeforeUnmount} from 'vue';
import {onBeforeRouteLeave,onBeforeRouteUpdate} from 'vue-router';
import {isAdmin} from '../home/auth';

import {getAccessEntries,checkAccessEntries,applyAccessEntries,type AccessSettings,type AccessSummary,type AccessCheck} from '../../api/accessEntries';
import HelpHint from './HelpHint.vue';
const props=defineProps<{navigationManaged?:boolean;extraDirty?:boolean;externalBusy?:boolean}>();
const emit=defineEmits<{discard:[]}>();
const summary=ref<AccessSummary|null>(null),draft=ref<AccessSettings|null>(null),checked=ref<AccessCheck|null>(null);
const busy=ref(false),error=ref(''),message=ref(''),pendingRead=ref<AccessSettings|null>(null);
let alive=true,generation=0;
const dirty=computed(()=>!!summary.value&&JSON.stringify(draft.value)!==JSON.stringify(summary.value.settings));
const editable=computed(()=>isAdmin.value&&!busy.value&&!pendingRead.value);

function entryText(value:string){const labels:Record<string,string>={'公网主站':'默认入口','内网主站':'其他入口','未配置内网主站地址':'未配置其他入口地址','公网与内网主站不能相同':'默认入口与其他入口不能相同'};return labels[value]??value;}
watch(draft,()=>{checked.value=null;message.value='';generation++;},{deep:true,flush:'sync'});
function problem(e:unknown){const v=e as {status?:number;detail?:unknown};return v.status===403?'当前会话无权修改入口；草稿已保留。':v.status===409?'设置或部署条件已改变，请回读后重新检查；草稿已保留。':typeof v.detail==='string'?v.detail:'操作未确认，请重试；输入已保留。';}
async function load(){if(!isAdmin.value)return;const seq=++generation,keepDraft=dirty.value;busy.value=true;error.value='';try{const value=await getAccessEntries();if(!alive||seq!==generation||!isAdmin.value)return;summary.value=value;if(keepDraft&&draft.value){draft.value={...draft.value,revision:value.settings.revision};message.value='已回读当前版本；你的草稿保留，请重新检查后应用。';}else draft.value={...value.settings};}catch(e){if(alive&&seq===generation)error.value=problem(e);}finally{if(alive)busy.value=false;}}
watch(isAdmin,allowed=>{generation++;if(allowed)void load();else{summary.value=null;checked.value=null;busy.value=false;}},{immediate:true});
async function check(){if(!draft.value||!editable.value)return;const value={...draft.value},seq=++generation;busy.value=true;error.value='';try{const result=await checkAccessEntries(value);if(alive&&seq===generation)checked.value=result;}catch(e){if(alive)error.value=problem(e);}finally{if(alive)busy.value=false;}}
async function readApplied(){if(!pendingRead.value)return;busy.value=true;try{const value=await getAccessEntries();if(!alive)return;const wanted=pendingRead.value;if(value.settings.enabled!==wanted.enabled||value.settings.public_origin!==wanted.public_origin||value.settings.private_origin!==wanted.private_origin||value.settings.revision!==wanted.revision+1)throw new Error('回读不一致');summary.value=value;draft.value={...value.settings};pendingRead.value=null;message.value='已应用并回读 · 版本 '+value.settings.revision+'。已打开的网站保持现场，新打开使用新设置。';error.value='';}catch(e){if(alive)error.value='提交结果尚未确认，请重试回读，不要重复应用。';}finally{if(alive)busy.value=false;}}
async function apply(){if(!draft.value||!checked.value?.can_apply||!editable.value)return;const wanted={...draft.value};busy.value=true;error.value='';try{await applyAccessEntries(wanted,checked.value.digest);if(!alive)return;pendingRead.value=wanted;await readApplied();}catch(e){if(!alive)return;const status=(e as {status?:number}).status;if(!status||status>=500){pendingRead.value=wanted;error.value='应用结果不确定；请回读确认，不会自动重复提交。';}else error.value=problem(e);}finally{if(alive)busy.value=false;}}
const leaving=ref<((allow:boolean)=>void)|null>(null);
function beforeLeave(){if(pendingRead.value||busy.value||props.externalBusy){error.value='请先完成当前操作与结果回读。';return false;}if(!dirty.value&&!props.extraDirty)return true;return new Promise<boolean>(resolve=>{leaving.value?.(false);leaving.value=resolve;});}
onBeforeRouteLeave(()=>props.navigationManaged?true:beforeLeave());
onBeforeRouteUpdate(to=>props.navigationManaged||to.query.section==='access'?true:beforeLeave());
defineExpose({beforeLeave});
function leave(allow:boolean){const resolve=leaving.value;leaving.value=null;if(allow){if(summary.value)draft.value={...summary.value.settings};emit('discard');}resolve?.(allow);}
onBeforeUnmount(()=>{alive=false;generation++;leave(false);});
</script>
<template><section class="access-settings" aria-label="主站入口地址">
<p v-if="!isAdmin" class="notice">请登录用户账号后修改主站入口。</p>
<p v-if="error" role="alert">{{error}} <button class="st-button" v-if="!pendingRead" :disabled="busy" @click="load">回读设置</button></p>
<form v-if="draft&&isAdmin" @submit.prevent="check"><fieldset :disabled="!editable">
 <div class="setting-row"><label for="public-origin">默认入口地址<HelpHint label="主站入口说明">完整 HTTPS 地址。当前兼容默认与另一条已部署入口；默认对应既有第一入口，不是公网用途标签。这里不修改 DNS、TLS 或登录回调，也不改变已安装 Agent 的汇报地址。</HelpHint></label><input id="public-origin" v-model="draft.public_origin" aria-label="默认入口地址" type="url" placeholder="https://stella.example.com" required/></div>
 <div class="setting-row"><label for="private-origin">其他入口地址<HelpHint label="其他入口说明">可留空；只填写已经部署的另一条完整 HTTPS 入口，不要求区分内外网。不会自动故障切换；网站默认跟随当前 Stella 入口。</HelpHint></label><input id="private-origin" :value="draft.private_origin||''" aria-label="其他入口地址" type="url" placeholder="未配置（可留空）" @input="draft.private_origin=($event.target as HTMLInputElement).value||null"/></div>
 <div v-if="dirty" class="actions"><button class="st-button" type="submit">{{busy?'检查中…':'检查设置'}}</button><button v-if="checked?.can_apply" class="st-button is-primary" type="button" @click="apply">应用设置</button></div>
</fieldset></form>
<details v-if="checked" class="check-summary" :open="!checked.can_apply"><summary>入口检查结果</summary><ul><li v-for="item in checked.checks" :key="item.name"><strong>{{entryText(item.name)}} · {{item.status==='configured'?'已配置':item.status==='unused'?'未配置':'待部署'}}</strong><span>{{entryText(item.reason)}}</span></li></ul><p>仅核对部署配置，不代表网络或原站登录已验证。</p></details>
<p v-if="message" role="status">{{message}}</p><button class="st-button" v-if="pendingRead" :disabled="busy" @click="readApplied">重试回读</button>
<Teleport to="body"><div v-if="leaving" class="access-mask"><section role="dialog" aria-modal="true" aria-label="保留入口地址草稿" class="access-dialog" @keydown.esc="leave(false)"><h3>主站地址尚未应用</h3><p>继续编辑会保留草稿；离开则放弃这次修改。</p><div class="actions"><button class="st-button" @click="leave(false)">继续编辑</button><button class="st-button" @click="leave(true)">放弃并离开</button></div></section></div></Teleport>
</section></template>
<style scoped>
.access-settings{color:var(--text-hi);min-width:0}fieldset{border:0;padding:0;margin:0;min-width:0}.setting-row{display:grid;grid-template-columns:minmax(140px,1fr) minmax(0,380px);gap:16px;align-items:center;padding:14px 0;border-bottom:1px solid var(--control-border)}.setting-row>label{display:flex;align-items:center;font-size:14px;gap:4px;min-width:0}.setting-row input{box-sizing:border-box;width:100%;min-width:0;min-height:38px;background:var(--bg-base);color:var(--text-hi);border:1px solid var(--control-border);border-radius:7px;padding:8px 10px;font:inherit;font-size:14px}p,small{color:var(--text-lo);line-height:1.7;font-size:14px}p{margin:10px 0}summary{font-size:14px;cursor:pointer;min-height:38px;align-content:center}.actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:10px;margin:14px 0}.check-summary li{font-size:14px;margin:12px 0}.check-summary span{display:block;color:var(--text-lo);line-height:1.7}.website-row{padding:12px 0;border-bottom:1px solid var(--control-border);overflow-wrap:anywhere}.website-row small{display:block}.deployment-details{margin:12px 0}a{color:var(--text-hi);overflow-wrap:anywhere}.access-mask{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;background:#0009;padding:16px}.access-dialog{box-sizing:border-box;width:min(440px,100%);background:var(--bg-panel);padding:24px;border:1px solid var(--control-border);border-radius:12px}.access-dialog h3{font-size:18px;margin:0}.access-settings :deep(.help-hint){border:0;padding:0;background:transparent}input:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}@media(max-width:600px){.setting-row{grid-template-columns:minmax(0,1fr);gap:6px;padding:10px 0}.setting-row input,summary{min-height:44px}}
</style>
