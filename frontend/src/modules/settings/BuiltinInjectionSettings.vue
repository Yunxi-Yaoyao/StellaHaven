<script setup lang="ts">
import {ref,watch,onBeforeUnmount} from 'vue';
import {getBuiltin,validateBuiltin,applyBuiltin,rollbackBuiltin,type BuiltinSite,type BuiltinState} from '../../api/builtinInjection';
import type {Injection} from '../../stores/navigation';
import Dropdown from '../../shell/Dropdown.vue';
const siteOptions=[{value:'drive',label:'网盘 OpenList'},{value:'gallery',label:'图库 Immich'}];
const timingOptions=[{value:'dom_ready',label:'DOM ready'},{value:'document_start',label:'document start（DOM 尚未就绪）'}];
const props=defineProps<{site?:BuiltinSite}>();
const site=ref<BuiltinSite>(props.site||'drive'),state=ref<BuiltinState|null>(null),busy=ref(false),message=ref(''),validated=ref(false),pending=ref<string|null>(null);
const fresh=():Injection=>({enabled:false,css:'',js:'',timing:'dom_ready',csp_policy:'reject'});
const draft=ref<Injection>(fresh());
let controller:AbortController|null=null,generation=0;
watch(draft,()=>{validated.value=false;},{deep:true});
function editable(value:Injection):Injection{return {enabled:value.enabled,css:value.css,js:value.js,timing:value.timing,csp_policy:'reject'};}
async function read(){
 const ticket=++generation;controller?.abort();controller=new AbortController();busy.value=true;message.value='';
 try{const current=await getBuiltin(site.value,controller.signal);if(ticket!==generation)return;
  if(pending.value&&pending.value!=='unknown'&&current.active.version!==pending.value)throw new Error('readback mismatch');
  const reconciled=!!pending.value;pending.value=null;state.value=current;draft.value=editable(current.draft||current.active);validated.value=false;
  if(reconciled)message.value='活动配置已回读；已打开页面请手动重载。';
 }catch(e){if(ticket!==generation)return;message.value=pending.value?'应用结果尚未确认；请刷新回读，暂不重复发布。':'无法读取内置注入；请先在集中安全设置完成管理解锁。';}
 finally{if(ticket===generation)busy.value=false;}
}
watch(()=>props.site,value=>{if(value&&value!==site.value&&!busy.value&&!pending.value)site.value=value;});
watch(site,()=>{pending.value=null;state.value=null;draft.value=fresh();validated.value=false;void read();},{immediate:true});
onBeforeUnmount(()=>{generation++;controller?.abort();});
async function validate(){if(busy.value||pending.value)return;busy.value=true;message.value='';try{const result=await validateBuiltin(site.value,draft.value);validated.value=result.valid;message.value=result.valid?'草稿校验通过，尚未应用。':result.errors.join('；');}catch{message.value='草稿未确认；请检查管理解锁与 JavaScript 语法。';}finally{busy.value=false;}}
async function publish(rollback=false){if(busy.value||pending.value)return;busy.value=true;message.value='';try{
 const result=rollback?await rollbackBuiltin(site.value):await applyBuiltin(site.value);pending.value=result.active.version;
 const current=await getBuiltin(site.value);if(current.active.version!==pending.value)throw new Error('readback mismatch');
 state.value=current;pending.value=null;validated.value=false;message.value='活动配置已回读；已打开页面请手动重载。';
 }catch(e){message.value=pending.value?'应用结果尚未确认；请刷新回读，暂不重复发布。':'请求未确认；请刷新活动版本再操作，不要重复发布。';validated.value=false;
 // Unknown network outcome must also prohibit replay until a read reconciles it.
 if(!pending.value&&(e as {status?:number})?.status===undefined)pending.value='unknown';
 }finally{busy.value=false;}}
