import {createApp,nextTick,type App} from 'vue';
import {it,expect,afterEach} from 'vitest';
import SessionRecordRow from './SessionRecordRow.vue';
let app:App;
afterEach(()=>{app?.unmount();document.body.innerHTML='';});
const row={id:'fixture-row',device:'Very long unknown user agent '.repeat(12),browser_name:'Firefox',os_name:'Android',ip:'2001:db8:1234:5678:abcd:ef01:2345:6789',remember:true,current:false,created_at:'2026-10-21T01:00:00Z',last_seen:'2026-10-21T01:05:00Z',expires_at:'2026-10-22T01:00:00Z',login_origin:'https://long-entry.example.test:5060'};
it('keeps session identity and actions above network/activity and collapses complete audit details',async()=>{
 const root=document.createElement('div');document.body.append(root);let revoked=0;
 app=createApp(SessionRecordRow,{row,onRevoke:()=>revoked++});app.mount(root);await nextTick();
 const summary=root.querySelector('.session-summary')!;expect(summary).not.toBeNull();expect(summary.textContent).toContain('Firefox · Android');expect(summary.textContent).toContain('有效会话');expect(summary.querySelector('button')?.textContent).toBe('下线');
 const network=root.querySelector('.session-network')!;expect(network.textContent).toContain(row.ip);expect(network.textContent).toContain('最近活动');
 const details=root.querySelector<HTMLElement>('.session-details')!;expect(details).not.toBeNull();expect(details.hidden).toBe(true);expect(details.textContent).toContain(row.login_origin);expect(details.textContent).toContain(row.device);for(const label of ['登录','到期','记住我'])expect(details.textContent).toContain(label);
 const toggle=root.querySelector<HTMLButtonElement>('[aria-expanded]')!;expect(toggle.getAttribute('aria-controls')).toBe(details.id);toggle.click();await nextTick();expect(details.hidden).toBe(false);expect(toggle.getAttribute('aria-expanded')).toBe('true');summary.querySelector<HTMLButtonElement>('button')!.click();expect(revoked).toBe(1);
});
