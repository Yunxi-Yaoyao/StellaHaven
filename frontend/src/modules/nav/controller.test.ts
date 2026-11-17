import {it,expect,vi} from 'vitest';
import {createNavController,defaults} from './controller';
import {effectiveStyle,defaultPreferences,destination,newCard} from './types';
it('explicit conflict rebase preserves unrelated server edits',async()=>{
 const module=await import('./types');expect('rebaseData' in module).toBe(true);
 const base=defaults(),g={id:'g',title:'base',description:'',icon:'',style:null,items:[{...newCard(),id:'c',title:'old',description:'base',url:'https://example.test'}]};base.groups=[g];
 const draft=structuredClone(base),latest=structuredClone(base);draft.groups[0]!.items[0]!.title='local';latest.groups[0]!.description='server-group';latest.groups[0]!.items[0]!.description='server-card';latest.preferences.title='server-settings';
 const merged=module.rebaseData(base,draft,latest);
 expect(merged.groups[0]!.items[0]!.title).toBe('local');expect(merged.groups[0]!.items[0]!.description).toBe('server-card');expect(merged.groups[0]!.description).toBe('server-group');expect(merged.preferences.title).toBe('server-settings');
});
it('an old read timeout never aborts a newer read',async()=>{
 vi.useFakeTimers();let n=0;const signals:AbortSignal[]=[];const settles:Array<(v:any)=>void>=[];
 const c=createNavController(async<T>(_p:string,o?:RequestInit)=>{n++;signals.push(o!.signal!);return new Promise<T>(r=>settles.push(r));},()=> 'a');
 const a=c.load();await vi.advanceTimersByTimeAsync(10000);const b=c.load();await vi.advanceTimersByTimeAsync(5001);
 expect(signals[1]!.aborted).toBe(false);
 settles[0]!({revision:0,data:defaults()});settles[1]!({revision:1,data:defaults()});await Promise.all([a,b]);vi.useRealTimers();expect(n).toBe(2);
});
it('times out pending reads instead of locking the page',async()=>{
 vi.useFakeTimers();
 const transport=async<T>(_p:string,options?:RequestInit)=>new Promise<T>((_resolve,reject)=>options?.signal?.addEventListener('abort',()=>reject(new DOMException('timeout','AbortError'))));
 const c=createNavController(transport,()=> 'a');const pending=c.load();
 await vi.advanceTimersByTimeAsync(15001);
 expect(c.loading.value).toBe(false);expect(c.error.value).toContain('读取失败');
 c.cancel();await pending;vi.useRealTimers();
});
it('preserves failure and blocks unknown writes until a fresh read',async()=>{
 let calls=0;
 const c=createNavController(async<T>(_path:string,o?:RequestInit)=>{calls++;if(o?.method==='PUT')throw new Error('lost ACK');return {revision:0,data:defaults()} as T;},()=> 'a');
 await c.load();expect(await c.save(defaults(),0)).toBe(false);expect(c.uncertain.value).toBe(true);
 const n=calls;expect(await c.save(defaults(),0)).toBe(false);expect(calls).toBe(n);
 await c.load();expect(c.uncertain.value).toBe(false);
});
it('late successful save cannot publish into another owner session',async()=>{
 let owner='a',resolve!:(v:any)=>void;
 const c=createNavController(async<T>()=>new Promise<T>(r=>resolve=r),()=>owner);
 const pending=c.save(defaults(),0);owner='b';c.reset();resolve({revision:1,data:defaults()});
 expect(await pending).toBe(false);expect(c.state.value).toBeNull();
});
it('tristate style preserves false and network choice never drops fallback',()=>{
 const p={...defaultPreferences(),hideTitle:true,hideDescription:true};
 expect(effectiveStyle({hideTitle:false,hideDescription:null,layout:'info'},p)).toMatchObject({hideTitle:false,hideDescription:true,layout:'info'});
 expect(effectiveStyle(null,p).layout).toBe('icon');
 const c={...newCard(),url:'https://example.test',lanUrl:''};expect(destination(c,'lan')).toBe(c.url);
});
it('native controller stores readback and fences cancelled/old owner results',async()=>{
 const module=await import('./controller');
 expect('createNavController' in module).toBe(true);
 const {createNavController,defaults}=module;
 let owner='a',resolve!:(v:any)=>void;
 const transport=async()=>new Promise<any>(r=>{resolve=r});
 const c=createNavController(transport,()=>owner);
 const task=c.load();owner='b';c.cancel();resolve({revision:1,data:defaults()});await task;
 expect(c.state.value).toBeNull();expect(c.loading.value).toBe(false);
});
