import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],test:{include:['src/modules/servers/alertFeedback.test.ts','src/modules/servers/alertMetrics.test.ts'],environment:'jsdom'}});
