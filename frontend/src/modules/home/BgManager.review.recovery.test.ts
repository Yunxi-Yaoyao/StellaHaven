// @vitest-environment jsdom
import {beforeEach,afterEach,test,expect,vi} from 'vitest';
import {createApp,nextTick} from 'vue';
import BgManager from './BgManager.vue';
import {auth} from './auth';
import {bgManagerOpen,homeSettings} from './settings';
import {backgroundEntries,backgroundMedia,loadBackgroundEntries} from './backgroundMedia';
const owner={id:'review-a',username:'a',display_name:'A',is_admin:false,avatar_url:'',home_bg:'/old.svg',email:'',email_verified:false};
const one={id:'one',name:'One',url:'/one.svg',ext:'png',isDefault:false};
let server:any, rows:any[], calls:string[], app:ReturnType<typeof createApp>;
const response=(data:any,status=200)=>new Response(JSON.stringify(data),{status});
async function flush(){for(let i=0;i<40;i++)await Promise.resolve();await nextTick();}
function button(label:string){return [...document.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===label);}
async function click(label:string){expect(button(label),label).toBeTruthy();button(label)!.click();await flush();}
async function mount(){const root=document.createElement('div');document.body.append(root);app=createApp(BgManager);app.mount(root);bgManagerOpen.value=true;await flush();}
beforeEach(()=>{server={...owner};rows=[{...one}];calls=[];Object.assign(auth,{me:{...owner},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false});bgManagerOpen.value=false;backgroundEntries.value=[];for(const k in backgroundMedia)delete backgroundMedia[k];localStorage.clear();homeSettings.bgCrop={cx:.5,cy:.5,w:1,h:1};vi.stubGlobal('fetch',vi.fn(async(input,init)=>{const u=String(input),m=init?.method||'GET';calls.push(m+' '+u);if(u==='/auth/me'){if(m==='PATCH')Object.assign(server,JSON.parse(String(init!.body)));return response(server);}if(u==='/homebg/'&&m==='GET')return response(rows);if(u==='/homebg/one'&&m==='DELETE'){rows=rows.filter(r=>r.id!=='one');return response({ok:true});}if(u==='/homebg/one'&&m==='PATCH'){Object.assign(rows[0],JSON.parse(String(init!.body)));return response(rows[0]);}if(u==='/homebg/upload'&&m==='POST'){const item={...one,id:'uploaded',url:'/uploaded.svg'};rows.push(item);return response(item);}throw new Error('DENY '+m+' '+u);}));});
afterEach(async()=>{app?.unmount();await flush();vi.restoreAllMocks();vi.unstubAllGlobals();document.body.innerHTML='';});

test('R1 superseded acknowledged pick has an explicit GET-only use-server exit across reopen',async()=>{
 await mount();document.querySelector<HTMLElement>('.cell')!.click();await flush();
 const base=vi.mocked(fetch).getMockImplementation()!;let fail=true;
 vi.mocked(fetch).mockImplementation(async(i,init)=>{
  if(String(i)==='/auth/me'&&!init?.method&&fail)return response({detail:'unavailable'},503);
  return base(i,init);
 });
 await click('确定更换');expect(server.home_bg).toBe(one.url);
 expect(button('采用服务器当前值')).toBeUndefined();
 bgManagerOpen.value=false;await flush();server.home_bg='/default.svg';fail=false;
 bgManagerOpen.value=true;await flush();await click('重试确认');await click('重试确认');
 expect(calls.filter(c=>c==='PATCH /auth/me')).toHaveLength(1);
 expect(button('确定更换')!.disabled).toBe(true);
 await click('采用服务器当前值');
 expect(auth.me?.home_bg).toBe('/default.svg');
 expect([...document.querySelectorAll<HTMLButtonElement>('[title="重命名"],[title="删除"]')].every(b=>!b.disabled)).toBe(true);
 expect(calls.filter(c=>c==='PATCH /auth/me')).toHaveLength(1);
 document.querySelector<HTMLButtonElement>('[title="重命名"]')!.click();await flush();
 const input=document.querySelector<HTMLInputElement>('.rename-input')!;input.value='new name';input.dispatchEvent(new Event('input'));await click('保存名称');
 expect(rows[0].name).toBe('new name');
});

