import {defineConfig} from 'vitest/config';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import full from './vitest.full.config.mjs';
// Preserve original suite selection and worker limits, but isolate this lane's cache.
export default defineConfig({...full,cacheDir:join(tmpdir(),'stella-custom-appearance-20261020-vitest')});
