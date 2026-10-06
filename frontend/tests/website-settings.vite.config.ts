import {defineConfig} from 'vite';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],cacheDir:process.env.TMPDIR+'/stella-website-vite',server:{host:'127.0.0.1',port:15179,strictPort:true,proxy:{}}});
