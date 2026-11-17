<script setup lang="ts">
import {computed,ref,useId} from 'vue';
interface Row {id:string;device:string;ip:string;remember:boolean;current:boolean;created_at:string;last_seen:string;expires_at:string|null;browser_name?:string|null;os_name?:string|null;login_origin?:string|null;ip_location?:string|null;state?:'expired'|'revoked';}
const props=defineProps<{row:Row;locationBusy?:boolean;locationError?:string;revokeBusy?:boolean}>();
const emit=defineEmits<{location:[];revoke:[]}>();
const expanded=ref(false),detailsId=`session-details-${useId()}`;
const internal=computed(()=>{const ip=props.row.ip.toLowerCase().replace(/^\[|\]$/g,'');if(ip==='::1'||ip==='localhost'||ip.startsWith('fc')||ip.startsWith('fd')||/^fe[89ab]/.test(ip))return true;const a=ip.split('.').map(Number);return a.length===4&&(a[0]===10||a[0]===127||a[0]===192&&a[1]===168||a[0]===172&&a[1]!>=16&&a[1]!<=31||a[0]===169&&a[1]===254);});
function time(iso:string|null){if(!iso)return '未知';const date=new Date(iso);return Number.isNaN(date.valueOf())?'未知':date.toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});}
</script>
<template>
 <article class="sess-row" :class="{'is-current':row.current}" :data-session-id="row.id">
  <div class="session-summary">
   <div class="session-device"><span class="sess-device" :title="`${row.browser_name || row.device || '浏览器未知'} · ${row.os_name || '系统未知'}`"><span class="session-browser">{{row.browser_name || row.device || '浏览器未知'}}</span><span class="session-os"> · {{row.os_name || '系统未知'}}</span></span><span class="session-state" :class="{'is-current':row.current,'is-inactive':!!row.state}">{{row.current?'当前会话':row.state==='revoked'?'已下线':row.state==='expired'?'已过期':'有效会话'}}</span></div>
   <div class="session-actions"><button v-if="!row.current&&!row.state" type="button" class="st-button is-danger" :disabled="revokeBusy" @click="emit('revoke')">下线</button><button type="button" class="st-button is-ghost session-expand" :aria-expanded="expanded" :aria-controls="detailsId" :aria-label="`${expanded?'收起':'展开'}${row.current?'当前会话':row.browser_name || '会话'}详情`" @click="expanded=!expanded">{{expanded?'收起':'详情'}}<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg></button></div>
  </div>
  <div class="session-network"><span class="session-ip">{{row.ip || 'IP 未知'}}</span><span>{{internal?'内网':row.ip_location || '地点未知'}}</span><button v-if="!internal && !row.ip_location && row.ip" class="st-button is-ghost session-location" type="button" :disabled="locationBusy" @click="emit('location')">{{locationBusy?'查询中…':'查询归属地'}}</button><span class="session-activity">最近活动 <time>{{time(row.last_seen)}}</time></span><p v-if="locationError" role="status" class="session-error">{{locationError}}</p></div>
  <div :id="detailsId" class="session-details" :hidden="!expanded">
   <dl class="session-entry"><dt>登录入口</dt><dd class="session-origin">{{row.login_origin || '入口未知'}}</dd><dt>设备信息</dt><dd>{{row.device || '浏览器未知'}}</dd></dl>
   <dl class="session-times"><dt>登录</dt><dd>{{time(row.created_at)}}</dd><dt>到期</dt><dd>{{time(row.expires_at)}}</dd><dt>记住我</dt><dd>{{row.remember?'是':'否'}}</dd></dl>
  </div>
 </article>
</template>
<style scoped>
.sess-row{display:grid;gap:4px;padding:10px 0;border-bottom:1px solid var(--control-border);font-size:14px;line-height:1.6;color:var(--text-hi);min-width:0;}
.sess-row.is-current{padding:10px 12px;border:1px solid var(--control-border);border-inline-start:3px solid var(--accent);border-radius:7px;background:var(--control-bg);margin-bottom:12px;}
.session-summary{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0;}
.session-device{display:flex;align-items:center;gap:4px 10px;min-width:0;}.sess-device{display:inline-flex;align-items:baseline;flex:0 1 auto;font-size:14px;font-weight:500;min-width:0;white-space:nowrap;}.session-browser{overflow:hidden;text-overflow:ellipsis;min-width:0;}.session-os{flex:none;white-space:pre;}.session-state{font-size:13px;color:var(--text-lo);flex:none;}.session-state.is-current{color:var(--accent);font-weight:500;}.session-state.is-inactive{color:var(--text-lo);}
.session-actions{display:flex;align-items:center;gap:4px;flex:none;}.session-actions button{min-height:36px;padding-inline:10px;}.session-expand{display:inline-flex;align-items:center;gap:4px;}.session-expand svg{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.5;transition:transform .16s ease;}.session-expand[aria-expanded=true] svg{transform:rotate(180deg);}
.session-network{display:flex;align-items:center;flex-wrap:wrap;gap:3px 12px;min-width:0;overflow-wrap:anywhere;font-size:13px;color:var(--text-lo);}.session-ip{color:var(--text-hi);font-variant-numeric:tabular-nums;}.session-activity{font-variant-numeric:tabular-nums;}.session-location{min-height:32px;font-size:13px;}.session-error{flex-basis:100%;font-size:13px;color:var(--danger);margin:3px 0 0;}
.session-details:not([hidden]){display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,.65fr);gap:10px 20px;padding:10px 0 4px;margin-top:4px;border-top:1px dashed var(--control-border);}.session-entry,.session-times{display:grid;grid-template-columns:64px minmax(0,1fr);gap:5px 8px;margin:0;font-size:13px;font-variant-numeric:tabular-nums;align-content:start;}.session-details dt{color:var(--text-lo);}.session-details dd{margin:0;overflow-wrap:anywhere;min-width:0;}
.session-expand:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
@container sessions (max-width:540px){.session-summary{align-items:flex-start;}.session-device{gap:2px 6px;flex-wrap:wrap;}.session-actions button,.session-location{min-height:44px;}.session-actions button{padding-inline:8px;}.session-network{gap:4px 10px;}.session-activity{flex-basis:100%;}.session-details:not([hidden]){grid-template-columns:minmax(0,1fr);}.sess-row.is-current{padding-inline:9px;}}
@media(prefers-reduced-motion:reduce){.session-expand svg{transition:none;}}
</style>
