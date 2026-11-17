import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({cacheDir: new URL('./node_modules/.cache/website-polish',import.meta.url).pathname,plugins:[vue()],test:{environment:'jsdom',include:['src/**/*.test.ts'],pool:'forks',maxWorkers:1,minWorkers:1}});
