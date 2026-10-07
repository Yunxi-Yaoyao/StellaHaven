import {it,expect} from 'vitest';
import config from '../../../vite.config';
it('proxies all centralized settings and feature APIs without changing Host in development',()=>{
 const proxy=(config as any).server.proxy;
 for(const path of ['/service-settings','/navigation','/external-modules','/integration-targets','/integration-presets','/builtin-injections','/integration-assets','/operations','/search','/timeline','/notes-tools']){
  expect(proxy[path],path).toBeDefined();
  expect(proxy[path].target).toBe('http://127.0.0.1:12031');
  expect(proxy[path].changeOrigin).not.toBe(true);
 }
});
