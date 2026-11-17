import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],cacheDir:process.env.TMPDIR+'/wp-recovery-vitest',test:{include:['src/modules/notes/webProjectRecovery.test.ts','src/modules/notes/webProjectPane.test.ts','src/modules/notes/notesPageWebProjects.test.ts'],environment:'jsdom',maxWorkers:1}});
