import {it,expect} from 'vitest';
import {createApp,nextTick} from 'vue';
import AppearanceSettings from './AppearanceSettings.vue';
it('describes account synchronization and local cache without an extra save control',async()=>{
 const host=document.createElement('div'),app=createApp(AppearanceSettings);document.body.append(host);app.mount(host);await nextTick();
 try{
  expect(host.querySelector('.appearance-sync')?.textContent).toContain('登录后随账号同步');
  host.querySelector<HTMLButtonElement>('[aria-label="外观范围"]')!.click();await nextTick();
  expect(document.body.querySelector('[role="tooltip"]')?.textContent).toContain('登录后随账号同步，本机保留缓存');
  expect(host.textContent).not.toContain('自动保存到当前设备');
  expect(host.querySelector('[aria-label="配色选择"]')?.querySelectorAll('button')).toHaveLength(3);
  expect(host.querySelector('[role="switch"][aria-label="调色模式"]')).not.toBeNull();
  expect(host.querySelector('[aria-label="Stella 交互样板"]')).not.toBeNull();
  expect([...host.querySelectorAll('button')].some(button=>button.textContent?.trim()==='保存外观')).toBe(false);
 }finally{app.unmount();host.remove();}
});
