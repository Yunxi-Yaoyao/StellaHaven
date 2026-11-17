import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import {mkdtempSync} from 'node:fs';
export default defineConfig({cacheDir:mkdtempSync(process.env.TMPDIR+'/v11-first-use-'),plugins:[vue()],test:{environment:'jsdom',include:['src/modules/settings/FirstUseChecklist.test.ts','src/modules/auth/firstUseRegistration.test.ts','src/modules/settings/SettingsPage.categories-v8.test.ts','src/modules/auth/loginModal.test.ts']}});
