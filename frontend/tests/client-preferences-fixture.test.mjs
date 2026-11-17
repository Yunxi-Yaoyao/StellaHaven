import assert from 'node:assert/strict';
import test from 'node:test';
import {createServer} from 'vite';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

// Use Vite's TS loader so the fixture exercises the actual product DTO validator.
const cache=await mkdtemp(join(tmpdir(),'prefs-fixture-'));
const server=await createServer({root:new URL('../',import.meta.url).pathname,configFile:false,cacheDir:cache,server:{proxy:{}},optimizeDeps:{entries:[]}});
try {
 const {createClientPreferencesFixture}=await server.ssrLoadModule('/tests/fixtures/clientPreferences.ts');
 test('persisted owner GET is the exact DTO, matches local defaults, and is detached',()=>{
  const fixture=createClientPreferencesFixture();
  const first=fixture.respond('GET','/operations/backups/client-preferences');
  assert.equal(first.status,200);assert.equal(first.json.revision,1);
  assert.deepEqual(Object.keys(first.json).sort(),['appearance','home','revision','ui']);
  assert.equal(first.json.home.bgImage,'/assets/homebg/default-bg-kimono-1920.webp');
  assert.equal(first.json.home.signature,'夜有星辰，晨有曦光。');
  first.json.home.siteTitle='must not mutate server';
  assert.equal(fixture.respond('GET','/operations/backups/client-preferences').json.home.siteTitle,'StellaHaven');
 });
 test('seed respects disabled animation, quality and legacy/current priority without touching raw storage',()=>{
  const storage={stella_live2d:'off',stella_home_particles:'off',stella_home_bg_quality:'original',__stella_drive_bg_mode__:'image',stella_client_preferences_owner:'not-portable',stella_token:'never-transfer'};
  const original=structuredClone(storage);
  const value=createClientPreferencesFixture({storage}).respond('GET','/operations/backups/client-preferences').json;
  assert.equal(value.home.live2d,false);assert.equal(value.home.particles,'off');assert.equal(value.ui.backgroundQuality,'original');assert.equal(value.ui.driveBackground,'image');
  assert.equal(createClientPreferencesFixture({storage:{...storage,stella_drive_bg_mode:'solid'}}).respond('GET','/operations/backups/client-preferences').json.ui.driveBackground,'solid');
  assert.equal(createClientPreferencesFixture({storage:{...storage,stella_drive_bg_mode:'invalid'}}).respond('GET','/operations/backups/client-preferences').json.ui.driveBackground,'image');
  assert.doesNotMatch(JSON.stringify(value),/never-transfer|not-portable/);assert.deepEqual(storage,original);
 });
 test('opted-in PUT validates exact DTO and revision, then GET reads the committed value',()=>{
  const fixture=createClientPreferencesFixture({allowWrite:true});
  const {revision,...content}=fixture.respond('GET','/operations/backups/client-preferences').json;
  const write={...content,ui:{...content.ui,backgroundQuality:'compressed2'},expected_revision:revision};
  const saved=fixture.respond('PUT','/operations/backups/client-preferences',write);
  assert.equal(saved.status,200);assert.equal(saved.json.revision,2);assert.equal(saved.json.ui.backgroundQuality,'compressed2');
  assert.deepEqual(fixture.respond('GET','/operations/backups/client-preferences').json,saved.json);
  assert.equal(fixture.respond('PUT','/operations/backups/client-preferences',write).status,409);
  for(const malformed of [{...write,expected_revision:2,unknown:true},{...write,expected_revision:2,home:{...write.home,private:'no'}},{...write,expected_revision:'2'},{...write,expected_revision:2,ui:{...write.ui,backgroundQuality:'invalid'}}])assert.equal(fixture.respond('PUT','/operations/backups/client-preferences',malformed).status,422);
  assert.deepEqual(fixture.respond('GET','/operations/backups/client-preferences').json,saved.json);
 });
 test('custom palette writes and retained A/B follow the same finite DTO contract',()=>{
  const fixture=createClientPreferencesFixture({allowWrite:true});const {revision,...content}=fixture.respond('GET','/operations/backups/client-preferences').json;
  const customAppearance={version:1,base:'B',overrides:{accent:'#AABBCC'}};
  const saved=fixture.respond('PUT','/operations/backups/client-preferences',{...content,appearance:'custom',customAppearance,expected_revision:revision});assert.equal(saved.status,200);assert.deepEqual(saved.json.customAppearance,customAppearance);
  const kept=fixture.respond('PUT','/operations/backups/client-preferences',{...content,appearance:'A',customAppearance,expected_revision:saved.json.revision});assert.equal(kept.status,200);assert.deepEqual(kept.json.customAppearance,customAppearance);
  assert.equal(fixture.respond('PUT','/operations/backups/client-preferences',{...content,appearance:'B',expected_revision:kept.json.revision}).json.customAppearance?.overrides.accent,'#AABBCC');
  assert.equal(fixture.respond('PUT','/operations/backups/client-preferences',{...content,appearance:'custom',customAppearance:{...customAppearance,overrides:{unknown:'#FFFFFF'}},expected_revision:kept.json.revision+1}).status,422);
 });
 test('negative control: no route match for unknown paths/methods or unapproved writes',()=>{
  const fixture=createClientPreferencesFixture();
  for(const [method,path] of [['GET','/operations/backups/client-preferences/unknown'],['POST','/operations/backups'],['DELETE','/operations/backups/client-preferences'],['PUT','/operations/backups/client-preferences']])assert.equal(fixture.respond(method,path,{}),null);
 });
} finally {await server.close();await rm(cache,{recursive:true,force:true});}
