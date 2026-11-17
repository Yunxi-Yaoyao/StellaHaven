import {expect,it} from 'vitest';
import {CLIENT_PREFERENCE_KEYS} from './backupClientPreferences';
const modules=import.meta.glob('./clientPreferenceContract.ts',{eager:true});
export const fixture=()=>({revision:3,appearance:'B' as const,home:{theme:'classic' as const,particles:'off' as const,bgImage:'',bgCrop:{cx:.4,cy:.5,w:.8,h:.9},siteTitle:'本机主页',signature:'签名',meetDate:'2026-05-31',live2d:false,avatar:'/avatar.png'},ui:{backgroundQuality:'original' as const,sidebarFold:true,serversFold:true,toolsOpen:true,worldMapCollapsed:true,monitorMode:'simple' as const,noteEditMode:'markdown' as const,listFold:true,driveBackground:'image' as const}});
it('roundtrips retained custom palette even while A is selected through HTTP and backup',()=>{
 const contract=modules['./clientPreferenceContract.ts'] as typeof import('./clientPreferenceContract');
 const customAppearance={version:1,base:'B',overrides:{accent:'#AABBCC','metric-cpu':'#ABCDEF'}};
 const remote={...fixture(),appearance:'A',customAppearance};
 const portable=contract.clientPreferencesToLocal(remote);
 expect(JSON.parse(portable.values.stella_custom_appearance!)).toEqual(customAppearance);
 expect(contract.localToClientPreferences(portable,3)).toEqual(remote);
 for(const custom of [{...customAppearance,css:'body{}'},{...customAppearance,overrides:{accent:'url(https://evil)'}},{...customAppearance,overrides:{unknown:'#FFFFFF'}},{...customAppearance,base:'C'}])expect(()=>contract.validateClientPreferences({...remote,customAppearance:custom})).toThrow();
 expect(()=>contract.validateClientPreferences({...fixture(),appearance:'custom'})).toThrow();
});
it('accepts only audited local avatar references in both directions',()=>{
  const contract=modules['./clientPreferenceContract.ts'] as typeof import('./clientPreferenceContract');
  const remote=fixture();remote.home.avatar='/assets/avatars/owner.png';
  expect(contract.localToClientPreferences(contract.clientPreferencesToLocal(remote),3)).toEqual(remote);
});
it('matches Python schema Unicode character limits and rejects year zero',()=>{
  const contract=modules['./clientPreferenceContract.ts'] as typeof import('./clientPreferenceContract');const remote=fixture();remote.home.siteTitle='🌟'.repeat(120);remote.home.signature='🌙'.repeat(512);
  expect(contract.validateClientPreferences(remote)).toEqual(remote);
  expect(()=>contract.validateClientPreferences({...remote,home:{...remote.home,meetDate:'0000-01-01'}})).toThrow(/偏好/);
});
it('maps all 19 audited local keys to the exact HTTP DTO and back, without arbitrary values',()=>{
  const contract=modules['./clientPreferenceContract.ts'] as typeof import('./clientPreferenceContract');expect(contract,'typed HTTP conversion missing').toBeDefined();
  const remote=fixture(), portable=contract.clientPreferencesToLocal(remote);
  expect(Object.keys(portable.values)).toEqual([...CLIENT_PREFERENCE_KEYS]);
  expect(portable.values.stella_live2d).toBe('off');expect(portable.values.stella_sidebar_fold).toBe('1');
  expect(contract.localToClientPreferences(portable,3)).toEqual(remote);
  expect(()=>contract.validateClientPreferences({...remote,token:'not-allowed'})).toThrow(/偏好/);
  expect(()=>contract.validateClientPreferences({...remote,ui:{...remote.ui,notes:'not-allowed'}})).toThrow(/偏好/);
  expect(()=>contract.validateClientPreferences({...remote,home:{...remote.home,live2d:'off'}})).toThrow(/偏好/);
});