function copyPreset(){if(!state.value?.preset)return;draft.value={...draft.value,css:state.value.preset.css};}
</script>
<template><section class="builtin-settings"><header><h3>网盘 / 图库注入</h3><span v-if="props.site">{{site === 'drive' ? 'OpenList' : 'Immich'}}</span><fieldset v-else class="inline-control" :disabled="busy||!!pending"><Dropdown :model-value="site" :options="siteOptions" @update:model-value="value => site = value as BuiltinSite" /></fieldset><button :disabled="busy" @click="read">刷新回读</button></header>
<p>设置保存在 PostgreSQL。自定义 CSS / JavaScript 仅在主动应用后于目标网站执行。图库匿名访客仅加载只读基础预设；自定义代码需有效 Stella owner 登录态，仍能在该浏览器查看，请勿填写密码、Token 或其他秘密。</p>
<p>关闭自定义仅关闭你的附加代码；网盘原主题、目录缓存与布局修复、图库原 logo 规则仍保留。草稿不会执行，已打开页面需手动重载。</p>
<p v-if="site==='gallery'">保留原 Immich 域名、OIDC 回调与移动 App API。目标站响应需接入受控 head loader；保存设置不会自行部署 nginx。原 CSP 保持不变。</p>
<template v-if="state"><p class="version">来源：{{state.source==='postgres'?'PostgreSQL':'内置默认'}} · 活动版本：{{state.active.version}}（{{state.active.status}}） · 上一版本：{{state.previous?.version||'无'}}（{{state.previous?.status||'无'}}）</p>
<fieldset :disabled="busy||!!pending"><label><input v-model="draft.enabled" type="checkbox"/>启用自定义代码</label><label>执行时机<Dropdown :model-value="draft.timing" :options="timingOptions" @update:model-value="value => draft.timing = value as Injection['timing']" /></label>
<label class="code">自定义 CSS<textarea v-model="draft.css" aria-label="自定义 CSS" spellcheck="false" /></label><label class="code">自定义 JavaScript<textarea v-model="draft.js" aria-label="自定义 JavaScript" spellcheck="false" /></label>
<details><summary>保留的原主题 / 兼容修复预设</summary><p>默认基础继续运行，可复制后增补覆盖；关闭自定义不会静默删除原修复。</p><label class="code">预设 CSS<textarea :value="state.preset?.css" readonly /></label><label class="code">预设 JavaScript<textarea :value="state.preset?.js" readonly /></label><button @click="copyPreset">复制主题 CSS 到可编辑草稿</button></details>
<div class="actions"><button @click="validate">校验并保存草稿</button><button :disabled="!validated" @click="publish()">应用版本</button><button :disabled="!state.previous" @click="publish(true)">回退上一版本</button></div></fieldset></template><p v-else>尚未读取活动配置。</p><p v-if="message" role="status">{{message}}</p></section></template>
<style scoped>.builtin-settings{margin-top:18px;padding:18px;border:1px solid #ffffff16;border-radius:12px;background:var(--bg-panel)}header{display:flex;align-items:center;gap:12px;flex-wrap:wrap}h3{font-size:14px;flex:1;margin:0}p{font-size:12px;line-height:1.7;color:var(--text-lo)}.version{overflow-wrap:anywhere}fieldset{border:0;margin:0;padding:0;min-width:0}label{display:flex;gap:8px;align-items:center;margin:12px 0;font-size:12px}button,select{font:inherit;background:var(--bg-raised);color:var(--text-hi);border:1px solid #ffffff20;border-radius:7px;padding:7px 10px;white-space:nowrap}button{cursor:pointer}button:disabled{opacity:.4;cursor:default}.code{display:block}textarea{display:block;box-sizing:border-box;width:100%;height:130px;background:var(--bg-base);color:var(--text-hi);border:1px solid #ffffff20;border-radius:8px;padding:10px;font-family:monospace;margin-top:8px}.actions{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}summary{font-size:12px;cursor:pointer;color:var(--accent)}</style>
