import {defineConfig} from '@playwright/test';
import {resolve} from 'node:path';

// Lane-owned Vite + bundled Chromium. No API proxy and no existing server reuse.
const artifacts=resolve(process.env.STELLA_SESSION_ARTIFACTS||'test-results/external-session');
export default defineConfig({
 testDir:'./e2e',testMatch:'external-session.spec.ts',workers:1,timeout:45000,
 expect:{timeout:5000},outputDir:artifacts+'/browser-artifacts',
 reporter:[['list'],['json',{outputFile:artifacts+'/browser-results.json'}]],
 use:{baseURL:'http://127.0.0.1:15287',serviceWorkers:'block',
  launchOptions:{args:['--no-sandbox']},viewport:{width:1440,height:1000},
  screenshot:'only-on-failure',trace:'retain-on-failure'},
 webServer:{cwd:new URL('.',import.meta.url).pathname,
  command:'node node_modules/vite/bin/vite.js --config vite.mock.config.ts --port 15287',
  env:{NODE_ENV:'development',TMPDIR:artifacts},
  port:15287,reuseExistingServer:false},
});
