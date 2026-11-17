import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:'/root/.hermes/cache/scratch/background-review-fix/empty-env',cacheDir:'/root/.hermes/cache/scratch/background-review-fix/vitest-cache',plugins:[vue()],server:{proxy:{}},test:{environment:'jsdom',include:['src/modules/home/*.recovery.test.ts'],pool:'forks',maxWorkers:1,minWorkers:1}});
