import {build} from './node_modules/vite/dist/node/index.js';
import vue from './node_modules/@vitejs/plugin-vue/dist/index.mjs';
import assert from 'node:assert/strict';
assert(process.env.STELLA_APP_DIST?.startsWith('/root/.hermes/cache/scratch/monitor-ux-batch/'));
await build({root:import.meta.dirname,configFile:false,envDir:false,plugins:[vue()],cacheDir:process.env.TMPDIR+'/vite-build',build:{outDir:process.env.STELLA_APP_DIST,assetsDir:'static',cssTarget:'chrome90',emptyOutDir:true}});