async function rename(name:string){
 document.querySelector<HTMLButtonElement>('[title="重命名"]')!.click();await flush();
 const input=document.querySelector<HTMLInputElement>('.rename-input')!;input.value=name;input.dispatchEvent(new Event('input'));await click('保存名称');
}
test('R1 superseded acknowledged rename offers use-server only after successful catalog read',async()=>{
 await mount();const base=vi.mocked(fetch).getMockImplementation()!;let fail=true;
 vi.mocked(fetch).mockImplementation(async(i,init)=>String(i)==='/homebg/'&&fail?response({detail:'unavailable'},503):base(i,init));
 await rename('old intent');expect(rows[0].name).toBe('old intent');expect(button('采用服务器当前值')).toBeUndefined();
 rows[0].name='another edit';fail=false;await click('重试确认');
 expect(document.querySelector<HTMLInputElement>('.rename-input')!.value).toBe('old intent');
 expect(button('采用服务器当前值')).toBeTruthy();
 fail=true;await click('重试确认');expect(button('采用服务器当前值')).toBeUndefined();
 fail=false;await click('重试确认');await click('采用服务器当前值');
 expect(backgroundEntries.value[0]!.name).toBe('another edit');expect(document.querySelector('.rename-input')).toBeNull();
 expect(calls.filter(c=>c==='PATCH /homebg/one')).toHaveLength(1);
 await rename('explicit new edit');expect(rows[0].name).toBe('explicit new edit');
 document.querySelector<HTMLButtonElement>('[title="删除"]')!.click();await flush();await click('确认删除');expect(rows).toEqual([]);
});

// Exact independent-review upload race, now asserting preservation (not characterization).
test.each(['shared','local'] as const)('R2 acknowledged upload survives an older %s list snapshot',async(channel)=>{
 await mount();let release!:(r:Response)=>void;const base=vi.mocked(fetch).getMockImplementation()!;let held=true;
 vi.mocked(fetch).mockImplementation(async(i,init)=>{if(String(i)==='/homebg/'&&held){held=false;return new Promise<Response>(r=>release=r);}return base(i,init);});
 let stale:Promise<unknown>|undefined;
 if(channel==='shared')stale=loadBackgroundEntries();
 else {bgManagerOpen.value=false;await flush();bgManagerOpen.value=true;}
 await flush();expect(release).toBeTypeOf('function');
 const input=document.querySelector<HTMLInputElement>('input[type="file"]')!;Object.defineProperty(input,'files',{value:[new File(['fixture'],'x.png',{type:'image/png'})]});input.dispatchEvent(new Event('change',{bubbles:true}));await flush();
 expect(backgroundEntries.value.map(e=>e.id)).toEqual(['one','uploaded']);expect(rows.map(e=>e.id)).toEqual(['one','uploaded']);
 release(response([one]));await stale;await flush();
 expect(backgroundEntries.value.map(e=>e.id)).toEqual(['one','uploaded']);
 await click('确定更换');expect(server.home_bg).toBe('/uploaded.svg');
 expect(calls.filter(c=>c==='POST /homebg/upload')).toHaveLength(1);
});

test('verified DELETE fences both older own load and shared list snapshots',async()=>{
 await mount();const base=vi.mocked(fetch).getMockImplementation()!;const releases:Array<(r:Response)=>void>=[];let hold=true;
 vi.mocked(fetch).mockImplementation(async(i,init)=>{if(String(i)==='/homebg/'&&hold)return new Promise<Response>(r=>releases.push(r));return base(i,init);});
 const shared=loadBackgroundEntries();bgManagerOpen.value=false;await flush();bgManagerOpen.value=true;await flush();expect(releases).toHaveLength(2);hold=false;
 document.querySelector<HTMLButtonElement>('[title="删除"]')!.click();await flush();await click('确认删除');expect(backgroundEntries.value).toEqual([]);
 releases.forEach(r=>r(response([one])));await shared;await flush();expect(backgroundEntries.value).toEqual([]);expect(rows).toEqual([]);
});

