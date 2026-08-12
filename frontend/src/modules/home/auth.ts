// 认证 store：当前用户、登录态、登录/登出/refresh 动作。
// access token 在 httpOnly cookie（30min），401 时静默 refresh 续命。
import { reactive, computed } from "vue";
import { homeSettings } from "./settings";

export interface Me {
  id: string;
  username: string;
  display_name: string;
  is_admin: boolean;
  avatar_url: string;
  email: string;
  email_verified: boolean;
}

export const auth = reactive({
  me: null as Me | null,
  checked: false, // 首次 /auth/me 探测过没有
});

export const loggedIn = computed(() => auth.me !== null);
export const isAdmin = computed(() => auth.me?.is_admin === true);
/** 头像唯一出口：登录用户的头像优先级最高，签名卡/侧栏都借它；未登录回退站点默认 */
export const currentAvatar = computed(() =>
  auth.me?.avatar_url || homeSettings.avatar
);

export async function fetchMe(): Promise<boolean> {
  try {
    const r = await fetch("/auth/me");
    if (r.ok) {
      auth.me = await r.json();
      auth.checked = true;
      return true;
    }
    // access 过期 → 试 refresh
    const rr = await fetch("/auth/refresh", { method: "POST" });
    if (rr.ok) {
      auth.me = await rr.json();
      auth.checked = true;
      return true;
    }
  } catch { /* 后端不在 */ }
  auth.me = null;
  auth.checked = true;
  return false;
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
