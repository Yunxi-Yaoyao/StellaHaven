import {afterEach,expect,it,vi} from 'vitest';
const modules=import.meta.glob('./backupClientPreferences.ts',{eager:true});
function helper(){expect(modules['./backupClientPreferences.ts'],'portable preference helper missing').toBeDefined();return modules['./backupClientPreferences.ts'] as typeof import('./backupClientPreferences');}
afterEach(()=>{localStorage.clear();vi.restoreAllMocks();});
it('reads only explicit audited keys, never enumerates storage or includes notes/tokens/runtime state',()=>{
  const {readBackupClientPreferences,CLIENT_PREFERENCE_KEYS}=helper();localStorage.setItem('stella_appearance','B');localStorage.setItem('stella_home_bgcrop',JSON.stringify({cx:.4,cy:.5,w:.8,h:.9}));localStorage.setItem('stella_note_edit_mode','markdown');localStorage.setItem('stella_token','secret-sentinel');localStorage.setItem('stella_bootstrap','private-doc');localStorage.setItem('stella_mood','private-content');localStorage.setItem('web_project_runtime','source-content');
  const get=vi.spyOn(Storage.prototype,'getItem'),key=vi.spyOn(Storage.prototype,'key'),set=vi.spyOn(Storage.prototype,'setItem');const result=readBackupClientPreferences(localStorage);
  expect(result.preferences).toMatchObject({version:1,values:{stella_appearance:'B',stella_home_bgcrop:JSON.stringify({cx:.4,cy:.5,w:.8,h:.9}),stella_note_edit_mode:'markdown'}});expect(result.warnings).toEqual([]);expect(key).not.toHaveBeenCalled();expect(set).not.toHaveBeenCalled();expect(get.mock.calls.every(([name])=>CLIENT_PREFERENCE_KEYS.includes(name as never))).toBe(true);expect(JSON.stringify(result)).not.toMatch(/secret-sentinel|private-doc|private-content|source-content/);
});
it.each([
 ['stella_appearance','C'],['stella_home_bgcrop','{"cx":0.5,"cy":0.5,"w":0,"h":1}'],['stella_home_bgcrop','{"cx":0.5,"cy":0.5,"w":1,"h":1,"token":"not-allowed"}'],['stella_home_bg','https://remote.example/bg?token=secret'],['stella_home_bg','/assets/homebg/%2e%2e/private'],['stella_signature','x'.repeat(513)],['stella_meet_date','2026-02-30'],['stella_sidebar_fold','true'],['stella_home_theme','coastline'],
])('skips invalid local %s with a bounded nonsecret warning [%#]', (key,value)=>{
  const {readBackupClientPreferences}=helper();localStorage.setItem(key,value);const result=readBackupClientPreferences(localStorage);expect(Object.keys(result.preferences.values)).toEqual([]);expect(result.warnings).toEqual([key]);expect(JSON.stringify(result)).not.toContain(value);
});
it('restores only validated listed settings with exact readback and an explicit reload-required result',()=>{
  const {applyBackupClientPreferences}=helper();expect(applyBackupClientPreferences).toBeTypeOf('function');localStorage.setItem('stella_token','untouched');localStorage.setItem('stella_signature','existing');
  const result=applyBackupClientPreferences({version:1,values:{stella_appearance:'B',stella_home_bgcrop:'{"cx":0.5,"cy":0.5,"w":1,"h":1}'}},localStorage);
  expect(result).toEqual({applied:['stella_appearance','stella_home_bgcrop'],reloadRequired:true});expect(localStorage.getItem('stella_appearance')).toBe('B');expect(localStorage.getItem('stella_signature')).toBe('existing');expect(localStorage.getItem('stella_token')).toBe('untouched');
});
it.each([
 {version:1,values:{stella_appearance:'custom'}},{version:1,values:{stella_appearance:'custom',stella_custom_appearance:'null'}},
 {version:1,values:{stella_custom_appearance:'{"version":1,"base":"B","overrides":{"accent":"#fff"}}'}},
 {version:2,values:{}},{version:1,values:{stella_token:'secret'}},{version:1,values:{stella_appearance:true}},
 {version:1,values:{stella_site_title:'x'.repeat(121)}},{version:1,values:{stella_home_bgcrop:'[]'}},
 {version:1,values:{stella_home_bgcrop:'{"cx":null,"cy":0.5,"w":1,"h":1}'}},
 {version:1,values:{stella_signature:'<private>\u0000'}},{version:1,values:{stella_home_bg:'javascript:alert(1)'}},
 JSON.parse('{"version":1,"values":{"__proto__":{"polluted":true}}}'),{version:1,values:{},unknown:'not allowed'},
])('rejects an entire invalid restore before touching storage: %#',payload=>{
  const {applyBackupClientPreferences}=helper();expect(applyBackupClientPreferences).toBeTypeOf('function');const set=vi.spyOn(Storage.prototype,'setItem'),remove=vi.spyOn(Storage.prototype,'removeItem');expect(()=>applyBackupClientPreferences(payload,localStorage)).toThrow(/偏好/);expect(set).not.toHaveBeenCalled();expect(remove).not.toHaveBeenCalled();expect(({} as Record<string,unknown>).polluted).toBeUndefined();
});
it('rolls back the whole preference subset on quota/readback failure without touching unrelated content',()=>{
  const {applyBackupClientPreferences}=helper();expect(applyBackupClientPreferences).toBeTypeOf('function');localStorage.setItem('stella_appearance','A');localStorage.setItem('stella_note_draft_private','sentinel');const set=Storage.prototype.setItem;let failed=false;
  vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,key,value){if(key==='stella_site_title'&&!failed){failed=true;throw new DOMException('QuotaExceeded','QuotaExceededError');}return set.call(this,key,value);});
  expect(()=>applyBackupClientPreferences({version:1,values:{stella_appearance:'B',stella_site_title:'new'}},localStorage)).toThrow(/已回滚/);expect(localStorage.getItem('stella_appearance')).toBe('A');expect(localStorage.getItem('stella_site_title')).toBeNull();expect(localStorage.getItem('stella_note_draft_private')).toBe('sentinel');
});
