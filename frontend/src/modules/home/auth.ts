// 认证 store：当前用户、登录态、登录/登出/refresh 动作。
// access token 在 httpOnly cookie（30min），401 时静默 refresh 续命。
import { reactive, ref, computed } from "vue";
import { getBrowserId } from '../auth/browserId';
import { homeSettings, siteBackground, DEFAULT_HOME_BG } from "./settings";

export interface Me {
  id: string;
  username: string;
  display_name: string;
  is_admin: boolean;
  avatar_url: string;
  home_bg: string;
  email: string;
  email_verified: boolean;
}

export const auth = reactive({
  me: null as Me | null,
  sessionGeneration: 0,
  requestEpoch: 0, // Network fence can advance while the editor lifetime stays intact.
  sessionClosing: false,
  logoutError: '',
  suspended: false, // Confirmed expiry freezes mounted drafts until reauthentication.
  checked: false, // 首次 /auth/me 探测过没有
  error: '', // Transport failures are not a confirmed guest session.
});

export const loggedIn = computed(() => auth.me !== null && !auth.suspended && !auth.sessionClosing);
/** Only an explicit successful login can resume an expired owner. */
export function acceptLogin(me:Me){
 if(auth.sessionClosing)throw new Error('正在退出登录，请稍候');
 auth.requestEpoch++;
 const resume=auth.suspended&&auth.me?.id===me.id&&!auth.sessionClosing;
 if(!resume)auth.sessionGeneration++;
 auth.sessionClosing=false;auth.suspended=false;auth.error='';auth.logoutError='';auth.me=me;auth.checked=true;
}
export interface SecurityState { enabled:boolean; configured:boolean; elevated:boolean; expires_at:string|null; single_user:boolean; setup_required:boolean }
export const security = reactive<SecurityState>({enabled:false,configured:true,elevated:false,expires_at:null,single_user:true,setup_required:false});
export const securityChecked = ref(false);
// Compatibility name used throughout the UI. Only server-confirmed owner login
// enables it; legacy is_admin metadata and management state are not authority.
export const isAdmin = computed(() => loggedIn.value);
let securityGeneration=0;
export async function loadSecurity() {
  const owner=auth.me?.id,epoch=auth.requestEpoch,sequence=++securityGeneration;
  if(!loggedIn.value){clearSecurity();return;}
  const r = await fetch('/auth/security');
  if (!r.ok) { securityChecked.value=false; throw new Error('安全状态加载失败'); }
  const state=await r.json();if(sequence!==securityGeneration||owner!==auth.me?.id||epoch!==auth.requestEpoch||!loggedIn.value)return;
  Object.assign(security, state); securityChecked.value=true;
}
export function clearSecurity() { securityGeneration++;securityChecked.value=false; Object.assign(security,{enabled:false,configured:true,elevated:false,expires_at:null,setup_required:false}); }
/** 系统是否已初始化（有管理员）。未初始化访客看默认壁纸；初始化后看管理员站点背景 */
export const initialized = ref(true);

/** 主页背景分流：
 *  - 登录：自己的壁纸（账号级 home_bg）→ 站点背景 → 默认壁纸
 *  - 未登录 + 未初始化：默认壁纸
 *  - 未登录 + 已初始化：管理员站点背景 → 默认壁纸
 */
export const displayBg = computed(() => {
  if (loggedIn.value) {
    return auth.me?.home_bg || siteBackground.value || DEFAULT_HOME_BG;
  }
  if (!initialized.value) return DEFAULT_HOME_BG;
  return siteBackground.value || DEFAULT_HOME_BG;
});

/** 头像唯一出口：登录用户的头像优先级最高，签名卡/侧栏都借它；未登录回退站点默认 */
export const currentAvatar = computed(() =>
  auth.me?.avatar_url || homeSettings.avatar
);

let _refreshing: {generation:number;epoch:number;promise:Promise<boolean>} | null = null;
const sessionCurrent=(generation:number,epoch:number)=>generation===auth.sessionGeneration&&epoch===auth.requestEpoch&&!auth.sessionClosing;
let lastActivityReport = 0;
/** Only actual input extends server idle time; background requests never do. */
export async function reportActivity(event: Event): Promise<void> {
  if (!event.isTrusted || document.visibilityState !== 'visible' || !loggedIn.value) return;
  const now = Date.now();
  if (now - lastActivityReport < 60000) return;
  lastActivityReport = now;
  try {
    const r = await fetch('/auth/activity', { method: 'POST' });
    if (r.status === 401 && await refreshAccess()) {
      await fetch('/auth/activity', { method: 'POST' });
    }
  } catch { lastActivityReport = 0; }
}

