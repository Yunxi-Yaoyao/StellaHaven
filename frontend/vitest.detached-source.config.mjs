import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:false,plugins:[vue()],cacheDir:process.env.TMPDIR+'/detached-source-vitest',test:{include:['src/modules/notes/detachedSource*.test.ts'],environment:'jsdom',maxWorkers:1}});
