import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import {fileURLToPath} from 'node:url';
// Private worktree dependency/cache tree; no shared full-suite cache or live API.
export default defineConfig({
 cacheDir:fileURLToPath(new URL('./node_modules/.cache/callback-vitest',import.meta.url)),
 plugins:[vue()],
 test:{environment:'jsdom',include:['src/api/authProvider.test.ts','src/modules/settings/AuthProviderSettings.test.ts','src/modules/settings/clientCallbacks.test.ts'],pool:'forks',maxWorkers:1,minWorkers:1},
});
