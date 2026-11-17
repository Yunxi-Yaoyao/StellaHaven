import {afterEach, expect, it, vi} from 'vitest';
vi.mock('../modules/home/auth',async()=>{const {reactive}=await import('vue');return {auth:reactive({me:{id:'fixture-owner'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false})};});
import {auth} from '../modules/home/auth';
const modules=import.meta.glob('./backupDownload.ts',{eager:true});
const load=()=>{const module=modules['./backupDownload.ts'] as {startNativeBackupDownload?:(id:string,signal?:AbortSignal)=>Promise<{filename:string,bytes:number}>}|undefined;expect(module?.startNativeBackupDownload,'native authenticated streaming download boundary missing').toBeTypeOf('function');return module!.startNativeBackupDownload!;};
const filename='stella-all-'+ 'a'.repeat(32)+'.zip';
function headers(){return new Headers({'Content-Type':'application/zip','Content-Length':String(2*1024**3),'Content-Disposition':`attachment; filename="${filename}"`});}
function clicks(){const values:{href:string;name:string}[]=[];vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function(this:HTMLAnchorElement){values.push({href:this.getAttribute('href')!,name:this.download});});return values;}
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();vi.useRealTimers();document.body.innerHTML='';Object.assign(auth,{me:{id:'fixture-owner'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false});});
it('does HEAD metadata only then hands large ZIP transfer to browser without reading body or Blob',async()=>{
 const start=load(), native=clicks();vi.useFakeTimers();const blob=vi.fn(()=>{throw Error('must not buffer ZIP');}),json=vi.fn(()=>{throw Error('must not read HEAD body');});
 const fetcher=vi.fn(async()=>({ok:true,status:200,headers:headers(),blob,json}));vi.stubGlobal('fetch',fetcher);
 const result=await start('id /?');expect(result).toEqual({filename,bytes:2*1024**3});expect(fetcher).toHaveBeenCalledOnce();expect(fetcher.mock.calls[0]).toMatchObject(['/operations/backups/id%20%2F%3F/download',{method:'HEAD',credentials:'same-origin',cache:'no-store'}]);
 expect(blob).not.toHaveBeenCalled();expect(json).not.toHaveBeenCalled();expect(native).toEqual([{href:'/operations/backups/id%20%2F%3F/download',name:filename}]);expect(document.querySelector('a')).toBeNull();
 await vi.advanceTimersByTimeAsync(60001);expect(vi.getTimerCount()).toBe(0);expect(native).toHaveLength(1);
});
it.each([401,403,404,500])('does not launch native transfer after preflight HTTP %s',async status=>{
 const start=load(), native=clicks();vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,status,headers:new Headers()})));await expect(start('id')).rejects.toMatchObject({status});expect(native).toEqual([]);
});
it('aborts a stalled preflight with short deadline and rejects ignored late success',async()=>{
 const start=load(),native=clicks();vi.useFakeTimers();let resolve!:(v:unknown)=>void;vi.stubGlobal('fetch',vi.fn(()=>new Promise(r=>resolve=r)));
 const observed=start('id').catch(e=>e);await vi.advanceTimersByTimeAsync(30001);expect(await observed).toMatchObject({name:'TimeoutError'});resolve({ok:true,status:200,headers:headers()});await Promise.resolve();await Promise.resolve();expect(native).toEqual([]);
});
it('fences a late metadata response across owner or request epoch changes',async()=>{
 const start=load(),native=clicks();let resolve!:(v:unknown)=>void;vi.stubGlobal('fetch',vi.fn(()=>new Promise(r=>resolve=r)));
 const observed=start('id').catch(e=>e);auth.requestEpoch++;resolve({ok:true,status:200,headers:headers()});expect(await observed).toMatchObject({name:'AbortError'});expect(native).toEqual([]);
});
it('rejects unsafe filenames and nonZIP response metadata without a native request',async()=>{
 const start=load(),native=clicks();const invalid=headers();invalid.set('Content-Disposition','attachment; filename="../overwrite.zip"');vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,status:200,headers:invalid})));await expect(start('id')).rejects.toThrow();expect(native).toEqual([]);
});
