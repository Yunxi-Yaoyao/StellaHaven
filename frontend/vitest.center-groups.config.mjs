import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:false,cacheDir:'.cache/center-groups',plugins:[vue()],test:{environment:'jsdom',maxWorkers:1,include:['src/modules/servers/centerGroups.test.ts']}});
