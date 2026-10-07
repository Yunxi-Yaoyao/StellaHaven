import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],cacheDir:'node_modules/.cache/experience-unit',test:{environment:'jsdom',include:['src/**/*.experience.test.ts'],pool:'forks',maxWorkers:1,minWorkers:1}});
