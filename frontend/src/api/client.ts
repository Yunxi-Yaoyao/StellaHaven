// fetch 封装：统一 JSON、错误带 status（409 乐观锁要靠它区分）
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
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
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
