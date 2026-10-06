import {defineConfig} from 'vitest/config';
export default defineConfig({test:{include:['src/api/websiteSaveKey.test.ts'],environment:'node'}});
