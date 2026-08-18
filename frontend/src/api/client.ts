// fetch 封装：统一 JSON、错误带 status（409 乐观锁要靠它区分）
import { refreshAccess } from "../modules/home/auth";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(`API ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const doFetch = () =>
    fetch(path, { headers: { "Content-Type": "application/json" }, ...options });

  let resp = await doFetch();
  // access token 过期（30min）→ 单例 refresh 续命后重试一次
  if (resp.status === 401) {
    if (await refreshAccess()) resp = await doFetch();
  }
  if (!resp.ok) {
    let detail: unknown = null;
    try {
      detail = (await resp.json()).detail;
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}
