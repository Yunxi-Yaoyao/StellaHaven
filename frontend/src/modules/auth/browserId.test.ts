import {afterEach,expect,it,vi} from 'vitest';
afterEach(()=>{vi.unstubAllGlobals();localStorage.clear();vi.resetModules();});
it('persists a UUID per browser storage and survives module reload without any fetch',async()=>{
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
 const {getBrowserId}=await import('./browserId');const first=getBrowserId();
 expect(first).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
 expect(localStorage.getItem('stella_browser_id')).toBe(first);
 vi.resetModules();expect((await import('./browserId')).getBrowserId()).toBe(first);expect(fetch).not.toHaveBeenCalled();
});
it('uses secure getRandomValues on old WebViews and keeps an in-memory ID when storage throws',async()=>{
 const getRandomValues=vi.fn((bytes:Uint8Array)=>{bytes.fill(37);return bytes;});
 vi.stubGlobal('crypto',{getRandomValues});vi.stubGlobal('localStorage',{getItem(){throw Error('blocked')},setItem(){throw Error('blocked')}});
 const {getBrowserId}=await import('./browserId');expect(getBrowserId()).toBe('25252525-2525-4525-a525-252525252525');expect(getBrowserId()).toBe(getBrowserId());expect(getRandomValues).toHaveBeenCalledTimes(1);
});
it('does not invent an insecure identifier without crypto',async()=>{
 vi.stubGlobal('crypto',{});const {getBrowserId}=await import('./browserId');expect(getBrowserId()).toBeUndefined();
});
it('replaces malformed stored values, but never derives identity from IP or UA',async()=>{
 localStorage.setItem('stella_browser_id','192.0.2.1');const {getBrowserId}=await import('./browserId');expect(getBrowserId()).not.toBe('192.0.2.1');
});
