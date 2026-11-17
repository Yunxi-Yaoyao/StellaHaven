// Read-only dependency reuse; no install, dependency copy or shared build cache.
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=fileURLToPath(new URL('.',import.meta.url));
const shared=process.env.STELLA_SHARED_FRONTEND||root;
const require=createRequire(shared+'/package.json');
const {defineConfig}=await import(pathToFileURL(shared+'/node_modules/vitest/dist/config.js').href);
const {default:vue}=await import(pathToFileURL(shared+'/node_modules/@vitejs/plugin-vue/dist/index.mjs').href);
export default defineConfig({root,envDir:false,server:{fs:{allow:[root,shared]}},cacheDir:(process.env.TMPDIR||'/root/.hermes/cache/scratch')+'/monitor-management-v8/vite-cache-final',plugins:[{name:'read-only-packages',enforce:'pre',resolveId(id){if(id==='vitest')return shared+'/node_modules/vitest/dist/index.js';if(id==='vue')return shared+'/node_modules/vue/dist/vue.runtime.esm-bundler.js';if(!id.startsWith('.')&&!id.startsWith('/')&&!id.startsWith('\0')&&!id.startsWith('node:')){try{return require.resolve(id)}catch{}}}},vue()],test:{environment:'jsdom',maxWorkers:1,include:['src/modules/servers/monitorManagementV8.test.ts']}});
