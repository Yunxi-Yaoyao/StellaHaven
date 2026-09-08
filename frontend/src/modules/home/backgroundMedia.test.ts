// @vitest-environment jsdom
import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import { createApp, effectScope, nextTick, ref } from 'vue';
import SettingsPanel from '../../shell/SettingsPanel.vue';
import BgManager from './BgManager.vue';
import { auth } from './auth';
import { settingsOpen, bgManagerOpen, homeSettings, DEFAULT_HOME_BG } from './settings';
import { backgroundMedia, backgroundEntries, storeBackgroundMedia, useBackgroundMedia, quality, setBackgroundQuality, QUALITY_KEY, reloadBackgroundMedia } from './backgroundMedia';
const url = '/assets/homebg/movie.mp4';
const record = (status: 'ready' | 'processing' | 'missing' | 'error' = 'ready') => ({ url, status, thumbnail: '/thumb.webp', poster: '/poster.webp', variants: { original: url, compressed1: '/small.mp4', compressed2: '/tiny.mp4' } });
const me = { id: 'u', username: 'u', display_name: 'U', is_admin: false, avatar_url: '', home_bg: url, email: '', email_verified: false };
let cleanups: (() => void)[] = [];
beforeEach(() => {
  vi.useFakeTimers(); auth.me = { ...me }; settingsOpen.value = false; bgManagerOpen.value = false;
  backgroundEntries.value = []; for (const key in backgroundMedia) delete backgroundMedia[key];
  setBackgroundQuality('compressed1');
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(record()), { status: 200 })));
});
afterEach(async () => { for (const clean of cleanups) clean(); cleanups = []; await nextTick(); vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML = ''; });
async function flush() { for (let i = 0; i < 20; i++) await Promise.resolve(); await nextTick(); }
function consume(input = ref(url)) {
  const scope = effectScope(); cleanups.push(() => scope.stop());
  return { scope, input, state: scope.run(() => useBackgroundMedia(input))! };
}
function mount(component: typeof SettingsPanel | typeof BgManager) {
  const node = document.createElement('div'); document.body.append(node);
  const app = createApp(component); app.mount(node); cleanups.push(() => app.unmount());
}
test('shared quality updates all consumers immediately without changing original identity', async () => {
  storeBackgroundMedia(record()); const a = consume(); const b = consume();
  expect(a.state.source.value).toBe('/small.mp4'); setBackgroundQuality('compressed2');
  expect(b.state.source.value).toBe('/tiny.mp4'); expect(auth.me?.home_bg).toBe(url);
  expect(localStorage.getItem(QUALITY_KEY)).toBe('compressed2');
  setBackgroundQuality('invalid'); expect(quality.value).toBe('compressed1');
  setBackgroundQuality('original'); expect(a.state.source.value).toBe(url);
});
test('missing variants fall back to original and external URLs never query backend', async () => {
  const a = consume(ref('https://outside.example/x.mp4')); await flush();
  expect(a.state.source.value).toBe('https://outside.example/x.mp4'); expect(fetch).not.toHaveBeenCalled();
  storeBackgroundMedia({ ...record(), variants: { original: url } });
  expect(consume().state.source.value).toBe(url);
});
test('requests singleflight and active polling stops with the last scope', async () => {
  vi.mocked(fetch).mockImplementation(async () => new Response(JSON.stringify(record('processing'))));
  await Promise.all([reloadBackgroundMedia(url), reloadBackgroundMedia(url)]); expect(fetch).toHaveBeenCalledTimes(1);
  const a = consume(); const b = consume(); await flush();
  await vi.advanceTimersByTimeAsync(3000); expect(fetch).toHaveBeenCalledTimes(2);
  a.scope.stop(); b.scope.stop(); await vi.advanceTimersByTimeAsync(30000); expect(fetch).toHaveBeenCalledTimes(2);
});
test('polling stops on failure and unauthenticated consumers never poll', async () => {
  storeBackgroundMedia(record('processing')); const a = consume();
  vi.mocked(fetch).mockRejectedValue(new Error('offline')); await vi.advanceTimersByTimeAsync(3000);
  expect(a.state.status.value).toBe('error'); const calls = vi.mocked(fetch).mock.calls.length;
  await vi.advanceTimersByTimeAsync(30000); expect(fetch).toHaveBeenCalledTimes(calls);
  a.scope.stop(); auth.me = null; storeBackgroundMedia(record('processing')); consume();
  await vi.advanceTimersByTimeAsync(30000); expect(fetch).toHaveBeenCalledTimes(calls);
});
test('missing logged-in managed background automatically queues exactly once', async () => {
  let queued = false;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input) === '/homebg/') return new Response(JSON.stringify([{ id: 'entry', name: 'Movie', url, ext: 'mp4', isDefault: false }]));
    if (init?.method === 'POST') { queued = true; return new Response(JSON.stringify(record('processing'))); }
    return new Response(JSON.stringify(record(queued ? 'processing' : 'missing')));
  });
  consume(); consume(); await flush();
  expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
});
test('settings uses effective account name, static thumbnail and nonoptimistic reset', async () => {
  const entry = { id: 'entry', name: 'Account movie', url, ext: 'mp4', isDefault: false, media: record() };
  storeBackgroundMedia(record()); homeSettings.bgImage = '/stale.png'; settingsOpen.value = true;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input) === '/homebg/') return new Response(JSON.stringify([entry]));
    if (init?.method === 'PATCH') return new Response('{}', { status: 500 });
    return new Response(JSON.stringify(record()));
  });
  mount(SettingsPanel); await flush();
  expect(document.querySelector('.bg-name')?.textContent).toBe('Account movie');
  expect(document.querySelector('.bg-preview img')?.getAttribute('src')).toBe('/thumb.webp');
  expect(document.querySelector('.bg-preview video')).toBeNull();
  const reset = [...document.querySelectorAll('button')].find(e => e.textContent === '恢复默认')!;
  reset.click(); await flush(); expect(auth.me?.home_bg).toBe(url);
  vi.mocked(fetch).mockImplementation(async () => new Response(JSON.stringify({ ...me, home_bg: DEFAULT_HOME_BG })));
  reset.click(); await flush(); expect(auth.me?.home_bg).toBe(DEFAULT_HOME_BG);
});
test('manager grid never creates videos, and upload network failure clears busy state', async () => {
  const entry = { id: 'entry', name: 'Movie', url, ext: 'mp4', isDefault: false, media: record() };
  vi.mocked(fetch).mockImplementation(async (input) => {
    if (String(input) === '/homebg/upload') throw new Error('offline');
    return new Response(JSON.stringify([entry]));
  });
  storeBackgroundMedia(record()); bgManagerOpen.value = true; mount(BgManager); await flush();
  expect(document.querySelector('.grid video')).toBeNull();
  expect(document.querySelector('.thumb img')?.getAttribute('src')).toBe('/thumb.webp');
  const input = document.querySelector('input[type=file]')!;
  Object.defineProperty(input, 'files', { value: [new File(['x'], 'test.mp4')], configurable: true });
  input.dispatchEvent(new Event('change')); await flush();
  expect(document.querySelector('.err')?.textContent).toContain('offline');
  expect(document.querySelector('.drop')?.textContent).not.toContain('上传中');
});
