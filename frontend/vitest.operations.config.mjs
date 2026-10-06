import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({ plugins: [vue()], cacheDir: process.env.TMPDIR + '/stella-operations-vitest-cache', test: { include: ['src/modules/settings/BackupHealthPanel.test.ts'], environment: 'jsdom' } });
