import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:false,cacheDir:'.cache/monitor-correction',plugins:[vue()],test:{environment:'jsdom',maxWorkers:1,include:['src/modules/servers/monitorRotation.test.ts','src/modules/servers/overviewTraffic.test.ts','src/modules/servers/serversFeedback.test.ts']}});
