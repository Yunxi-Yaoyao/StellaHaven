import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:false,cacheDir:'.cache/monitor-v5',plugins:[vue()],test:{environment:'jsdom',maxWorkers:1,include:['src/modules/servers/monitorCardsV5.test.ts','src/modules/servers/monitorExperienceV5.test.ts','src/modules/servers/centerGroups.test.ts','src/modules/servers/monitorRotation.test.ts']}});
