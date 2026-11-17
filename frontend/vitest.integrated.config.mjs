import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],test:{environment:'jsdom',include:['src/App.drawerKeys.test.ts','src/modules/settings/SettingsPage.integrated.test.ts'],pool:'forks',minWorkers:1,maxWorkers:1}});
