import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import { execFileSync } from 'node:child_process';
// Reproduce the approved regressions on the immutable baseline without editing another tree.
const baseline = { name:'appearance-baseline', enforce:'pre', load(id) {
  if (process.env.APPEARANCE_BASELINE !== '1') return;
  for (const path of ['src/shell/NotificationBell.vue', 'src/modules/home/settings.ts']) {
    if (id.endsWith('/frontend/' + path)) return execFileSync('git', ['show', 'd15e81b9dc3ca03d77199b8938243f7375998fc7:frontend/' + path], {encoding:'utf8'});
  }
} };
export default defineConfig({ plugins: [baseline, vue()], cacheDir: '../.cache/appearance-vite', test: { environment: 'jsdom', include: ['src/stores/appearance.test.ts', 'src/shell/appearance.test.ts'], pool: 'forks', maxWorkers: 1, minWorkers: 1 } });
