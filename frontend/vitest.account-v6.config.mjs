import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({cacheDir:'/root/.hermes/cache/scratch/account-v6/vite-tests',plugins:[vue()],test:{environment:'jsdom',include:['src/modules/settings/ProfileSettings.test.ts','src/modules/settings/SettingsPage*.test.ts','src/modules/settings/independentSmtpReview.test.ts','src/modules/settings/AccountV6.test.ts','src/modules/settings/AccountSessionsV6.test.ts'],pool:'forks',minWorkers:1,maxWorkers:1}});
