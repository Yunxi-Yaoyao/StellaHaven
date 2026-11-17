<script setup lang="ts">
import {toast} from "../../composables/useToast";
// 单用户集中设置；权限来自有效用户会话，危险操作保留对象确认。
import { ref, computed, onMounted, watch, onBeforeUnmount, onActivated, onDeactivated, inject, nextTick } from "vue";
import { auth, logout } from "../home/auth";
import { useRouter, useRoute, onBeforeRouteLeave, onBeforeRouteUpdate, matchedRouteKey } from "vue-router";
import ProfileSettings, {type ProfileRecord} from "./ProfileSettings.vue";
import HelpHint from "./HelpHint.vue";
import SettingsNavigation from './SettingsNavigation.vue';
import FirstUseChecklist from './FirstUseChecklist.vue';
import SessionRecordRow from './SessionRecordRow.vue';
import AuthProviderSettings from "./AuthProviderSettings.vue";
import NavigationSettings from "./NavigationSettings.vue";
import SettingsPanel from "../../shell/SettingsPanel.vue";
import PerformanceSettings from "./PerformanceSettings.vue";
import AppearanceSettings from './AppearanceSettings.vue';
import BackupCenter from './BackupCenter.vue';
import AccessEntrySettings from './AccessEntrySettings.vue';

import './settings-experience.css';
import { api } from "../../api/client";

const router = useRouter();
const route = useRoute();

/* ---------- 标签页 ---------- */
function canonicalSection(section:unknown,legacy:unknown){const key=String(section||(legacy==='servers'?'servers':legacy==='admin'?'services':legacy==='misc'?'performance':'account'));return ['profile','authentication'].includes(key)?'account':key==='access'?'services':key;}
const tab = computed(() => canonicalSection(route.query.section,route.query.tab));
function chooseSection(key:string,hash=''){router.replace({path:"/settings",query:{section:key},hash});}
watch(()=>[route.fullPath,tab.value],async()=>{await nextTick();const hash=route.hash||(route.query.section==='authentication'?'#login-security':route.query.section==='access'?'#site-addresses':'');if(hash)document.getElementById(hash.slice(1))?.scrollIntoView?.({block:'start'});},{immediate:true,flush:'post'});
// Legacy bookmarks open the local Notes drawer; no duplicate global settings tab.
watch(()=>route.query.section,section=>{if(section==='notes')void router.replace('/notes?settings=open');if(section==='access')void router.replace({path:'/settings',query:{...route.query,section:'services'},hash:route.hash||'#site-addresses'});},{immediate:true});
watch(()=>[route.query.section,route.query.tab],([section,legacy])=>{if(section==='servers'||(!section&&legacy==='servers'))void router.replace('/status?view=overview#service-monitors');},{immediate:true});

/* ---------- 资料及离开保护 ---------- */
const profileDirty=ref(false);
const callbackSettings=ref<InstanceType<typeof AuthProviderSettings>|null>(null);
const entrySettings=ref<InstanceType<typeof AccessEntrySettings>|null>(null);
const profileRequest:typeof fetch=(...args)=>fetch(...args);
function confirmProfile(value:ProfileRecord){if(auth.me&&auth.me.id===value.id)auth.me={...auth.me,username:value.username,display_name:value.display_name,email:value.email??'',email_verified:!!value.email_verified,avatar_url:value.avatar_url??''};}
const pwdOpen=ref(false),oldPwd=ref(''),newPwd=ref(''),pwdMsg=ref('');
const pwdBusy=ref(false);let pwdGeneration=0,pwdController=new AbortController();
const pwdDialog=ref<HTMLElement>(),revokeDialog=ref<HTMLElement>();
let actionDialogOrigin:HTMLElement|null=null;
function closeActionDialog(kind:'password'|'revoke'){if(kind==='password'){if(!pwdBusy.value)pwdOpen.value=false;}else if(!revokeBusy.value)revokeTarget.value=null;}
function actionDialogKeys(event:KeyboardEvent,kind:'password'|'revoke'){
 if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeActionDialog(kind);return;}
 if(event.key!=='Tab')return;const dialog=kind==='password'?pwdDialog.value:revokeDialog.value;
 const items=[...dialog?.querySelectorAll<HTMLElement>('input:not(:disabled),button:not(:disabled),a[href]')??[]];if(!items.length)return;
 const first=items[0]!,last=items.at(-1)!;
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
}
const discardOpen=ref(false), discardDialog=ref<HTMLElement|null>(null);
let discardOrigin:HTMLElement|null=null;
watch(discardOpen,async open=>{if(open){await nextTick();discardDialog.value?.querySelector<HTMLButtonElement>('button')?.focus();}});
function discardKeys(event:KeyboardEvent){if(event.key!=='Tab')return;const buttons=Array.from(discardDialog.value?.querySelectorAll<HTMLButtonElement>('button')??[]);if(!buttons.length)return;event.preventDefault();const index=buttons.indexOf(document.activeElement as HTMLButtonElement);buttons[(index+(event.shiftKey?-1:1)+buttons.length)%buttons.length]?.focus();}
let discardResolve:((value:boolean)=>void)|null=null;
async function beforeLeave(){
 if(tab.value==='services')return entrySettings.value?.beforeLeave?.()??true;
 if(!profileDirty.value)return tab.value==='account'?(callbackSettings.value?.beforeLeave?.()??true):true;
 if(discardResolve)return false;
 discardOrigin=document.activeElement as HTMLElement;
 discardOpen.value=true;
 const discard=await new Promise<boolean>(resolve=>{discardResolve=resolve;});
 return discard&&(tab.value!=='account'||(await callbackSettings.value?.beforeLeave?.()??true));
}
function resolveDiscard(value:boolean){discardOpen.value=false;const resolve=discardResolve;discardResolve=null;resolve?.(value);if(!value)void nextTick(()=>discardOrigin?.isConnected&&discardOrigin.focus());}
if(inject(matchedRouteKey,null)){onBeforeRouteLeave(beforeLeave);onBeforeRouteUpdate((to,from)=>to.fullPath===from.fullPath||canonicalSection(to.query.section,to.query.tab)===tab.value?true:beforeLeave());}
function beforeUnload(event:BeforeUnloadEvent){if(profileDirty.value){event.preventDefault();event.returnValue='';}}
onMounted(()=>window.addEventListener('beforeunload',beforeUnload));
onBeforeUnmount(()=>{window.removeEventListener('beforeunload',beforeUnload);resolveDiscard(false);});
watch([()=>auth.me?.id,()=>auth.sessionGeneration,()=>auth.requestEpoch,()=>auth.suspended,()=>auth.sessionClosing],()=>{profileDirty.value=false;resolveDiscard(false);pwdGeneration++;pwdController.abort();pwdController=new AbortController();pwdBusy.value=false;pwdMsg.value='';pwdOpen.value=false;oldPwd.value='';newPwd.value='';},{flush:'sync'});
onBeforeUnmount(()=>{pwdGeneration++;pwdController.abort();});
async function changePwd() {
 if(pwdBusy.value||!auth.me||auth.suspended||auth.sessionClosing)return;
 if(newPwd.value.length<6){pwdMsg.value='新密码至少 6 位';return;}
 const generation=pwdGeneration;pwdBusy.value=true;pwdMsg.value='';
 try{
  const r=await fetch('/auth/password',{method:'POST',signal:pwdController.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({old_password:oldPwd.value,new_password:newPwd.value})});
  const d=await r.json();if(generation!==pwdGeneration)return;
  if(!r.ok){pwdMsg.value=typeof d.detail==='string'?d.detail:'修改失败，请重试';return;}
  oldPwd.value='';newPwd.value='';toast('密码已修改，所有会话已下线，请重新登录');await doLogout();
 }catch{if(generation===pwdGeneration)pwdMsg.value='修改失败，尚未确认结果；请重试或用新密码重新登录';}
 finally{if(generation===pwdGeneration)pwdBusy.value=false;}
}

