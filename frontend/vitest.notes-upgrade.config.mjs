import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],cacheDir:process.env.TMPDIR+'/stella-notes-vitest',test:{include:['src/modules/notes/upgrade*.test.ts'],environment:'jsdom'}});
