import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:false,plugins:[vue()],cacheDir:process.env.TMPDIR+'/monitor-regressions',test:{environment:'jsdom',maxWorkers:1,include:['src/modules/servers/monitor*.test.ts'],exclude:['src/modules/servers/monitorStats.test.ts']}});
