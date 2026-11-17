import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:false,cacheDir:'.cache/channel-inline',plugins:[vue()],test:{environment:'jsdom',maxWorkers:1,include:['src/modules/servers/reportChannels.test.ts','src/modules/servers/channelInline.test.ts','src/modules/servers/agentManagement.test.ts','src/modules/servers/agentManagementFix.test.ts']}});
