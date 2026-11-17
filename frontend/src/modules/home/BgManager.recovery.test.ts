// @vitest-environment jsdom
import { beforeEach, afterEach, test, expect, vi } from 'vitest';
import { createApp, nextTick, h, KeepAlive, ref } from 'vue';
import BgManager from './BgManager.vue';
import { auth } from './auth';
import { bgManagerOpen, homeSettings } from './settings';
import { backgroundEntries, backgroundMedia } from './backgroundMedia';
const original = { id:'owner-a', username:'a', display_name:'A', is_admin:false, avatar_url:'',home_bg:'/old.svg',email:'',email_verified:false };
const entry = {id:'one',name:'原背景',url:'/one.svg',ext:'png',isDefault:false};
let server: typeof original;
let rows: typeof entry[];
let calls: string[];
let failWrite = false, failRead = false;
let app: ReturnType<typeof createApp>;
const json = (body:unknown,status=200) => new Response(JSON.stringify(body),{status});
async function flush(){for(let i=0;i<30;i++) await Promise.resolve(); await nextTick();}
async function mount(){const root=document.createElement('div');document.body.append(root);app=createApp(BgManager);app.mount(root);bgManagerOpen.value=true;await flush();}
function button(text:string){return [...document.querySelectorAll<HTMLButtonElement>('button')].find(e=>e.textContent?.trim()===text)!;}
async function click(text:string){button(text).click();await flush();}
beforeEach(()=>{
 server={...original};rows=[{...entry}];calls=[];failWrite=false;failRead=false;
 Object.assign(auth,{me:{...original},sessionGeneration:0,requestEpoch:0,sessionClosing:false,suspended:false});
 bgManagerOpen.value=false;backgroundEntries.value=[];for(const key in backgroundMedia) delete backgroundMedia[key];
 homeSettings.bgCrop={cx:.5,cy:.5,w:1,h:1};localStorage.clear();
 vi.stubGlobal('fetch',vi.fn(async(input,init)=>{
  const url=String(input),method=init?.method||'GET';calls.push(`${method} ${url}`);
  if(method!=='GET'&&failWrite)return json({detail:'拒绝写入'},403);
  if(method==='GET'&&url==='/auth/me'&&failRead)return json({detail:'读回失败'},503);
  if(url==='/auth/me'){if(method==='PATCH')Object.assign(server,JSON.parse(String(init!.body)));return json(server);}
  if(url==='/homebg/') { if(failRead)return json({detail:'读回失败'},503);return json(rows); }
  if(url==='/homebg/one'&&method==='PATCH'){Object.assign(rows[0]!,JSON.parse(String(init!.body)));return json(rows[0]);}
  if(url==='/homebg/one'&&method==='DELETE'){rows=rows.filter(e=>e.id!=='one');return json({ok:true});}
  throw new Error(`DENY ${method} ${url}`);
 }));
});
afterEach(async()=>{app?.unmount();await flush();vi.restoreAllMocks();vi.unstubAllGlobals();document.body.innerHTML='';});
test.each(['rename','delete','load','upload'] as const)('late %s response never publishes into another owner',async(kind)=>{
 await mount();let release!:()=>void;const held=new Promise<void>(r=>release=r);let started=false;
 const fetcher=vi.mocked(fetch).getMockImplementation()!;
 vi.mocked(fetch).mockImplementation(async(input,init)=>{
   const hit=kind==='load'?String(input)==='/homebg/':kind==='upload'?String(input)==='/homebg/upload':init?.method===(kind==='delete'?'DELETE':'PATCH');
   if(hit){started=true;await held;if(kind==='upload')return json({...entry,id:'uploaded'});}
   return fetcher(input,init);
 });
 if(kind==='load'){bgManagerOpen.value=false;await flush();bgManagerOpen.value=true;}
 if(kind==='upload'){const input=document.querySelector<HTMLInputElement>('input[type="file"]')!;Object.defineProperty(input,'files',{value:[new File(['image'],'a.png',{type:'image/png'})]});input.dispatchEvent(new Event('change',{bubbles:true}));}
 if(kind==='rename'){document.querySelector<HTMLButtonElement>('[title="重命名"]')!.click();await flush();const input=document.querySelector<HTMLInputElement>('.rename-input')!;input.value='迟到名称';input.dispatchEvent(new Event('input'));input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}));}
 if(kind==='delete'){document.querySelector<HTMLButtonElement>('[title="删除"]')!.click();await flush();button('确认删除').click();}
 await flush();expect(started).toBe(true);auth.me={...original,id:'owner-b'};backgroundEntries.value=[{...entry,id:'b',name:'B'}];await flush();release();await flush();
 expect(backgroundEntries.value.map(e=>e.name)).toEqual(['B']);expect(document.body.textContent).not.toContain('迟到名称');
});

