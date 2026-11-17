/// <reference types="node" />
import {defineConfig} from '@playwright/test';
const out=process.env.APPEARANCE_OUT??'/root/.hermes/cache/scratch/stella-appearance-feedback';
export default defineConfig({testDir:'.',testMatch:'appearance-feedback.spec.ts',workers:1,timeout:30000,reporter:[['list'],['json',{outputFile:out+'/browser-results.json'}]],outputDir:out+'/traces',use:{baseURL:'http://127.0.0.1:15232',deviceScaleFactor:1,launchOptions:{executablePath:'/usr/sbin/google-chrome-stable',args:['--no-sandbox']},trace:'retain-on-failure'},webServer:{command:'NOTES_REFRESH_PORT=15232 node e2e/notes-refresh-server.mjs',cwd:new URL('..',import.meta.url).pathname,port:15232,reuseExistingServer:false}});
