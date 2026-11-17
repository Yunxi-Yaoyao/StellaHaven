import {afterEach,expect,it,vi} from 'vitest';
vi.mock('../home/auth',async()=>{const {reactive}=await import('vue');return {auth:reactive({me:{id:'fixture-owner'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false})};});
import {auth} from '../home/auth';
import {getBackups} from '../../api/backups';
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();Object.assign(auth,{sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false});});
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
it('aborts even if fetch ignores the signal and never publishes its late body',async()=>{
  let resolve!:(r:Response)=>void;vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(r=>{resolve=r;})));
  const controller=new AbortController();let outcome='pending';void getBackups(controller.signal).then(()=>outcome='resolved',error=>outcome=error.name);controller.abort();await flush();expect(outcome).toBe('AbortError');
  resolve(new Response('{}'));await flush();expect(outcome).toBe('AbortError');
});
it('bounds response body parsing by an abortable 30s deadline',async()=>{
  vi.useFakeTimers();let signal:AbortSignal|undefined;vi.stubGlobal('fetch',vi.fn((_url:string,options:RequestInit)=>{signal=options.signal as AbortSignal;return Promise.resolve({ok:true,status:200,json:()=>new Promise(()=>{})});}));
  let outcome='pending';void getBackups().then(()=>outcome='resolved',error=>outcome=error.name);await vi.advanceTimersByTimeAsync(30001);expect(outcome).toBe('TimeoutError');expect(signal?.aborted).toBe(true);expect(vi.getTimerCount()).toBe(0);
});
it('fences a late body across session invalidation instead of returning another owner snapshot',async()=>{
  let resolve!:(value:unknown)=>void;vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,status:200,json:()=>new Promise(r=>{resolve=r;})})));
  let outcome='pending';void getBackups().then(()=>outcome='resolved',error=>outcome=error.name);await flush();auth.requestEpoch++;resolve({config:{directory:'private-old-owner'}});await flush();expect(outcome).toBe('AbortError');
});