/** 单例 refresh：并发 401 时只发一个 refresh，避免旋转制 refresh token 被并发转废 */
export function refreshAccess(): Promise<boolean> {
  const generation=auth.sessionGeneration,epoch=auth.requestEpoch;
  if(!sessionCurrent(generation,epoch)||auth.suspended)return Promise.resolve(false);
  if(_refreshing?.generation===generation&&_refreshing.epoch===epoch)return _refreshing.promise;
  // A late old finally must not clear the new session's single-flight request.
  const flight={generation,epoch,promise:Promise.resolve(false)};
  _refreshing=flight;
  flight.promise=(async()=>{
    let rejected=false;
    try {
      for(let attempt=0;attempt<2;attempt++) {
        if(!sessionCurrent(generation,epoch))return false;
        try {
          const r=await fetch('/auth/refresh',{method:'POST'});
          if(!sessionCurrent(generation,epoch))return false;
          if(r.ok){const me=await r.json();if(!sessionCurrent(generation,epoch))return false;auth.me=me;auth.error='';return true;}
          if(r.status!==401&&r.status!==403){auth.error='身份确认失败，请重试';return false;}
          rejected=true;
          // A missing refresh cookie / 403 is final. An already-rotated token
          // has the same server rejection as expiry; retain one bounded recovery
          // even on a cold tab with no in-memory identity. Never persist identity.
          const detail=r.status===401?(await r.json().catch(()=>null))?.detail:null;
          const rotationRace=r.status===401 && detail!=='无刷新令牌' && (!!auth.me || detail==='会话已失效');
          if(!sessionCurrent(generation,epoch))return false;
          if(attempt===0 && rotationRace)await new Promise(resolve=>setTimeout(resolve,300));
          else break;
        } catch {if(sessionCurrent(generation,epoch))auth.error='身份确认失败，请重试';return false;}
      }
      if(rejected&&sessionCurrent(generation,epoch)){
        auth.requestEpoch++;auth.suspended=!!auth.me;auth.error='';auth.checked=true;clearSecurity();
        if(!auth.me)void loadSiteConfig();
      }
      return false;
    } finally {if(_refreshing===flight)_refreshing=null;}
  })();
  return flight.promise;
}

let identityFlight: {generation:number;epoch:number;promise:Promise<boolean>} | null = null;
export function fetchMe(): Promise<boolean> {
  const generation=auth.sessionGeneration,epoch=auth.requestEpoch;
  if(identityFlight?.generation===generation&&identityFlight.epoch===epoch)return identityFlight.promise;
  const flight={generation,epoch,promise:Promise.resolve(false)};
  identityFlight=flight;
  flight.promise=fetchMeRequest().finally(()=>{if(identityFlight===flight)identityFlight=null;});
  return flight.promise;
}
async function fetchMeRequest(): Promise<boolean> {
  const generation=auth.sessionGeneration,epoch=auth.requestEpoch;
  if(!sessionCurrent(generation,epoch)||auth.suspended)return false;
  try {
    const r=await fetch('/auth/me');
    if(!sessionCurrent(generation,epoch))return false;
    if(r.ok){
      const me=await r.json();if(!sessionCurrent(generation,epoch))return false;
      auth.me=me;auth.error='';auth.checked=true;void migrateLegacyBg();return true;
    }
    if(r.status!==401&&r.status!==403){auth.error='身份确认失败，请重试';auth.checked=true;return false;}
    const refreshed=await refreshAccess();if(!sessionCurrent(generation,epoch))return false;
    if(refreshed){auth.checked=true;void migrateLegacyBg();return true;}
  } catch {if(sessionCurrent(generation,epoch)){auth.error='身份确认失败，请重试';auth.checked=true;}return false;}
  if(!sessionCurrent(generation,epoch))return false;
  auth.checked=true;
  if(!auth.me)void loadSiteConfig();
  return false;
}

