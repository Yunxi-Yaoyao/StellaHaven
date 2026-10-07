import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { computed } from 'vue';
import { auth } from '../modules/home/auth';
import { navigation, resetNavigation, type Website } from './navigation';
import { effectiveWebsiteBackground, confirmWebsiteBackground } from './websiteBackground';
const site=(id='ordinary'):Website=>({id,name:'普通网站',icon:'globe',mode:'iframe',adapter:'generic',browser_url:'https://example.test/',enabled:true,background:'home'});
beforeEach(()=>{localStorage.clear();resetNavigation();Object.assign(auth,{me:{id:'preference-test-owner'}});});
afterEach(()=>{vi.restoreAllMocks();resetNavigation();});
it('falls back to the website record when storage is unavailable or absent',()=>{
 navigation.legacy_routes={drive:'ordinary'};expect(effectiveWebsiteBackground(site())).toEqual({mode:'home',legacy:false});
 vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw new DOMException('disabled');});
 expect(effectiveWebsiteBackground(site())).toEqual({mode:'home',legacy:false});
});
it('keeps a confirmed selection effective in memory if local persistence is blocked',()=>{
 navigation.legacy_routes={drive:'blocked'};localStorage.setItem('stella_drive_bg_mode','solid');const item=site('blocked');
 const effective=computed(()=>effectiveWebsiteBackground(item));expect(effective.value.mode).toBe('solid');
 vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new DOMException('disabled');});vi.spyOn(Storage.prototype,'removeItem').mockImplementation(()=>{throw new DOMException('disabled');});
 confirmWebsiteBackground(item);expect(effective.value.mode).toBe('home');expect(effective.value.legacy).toBe(false);
});
it('does not clear unrelated legacy keys or write when merely reading or confirming another module',()=>{
 navigation.legacy_routes={drive:'different'};localStorage.setItem('stella_drive_bg_mode','solid');const write=vi.spyOn(Storage.prototype,'setItem');
 effectiveWebsiteBackground(site());confirmWebsiteBackground(site());expect(localStorage.getItem('stella_drive_bg_mode')).toBe('solid');expect(write).not.toHaveBeenCalled();
});
it('the explicit marker is bound to owner and module, not all devices or websites',()=>{
 navigation.legacy_routes={drive:'ordinary'};localStorage.setItem('stella_drive_bg_mode','solid');confirmWebsiteBackground(site());localStorage.setItem('stella_drive_bg_mode','solid');
 expect(effectiveWebsiteBackground(site()).mode).toBe('home');auth.me={...auth.me!,id:'another-owner'};expect(effectiveWebsiteBackground(site()).mode).toBe('solid');
 navigation.legacy_routes={drive:'another-module'};expect(effectiveWebsiteBackground(site('another-module')).mode).toBe('solid');
});
