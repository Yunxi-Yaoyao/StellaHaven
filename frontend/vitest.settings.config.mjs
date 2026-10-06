import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({ plugins:[vue()], cacheDir: process.env.TMPDIR + '/stella-vitest-cache', test: { include: ['src/api/client.test.ts', 'src/api/integrations.test.ts', 'src/stores/navigation.test.ts', 'src/modules/settings/*.test.ts'], environment: 'jsdom' } });
