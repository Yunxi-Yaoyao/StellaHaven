import {defineConfig} from 'vite';
import vue from '@vitejs/plugin-vue';
import {websiteUiHttp} from './website-ui-http.ts';
export default defineConfig({plugins:[websiteUiHttp(),vue()],cacheDir:process.env.TMPDIR+'/stella-website-ui-http-vite',optimizeDeps:{entries:['tests/website-settings.mount.ts','tests/entry-addresses.mount.ts'],include:['vue','vue-router']},server:{host:'127.0.0.1',port:15189,strictPort:true,proxy:{}}});
