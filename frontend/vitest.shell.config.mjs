import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({ plugins: [vue()], test: { environment: 'jsdom', include: ['src/shell/lazyShell.test.ts', 'src/router/startup.test.ts'], pool: 'forks', maxWorkers: 1, minWorkers: 1 } });
