import { expect, it, vi, afterEach } from 'vitest';
import { createApp, nextTick } from 'vue';
import type { Component } from 'vue';
import { api } from '../../api/client';
vi.mock('../../api/client', () => ({ api: vi.fn() }));
const panels = import.meta.glob('./BackupHealthPanel.vue', { eager: true, import: 'default' });
afterEach(() => { vi.resetAllMocks(); document.body.innerHTML = ''; });
it('shows checksum and restore as independent evidence, never provides a backup write action', async () => {
  expect(panels['./BackupHealthPanel.vue'], 'readonly backup health component missing').toBeDefined();
  vi.mocked(api).mockResolvedValue({timestamp:'2026-10-06T00:00:00Z',status:'verified',checksumverified:true,restoreverified:false,source:'postgres-dump'});
  const root = document.createElement('div'); document.body.append(root);
  const app = createApp(panels['./BackupHealthPanel.vue'] as Component); app.mount(root);
  await new Promise(resolve => setTimeout(resolve, 0)); await nextTick();
  expect(root.textContent).toContain('校验和已验证');
  expect(root.textContent).toContain('恢复未验证');
  expect(root.textContent).toContain('dump 目录可读不等于恢复成功');
  expect(api).toHaveBeenCalledWith('/operations/backup-health', expect.objectContaining({signal:expect.any(AbortSignal)}));
  expect(Array.from(root.querySelectorAll('button')).map(x => x.textContent)).toEqual(['刷新证据']);
  app.unmount();
});
it('does not claim a backup exists while evidence is loading and aborts a pending read on unmount', async () => {
  let signal: AbortSignal | undefined;
  vi.mocked(api).mockImplementation(async (_path, options) => {
    signal = options?.signal as AbortSignal;
    return new Promise(() => {});
  });
  const root = document.createElement('div'); document.body.append(root);
  const app = createApp(panels['./BackupHealthPanel.vue'] as Component); app.mount(root);
  await nextTick();
  expect(root.textContent).toContain('正在读取证据');
  expect(root.textContent).not.toContain('恢复已验证');
  app.unmount();
  expect(signal?.aborted).toBe(true);
});
it('does not display stale success after an API failure', async () => {
  vi.mocked(api).mockRejectedValue(new Error('private request details'));
  const root = document.createElement('div'); document.body.append(root);
  const app = createApp(panels['./BackupHealthPanel.vue'] as Component); app.mount(root);
  await new Promise(resolve => setTimeout(resolve, 0)); await nextTick();
  expect(root.querySelector('[role="alert"]')?.textContent).toContain('无法读取备份证据');
  expect(root.textContent).not.toContain('private request details');
  expect(root.textContent).not.toContain('校验和已验证');
  app.unmount();
});