async function doLogout() {
  try { await logout(); void router.push("/login"); }
  catch { /* auth.logoutError remains visible beside the retry button. */ }
}
/* ---------- 登录记录 ---------- */
interface SessionRow {
  id: string; device: string; ip: string; remember: boolean;
  created_at: string; last_seen: string; expires_at: string | null; current: boolean;
  owner: string; mine: boolean; state?: 'expired' | 'revoked';
  browser_name?: string | null; os_name?: string | null; login_origin?: string | null; ip_location?: string | null;
}
const sessions = ref<SessionRow[]>([]);
const currentSessions = ref<SessionRow[]>([]);
const sessionsActive = ref(true);
const documentVisible=ref(document.visibilityState==='visible'),windowFocused=ref(document.hasFocus());
const sessionsAllowed = computed(() => sessionsActive.value && documentVisible.value && windowFocused.value && tab.value === 'account' && !!auth.me && !auth.suspended && !auth.sessionClosing);
const sessionsBusy=ref(false),sessionsLoaded=ref(false),activeHasMore=ref(false);
let refreshTimer:ReturnType<typeof setTimeout>|undefined,sessionRun:Promise<void>|null=null,refreshQueued=false,refreshFailures=0;
function stopSessionRefresh(){clearTimeout(refreshTimer);refreshTimer=undefined;sessionLifetime++;listRequest++;historyRequest++;sessionsBusy.value=false;historyBusy.value=false;locationBusy.value=[];}
function scheduleSessionRefresh(){clearTimeout(refreshTimer);if(sessionsAllowed.value)refreshTimer=setTimeout(()=>void loadSessions(),Math.min(120000,30000*2**Math.min(refreshFailures,2)));}
function visibilityChanged(){documentVisible.value=document.visibilityState==='visible';windowFocused.value=document.hasFocus();}
function windowFocus(){windowFocused.value=true;}
function windowBlur(){windowFocused.value=false;}
let sessionLifetime = 0, listRequest = 0, historyRequest = 0;
function sessionTicket() { return {lifetime:sessionLifetime,owner:auth.me?.id,generation:auth.sessionGeneration,epoch:auth.requestEpoch}; }
function sessionCurrent(t:ReturnType<typeof sessionTicket>) { return sessionsAllowed.value && t.lifetime===sessionLifetime && t.owner===auth.me?.id && t.generation===auth.sessionGeneration && t.epoch===auth.requestEpoch; }
function invalidateSessions() {
  stopSessionRefresh();refreshQueued=false;
  sessionLifetime++; listRequest++; historyRequest++;
  sessions.value=[]; currentSessions.value=[]; historyRows.value=[]; historyBusy.value=false;
  historyError.value=''; sessMsg.value=''; locationBusy.value=[]; locationError.value={}; revokeTarget.value=null;revokeError.value='';
  sessionsLoaded.value=false;activePage.value=1;historyPage.value=1;activeHasMore.value=false;historyTotal.value=0;
}
watch([()=>auth.me?.id,()=>auth.sessionGeneration,()=>auth.requestEpoch,()=>auth.suspended,()=>auth.sessionClosing], ()=>{
  invalidateSessions();
  if(sessionsAllowed.value)void loadSessions();
}, {flush:'sync'});
watch(sessionsAllowed,allowed=>{stopSessionRefresh();if(allowed)void loadSessions();},{flush:'sync'});
onDeactivated(()=>{sessionsActive.value=false;});
onActivated(()=>{sessionsActive.value=true;});
onBeforeUnmount(()=>{sessionsActive.value=false;invalidateSessions();document.removeEventListener('visibilitychange',visibilityChanged);window.removeEventListener('focus',windowFocus);window.removeEventListener('blur',windowBlur);});
const sessMsg = ref("");
const activePage = ref(1);
const historyPage = ref(1);
const historyTotal = ref(0);
const historyRows = ref<SessionRow[]>([]);
const historyOpen = ref(false);
const historyBusy = ref(false);
const historyError = ref('');
async function loadHistory(page = historyPage.value) {
  if (!sessionsAllowed.value || historyBusy.value) return;
  const ticket=sessionTicket(), request=++historyRequest;
  const current=()=>sessionCurrent(ticket)&&request===historyRequest;
  historyBusy.value = true;
  historyError.value = '';
  try {
    const r = await fetch(`/auth/sessions/history?page=${page}&page_size=20`);
    if (!r.ok) throw new Error('加载历史失败');
    const data = await r.json();
    if (!current()) return;
    historyRows.value = mergeSessions(data.items,historyRows.value);
    historyTotal.value = data.total;
    historyPage.value = data.page;
  } catch { if(current()) historyError.value = '加载历史失败，请重试'; }
  finally { if(current()) historyBusy.value = false; }
}
function toggleHistory(event: Event) {
  historyOpen.value = (event.target as HTMLDetailsElement).open;
  if (historyOpen.value) void loadHistory();
}
function mergeSessions(rows:SessionRow[],old:SessionRow[]){return rows.map(row=>{const previous=old.find(s=>s.id===row.id);return {...row,ip_location:row.ip_location||(previous?.ip===row.ip?previous.ip_location:null)};});}
const locationBusy = ref<string[]>([]), locationError = ref<Record<string,string>>({});
async function loadLocation(s:SessionRow) {
  if(!sessionsAllowed.value || locationBusy.value.includes(s.id))return;
  const ticket=sessionTicket();
  locationBusy.value.push(s.id);delete locationError.value[s.id];
  try {
    const r=await fetch(`/auth/sessions/${encodeURIComponent(s.id)}/location`);
    if(!r.ok)throw Error('location');
    const data=await r.json();
    // A late answer for an older IP must not overwrite the latest network metadata.
    if(sessionCurrent(ticket))for(const row of [...sessions.value,...currentSessions.value,...historyRows.value])if(row.id===s.id&&data.ip===row.ip)row.ip_location=data.ip_location || '地点未知';
  } catch { if(sessionCurrent(ticket)) locationError.value[s.id]='地点查询失败，可重试'; }
  finally {if(sessionCurrent(ticket))locationBusy.value=locationBusy.value.filter(id=>id!==s.id);}
}

