import { expect, test, vi } from 'vitest';
const state = vi.hoisted(() => ({ homeImports: 0, privateImports: 0, release: null as null | (() => void) }));
vi.mock('../modules/home/HomePage.vue', () => { state.homeImports++; return { __esModule: true, default: { render: () => null } }; });
vi.mock('../modules/settings/SettingsPage.vue', () => { state.privateImports++; return { __esModule: true, default: { render: () => null } }; });
vi.mock('../modules/auth/LoginPage.vue', () => ({ __esModule: true, default: { render: () => null } }));
vi.mock('../modules/home/auth', () => {
 const auth = { checked: false };
 return { auth, loggedIn: { value: false }, fetchMe: () => new Promise<void>(resolve => { state.release = () => { auth.checked = true; resolve(); }; }) };
});
async function pendingGuard() { for (let i = 0; i < 30; i++) await new Promise(resolve => setTimeout(resolve, 0)); expect(state.release).not.toBeNull(); }
test('only selected public route starts importing while session check is pending', async () => {
 const { default: router } = await import('./index');
 const pending = router.push('/'); await pendingGuard();
 expect(state.homeImports).toBe(1);
 state.release!(); await pending;
 expect(router.currentRoute.value.name).toBe('home');
});
test('unauthenticated private route is not prefetched and still redirects to login', async () => {
 const { default: router } = await import('./index');
 const { auth } = await import('../modules/home/auth'); auth.checked = false; state.release = null;
 const pending = router.push('/settings'); await pendingGuard();
 expect(state.privateImports).toBe(0);
 state.release!(); await pending;
 expect(router.currentRoute.value.name).toBe('login');
 expect(router.currentRoute.value.query.next).toBe('/settings');
 expect(state.privateImports).toBe(0);
});
