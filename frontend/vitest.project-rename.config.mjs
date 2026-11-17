import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:false,plugins:[vue()],cacheDir:process.env.TMPDIR+'/project-rename-vitest',test:{include:['src/modules/notes/projectRename.test.ts','src/modules/settings/appearanceCopy.test.ts'],environment:'jsdom',maxWorkers:1}});