async function loadSessions() {
  if (!sessionsAllowed.value) return;
  clearTimeout(refreshTimer);
  if(sessionRun){refreshQueued=true;return sessionRun;}
  sessionRun=refreshSessions();
  try{await sessionRun;}finally{sessionRun=null;if(refreshQueued&&sessionsAllowed.value){refreshQueued=false;void loadSessions();}else{refreshQueued=false;scheduleSessionRefresh();}}
}
async function refreshSessions(){
  const ticket=sessionTicket(), request=++listRequest, page=activePage.value;
  const current=()=>sessionCurrent(ticket)&&request===listRequest;
  sessionsBusy.value=true;
  try {
    // page_size also determines offset: a one-row query at page 20p+1 is the exact lookahead.
    const [list,pinned,next]=await Promise.all([fetch(`/auth/sessions?page=${page}&page_size=20&exclude_current=true`),fetch('/auth/sessions?current_only=true'),fetch(`/auth/sessions?page=${page*20+1}&page_size=1&exclude_current=true`)]);
    if(!list.ok || !pinned.ok || !next.ok)throw new Error('sessions');
    const [rows,own,following]=await Promise.all([list.json(),pinned.json(),next.json()]);
    if(!current())return;
    if(!Array.isArray(rows)||!Array.isArray(own)||!Array.isArray(following))throw Error('invalid sessions');
    sessions.value=mergeSessions(rows,sessions.value);currentSessions.value=mergeSessions(own.filter((s:SessionRow)=>s.current),currentSessions.value);activeHasMore.value=following.length>0;sessionsLoaded.value=true;sessMsg.value='';refreshFailures=0;
    if(!rows.length&&page>1){activePage.value--;refreshQueued=true;}
    if(historyOpen.value)await loadHistory();
  } catch { if(current()){sessMsg.value='会话更新失败，保留上次记录';refreshFailures++;} }
  finally{if(current())sessionsBusy.value=false;}
}