test('uncertain DELETE still present requires another explicit confirmation',async()=>{
 await mount();const base=vi.mocked(fetch).getMockImplementation()!;let lost=true;let deletes=0;
 vi.mocked(fetch).mockImplementation(async(i,init)=>{if(init?.method==='DELETE'){deletes++;if(lost){lost=false;throw new Error('request lost before commit');}}return base(i,init);});
 document.querySelector<HTMLButtonElement>('[title="删除"]')!.click();await flush();await click('确认删除');await click('重试确认');expect(rows).toHaveLength(1);expect(deletes).toBe(1);expect(button('确认删除')).toBeTruthy();await click('确认删除');expect(deletes).toBe(2);expect(rows).toEqual([]);
});


test.each(['owner','session','epoch','suspended','closing'] as const)('R1 already-read adoption snapshot is discarded on %s change',async(change)=>{
 await mount();const base=vi.mocked(fetch).getMockImplementation()!;
 vi.mocked(fetch).mockImplementation(async(i,init)=>{const result=await base(i,init);if(init?.method==='PATCH')rows[0].name='server override';return result;});
 await rename('OWNER_A_PRIVATE_INTENT');expect(button('采用服务器当前值')).toBeTruthy();
 const staleButton=button('采用服务器当前值')!;
 if(change==='owner')auth.me={...owner,id:'owner-b'};
 if(change==='session')auth.sessionGeneration++;
 if(change==='epoch')auth.requestEpoch++;
 if(change==='suspended')auth.suspended=true;
 if(change==='closing')auth.sessionClosing=true;
 backgroundEntries.value=[{...one,id:'b',name:'B'}];staleButton.click();await flush();
 expect(button('采用服务器当前值')).toBeUndefined();expect(backgroundEntries.value.map(e=>e.name)).toEqual(['B']);
 expect(document.body.textContent).not.toContain('OWNER_A_PRIVATE_INTENT');expect(JSON.stringify(localStorage)).not.toContain('OWNER_A_PRIVATE_INTENT');
});
test.each([401,403,503])('R1 failed pick read %s revokes a prior successful adoption snapshot',async(status)=>{
 await mount();document.querySelector<HTMLElement>('.cell')!.click();await flush();
 const base=vi.mocked(fetch).getMockImplementation()!;let bad=false;
 vi.mocked(fetch).mockImplementation(async(i,init)=>String(i)==='/auth/me'&&!init?.method?response(bad?{detail:'read failed'}:owner,bad?status:200):base(i,init));
 await click('确定更换');expect(button('采用服务器当前值')).toBeTruthy();bad=true;await click('重试确认');
 expect(button('采用服务器当前值')).toBeUndefined();expect(button('确定更换')!.disabled).toBe(true);expect(calls.filter(c=>c==='PATCH /auth/me')).toHaveLength(1);
});
test('R1 crop abandonment preserves device crop and never persists the frozen intent',async()=>{
 await mount();const before={...homeSettings.bgCrop};
 document.querySelector<HTMLElement>('.cell')!.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));await flush();
 const base=vi.mocked(fetch).getMockImplementation()!;
 vi.mocked(fetch).mockImplementation(async(i,init)=>String(i)==='/auth/me'&&!init?.method?response({...owner,home_bg:'/default.svg'}):base(i,init));
 const storage=vi.spyOn(Storage.prototype,'setItem');await click('使用这个取景');await click('采用服务器当前值');
 expect(homeSettings.bgCrop).toEqual(before);expect(storage).not.toHaveBeenCalled();
 await vi.waitFor(()=>expect(document.querySelector('.preview-mask')).toBeNull());
 expect(auth.me?.home_bg).toBe('/default.svg');expect(calls.filter(c=>c==='PATCH /auth/me')).toHaveLength(1);
});
test.each([{id:owner.id}, {...owner,id:'other-owner'}])('R1 incomplete or wrong-owner pick read cannot offer adoption: %j',async(me)=>{
 await mount();document.querySelector<HTMLElement>('.cell')!.click();await flush();
 const base=vi.mocked(fetch).getMockImplementation()!;
 vi.mocked(fetch).mockImplementation(async(i,init)=>String(i)==='/auth/me'&&!init?.method?response(me):base(i,init));
 await click('确定更换');expect(button('采用服务器当前值')).toBeUndefined();expect(auth.me?.home_bg).toBe(owner.home_bg);
});
