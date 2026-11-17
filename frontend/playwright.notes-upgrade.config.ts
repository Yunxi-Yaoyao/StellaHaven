import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'./e2e',testMatch:'notes-upgrade.spec.ts',workers:1,timeout:30000,
 outputDir:(process.env.STELLA_SERVICE_ARTIFACTS||'test-results/notes-upgrade')+'/traces',reporter:[['list'],['json',{outputFile:(process.env.STELLA_SERVICE_ARTIFACTS||'test-results/notes-upgrade')+'/e2e-results.json'}]],
 use:{baseURL:'http://127.0.0.1:15174',launchOptions:{executablePath:'/usr/sbin/google-chrome-stable',args:['--no-sandbox']},viewport:{width:1440,height:1000}},
 webServer:{command:'NOTES_REFRESH_PORT=15174 node e2e/notes-refresh-server.mjs',port:15174,reuseExistingServer:false}});
