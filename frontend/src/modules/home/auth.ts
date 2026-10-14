// 认证 store：当前用户、登录态、登录/登出/refresh 动作。
// access token 在 httpOnly cookie（30min），401 时静默 refresh 续命。
import { reactive, ref, computed } from "vue";
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
  suspended: false, // Confirmed expiry freezes mounted drafts until reauthentication.
  checked: false, // 首次 /auth/me 探测过没有
  error: '', // Transport failures are not a confirmed guest session.
});

export const loggedIn = computed(() => auth.me !== null && !auth.suspended && !auth.sessionClosing);
/** Only an explicit successful login can resume an expired owner. */
export function acceptLogin(me:Me){
 auth.requestEpoch++;
 const resume=auth.suspended&&auth.me?.id===me.id&&!auth.sessionClosing;
 if(!resume)auth.sessionGeneration++;
 auth.sessionClosing=false;auth.suspended=false;auth.error='';auth.me=me;auth.checked=true;
}
export interface SecurityState { enabled:boolean; configured:boolean; elevated:boolean; expires_at:string|null; single_user:boolean; setup_required:boolean }
export const security = reactive<SecurityState>({enabled:true,configured:false,elevated:false,expires_at:null,single_user:true,setup_required:true});
export const securityChecked = ref(false);
export const isAdmin = computed(() => !!auth.me && securityChecked.value && (!security.enabled || security.elevated && (!security.expires_at || Date.parse(security.expires_at)>Date.now())));
let securityExpiry:ReturnType<typeof setTimeout>|undefined;
let securityGeneration=0;
export async function loadSecurity() {
  const owner=auth.me?.id,sequence=++securityGeneration;
  const r = await fetch('/auth/security');
  if (!r.ok) { securityChecked.value=false; throw new Error('安全状态加载失败'); }
  const state=await r.json();if(sequence!==securityGeneration||owner!==auth.me?.id)return;
  Object.assign(security, state); securityChecked.value=true;
  clearTimeout(securityExpiry);
  if(security.enabled && security.elevated && security.expires_at)securityExpiry=setTimeout(()=>{security.elevated=false;},Math.max(0,Date.parse(security.expires_at)-Date.now()));
}
export function clearSecurity() { securityGeneration++;clearTimeout(securityExpiry);securityChecked.value=false; Object.assign(security,{enabled:true,configured:false,elevated:false,expires_at:null,setup_required:true}); }
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

let _refreshing: {generation:number;promise:Promise<boolean>} | null = null;
const sessionCurrent=(generation:number)=>generation===auth.sessionGeneration&&!auth.sessionClosing;
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
  const generation=auth.sessionGeneration;
  if(!sessionCurrent(generation)||auth.suspended)return Promise.resolve(false);
  if(_refreshing?.generation===generation)return _refreshing.promise;
  // A late old finally must not clear the new session's single-flight request.
  const flight={generation,promise:Promise.resolve(false)};
  _refreshing=flight;
  flight.promise=(async()=>{
    let rejected=false;
    try {
      for(let attempt=0;attempt<2;attempt++) {
        if(!sessionCurrent(generation))return false;
        try {
          const r=await fetch('/auth/refresh',{method:'POST'});
          if(!sessionCurrent(generation))return false;
          if(r.ok){const me=await r.json();if(!sessionCurrent(generation))return false;auth.me=me;auth.error='';return true;}
          if(r.status!==401&&r.status!==403){auth.error='身份确认失败，请重试';return false;}
          rejected=true;
          if(attempt===0)await new Promise(resolve=>setTimeout(resolve,300));
        } catch {if(sessionCurrent(generation))auth.error='身份确认失败，请重试';return false;}
      }
      if(rejected&&sessionCurrent(generation)){auth.requestEpoch++;auth.suspended=!!auth.me;auth.error='';clearSecurity();}
      return false;
    } finally {if(_refreshing===flight)_refreshing=null;}
  })();
  return flight.promise;
}

export async function fetchMe(): Promise<boolean> {
  const generation=auth.sessionGeneration;
  if(!sessionCurrent(generation)||auth.suspended)return false;
  try {
    const r=await fetch('/auth/me');
    if(!sessionCurrent(generation))return false;
    if(r.ok){
      const me=await r.json();if(!sessionCurrent(generation))return false;
      auth.me=me;auth.error='';auth.checked=true;void migrateLegacyBg();return true;
    }
    if(r.status!==401&&r.status!==403){auth.error='身份确认失败，请重试';auth.checked=true;return false;}
    const refreshed=await refreshAccess();if(!sessionCurrent(generation))return false;
    if(refreshed){auth.checked=true;void migrateLegacyBg();return true;}
  } catch {if(sessionCurrent(generation)){auth.error='身份确认失败，请重试';auth.checked=true;}return false;}
  if(!sessionCurrent(generation))return false;
  auth.checked=true;
  if(!auth.me)void loadSiteConfig();
  return false;
}

/** 未登录访客：拉初始化状态 + 站点背景，决定主页背景显示哪张 */
export async function loadSiteConfig(): Promise<void> {
  try {
    const [st, bg] = await Promise.all([
      fetch("/auth/status").then((r) => (r.ok ? r.json() : null)),
      fetch("/config/site-background").then((r) => (r.ok ? r.json() : null)),
    ]);
    if (st) initialized.value = !!st.initialized;
    if (bg) siteBackground.value = bg.value || "";
  } catch { /* 后端不在就保持默认 */ }
}

/** 背景从 localStorage 迁到账号级 home_bg：登录后若 home_bg 空，把旧 localStorage 背景迁过去（一次性） */
async function migrateLegacyBg() {
  const generation=auth.sessionGeneration,owner=auth.me?.id;
  if(!owner||!sessionCurrent(generation))return;
  if (auth.me?.home_bg) return; // 已有账号级背景，不用迁移
  try {
    const legacy = localStorage.getItem("stella_home_bg");
    if (!legacy || legacy === DEFAULT_HOME_BG || legacy === "") return;
    const r = await fetch("/auth/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ home_bg: legacy }),
    });
    if(r.ok){const me=await r.json();if(sessionCurrent(generation)&&auth.me?.id===owner)auth.me=me;}
  } catch { /* 迁移失败不致命，用户可手动重设 */ }
}

export async function login(username: string, password: string, remember: boolean, device?: string): Promise<string | null> {
  const r = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, remember, device }),
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
    body: JSON.stringify({ username, password, display_name: displayName }),
  });
  if (!r.ok) return (await r.json()).detail ?? "注册失败";
  acceptLogin(await r.json());
  return null;
}

export async function logout(): Promise<void> {
  auth.requestEpoch++;auth.sessionClosing = true; auth.sessionGeneration++;
  clearSecurity();
  const r = await fetch("/auth/logout", { method: "POST" });
  if (!r.ok) throw new Error('退出未成功，请检查网络后重试');
  auth.me = null; auth.suspended=false; auth.sessionClosing = false; auth.error='';
  lastActivityReport = 0;
}

export async function authStatus(): Promise<boolean> {
  try {
    const r = await fetch("/auth/status");
    return (await r.json()).has_users;
  } catch {
    return true;
  }
}
