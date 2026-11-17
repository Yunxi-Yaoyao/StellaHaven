import {expect,it,vi,afterEach} from 'vitest';
import {createApp,nextTick} from 'vue';
import AppearanceSettings from './AppearanceSettings.vue';
import * as s from '../../stores/appearance';
import {clientPreferenceSync} from './clientPreferenceSync';
const roots:(()=>void)[]=[];afterEach(()=>{roots.splice(0).forEach(f=>f());s.cancelAppearanceEdit();localStorage.clear();clientPreferenceSync.state.phase='idle';});
async function mount(){const root=document.createElement('div');document.body.append(root);const app=createApp(AppearanceSettings);app.mount(root);roots.push(()=>{app.unmount();root.remove();});await nextTick();return root;}
it('commits each valid color without done; close, object change, mode and unmount never discard it',async()=>{
 s.hydrateAppearance('A',null);const fetch=vi.spyOn(window,'fetch');const root=await mount();
 const toggle=root.querySelector<HTMLButtonElement>('[role=switch][aria-label="调色模式"]')!;expect(toggle.getAttribute('aria-checked')).toBe('true');
 root.querySelector<HTMLElement>('[data-theme-part="primary"]')!.click();await nextTick();expect(s.appearance.value).toBe('A');
 const input=root.querySelector<HTMLInputElement>('[aria-label="颜色值"]')!;input.value='#123456';input.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();
 expect(s.appearancePreference.value.appearance).toBe('custom');expect(root.textContent).not.toMatch(/完成后|取消本次|完成调色|恢复基底/);
 root.querySelector<HTMLButtonElement>('[aria-label="关闭调色器"]')!.click();await nextTick();expect(s.resolvedPalette.value['button-top']).toBe('#123456');
 root.querySelector<HTMLElement>('[data-theme-part="primary"]')!.click();await nextTick();toggle.click();await nextTick();expect(toggle.getAttribute('aria-checked')).toBe('false');expect(localStorage.getItem('stella_appearance_edit_mode')).toBe('off');
 roots.pop()!();expect(JSON.parse(localStorage.getItem('stella_custom_appearance')!).overrides['button-top']).toBe('#123456');expect(fetch).not.toHaveBeenCalled();fetch.mockRestore();
});
it('rejects incomplete color without changing the saved value or trapping close',async()=>{
 s.hydrateAppearance('A',null);const root=await mount();root.querySelector<HTMLElement>('[data-theme-part="page"]')!.click();await nextTick();
 const input=root.querySelector<HTMLInputElement>('[aria-label="颜色值"]')!;input.value='#12';input.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();expect(input.getAttribute('aria-invalid')).toBe('true');expect(s.appearance.value).toBe('A');
 root.querySelector<HTMLButtonElement>('[aria-label="关闭调色器"]')!.click();await nextTick();expect(root.querySelector('[aria-label="颜色值"]')).toBeNull();
});
it('has no normal recovery/sync action row and errors retain a single contextual retry',async()=>{
 s.hydrateAppearance('A',null);const root=await mount();expect(root.querySelector('.sync-actions')).toBeNull();expect(root.querySelector('.recovery')).toBeNull();
 clientPreferenceSync.state.phase='error';clientPreferenceSync.state.message='网络暂不可用';await nextTick();expect(root.textContent).toContain('同步失败，本机配色已保存');root.querySelector<HTMLButtonElement>('[aria-label=同步失败详情]')!.click();await nextTick();expect(document.body.querySelector('[role=tooltip]')?.textContent).toContain('网络暂不可用');expect(root.querySelectorAll('[data-appearance-retry]')).toHaveLength(1);expect(root.textContent).not.toMatch(/保留本机|使用账号配色/);
});
it('uses shared busy button spinner rather than adding a duplicate child spinner',async()=>{
 const root=await mount();const busy=root.querySelector('[aria-busy=true]')!;expect(busy.textContent).toContain('处理中');expect(busy.children).toHaveLength(0);
});
