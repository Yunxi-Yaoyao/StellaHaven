import {defineConfig} from '@playwright/test';
import {resolve} from 'node:path';
// Existing mock suites at their explicit owned origins. No legacy production targets.
const out=resolve(process.env.STELLA_SERVICE_ARTIFACTS||'test-results/service-regression');
const projects=[
 {name:'websites',testDir:'./tests',testMatch:'website-settings.spec.ts',port:15179,config:'tests/website-settings.vite.config.ts'},
 {name:'low-config',testDir:'./e2e',testMatch:'low-config.spec.ts',port:15274,config:'vite.mock.config.ts'},
 {name:'iframe-cache',testDir:'./e2e',testMatch:'iframe-cache.spec.ts',port:15286,config:'vite.mock.config.ts'},
 {name:'external-session',testDir:'./e2e',testMatch:'external-session.spec.ts',port:15287,config:'vite.mock.config.ts'},
 {name:'notes-upgrade',testDir:'./e2e',testMatch:'notes-upgrade.spec.ts',port:15174,config:'vite.mock.config.ts'},
];
export default defineConfig({workers:1,timeout:45000,outputDir:out+'/browser-artifacts',reporter:[['list'],['json',{outputFile:out+'/browser-results.json'}]],use:{serviceWorkers:'block',launchOptions:{args:['--no-sandbox']},viewport:{width:1440,height:1000},screenshot:'only-on-failure',trace:'retain-on-failure'},projects:projects.map(p=>({name:p.name,testDir:p.testDir,testMatch:p.testMatch,use:{baseURL:'http://127.0.0.1:'+p.port}})),webServer:projects.map(p=>({command:`node node_modules/vite/bin/vite.js --config ${p.config} --port ${p.port}`,env:{NODE_ENV:'development',TMPDIR:out+'/'+p.name},port:p.port,reuseExistingServer:false}))});
