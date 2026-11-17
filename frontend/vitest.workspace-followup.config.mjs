import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
export default defineConfig({
  plugins:[vue()],
  cacheDir:join(tmpdir(),'stella-notes-followup-workspace-vitest'),
  test:{environment:'jsdom',include:['src/modules/notes/**/*.test.ts'],exclude:['src/modules/notes/richMarkdown.test.ts'],pool:'forks',maxWorkers:1,minWorkers:1},
});