async function revoke(s: SessionRow) {
  revokeTarget.value = s;revokeError.value='';
}
const revokeTarget = ref<SessionRow | null>(null);
const revokeBusy=ref(false),revokeError=ref('');
watch(()=>pwdOpen.value||!!revokeTarget.value,async open=>{if(open){actionDialogOrigin=document.activeElement as HTMLElement;await nextTick();(pwdOpen.value?pwdDialog.value:revokeDialog.value)?.querySelector<HTMLElement>('input,button')?.focus();}else{const origin=actionDialogOrigin;actionDialogOrigin=null;await nextTick();if(origin?.isConnected)origin.focus();}});
async function confirmRevoke() {
  const s = revokeTarget.value; if (!s || !sessionsAllowed.value || revokeBusy.value) return;
  const ticket=sessionTicket();
  revokeBusy.value=true;
  try{
  const r = await fetch(`/auth/sessions/${s.id}`, { method: "DELETE" });
  if(!sessionCurrent(ticket))return;
  if (r.ok) {
    revokeTarget.value = null;
    toast('该会话已下线');
    loadSessions();

  } else {
    const data=await r.json();if(sessionCurrent(ticket))revokeError.value=typeof data.detail==='string'?data.detail:'下线失败，请重试';
  }
  }catch{if(sessionCurrent(ticket))revokeError.value='下线失败，请重试';}finally{revokeBusy.value=false;}
}

/* ---------- Stella 邮箱服务（admin） ---------- */
const emailCfg = ref({ host: "", port: 465, username: "", password: "", from_name: "StellaHaven 港务局", enabled: false });
const emailMsg = ref("");
const emailLoaded = ref(false), emailBusy = ref(false), smtpPassword = ref(""), smtpHasPassword = ref(false);
const testTo = ref("");
const testMsg = ref("");

const smtpInput = ref<HTMLInputElement | null>(null);
const emailActive = ref(true);
const emailAllowed = computed(() => emailActive.value && tab.value === 'services' && !!auth.me && !auth.suspended && !auth.sessionClosing);
const emailReadback = ref(false);
let emailGeneration = 0, secretEdit = 0, configEdit = 0;
let configDirty = false;
let emailController = new AbortController();
let submittedEdit: {secret: number; config: number} | null = null;
watch(smtpPassword, () => { secretEdit++; }, {flush:'sync'});
function editEmailConfig() { configEdit++; configDirty = true; }
function clearSmtpSecret() {
  smtpPassword.value = '';
  // Vue patches on the next tick; privacy boundaries must scrub the existing DOM now.
  if (smtpInput.value) smtpInput.value.value = '';
}
function invalidateEmail() {
  emailGeneration++;
  emailController.abort(); emailController = new AbortController();
  clearSmtpSecret(); emailBusy.value = false; emailLoaded.value = false;
  emailMsg.value = ''; testMsg.value = '';
}
watch([emailAllowed, () => auth.me?.id, () => auth.sessionGeneration, () => auth.requestEpoch], (_now, old) => {
  invalidateEmail();
  if (old && (old[1] !== auth.me?.id || old[2] !== auth.sessionGeneration)) {
    configDirty = false; emailReadback.value = false; submittedEdit = null;
  }
  if (emailAllowed.value) void loadEmailCfg();
}, {flush:'sync'});
onDeactivated(() => { emailActive.value = false; });
onActivated(() => { emailActive.value = true; });
onBeforeUnmount(() => { emailActive.value = false; invalidateEmail(); });
const emailCurrent = (generation: number) => generation === emailGeneration && emailAllowed.value;
async function loadEmailCfg() {
  if (!emailAllowed.value || emailBusy.value) return false;
  const generation = emailGeneration, edit = configEdit, submitted = submittedEdit;
  emailBusy.value = true; emailMsg.value = '';
  try {
    const config = await api<typeof emailCfg.value>('/admin/email/config', {signal:emailController.signal});
    if (!emailCurrent(generation)) return false;
    smtpHasPassword.value = !!config.password;
    // Neither a lifecycle read nor an older save readback owns newer local edits.
    if (edit === configEdit && (!configDirty || submitted?.config === configEdit)) {
      emailCfg.value = {...config, password:''}; configDirty = false;
    }
    if (submitted && submitted.secret === secretEdit) clearSmtpSecret();
    emailLoaded.value = true;
    if (emailReadback.value) toast('配置已保存');
    emailReadback.value = false; submittedEdit = null;
    return true;
  } catch {
    if (emailCurrent(generation)) emailMsg.value = emailReadback.value ? '配置已提交，回读失败；请重试读取' : '邮箱配置读取失败';
    return false;
  } finally { if (emailCurrent(generation)) emailBusy.value = false; }
}
async function saveEmailCfg() {
  if (!emailAllowed.value || !emailLoaded.value || emailBusy.value) return;
  if (emailReadback.value) { await loadEmailCfg(); return; }
  const generation = emailGeneration;
  const edit = {secret:secretEdit, config:configEdit};
  emailMsg.value = ''; emailBusy.value = true;
  try {
    await api('/admin/email/config', {method:'PUT',signal:emailController.signal,body:JSON.stringify({...emailCfg.value,password:smtpPassword.value || (smtpHasPassword.value ? '••••••' : '')})});
    if (!emailCurrent(generation)) return;
    submittedEdit = edit; emailReadback.value = true;
    emailBusy.value = false; await loadEmailCfg();
  } catch { if (emailCurrent(generation)) emailMsg.value = '未保存，请重试'; }
  // Failed writes retain the draft only inside the active privileged editing lifetime.
  finally { if (emailCurrent(generation)) emailBusy.value = false; }
}
async function sendTestMail() {
  if (!emailAllowed.value) return;
  const generation = emailGeneration;
  testMsg.value = '';
  if (!testTo.value.includes('@')) { testMsg.value = '请填写收件邮箱'; return; }
  try { await api('/admin/email/test',{method:'POST',signal:emailController.signal,body:JSON.stringify({to:testTo.value})}); if (emailCurrent(generation)) toast('测试邮件已提交发送'); }
  catch { if (emailCurrent(generation)) testMsg.value='测试邮件未发送'; }
}

