import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:false,plugins:[vue()],cacheDir:process.env.TMPDIR+'/detached-source-regression',test:{include:['src/modules/notes/notesPageWebProjects.test.ts','src/modules/notes/projectFilesPage.test.ts','src/modules/notes/webProjectPane.test.ts','src/modules/notes/upgradeConsumption.test.ts'],setupFiles:['tests/detached-source-regression-setup.ts'],environment:'jsdom',maxWorkers:1}});
