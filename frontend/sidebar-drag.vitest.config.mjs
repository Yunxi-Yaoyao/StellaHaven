import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],cacheDir:'node_modules/.cache/sidebar-drag',test:{environment:'jsdom',include:['src/modules/settings/NavigationOrder.drag.test.ts','src/composables/navigationOrder.test.ts','src/shell/SideBar.experience.test.ts','src/modules/settings/NavigationSettings.experience.test.ts'],maxWorkers:1,minWorkers:1}});
