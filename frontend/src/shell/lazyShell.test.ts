import { afterEach, expect, test, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, ref } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
const loaded = vi.hoisted(() => ({ palette: 0, settings: 0, background: 0 }));
vi.mock('./SideBar.vue', () => ({ default: { render: () => null } }));
vi.mock('./AdminElevationModal.vue', () => ({ default: { render: () => null } }));
vi.mock('./ExternalModuleCache.vue', () => ({ default: { render: () => null } }));
vi.mock('./SettingsPanel.vue', () => { loaded.settings++; return { default: { render: () => null } }; });
vi.mock('../modules/home/BgManager.vue', () => { loaded.background++; return { __esModule: true, default: { render: () => h('div', { class: 'background-test' }) } }; });
vi.mock('../modules/notes/CommandPalette.vue', () => {
 loaded.palette++;
 return { __esModule: true, default: defineComponent({ setup(_, { expose }) { const open = ref(false); expose({ show: () => { open.value = true; }, close: () => { open.value = false; } }); return () => open.value ? h('div', { role: 'dialog' }, 'palette-test') : null; } }) };
});
vi.mock('../modules/home/auth', async () => {
 const { reactive, computed } = await import('vue');
 const auth = reactive({ me: { id: 'test-owner' } as {id:string}|null, sessionGeneration: 0, sessionClosing: false });
 return { auth, loggedIn: computed(() => !!auth.me), fetchMe: vi.fn(), reportActivity: vi.fn(), loadSecurity: vi.fn().mockResolvedValue(undefined), clearSecurity: vi.fn() };
});
vi.mock('../stores/navigation', () => ({ navigationRows: ref([]), loadNavigation: vi.fn(), resetNavigation: vi.fn() }));
vi.mock('../stores/notes', () => ({ useNotesStore: () => ({ resetSession: vi.fn() }) }));
vi.mock('../stores/notifications', () => ({ startNotifications: vi.fn(), stopNotifications: vi.fn() }));
const cleanup: (() => void)[] = [];
afterEach(() => { cleanup.splice(0).forEach(f => f()); });
async function flush() { for (let i = 0; i < 30; i++) { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick(); } }
async function mountShell() {
 const { default: App } = await import('../App.vue');
 const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }, { path: '/settings', component: { render: () => null } }] });
 await router.push('/'); await router.isReady();
 const host = document.createElement('div'); document.body.append(host);
 const app = createApp(App).use(router); app.mount(host);
 cleanup.push(() => { app.unmount(); host.remove(); }); await flush(); return router;
}
test('closed palette preserves its lightweight global integration marker', async () => {
 await mountShell();
 expect(document.querySelector('.command-palette-root')).not.toBeNull();
 expect(loaded.palette).toBe(0);
});
test('authenticated shell does not import closed command palette', async () => {
 await mountShell();
 expect(loaded.palette).toBe(0);
 window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, cancelable: true }));
 await flush();
 expect(loaded.palette).toBe(1);
 expect(document.querySelector('[role="dialog"]')?.textContent).toBe('palette-test');
});
test('background manager is imported on first open and retained after close', async () => {
 const { bgManagerOpen } = await import('../modules/home/settings');
 bgManagerOpen.value = false;
 await mountShell();
 expect(loaded.background).toBe(0);
 bgManagerOpen.value = true; await flush();
 expect(loaded.background).toBe(1);
 expect(document.querySelector('.background-test')).not.toBeNull();
 bgManagerOpen.value = false; await flush();
 expect(document.querySelector('.background-test')).not.toBeNull();
});
test('legacy home settings trigger redirects without importing appearance form', async () => {
 const { settingsOpen } = await import('../modules/home/settings');
 settingsOpen.value = false;
 const router = await mountShell();
 expect(loaded.settings).toBe(0);
 settingsOpen.value = true; await flush();
 expect(router.currentRoute.value.fullPath).toBe('/settings?section=navigation&module=home');
 expect(settingsOpen.value).toBe(false);
});
test('two shortcut presses before async mount cancel the pending opening', async () => {
 await mountShell();
 window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, cancelable: true }));
 window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, cancelable: true }));
 await flush();
 expect(document.querySelector('[role="dialog"]')).toBeNull();
});
test('custom event opens on first intent and logout removes activation listeners', async () => {
 await mountShell();
 window.dispatchEvent(new Event('stella:command-palette')); await flush();
 expect(document.querySelector('[role="dialog"]')).not.toBeNull();
 const { auth } = await import('../modules/home/auth');
 auth.me = null; await flush();
 window.dispatchEvent(new Event('stella:command-palette')); await flush();
 expect(document.querySelector('[role="dialog"]')).toBeNull();
});