onMounted(() => {
  document.addEventListener('visibilitychange',visibilityChanged);window.addEventListener('focus',windowFocus);window.addEventListener('blur',windowBlur);
  loadSessions();
  if (emailAllowed.value) loadEmailCfg();
});
</script>

<template>
  <div class="page">
    <SettingsNavigation :section="tab" @navigate="chooseSection">
      <FirstUseChecklist v-if="tab==='first-use'" embedded />

      <ProfileSettings v-if="tab==='account' && auth.me && !auth.suspended && !auth.sessionClosing" :key="`${auth.me.id}:${auth.sessionGeneration}:${auth.requestEpoch}`" :initial-profile="auth.me" :request="profileRequest" @confirmed="confirmProfile" @dirty="profileDirty=$event" @security="chooseSection('account','#login-security')" @services="chooseSection('services','#email-service')" />

      <template v-if="tab === 'account'">
        <section id="login-security" class="card">
          <h2 class="sec-t">登录与会话</h2>
          <div class="btn-row">
            <button class="btn ghost st-button is-ghost" @click="pwdOpen = true">修改密码</button>
            <button class="btn ghost st-button is-ghost" :disabled="auth.sessionClosing" @click="doLogout">退出登录</button>
          </div>
          <p v-if="auth.logoutError" role="alert">{{ auth.logoutError }}（尚未确认退出，请再次点击退出登录）</p>
        </section>

      </template>
      <KeepAlive><AuthProviderSettings v-if="tab === 'account'" ref="callbackSettings" navigation-managed /></KeepAlive>
      <p v-if="tab === 'account'" class="field-help"><RouterLink to="/settings?section=services#site-addresses">主站入口地址</RouterLink></p>
      <template v-if="tab === 'account'">
        <section id="sessions" class="card">
          <div class="sec-t">登录记录 <HelpHint label="登录记录说明">当前会话独立读取，换页仍保留；其他有效会话按页展示。记住我：自登录起 30 天，不随 refresh 续期；否则自最后真实操作起 30 分钟。后台轮询不续期；有效会话不表示正在使用。</HelpHint></div>
          <p class="hint" data-session-location-notice>查询归属地会将该会话的 IP 发送给 IPinfo；地点可能是代理出口，并非实际位置。</p>
          <div v-if="sessMsg" class="session-update-error" role="status">{{sessMsg}} <button class="st-button is-ghost" :disabled="sessionsBusy" @click="loadSessions">重试</button></div>
          <p v-if="!sessionsLoaded&&!sessMsg" class="session-loading" role="status">{{sessionsAllowed?'正在读取会话…':'等待页面激活后读取会话'}}</p>
          <div class="session-records">
            <SessionRecordRow v-for="s in currentSessions" :key="s.id" :row="s" :location-busy="locationBusy.includes(s.id)" :location-error="locationError[s.id]" @location="loadLocation(s)" />
            <div v-if="sessions.length" data-other-sessions><h3 class="sess-group">其他有效会话</h3><SessionRecordRow v-for="s in sessions.filter(s=>!s.current&&!currentSessions.some(c=>c.id===s.id))" :key="s.id" :row="s" :location-busy="locationBusy.includes(s.id)" :location-error="locationError[s.id]" :revoke-busy="revokeBusy" @location="loadLocation(s)" @revoke="revoke(s)" /></div>
            <p v-if="sessionsLoaded&&!sessions.length&&!currentSessions.length" class="session-loading">暂无有效会话</p>
            <div v-if="activePage>1||activeHasMore" class="btn-row session-pagination" data-active-pagination><button class="st-button" :disabled="sessionsBusy||activePage<=1" @click="activePage--;loadSessions()">上一页</button><span>第 {{activePage}} 页</span><button class="st-button" :disabled="sessionsBusy||!activeHasMore" @click="activePage++;loadSessions()">下一页</button></div>
            <details @toggle="toggleHistory">
              <summary class="sess-group">历史登录记录（已过期 / 已下线）<span v-if="historyTotal"> · {{historyTotal}} 条</span></summary>
              <p v-if="historyBusy&&!historyRows.length" role="status">正在读取历史…</p><p v-if="historyError" class="session-update-error" role="alert">{{historyError}} <button class="st-button" @click="loadHistory()">重试</button></p>
              <SessionRecordRow v-for="s in historyRows" :key="s.id" :row="s" :location-busy="locationBusy.includes(s.id)" :location-error="locationError[s.id]" @location="loadLocation(s)" />
              <p v-if="!historyBusy&&!historyError&&!historyRows.length" class="session-loading">暂无历史记录</p>
              <div v-if="historyTotal>20" class="btn-row session-pagination"><button class="st-button" :disabled="historyBusy||historyPage<=1" @click="loadHistory(historyPage-1)">上一页</button><span>共 {{historyTotal}} 条 · {{historyPage}} / {{Math.ceil(historyTotal/20)}} 页</span><button class="st-button" :disabled="historyBusy||historyPage*20>=historyTotal" @click="loadHistory(historyPage+1)">下一页</button></div>
            </details>
          </div>
        </section>
      </template>

      <!-- ═══ 管理员设置 ═══ -->
      <template v-if="tab === 'navigation'">
        <NavigationSettings><template #builtin="{id}">
          <SettingsPanel v-if="id==='home'" embedded />
        </template></NavigationSettings>
      </template>

      <template v-if="tab === 'services'">
        <section id="site-addresses" class="entry-group" aria-label="主站域名与访问入口">
          <h2 class="sec-t">主站域名与访问入口</h2>
          <AccessEntrySettings ref="entrySettings" navigation-managed />
        </section>
        <section id="email-service" class="card mail-service">
          <div class="sec-t">Stella 邮箱服务<HelpHint label="邮箱服务与通知说明">网站外发邮件（重置密码验证码等）使用 SMTP。站内通知通过侧栏铃铛查看，邮件通知使用下方 SMTP 服务。</HelpHint></div>
          <p v-if="!emailAllowed" class="hint">登录后读取 SMTP 配置。</p>
          <button v-else-if="!emailLoaded" class="btn st-button is-primary" :disabled="emailBusy" @click="loadEmailCfg">读取 SMTP 配置</button>
          <template v-if="emailLoaded && emailAllowed"><div class="smtp-fields" @input="editEmailConfig">
          <div class="field-row smtp-toggle">
            <span class="f-label">开关</span>
            <button class="switch" :class="{ on: emailCfg.enabled }" role="switch" aria-label="启用 SMTP 服务" :aria-checked="emailCfg.enabled" @click="emailCfg.enabled = !emailCfg.enabled; editEmailConfig()"><i /></button>
            <span class="f-hint">开启后启用邮箱认证登录 / 忘记密码</span>
          </div>
          <div class="smtp-endpoint">
          <div class="field-row smtp-host"><span class="f-label">域名</span><input v-model="emailCfg.host" aria-label="SMTP 服务地址" class="input" placeholder="smtp.example.com" /></div>
          <div class="field-row smtp-port"><span class="f-label">端口</span><input v-model.number="emailCfg.port" aria-label="SMTP 端口" type="number" min="1" max="65535" class="input" placeholder="465" /></div>
          </div>
          <div class="field-row"><span class="f-label">账号</span><input v-model="emailCfg.username" aria-label="SMTP 账号" class="input" placeholder="noreply@xiya.live" /></div>
          <div class="field-row"><span class="f-label">密钥</span><input ref="smtpInput" v-model="smtpPassword" @input.stop type="password" aria-label="SMTP 密钥" class="input" :placeholder="smtpHasPassword ? '已保存 · 留空不修改' : 'SMTP 密码 / 授权码'" autocomplete="new-password" /></div>
          <div class="field-row"><span class="f-label">签名</span><input v-model="emailCfg.from_name" aria-label="SMTP 签名" class="input" placeholder="StellaHaven 港务局" /></div>
          </div><button class="btn st-button is-primary" :disabled="emailBusy" @click="saveEmailCfg">{{ emailReadback ? '重试读取 SMTP 配置' : '应用 SMTP 配置' }}</button>

          <div class="mail-test">
            <input v-model="testTo" type="email" aria-label="测试收件邮箱" class="input" placeholder="测试收件邮箱" />
            <button class="btn st-button is-primary" @click="sendTestMail">发送测试邮件</button>
          </div>
          <div v-if="testMsg" class="ok-msg">{{ testMsg }}</div></template><p v-if="emailMsg" role="status">{{emailMsg}}</p>
        </section>
      </template>

      <section v-if="tab === 'services'" id="notifications" class="card" aria-label="通知"><h2 class="sec-t">通知</h2><p class="hint">站内通知通过侧栏铃铛查看；邮件通知使用上方 SMTP 服务。</p><div class="notification-note"><RouterLink to="/status?view=alerts">节点告警规则与通知</RouterLink></div></section>
      <AppearanceSettings v-if="tab === 'appearance'" />
      <KeepAlive><BackupCenter v-if="tab === 'backups'" /></KeepAlive>
      <template v-if="!['first-use','account','profile','appearance','authentication','access','navigation','notes','servers','services','backups'].includes(tab)"><PerformanceSettings /></template>
    </SettingsNavigation>

    <Teleport to="body"><div v-if="revokeTarget" class="mini-mask" @click.self="closeActionDialog('revoke')" @keydown="actionDialogKeys($event,'revoke')"><section ref="revokeDialog" class="mini-pop" role="dialog" aria-modal="true" aria-label="确认下线设备"><h2>确认下线 {{ revokeTarget.browser_name || revokeTarget.device }}？</h2><p class="session-confirm-target">{{revokeTarget.ip}}<br>{{revokeTarget.login_origin || '入口未知'}}</p><p>此设备需要重新登录。</p><p v-if="revokeError" role="alert" class="session-update-error">{{revokeError}}</p><div class="mp-actions"><button class="btn ghost st-button is-ghost" :disabled="revokeBusy" @click="revokeTarget = null">取消</button><button class="btn st-button is-primary" :disabled="revokeBusy" :aria-busy="revokeBusy" @click="confirmRevoke">确认下线</button></div></section></div></Teleport>


    <!-- 修改密码浮窗 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="pwdOpen" class="mini-mask" @click.self="closeActionDialog('password')" @keydown="actionDialogKeys($event,'password')">
          <form ref="pwdDialog" class="mini-pop" role="dialog" aria-modal="true" aria-label="修改用户密码" @submit.prevent="changePwd">
            <div class="mp-t">修改密码</div>
            <input v-model="oldPwd" aria-label="原用户密码" autocomplete="current-password" :readonly="pwdBusy" type="password" class="input" placeholder="原密码" />
            <input v-model="newPwd" aria-label="新用户密码" autocomplete="new-password" :readonly="pwdBusy" type="password" class="input" placeholder="新密码（至少 6 位）" minlength="6" style="margin-top:10px" />
            <div v-if="pwdMsg" data-password-error role="alert" class="session-update-error">{{pwdMsg}}</div>
            <div class="mp-actions">
              <button type="button" class="btn ghost st-button is-ghost" :disabled="pwdBusy" @click="pwdOpen=false">取消</button>
              <button data-password-submit type="submit" class="btn st-button is-primary" :aria-busy="pwdBusy" :disabled="pwdBusy||!oldPwd||newPwd.length<6">修改密码</button>
            </div>
            <div class="session-loading">修改后所有会话下线，需要重新登录。</div>
          </form>
        </div>
      </Transition>
    </Teleport>

    <Teleport to="body"><div v-if="discardOpen" class="mini-mask" @click.self="resolveDiscard(false)" @keydown.esc.stop="resolveDiscard(false)"><section ref="discardDialog" class="mini-pop" role="alertdialog" @keydown="discardKeys" aria-modal="true" aria-label="离开未保存的资料"><h2>离开未保存的资料？</h2><p>当前昵称、用户名或邮箱草稿尚未保存。留在这里可继续编辑。</p><div class="mp-actions"><button class="btn ghost st-button is-ghost" autofocus @click="resolveDiscard(false)">继续编辑</button><button class="btn st-button is-primary" @click="resolveDiscard(true)">放弃草稿并离开</button></div></section></div></Teleport>
  </div>
