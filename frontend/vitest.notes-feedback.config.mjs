import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({
  envDir:false,
  plugins:[vue()],
  cacheDir:'.cache/notes-feedback-vitest',
  test:{
    environment:'jsdom',maxWorkers:1,
    include:[
      'src/modules/notes/projectIdentity.test.ts',
      'src/modules/notes/notesPageWebProjects.test.ts',
      'src/modules/notes/detachedSourceCatalog.test.ts',
      'src/modules/notes/projectFiles.test.ts',
      'src/modules/notes/upgradeNotesSettings.test.ts',
      'src/modules/notes/notesSettingsContext.test.ts',
    ],
  },
});
