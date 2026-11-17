import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
// No environment-file discovery: this suite uses fixture HTTP/auth only.
export default defineConfig({
 envDir:false,plugins:[vue()],cacheDir:process.env.TMPDIR+'/project-async-regression-vitest',
 test:{include:[
  'src/modules/notes/webProjectRecovery.test.ts',
  'src/modules/notes/webProjectPane.test.ts',
  'src/modules/notes/projectAssetCopy.test.ts',
  'src/modules/notes/projectFiles.test.ts',
  'src/modules/notes/projectFilesEditor.test.ts',
  'src/modules/notes/projectFilesPage.test.ts',
 ],environment:'jsdom',maxWorkers:1},
});
