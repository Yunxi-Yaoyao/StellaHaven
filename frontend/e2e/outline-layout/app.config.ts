import {defineConfig} from '@playwright/test';
import {tmpdir} from 'node:os';
import path from 'node:path';
export default defineConfig({testDir:'.',testMatch:'app.spec.ts',workers:1,timeout:45000,reporter:'list',outputDir:process.env.STELLA_LAYOUT_OUTPUT?path.join(process.env.STELLA_LAYOUT_OUTPUT,'traces'):path.join(tmpdir(),'stella-outline-layout-traces'),use:{reducedMotion:'reduce',baseURL:'http://127.0.0.1:15207',launchOptions:{executablePath:process.env.CHROMIUM_PATH||'/usr/sbin/google-chrome-stable',args:['--no-sandbox']},trace:'retain-on-failure'},webServer:{command:'NOTES_REFRESH_PORT=15207 node e2e/notes-refresh-server.mjs',cwd:new URL('../..',import.meta.url).pathname,port:15207,reuseExistingServer:false}});
