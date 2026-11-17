// Programmatic config avoids Vite's shared node_modules/.vite-temp writes.
import {startVitest} from 'vitest/node';
import vue from '@vitejs/plugin-vue';
const ctx=await startVitest('test',process.argv.slice(2),{config:false,environment:'jsdom',maxWorkers:1,watch:false},{configFile:false,plugins:[vue()],envDir:false,cacheDir:process.cwd()+'/.cache/entry-monitoring'});
if (!ctx) process.exitCode=1;
else {process.exitCode=ctx.state.getUnhandledErrors().length||ctx.state.getFiles().some(f=>f.result?.state==='fail')?1:0;await ctx.close();}