test('acknowledged pick with mismatched readback stays GET-only',async()=>{
 await mount();document.querySelector<HTMLElement>('.cell')!.click();await flush();
 const fetcher=vi.mocked(fetch).getMockImplementation()!;
 vi.mocked(fetch).mockImplementation(async(input,init)=>String(input)==='/auth/me'&&(!init||!init.method)?json(original):fetcher(input,init));
 await click('确定更换');expect(server.home_bg).toBe(entry.url);await click('重试确认');
 expect(calls.filter(x=>x==='PATCH /auth/me')).toHaveLength(1);expect(bgManagerOpen.value).toBe(true);
});

test('rejected rename can be corrected without losing the draft',async()=>{
 await mount();document.querySelector<HTMLButtonElement>('[title="重命名"]')!.click();await flush();
 const input=document.querySelector<HTMLInputElement>('.rename-input')!;input.value='原草稿';input.dispatchEvent(new Event('input'));failWrite=true;await click('保存名称');
 await click('继续修改');expect(document.querySelector<HTMLInputElement>('.rename-input')!.value).toBe('原草稿');
 const edit=document.querySelector<HTMLInputElement>('.rename-input')!;expect(edit.readOnly).toBe(false);edit.value='修正名称';edit.dispatchEvent(new Event('input'));failWrite=false;await click('保存名称');expect(rows[0]!.name).toBe('修正名称');
});

test('rename retains text after rejection and successful-write failed-read retries only GET',async()=>{
 await mount();document.querySelector<HTMLButtonElement>('[title="重命名"]')!.click();await flush();
 const input=document.querySelector<HTMLInputElement>('.rename-input')!;input.value='保留名称';input.dispatchEvent(new Event('input',{bubbles:true}));failWrite=true;
 input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));await flush();
 expect(document.querySelector<HTMLInputElement>('.rename-input')?.value).toBe('保留名称');expect(document.body.textContent).toContain('拒绝写入');
 failWrite=false;failRead=true;await click('重试重命名');expect(rows[0]!.name).toBe('保留名称');
 failRead=false;await click('重试确认');expect(backgroundEntries.value[0]!.name).toBe('保留名称');
 expect(calls.filter(x=>x==='PATCH /homebg/one')).toHaveLength(2);expect(document.querySelector('.rename-input')).toBeNull();
});
test('delete uses exact-scope dialog and reconciles lost response without replay',async()=>{
 await mount();const native=vi.spyOn(window,'confirm').mockReturnValue(false);
 document.querySelector<HTMLButtonElement>('[title="删除"]')!.click();await flush();
 expect(native).not.toHaveBeenCalled();expect(document.querySelector('[role="dialog"][aria-label="删除背景"]')?.textContent).toContain('原背景');
 const fetcher=vi.mocked(fetch).getMockImplementation()!;
 vi.mocked(fetch).mockImplementation(async(input,init)=>{const result=await fetcher(input,init);if(init?.method==='DELETE')throw new Error('lost response');return result;});
 await click('确认删除');expect(rows).toHaveLength(0);expect(backgroundEntries.value).toHaveLength(1);
 failRead=true;await click('重试确认');expect(backgroundEntries.value).toHaveLength(1);
 failRead=false;await click('重试确认');expect(backgroundEntries.value).toHaveLength(0);expect(calls.filter(x=>x==='DELETE /homebg/one')).toHaveLength(1);
});

test('crop reports a failing existing persistence watcher instead of closing',async()=>{
 await mount();document.querySelector<HTMLElement>('.cell')!.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));await flush();
 const set=Storage.prototype.setItem;let writes=0;
 vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,k,v){if(k==='stella_home_bgcrop'&&++writes>1)throw new Error('second write quota');set.call(this,k,v);});
 await click('使用这个取景');expect(bgManagerOpen.value).toBe(true);expect(document.body.textContent).toContain('当前设备');
 vi.restoreAllMocks();await click('重试本地保存');expect(bgManagerOpen.value).toBe(false);
});