</template>

<style scoped>
.page { min-height:100%; padding: 8px 0 32px; min-width:0; }
.smtp-fields{display:grid;grid-template-columns:1fr 1fr;gap:10px 20px;margin:14px 0}.smtp-fields .field-row{margin:0}@media(max-width:650px){.smtp-fields{grid-template-columns:1fr}}
.smtp-fields > .smtp-toggle, .smtp-endpoint{grid-column:1 / -1}
.smtp-endpoint{display:flex;flex-wrap:wrap;gap:10px 20px;max-width:44rem}
.smtp-host{flex:1 1 260px;min-width:0}.smtp-port{flex:0 0 auto}
.smtp-port .input{width:9ch;min-width:9ch}
.smtp-fields .input{min-width:0}.smtp-fields > .field-row{min-width:0}
.public-host{max-width:none}.public-host .input{min-width:0}
.entry-group{margin-bottom:28px;min-width:0}.entry-group .sec-t{font-size:16px;margin:0 0 12px;letter-spacing:0}.entry-setting-row{display:grid;grid-template-columns:minmax(140px,1fr) minmax(0,380px);gap:16px;align-items:center;padding:14px 0;border-bottom:1px solid var(--control-border)}.entry-setting-row label{display:flex;align-items:center;gap:4px;font-size:14px;color:var(--text-hi)}.entry-setting-row .input{box-sizing:border-box;font-size:14px;min-height:38px;width:100%;border-radius:7px;background:var(--bg-base);border:1px solid var(--control-border)}.entry-actions{display:flex;justify-content:flex-end;margin-top:12px}.entry-group>p{font-size:14px;color:var(--text-lo);line-height:1.7}@media(max-width:600px){.entry-setting-row{grid-template-columns:minmax(0,1fr);gap:6px;padding:10px 0}.entry-setting-row .input{min-height:44px}}
.notification-note{display:flex;flex-wrap:wrap;gap:6px 16px}.notification-note a{overflow-wrap:anywhere}
.mail-service .mail-test{max-width:44rem;flex-wrap:wrap}.mail-service .mail-test .input{min-width:0;flex:1 1 220px}
.wrap { max-width: 1040px; margin: 0 auto; min-width:0; }
.h1 { font-size: 24px; font-weight: 600; color: var(--text-hi); letter-spacing: 3px; margin-bottom: 20px; }

