import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
export default defineConfig({cacheDir:join(tmpdir(),'stella-node-policy-vite'),plugins:[vue()],test:{environment:'jsdom',include:['src/modules/settings/nodeMonitoringPolicy.test.ts'],pool:'forks',maxWorkers:1,minWorkers:1}});
