import { beforeEach, expect, it, vi } from 'vitest';
import settingsSource from '../settings/SettingsPage.vue?raw';
import appSource from '../../App.vue?raw';
vi.mock('./settings', () => ({ homeSettings: {}, siteBackground: { value: '' }, DEFAULT_HOME_BG: '' }));
import * as store from './auth';
beforeEach(() => { vi.restoreAllMocks(); store.auth.me = { id: 'u' } as any; });
it('only trusted visible input sends throttled activity', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true });
  vi.stubGlobal('fetch', fetch);
  expect(typeof store.reportActivity).toBe('function');
  await store.reportActivity({ isTrusted: false } as Event);
  expect(fetch).not.toHaveBeenCalled();
  await store.reportActivity({ isTrusted: true } as Event);
  await store.reportActivity({ isTrusted: true } as Event);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith('/auth/activity', { method: 'POST' });
});
it('history starts folded and offers bounded navigation', () => {
  const source = settingsSource;
  expect(source).toContain('<details');
  expect(source).toContain('loadHistory');
  expect(source).toContain('historyPage');
  expect(source).toContain('historyTotal');
  expect(source).toContain('page_size=20');
});
it('watchdog installs and removes explicit input listeners', () => {
  const source = appSource;
  expect(source).toContain('addEventListener(event, reportActivity');
  expect(source).toContain('removeEventListener(event, reportActivity');
});

it('temporary refresh failure retains known session', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok:false,status:503}));
  expect(await store.refreshAccess()).toBe(false);
  expect(store.auth.me?.id).toBe('u');
});
it('failed logout does not falsely report local logout', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok:false,status:503}));
  await expect(store.logout()).rejects.toThrow();
  expect(store.auth.me?.id).toBe('u');
});
