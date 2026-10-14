import { refreshAccess, auth } from '../modules/home/auth';
export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) { super(`API ${status}`); this.status = status; this.detail = detail; }
}
export type ElevationCode = 'admin_elevation_required' | 'admin_setup_required';
type ElevationHandler = (code: ElevationCode, path: string) => Promise<boolean>;
let elevationHandler: ElevationHandler | undefined;
export function setElevationHandler(handler?: ElevationHandler) { elevationHandler = handler; }
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  if (typeof FormData !== 'undefined' && options?.body instanceof FormData) {
    headers.delete('Content-Type'); // Browser supplies the matching multipart boundary.
  } else if (typeof options?.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const generation=auth.sessionGeneration,epoch=auth.requestEpoch,owner=auth.me?.id;
  const check=()=>{if(auth&&(auth.suspended||auth.sessionClosing||generation!==auth.sessionGeneration||epoch!==auth.requestEpoch||owner!==auth.me?.id))throw new DOMException('登录后继续','AbortError');};
  const doFetch = () => {check();return fetch(path, { ...options, headers });};
  let response = await doFetch();
  if (response.status === 401 && !path.startsWith('/auth/admin/') && path !== '/auth/security' && await refreshAccess()) response = await doFetch();
  if (response.status === 403 && elevationHandler && !path.startsWith('/auth/admin/') && path !== '/auth/security') {
    const detail = await response.clone().json().then(body => body.detail).catch(() => null);
    if (['admin_elevation_required','admin_setup_required'].includes(detail?.code) && await elevationHandler(detail.code, path)) {
      if (options?.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      response = await doFetch(); // Exactly one retry, after the user's explicit confirmation.
    }
  }
  if (!response.ok) {
    const detail = await response.json().then(body => body.detail).catch(() => null);
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  const value=await response.json();check();return value;
}
