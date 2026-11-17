import { reactive } from 'vue';

/** Public capability cache. Unknown never means an uninitialized installation. */
export const loginStatus = reactive({ initialized: null as boolean | null, emailEnabled: false });
let checkedAt = 0;
let pending: Promise<void> | null = null;
let generation = 0;

/** Successful authentication proves initialization; fence older public status reads. */
export function confirmLoginInitialized(): void {
 generation++;
 loginStatus.initialized = true;
 checkedAt = 0;
}

/** Warm from App startup; modal opens synchronously and never waits for transport. */
export function refreshLoginStatus(): Promise<void> {
 if (pending) return pending;
 if (checkedAt && Date.now() - checkedAt < 30000) return Promise.resolve();
 const controller = new AbortController();
 const sequence = generation;
 const timeout = setTimeout(() => controller.abort(), 8000);
 pending = (async () => {
  try {
   const response = await fetch('/auth/status', { signal: controller.signal });
   if (!response.ok) return;
   const status = await response.json();
   if (sequence !== generation || typeof status.initialized !== 'boolean') return;
   loginStatus.initialized = status.initialized;
   loginStatus.emailEnabled = status.email_enabled === true;
   checkedAt = Date.now();
  } catch { /* Keep known capabilities; ordinary password login remains available. */ }
  finally { clearTimeout(timeout); pending = null; }
 })();
 return pending;
}