test('crop waits for account readback and storage readback, retaining the preview for local-only retry',async()=>{
 await mount();document.querySelector<HTMLElement>('.cell')!.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));await flush();
 const before={...homeSettings.bgCrop};failWrite=true;await click('使用这个取景');
 expect(document.querySelector('.preview-mask')).not.toBeNull();expect(homeSettings.bgCrop).toEqual(before);
 failWrite=false;const set=Storage.prototype.setItem;vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,k,v){if(k==='stella_home_bgcrop')throw new Error('quota');set.call(this,k,v);});
 await click('重试保存');expect(server.home_bg).toBe(entry.url);expect(document.querySelector('.preview-mask')).not.toBeNull();expect(document.body.textContent).toContain('当前设备');
 vi.restoreAllMocks();await click('重试本地保存');
 expect(JSON.parse(localStorage.getItem('stella_home_bgcrop')!)).toEqual(homeSettings.bgCrop);expect(bgManagerOpen.value).toBe(false);
 expect(calls.filter(x=>x==='PATCH /auth/me')).toHaveLength(2);
});

test.each(['logout','owner','epoch','unmount'] as const)('late pick is fenced after %s',async(change)=>{
 await mount();document.querySelector<HTMLElement>('.cell')!.click();await flush();
 let release!:()=>void;const held=new Promise<void>(r=>release=r);
 const fetcher=vi.mocked(fetch).getMockImplementation()!;
 vi.mocked(fetch).mockImplementation(async(input,init)=>{if(init?.method==='PATCH'){await held;return json({...original,home_bg:entry.url});}return fetcher(input,init);});
 button('确定更换').click();await flush();
 if(change==='logout')auth.me=null;
 if(change==='owner')auth.me={...original,id:'owner-b',home_bg:'/b.svg'};
 if(change==='epoch')auth.requestEpoch++;
 if(change==='unmount')app.unmount();
 await flush();release();await flush();
 expect(auth.me?.home_bg).toBe(change==='logout'?undefined:change==='owner'?'/b.svg':'/old.svg');
 expect(calls.filter(x=>x==='GET /auth/me')).toHaveLength(0);
});

test.each(['deactivate','unmount','owner','session','suspended'] as const)('late successful readback is ignored after %s',async(change)=>{
 const visible=ref(true);const node=document.createElement('div');document.body.append(node);
 app=createApp({render:()=>h(KeepAlive,{},()=>visible.value?h(BgManager):null)});app.mount(node);bgManagerOpen.value=true;await flush();
 document.querySelector<HTMLElement>('.cell')!.click();await flush();
 const fetcher=vi.mocked(fetch).getMockImplementation()!;let release!:(r:Response)=>void;let reading=false;
 vi.mocked(fetch).mockImplementation(async(input,init)=>{if(String(input)==='/auth/me'&&(!init||!init.method)){reading=true;return new Promise<Response>(r=>release=r);}return fetcher(input,init);});
 button('确定更换').click();await flush();expect(reading).toBe(true);
 if(change==='deactivate')visible.value=false;
 if(change==='unmount')app.unmount();
 if(change==='owner')auth.me={...original,id:'owner-b'};
 if(change==='session')auth.sessionGeneration++;
 if(change==='suspended')auth.suspended=true;
 await flush();release(json(server));await flush();expect(auth.me?.home_bg).toBe('/old.svg');
});

test('delete rejects and malformed readback never confirms absence',async()=>{
 await mount();document.querySelector<HTMLButtonElement>('[title="删除"]')!.click();await flush();failWrite=true;await click('确认删除');
 expect(rows).toHaveLength(1);expect(backgroundEntries.value).toHaveLength(1);expect(document.body.textContent).toContain('拒绝写入');
 failWrite=false;const fetcher=vi.mocked(fetch).getMockImplementation()!;
 vi.mocked(fetch).mockImplementation(async(input,init)=>String(input)==='/homebg/'?json({partial:[]}):fetcher(input,init));
 await click('确认删除');expect(rows).toHaveLength(0);expect(backgroundEntries.value).toHaveLength(1);await click('重试确认');
 expect(calls.filter(x=>x==='DELETE /homebg/one')).toHaveLength(2);expect(document.body.textContent).toContain('不完整');
});

test('pick retains selected draft on rejection and only closes after authoritative readback',async()=>{
 await mount();document.querySelector<HTMLElement>('.cell')!.click();await flush();failWrite=true;await click('确定更换');
 expect(bgManagerOpen.value).toBe(true);expect(auth.me?.home_bg).toBe('/old.svg');expect(document.body.textContent).toContain('拒绝写入');
 failWrite=false;failRead=true;await click('重试保存');
 expect(server.home_bg).toBe(entry.url);expect(bgManagerOpen.value).toBe(true);expect(auth.me?.home_bg).toBe('/old.svg');
 failRead=false;await click('重试确认');
 expect(calls.filter(x=>x==='PATCH /auth/me')).toHaveLength(2);expect(auth.me?.home_bg).toBe(entry.url);expect(bgManagerOpen.value).toBe(false);
});
