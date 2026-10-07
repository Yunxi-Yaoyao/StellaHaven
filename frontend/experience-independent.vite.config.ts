import {defineConfig} from 'vite';
import vue from '@vitejs/plugin-vue';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here=fileURLToPath(new URL('.',import.meta.url));
const source = path.resolve(process.env.STELLA_SOURCE_ROOT || path.join(here,'..'));
const output=process.env.STELLA_QA_OUTPUT || '/opt/hermes-workstation/docs/2026-10-08-Stella-experience-fix/qa/independent';
// No product config merge, no backend proxy, no writes in shared node_modules.
export default defineConfig({root:path.join(source,'frontend'),plugins:[vue()],cacheDir:path.join(output,'vite-cache'),server:{host:'127.0.0.1',port:15487,strictPort:true,proxy:{},fs:{allow:[path.join(source,'frontend'),path.join(here,'node_modules')]}}});
