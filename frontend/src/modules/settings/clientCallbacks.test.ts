import {describe,it,expect} from 'vitest';
import {importCallbacks,expandCallbacks,callbackDiff,callbackProblem} from './clientCallbacks';

describe('exact per-application callback model',()=>{
 it('imports sparse origins without completing a matrix or losing order and legacy values',()=>{
  const uris=['https://photos.test/auth/login','http://localhost:2283/auth/login','https://photos.p/user-settings','app.immich:///oauth-callback','https://yunxi.life/old?legacy=1'];
  const model=importCallbacks(uris);
  expect(model.web.map(row=>[row.origin,row.paths])).toEqual([['https://photos.test',['/auth/login']],['https://photos.p',['/user-settings']]]);
  expect(model.native).toEqual(['app.immich:///oauth-callback']);
  expect(model.compatibility).toEqual(['http://localhost:2283/auth/login','https://yunxi.life/old?legacy=1']);
  expect(expandCallbacks(model)).toEqual(uris);
  expect(callbackDiff(uris,expandCallbacks(model))).toEqual({added:[],removed:[]});
 });
 it('keeps explicit default ports and domain case exact instead of URL-normalizing them',()=>{
  const uri='https://Photos.test:443/auth/login';const model=importCallbacks([uri]);
  expect(model.web).toEqual([{origin:'https://Photos.test:443',paths:['/auth/login']}]);
  expect(callbackProblem(model,[uri])).toBe('');expect(expandCallbacks(model)).toEqual([uri]);
 });
 it('requires explicit additions for each origin and reports actual additions and removals',()=>{
  const before=['https://photos.test/auth/login','https://photos.p/user-settings'];
  const model=importCallbacks(before);model.web[0]!.paths.push('/user-settings');model.web[1]!.paths.push('/auth/login');
  expect(callbackDiff(before,expandCallbacks(model))).toEqual({added:['https://photos.test/user-settings','https://photos.p/auth/login'],removed:[]});
  model.web[0]!.paths.splice(0,1);
  expect(callbackDiff(before,expandCallbacks(model)).removed).toEqual(['https://photos.test/auth/login']);
 });
 for(const [origin,path] of [['https://rp.test/extra','/cb'],['https://rp.test','//evil.test/cb'],['https://rp.test','/cb?x=1'],['http://localhost','/cb'],['https://user:pw@rp.test','/cb'],['https://rp.test','/%2acb'],['https://rp.test','/../cb'],['https://rp.test:bad','/cb'],['https://*.test','/cb'],['https://rp.test','/cb#x'],['https://rp.test','/%0acb']]){
  it(`rejects unsafe or normalized input ${origin} ${path}`,()=>{
   const model=importCallbacks([]);model.web.push({origin:origin!,paths:[path!]});
   expect(callbackProblem(model,[])).not.toBe('');
  });
 }
 it('permits only exact retained native and compatibility callbacks, not arbitrary additions',()=>{
  const before=['app.immich:///oauth-callback','http://localhost/cb','unknown:///legacy'];
  const model=importCallbacks(before);expect(callbackProblem(model,before)).toBe('');
  model.native.push('app.immich:////oauth-callback');expect(callbackProblem(model,before)).not.toBe('');
  model.native.pop();model.compatibility.push('http://localhost/new');expect(callbackProblem(model,before)).not.toBe('');
 });
 it('rejects duplicate callbacks and does not erase empty/invalid rows before validation',()=>{
  const model=importCallbacks(['https://rp.test/cb']);model.web[0]!.paths.push('/cb');
  expect(callbackProblem(model,model.order)).not.toBe('');
  model.web[0]!.paths=[''];expect(callbackProblem(model,model.order)).not.toBe('');
 });
});