.tabs { display: flex; flex-wrap:wrap; gap: 6px; margin-bottom: 18px; border-bottom: 1px solid rgba(255,255,255,0.07); }
.tab {
  padding: 9px 18px;
  border: none;
  background: transparent;
  color: var(--text-lo);
  font-size: 13.5px;
  font-family: inherit;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: all 200ms;
  letter-spacing: 1px;
}
.tab:hover { color: var(--text-hi); }
.tab.on { color: var(--accent); border-bottom-color: var(--accent); }

.card {
  background: color-mix(in srgb, var(--bg-panel) 80%, transparent);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 16px;
  padding: 20px 22px;
  margin-bottom: 18px;
}
.sec-t { font-size: 14.5px; font-weight: 600; color: var(--text-hi); letter-spacing: 1.5px; margin-bottom: 14px; }
.sec-sub { font-size: 11.5px; color: var(--text-faint); font-weight: 400; margin-left: 8px; }
.me-row { display: flex; align-items: center; gap: 14px; }
.me-avatar-btn {
  position: relative;
  width: 52px; height: 52px;
  border-radius: 50%;
  border: 2px solid var(--accent-dim);
  padding: 0;
  cursor: pointer;
  overflow: hidden;
  background: none;
  flex-shrink: 0;
}
.me-avatar { width: 100%; height: 100%; object-fit: cover; display: block; }
.me-avatar-hint {
  position: absolute; inset: 0;
  display: grid; place-items: center;
  background: rgba(10, 14, 20, 0.45);
  color: #fff; font-size: 15px;
  opacity: 0; transition: opacity 180ms;
}
.me-avatar-btn:hover .me-avatar-hint { opacity: 1; }
.me-info { flex: 1; min-width: 0; }
.me-name-row { display: flex; align-items: center; gap: 8px; }
.me-name { font-size: 16px; font-weight: 600; color: var(--text-hi); }
.me-sub { font-size: 12px; color: var(--text-lo); margin-top: 3px; }
.hint { margin-top: 12px; font-size: 11.5px; color: var(--text-faint); line-height: 1.6; }
[data-session-location-notice] { font-size: 12px; color: var(--text-hi); }
.ok-msg { margin: 10px 0 0; font-size: 12.5px; color: var(--success); }
.field { margin-bottom: 10px; }
.input {
  width: 100%; padding: 9px 12px; border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-hi); font-size: 13px; font-family: inherit; outline: none;
}
.input:focus { border-color: var(--accent-dim); }
.name-input { width: 160px; }
.session-records{container: sessions / inline-size;}
.session-update-error{font-size:14px;color:var(--danger);margin:12px 0;}.session-loading{font-size:14px;color:var(--text-lo);line-height:1.6;}.session-pagination{align-items:center;flex-wrap:wrap;font-size:13px;}
summary { cursor:pointer; }
.mini:not(.st-button) {
  padding: 4px 12px; border-radius: 8px; border: none;
  font-size: 11.5px; cursor: pointer; font-family: inherit;
  background: rgba(255, 255, 255, 0.06); color: var(--text-lo);
}
.mini:not(.st-button):hover { color: var(--text-hi); }
.mini:not(.st-button).danger:not(.st-button):hover { background: rgba(150, 60, 75, 0.5); color: var(--danger); }
.user-row { display: flex; align-items: baseline; gap: 10px; padding: 8px 4px; }
.u-name { font-size: 14px; color: var(--text-hi); }
.u-sub { font-size: 11.5px; color: var(--text-faint); }
.u-admin { font-size: 10px; padding: 1px 8px; border-radius: 999px; background: rgba(232, 160, 191, 0.15); color: var(--pink); }
.btn:not(.st-button) {
  padding: 8px 18px; border-radius: 10px; border: none;
  background: var(--accent); color: #141824;
  font-size: 13px; font-weight: 600; cursor: pointer; font-family: inherit;
  white-space: nowrap; flex-shrink: 0;
}
.btn:not(.st-button):disabled { opacity: 0.4; cursor: not-allowed; }
.btn:not(.st-button).ghost { background: transparent; color: var(--text-lo); border: 1px solid rgba(255, 255, 255, 0.12); font-weight: 400; }
.btn:not(.st-button).ghost:hover { color: var(--text-hi); }
.btn-row { display: flex; gap: 10px; margin-top: 16px; }
.avatar-history { margin-top: 16px; }
.ah-label { font-size: 11.5px; color: var(--text-faint); letter-spacing: 1px; margin-bottom: 8px; }
.ah-row { display: flex; gap: 8px; }
.ah-thumb {
  width: 40px; height: 40px; border-radius: 50%;
  object-fit: cover; cursor: pointer;
  border: 2px solid transparent;
  opacity: 0.65;
  transition: all 180ms;
}
.ah-thumb:hover { opacity: 1; transform: scale(1.08); }
.ah-thumb.on { border-color: var(--accent); opacity: 1; }
.sess-group {
  font-size:14px;color:var(--text-lo);font-weight:500;letter-spacing:0;margin:18px 0 0;min-height:36px;align-content:center;
}
.sess-group:first-of-type { margin-top: 0; }
.field-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.field-row .f-label { min-width: 44px; flex-shrink: 0; font-size: 12.5px; color: var(--text-lo); white-space: nowrap; }
.f-hint { font-size: 11.5px; color: var(--text-faint); }
.mail-test { display: flex; gap: 10px; margin-top: 14px; }
.switch {
  width: 40px; height: 22px; border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.08);
  cursor: pointer; position: relative; transition: all 220ms; padding: 0;
  flex-shrink: 0;
}
.switch i {
  position: absolute; left: 2px; top: 2px;
  width: 16px; height: 16px; border-radius: 50%;
  background: var(--text-lo);
  transition: all 220ms cubic-bezier(0.22, 1, 0.36, 1);
}
.switch.on { background: color-mix(in srgb, var(--accent) 55%, transparent); border-color: var(--accent-dim); }
.switch.on i { left: 20px; background: #fff; }
.mini-mask {
  position: fixed; inset: 0; z-index: 135;
  background: rgba(6, 10, 16, 0.5);
  display: flex; align-items: center; justify-content: center;
}
.mini-pop {
  box-sizing:border-box;width:min(420px,calc(100vw - 32px));max-height:calc(100dvh - 32px);overflow:auto;
  background: color-mix(in srgb, var(--bg-panel) 94%, transparent);
  backdrop-filter: var(--blur);
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 16px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.5);
  padding: 20px 22px;
}
.session-confirm-target{overflow-wrap:anywhere;font-size:14px;line-height:1.6;}
.mail-badge {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 999px;
  margin-left: 4px;
  vertical-align: 1px;
}
.mail-badge.pending { color: var(--warning); background: rgba(220, 120, 140, 0.14); border: 1px solid rgba(220, 120, 140, 0.3); }
.mail-badge.ok { color: var(--success); background: rgba(130, 210, 150, 0.12); border: 1px solid rgba(130, 210, 150, 0.3); }
.ok-msg.warn { color: var(--warning); }
.mp-t { font-size: 14px; font-weight: 600; color: var(--text-hi); letter-spacing: 2px; margin-bottom: 12px; }
.mp-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; }
.fade-enter-active, .fade-leave-active { transition: opacity 240ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>