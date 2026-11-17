import {defineConfig} from '@playwright/test';
import independent from '../playwright.experience-independent.config';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const output=path.resolve(process.env.STELLA_QA_OUTPUT||'node_modules/.cache/client-preferences-fixture');
// Deliberately separate from the immutable 23-check experience gate contract.
export default defineConfig({...independent,testDir:'.',testMatch:'client-preferences-fixture.spec.ts',webServer:{command:'node node_modules/vite/bin/vite.js --config experience-independent.vite.config.ts',url:'http://127.0.0.1:15487',reuseExistingServer:false,timeout:30000,cwd:fileURLToPath(new URL('../',import.meta.url))},outputDir:path.join(output,'artifacts'),reporter:[['list'],['junit',{outputFile:path.join(output,'fixture-browser.junit.xml')}],['json',{outputFile:path.join(output,'fixture-browser.json')}]]});