/** Public config is coalesced only within the current identity epoch. */
let siteConfigFlight: {generation:number;epoch:number;owner:string|undefined;promise:Promise<void>} | null = null;
export function loadSiteConfig(): Promise<void> {
  const generation=auth.sessionGeneration,epoch=auth.requestEpoch,owner=auth.me?.id;
  if(siteConfigFlight?.generation===generation && siteConfigFlight.epoch===epoch && siteConfigFlight.owner===owner)return siteConfigFlight.promise;
  const flight={generation,epoch,owner,promise:Promise.resolve()};
  siteConfigFlight=flight;
  flight.promise=(async()=>{
    try {
      const [st, bg] = await Promise.all([
        fetch("/auth/status").then((r) => (r.ok ? r.json() : null)),
        fetch("/config/site-background").then((r) => (r.ok ? r.json() : null)),
      ]);
      if(!sessionCurrent(generation,epoch)||auth.me?.id!==owner)return;
      if (st) initialized.value = !!st.initialized;
      if (bg) siteBackground.value = bg.value || "";
    } catch { /* 后端不在就保持默认 */ }
    finally {if(siteConfigFlight===flight)siteConfigFlight=null;}
  })();
  return flight.promise;
}

/** 背景从 localStorage 迁到账号级 home_bg：登录后若 home_bg 空，把旧 localStorage 背景迁过去（一次性） */
async function migrateLegacyBg() {
  const generation=auth.sessionGeneration,epoch=auth.requestEpoch,owner=auth.me?.id;
  if(!owner||!sessionCurrent(generation,epoch))return;
  if (auth.me?.home_bg) return; // 已有账号级背景，不用迁移
  try {
    const legacy = localStorage.getItem("stella_home_bg");
    if (!legacy || legacy === DEFAULT_HOME_BG || legacy === "") return;
    const r = await fetch("/auth/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ home_bg: legacy }),
    });
    if(r.ok){const me=await r.json();if(sessionCurrent(generation,epoch)&&auth.me?.id===owner)auth.me=me;}
  } catch { /* 迁移失败不致命，用户可手动重设 */ }
}

export async function login(username: string, password: string, remember: boolean, device?: string): Promise<string | null> {
  const r = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, remember, device, browser_id: getBrowserId(), entry_origin: window.location.origin }),
  });
  if (!r.ok) return (await r.json()).detail ?? "登录失败";
  acceptLogin(await r.json());
  migrateLegacyBg(); // 迁旧背景（一次性）
  return null;
}

export async function register(username: string, password: string, displayName?: string): Promise<string | null> {
  const r = await fetch("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, display_name: displayName, browser_id: getBrowserId(), entry_origin: window.location.origin }),
  });
  if (!r.ok) return (await r.json()).detail ?? "注册失败";
  acceptLogin(await r.json());
  return null;
}

let logoutFlight: Promise<void> | null = null;
export function logout(): Promise<void> {
  if(logoutFlight)return logoutFlight;
  const epoch=++auth.requestEpoch, generation=auth.sessionGeneration, owner=auth.me?.id;
  auth.logoutError='';auth.sessionClosing=true;clearSecurity();
  const current=()=>auth.sessionClosing&&auth.requestEpoch===epoch&&auth.sessionGeneration===generation&&auth.me?.id===owner;
  const pending=(async()=>{
    try {
      const r=await fetch('/auth/logout',{method:'POST'});
      if(!current())return;
      if(!r.ok)throw new Error('退出未成功，请检查网络后重试');
      // Destroy owner state only after the server's cookie-clearing response settles.
      auth.requestEpoch++;auth.sessionGeneration++;auth.me=null;
      auth.suspended=false;auth.error='';lastActivityReport=0;
    } catch(cause) {
      if(current())auth.logoutError='退出未成功，请检查网络后重试';
      throw cause;
    } finally {
      if(current() || auth.requestEpoch===epoch+1&&auth.me===null&&auth.sessionGeneration===generation+1)auth.sessionClosing=false;
    }
  })();
  logoutFlight=pending;
  void pending.then(()=>{if(logoutFlight===pending)logoutFlight=null;},()=>{if(logoutFlight===pending)logoutFlight=null;});
  return pending;
}

export async function authStatus(): Promise<boolean> {
  try {
    const r = await fetch("/auth/status");
    return (await r.json()).has_users;
  } catch {
    return true;
  }
}
