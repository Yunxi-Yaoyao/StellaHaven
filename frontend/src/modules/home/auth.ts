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
  checked: false, // 首次 /auth/me 探测过没有
});

export const loggedIn = computed(() => auth.me !== null);
export const isAdmin = computed(() => auth.me?.is_admin === true);
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

let _refreshing: Promise<boolean> | null = null;

/** 单例 refresh：并发 401 时只发一个 refresh，避免旋转制 refresh token 被并发转废 */
export function refreshAccess(): Promise<boolean> {
  if (!_refreshing) {
    _refreshing = (async () => {
      try {
        for (let attempt = 0; attempt < 2; attempt++) {
          try {
            const r = await fetch("/auth/refresh", { method: "POST" });
            if (r.ok) {
              auth.me = await r.json();
              return true;
            }
            // 401 可能是同域名多 tab 并发旋转（另一个 tab 已更新 cookie），稍等后用新 cookie 重试
            await new Promise((res) => setTimeout(res, 300));
          } catch {
            /* 网络错误 */
          }
        }
        auth.me = null; // 重试仍失败 → 会话真失效，清登录态
        return false;
      } finally {
        _refreshing = null;
      }
    })();
  }
  return _refreshing;
}

export async function fetchMe(): Promise<boolean> {
  try {
    const r = await fetch("/auth/me");
    if (r.ok) {
      auth.me = await r.json();
      auth.checked = true;
      migrateLegacyBg(); // 迁旧背景
      return true;
    }
    // access 过期 → 试 refresh（单例）
    if (await refreshAccess()) {
      auth.checked = true;
      migrateLegacyBg(); // 迁旧背景
      return true;
    }
  } catch { /* 后端不在 */ }
  auth.me = null;
  auth.checked = true;
  loadSiteConfig(); // 未登录 → 拉初始化状态 + 管理员站点背景
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
  if (auth.me?.home_bg) return; // 已有账号级背景，不用迁移
  try {
    const legacy = localStorage.getItem("stella_home_bg");
    if (!legacy || legacy === DEFAULT_HOME_BG || legacy === "") return;
    const r = await fetch("/auth/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ home_bg: legacy }),
    });
    if (r.ok) auth.me = await r.json();
  } catch { /* 迁移失败不致命，用户可手动重设 */ }
}

export async function login(username: string, password: string, remember: boolean, device?: string): Promise<string | null> {
  const r = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, remember, device }),
  });
  if (!r.ok) return (await r.json()).detail ?? "登录失败";
  auth.me = await r.json();
  auth.checked = true;
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
  auth.me = await r.json();
  auth.checked = true;
  return null;
}

export async function logout(): Promise<void> {
  await fetch("/auth/logout", { method: "POST" });
  auth.me = null;
}

export async function authStatus(): Promise<boolean> {
  try {
    const r = await fetch("/auth/status");
    return (await r.json()).has_users;
  } catch {
    return true;
  }
}
