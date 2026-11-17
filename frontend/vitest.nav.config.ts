import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],test:{include:['src/modules/nav/*.test.ts'],environment:'jsdom'}});
