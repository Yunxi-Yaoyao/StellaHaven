// Mandatory independent experience suite plus reviewed regression additions.
// Do not fork its assertions, fixtures, image colors or pixel budgets here.
import {defineConfig} from '@playwright/test';
import independent from './playwright.experience-independent.config';
import path from 'node:path';
const output=path.resolve(process.env.STELLA_QA_OUTPUT || 'node_modules/.cache/experience');
export default defineConfig({...independent,
  testMatch:['experience-independent-navigation.spec.ts','experience-independent-background.spec.ts','experience-independent-auth.spec.ts'],
  forbidOnly:true,workers:1,retries:0,outputDir:path.join(output,'artifacts'),
  reporter:[['list'],['json',{outputFile:path.join(output,'results.json')}],['./e2e/experience-gate/reporter.ts']],
  use:{...independent.use,launchOptions:{...(process.env.STELLA_CHROMIUM?{executablePath:process.env.STELLA_CHROMIUM}:{}),args:['--no-sandbox']}}
});
