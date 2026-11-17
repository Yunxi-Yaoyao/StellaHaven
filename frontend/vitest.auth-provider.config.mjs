import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
export default defineConfig({
  cacheDir:join(tmpdir(),'stella-auth-provider-vite'), plugins:[vue()],
  test:{environment:'jsdom',include:['src/modules/settings/AuthProviderSettings.test.ts','src/modules/settings/SettingsPage.authentication.test.ts','src/api/authProvider.test.ts'],pool:'forks',minWorkers:1,maxWorkers:1},
});
