import { expect, test, vi } from 'vitest';
import { createApp, nextTick } from 'vue';
const imports = vi.hoisted(() => ({ pixi: 0 }));
vi.mock('pixi.js', () => { imports.pixi++; return {}; });
vi.mock('./BgLayer.vue', () => ({ default: { render: () => null } }));
vi.mock('./settings', () => ({ homeSettings: {theme:'daybreak', particles:'off', live2d: false, signature:'', meetDate:'2026-05-31'}, settingsOpen: {value:false} }));
vi.mock('./auth', () => ({ displayBg: {value:''}, loggedIn:{value:false}, currentAvatar:{value:''}, currentUser:{value:null} }));

test('disabled Home never loads Pixi or Cubism runtime', async () => {
  const { default: Home } = await import('./HomePage.vue');
  const host=document.createElement('div'); document.body.append(host);
  const app=createApp(Home); app.mount(host);
  for(let i=0;i<20;i++) await Promise.resolve(); await nextTick();
  expect(imports.pixi).toBe(0);
  expect(document.querySelector('script[src*="cubism"]')).toBeNull();
  app.unmount(); host.remove();
});
