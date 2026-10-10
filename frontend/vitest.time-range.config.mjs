import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({
  cacheDir: 'node_modules/.tmp/time-range-vite',
  plugins: [vue()],
  test: { environment: 'jsdom', include: ['src/modules/servers/timeRange*.test.ts'], pool: 'forks', maxWorkers: 1, minWorkers: 1 },
});
