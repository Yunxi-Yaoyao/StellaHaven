import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:false,cacheDir:'.cache/preference-correction',plugins:[vue()],test:{environment:'jsdom',maxWorkers:1,include:['src/modules/notes/notesPageWebProjects.test.ts','src/modules/settings/ClientPreferenceStatus.correction.test.ts','src/modules/settings/clientPreferenceSync.test.ts','src/modules/settings/clientPreferenceController.test.ts']}});
