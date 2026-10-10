import { afterEach, expect, test } from 'vitest';
import { createApp, h } from 'vue';
import Panel from './StoragePanel.vue';
import type { StorageStatus } from '../../api/servers';
let app: ReturnType<typeof createApp> | undefined;
let root: HTMLElement;
afterEach(() => { app?.unmount(); root?.remove(); });
const item = { device: 'disk0', mount: 'D:/', kind: 'volume', total: 1000, used: 500, percent: 50, fstype: 'NTFS', usage_scope: 'measured', sampled_at: '2026-10-10T08:00:00Z' };
function mount(status: StorageStatus, now=Date.parse('2026-10-10T08:00:05Z')) {
 root=document.createElement('div');document.body.append(root);
 app=createApp({render:()=>h(Panel,{storage:[item] as any,storageStatus:status,now})});app.mount(root);
}
test('failed refresh keeps valid storage rows and immediately reports concise failure',()=>{
 mount({state:'query_failed',sampled_at:item.sampled_at,attempted_at:'2026-10-10T08:00:04Z'});
 expect(root.textContent).toContain('存储刷新失败');expect(root.textContent).toContain('D:/');expect(root.textContent).toContain('50 %');
 expect(root.textContent).not.toContain('未读取');expect(root.textContent).not.toContain('来源');
});
test('available storage is quiet, not a diagnostic status block',()=>{
 mount({state:'available',sampled_at:item.sampled_at});expect(root.querySelector('[role=status]')).toBeNull();
});
test('failed old snapshot shows both failure and age without updating the measurement',()=>{
 mount({state:'query_failed',sampled_at:item.sampled_at},Date.parse('2026-10-10T08:04:00Z'));
 expect(root.textContent).toContain('存储刷新失败');expect(root.textContent).toContain('数据已过期');
});
