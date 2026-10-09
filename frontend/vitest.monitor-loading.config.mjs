import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
export default defineConfig({
  cacheDir: join(tmpdir(), 'stella-monitor-fix-vite'),
  plugins: [vue()],
  test: { environment: 'jsdom', include: ['src/modules/servers/monitorLoading.test.ts'], pool: 'forks', maxWorkers: 1, minWorkers: 1 },
});
