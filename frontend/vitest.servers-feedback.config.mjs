import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({
  cacheDir: 'node_modules/.cache/servers-feedback',
  plugins: [vue()],
  test: { environment: 'jsdom', include: ['src/modules/servers/serversFeedback.test.ts', 'src/modules/servers/overviewTraffic.test.ts'], pool: 'forks', maxWorkers: 1, minWorkers: 1 },
});
