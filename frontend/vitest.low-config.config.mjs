import {defineConfig} from 'vitest/config';
export default defineConfig({cacheDir:process.env.TMPDIR+'/stella-lowconfig-vitest',test:{include:['src/api/integrations.low-config.test.ts'],environment:'node'}});
