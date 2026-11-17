import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({cacheDir:'node_modules/.agent-management-vite',plugins:[vue()],test:{environment:'jsdom',include:['src/modules/servers/agentManagement.test.ts','src/modules/servers/reportChannels.test.ts','src/modules/servers/agentManagementFix.test.ts'],pool:'forks',maxWorkers:1,minWorkers:1}});
