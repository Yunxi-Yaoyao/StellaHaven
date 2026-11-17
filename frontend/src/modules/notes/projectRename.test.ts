import {afterEach,beforeEach,it,expect,vi} from 'vitest';
import {createApp,h,nextTick,type App} from 'vue';
import WebProjectPane from './WebProjectPane.vue';
import {auth} from '../home/auth';
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}),refreshAccess:vi.fn(async()=>false)}));
vi.mock('./ProjectSourceEditor.vue',()=>({default:{props:['modelValue','filename','readonly'],template:'<textarea :readonly="readonly" :value="modelValue" :data-filename="filename" @input="$emit(\'update:modelValue\',$event.target.value)" />'}}));
let pane:any; let app:App,host:HTMLElement,puts:any[],fail:boolean,held:((r:Response)=>void)|null,hold:boolean;
const file={id:'file',path:'js/app.js',kind:'text',mime:'text/javascript',updated_at:'v1',content:'original bytes',url:null};
let remote:any;
const project:any={id:'root',workspace_id:'ws',title:'Project',entry:'index.html',files:[file],directories:[]};
const settle=async()=>{for(let i=0;i<35;i++){await Promise.resolve();await nextTick();}};
const res=(data:any,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
const button=(text:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===text)!;
const input=()=>host.querySelector<HTMLInputElement>('input[aria-label="文件名（不含扩展名）"]')!;
function type(value:string){input().value=value;input().dispatchEvent(new Event('input',{bubbles:true}));}
beforeEach(()=>{
 puts=[];fail=false;hold=false;held=null;remote={...file};
 Object.assign(auth,{me:{id:'owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});
 HTMLDialogElement.prototype.showModal=function(){this.open=true;};HTMLDialogElement.prototype.close=function(){this.open=false;};
 vi.stubGlobal('fetch',vi.fn(async(path:string,options?:RequestInit)=>{
  if(path==='/web-projects/root/files/file')return res(remote);
  if(path==='/documents/file'&&options?.method==='PUT'){const body=JSON.parse(String(options.body));puts.push(body);if(hold)return new Promise<Response>(r=>held=r);if(fail)return res({detail:'Conflict'},409);remote={...remote,path:'js/'+body.title,updated_at:'v2'};return res({...remote,title:body.title});}
  if(path==='/web-projects/root')return res({...project,files:[remote]});
  throw Error('Unexpected '+path);
 }));
 host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(WebProjectPane,{ref:(v:any)=>pane=v,project,fileId:'file',active:true})});app.mount(host);
});
afterEach(()=>{app?.unmount();host?.remove();vi.unstubAllGlobals();});
it('public source action warns before filename CAS, preserves extension and updates source revision without refresh',async()=>{
 await settle();expect(button('重命名文件')).toBeTruthy();button('重命名文件').focus();button('重命名文件').click();await settle();
 expect(host.textContent).toContain('不会自动修复');expect(host.textContent).toContain('手动刷新');expect(input().value).toBe('app');expect(document.activeElement).toBe(input());
 input().dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));expect(document.activeElement).toBe(button('确认重命名'));
 type('renamed');host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await settle();
 expect(puts).toEqual([{updated_at:'v1',title:'renamed.js'}]);expect(host.querySelector('textarea')?.getAttribute('data-filename')).toBe('js/renamed.js');expect(host.textContent).toContain('已重命名');expect(document.activeElement).toBe(button('重命名文件'));
});
it('cancel and illegal names do not write; failed CAS keeps the exact input and base for explicit retry',async()=>{
 await settle();expect(button('重命名文件')).toBeTruthy();button('重命名文件').click();await settle();type('../bad');button('确认重命名').click();await settle();expect(puts).toHaveLength(0);expect(input().value).toBe('../bad');
 button('取消').click();await settle();expect(puts).toHaveLength(0);button('重命名文件').click();await settle();type('kept');fail=true;button('确认重命名').click();await settle();expect(input().value).toBe('kept');expect(host.textContent).toContain('冲突');expect(document.activeElement).toBe(input());
 fail=false;button('确认重命名').click();await settle();expect(puts).toEqual([{updated_at:'v1',title:'kept.js'},{updated_at:'v1',title:'kept.js'}]);
});
it('same-owner authentication suspension closes rename and restores source editing on recovery',async()=>{
 await settle();button('重命名文件').click();await settle();expect(host.querySelector('textarea')?.readOnly).toBe(true);
 auth.suspended=true;auth.requestEpoch++;await settle();auth.suspended=false;auth.requestEpoch++;await settle();expect(host.querySelector('dialog[open]')).toBeNull();expect(host.querySelector('textarea')?.readOnly).toBe(false);
});
it('IME Enter is not a submission, and a transport failure keeps the filename for retry',async()=>{
 await settle();button('重命名文件').click();await settle();type('输入保留');const composing=new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true,cancelable:true});input().dispatchEvent(composing);expect(composing.defaultPrevented).toBe(true);expect(puts).toHaveLength(0);
 const original=fetch;vi.stubGlobal('fetch',vi.fn(async(path:string,options?:RequestInit)=>{if(path==='/documents/file'&&options?.method==='PUT')throw Error('offline');return original(path,options);}));
 button('确认重命名').click();await settle();expect(input().value).toBe('输入保留');expect(host.textContent).toContain('offline');expect(document.activeElement).toBe(input());
});
it('a failed pending source save prevents opening rename without losing the source draft',async()=>{
 await settle();const original=fetch;vi.stubGlobal('fetch',vi.fn(async(path:string,options?:RequestInit)=>{if(options?.method==='PATCH')throw Error('source save offline');return original(path,options);}));const text=host.querySelector('textarea')!;text.value='pending source';text.dispatchEvent(new Event('input',{bubbles:true}));button('重命名文件').click();await settle();expect(host.querySelector('dialog[open]')).toBeNull();expect(puts).toHaveLength(0);expect(text.value).toBe('pending source');
});
it('owner change hides the dialog and ignores a held rename response',async()=>{
 await settle();expect(button('重命名文件')).toBeTruthy();button('重命名文件').click();await settle();type('private');hold=true;button('确认重命名').click();await settle();expect(puts).toHaveLength(1);
 auth.me={...auth.me!,id:'other'};auth.sessionGeneration++;await settle();held!(res({id:'file',title:'private.js',updated_at:'v2'}));await settle();expect(host.querySelector('dialog[open]')).toBeNull();expect(host.textContent).not.toContain('private');
});

// R01: retain the independent held-save oracle in the product owning suite.
it.each(['prepareNavigation','prepareDeletion'])('REVIEW %s rechecks rename admitted during awaited source save',async(method)=>{
 await settle();let release:any=null;const original=fetch;
 vi.stubGlobal('fetch',vi.fn(async(path:string,opts?:RequestInit)=>{if(opts?.method==='PATCH')return new Promise<Response>(r=>release=r);return original(path,opts);}));
 const text=host.querySelector('textarea')!;text.value='draft';text.dispatchEvent(new Event('input',{bubbles:true}));
 const navigating=pane[method]();await settle();expect(release).not.toBeNull();
 button('重命名文件').click();await settle();release(res({...remote,content:'draft',updated_at:'v2'}));
 await settle();expect(host.querySelector('dialog[open]')).not.toBeNull();expect(await navigating).toBe(false);
});
