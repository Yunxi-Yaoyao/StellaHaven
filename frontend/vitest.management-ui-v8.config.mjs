import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:false,cacheDir:'/root/.hermes/cache/scratch/v8-management-ui-vitest',plugins:[vue()],test:{environment:'jsdom',maxWorkers:1,include:['src/modules/servers/managementUiV8.test.ts']}});
