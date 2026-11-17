import assert from 'node:assert/strict';
import {resolveConfig} from 'vite';
const config=await resolveConfig({configFile:'vite.config.ts'},'serve');
const matches=Object.keys(config.server.proxy||{}).filter(prefix=>prefix.startsWith('^')?new RegExp(prefix).test('/notes-preferences'):'/notes-preferences'.startsWith(prefix));
console.log(JSON.stringify({path:'/notes-preferences',proxyMatches:matches,allProxies:Object.keys(config.server.proxy||{})}));
assert.ok(matches.length,'new owner preferences API must reach the backend from the supported Vite dev server');
