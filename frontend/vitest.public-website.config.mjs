import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({
  plugins: [vue()],
  envDir: process.env.TMPDIR,
  cacheDir: process.env.TMPDIR + '/stella-public-website-vitest',
  test: {
    include: ['src/modules/settings/publicWebsiteProjection.test.ts', 'src/api/integrations.test.ts', 'src/stores/navigation.test.ts'],
    environment: 'jsdom',
  },
});
