import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],test:{environment:'jsdom',include:['src/modules/auth/browserId.test.ts','src/modules/auth/browserLogin.test.ts','src/modules/settings/SettingsPage.browserSessions.test.ts'],pool:'forks',minWorkers:1,maxWorkers:1}});
