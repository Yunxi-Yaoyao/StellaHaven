import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({ plugins: [vue()], test: { environment: 'jsdom', include: ['src/modules/servers/performance.test.ts','src/modules/home/performance.test.ts'], pool: 'forks', maxWorkers: 1, minWorkers: 1 } });
