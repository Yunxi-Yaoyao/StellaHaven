import {defineConfig} from '@playwright/test';
const out=process.env.STELLA_ACCOUNT_OUTPUT||'/root/.hermes/cache/scratch/account-polish-v6/browser';
export default defineConfig({
 testDir:'./e2e/account-v6',testMatch:'geometry.spec.ts',workers:1,timeout:45000,
 outputDir:out+'/artifacts',reporter:[['list'],['json',{outputFile:out+'/results.json'}]],
 use:{baseURL:'http://127.0.0.1:15487',serviceWorkers:'block',launchOptions:{executablePath:'/usr/sbin/google-chrome-stable',args:['--no-sandbox','--disable-background-networking']}},
 webServer:{command:'node e2e/account-v6/geometry.server.mjs',url:'http://127.0.0.1:15487',reuseExistingServer:false},
});
