import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({envDir:false,plugins:[vue()],cacheDir:process.env.TMPDIR+'/monitor-ux-vitest',test:{environment:'jsdom',maxWorkers:1,include:['src/modules/servers/monitorBatchDraft.test.ts','src/modules/servers/monitorUxBatch.test.ts','src/modules/servers/monitorBulkDelete.test.ts','src/modules/servers/monitorCreateDialog.test.ts']}});
