import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// All Vitest suites; native node:test suites run in the second test:full step.
export default defineConfig({
  cacheDir: join(tmpdir(), 'stella-monitor-full-vite'),
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    exclude: ['src/modules/notes/richMarkdown.test.ts', 'src/modules/servers/polling.test.ts',
      'src/modules/servers/taskWait.test.ts', 'src/modules/servers/lazyImports.test.ts',
      'src/modules/servers/monitorStats.test.ts'],
    pool: 'forks', maxWorkers: 1, minWorkers: 1,
  },
});
