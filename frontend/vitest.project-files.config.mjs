import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:false,plugins:[vue()],cacheDir:process.env.TMPDIR+'/project-files-vitest',test:{include:['src/modules/notes/projectAssetCopy.test.ts','src/modules/notes/projectFiles.test.ts','src/modules/notes/projectFilesEditor.test.ts','src/modules/notes/projectFilesPage.test.ts'],environment:'jsdom',maxWorkers:1}});
