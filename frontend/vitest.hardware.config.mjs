import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import { join } from 'node:path';
const scratch = process.env.TMPDIR || '/root/.hermes/cache/scratch';
export default defineConfig({
  cacheDir: join(scratch, 'hardware-frontend/vite-cache'),
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    include: ['src/modules/servers/hardware.test.ts', 'src/modules/servers/storageStatus.test.ts'],
    pool: 'forks', maxWorkers: 1, minWorkers: 1,
  },
});
