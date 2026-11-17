import {describe,it,expect,vi} from 'vitest';
import {ref} from 'vue';
import * as assets from './projectAssetCopy';
const source={root:'10000000-0000-4000-8000-000000000001',file:'10000000-0000-4000-8000-000000000002',path:'images/cat.png',mime:'image/png'};
const attachment='20000000-0000-4000-8000-000000000001';
describe('project image copy admission and stable retry',()=>{
 it('a synchronous invalidation cannot let the old finally unlock a new same-task flight',async()=>{
  const epoch=ref(1),insert=vi.fn();let finish!:(x:any)=>void;
  const copy=vi.fn().mockImplementationOnce(()=>new Promise(()=>{})).mockImplementationOnce(()=>new Promise(r=>finish=r));
  const task=assets.createProjectAssetCopy({copy,target:()=> 'target',capture:()=>{const captured=epoch.value;return()=>epoch.value===captured;},insert});
  const old=task.start(source);epoch.value++;expect(task.busy.value).toBe(false);
  const fresh=task.retry();await old;
  expect(task.busy.value).toBe(true);expect(task.pending.value).toBe(true);expect(copy).toHaveBeenCalledTimes(2);
  expect(copy.mock.calls[0]![3]).toBe(copy.mock.calls[1]![3]);expect(copy.mock.calls[0]![4].aborted).toBe(true);
  expect(copy.mock.calls[1]![4].aborted).toBe(false);expect(insert).not.toHaveBeenCalled();
  finish({url:'/attachments/'+attachment,filename:'cat.png'});await fresh;
  expect(insert).toHaveBeenCalledTimes(1);expect(task.busy.value).toBe(false);expect(task.pending.value).toBe(false);
 });
 it.each(['discard','dispose'] as const)('%s aborts a hanging flight and cleans its deadline without waiting for the transport',async action=>{
  vi.useFakeTimers();
  try{
   const insert=vi.fn(),copy=vi.fn(()=>new Promise<any>(()=>{}));
   const task=assets.createProjectAssetCopy({copy,target:()=> 'target',capture:()=>()=>true,insert});
   const pending=task.start(source);expect(vi.getTimerCount()).toBe(1);task[action]();await pending;
   expect(vi.getTimerCount()).toBe(0);expect(task.busy.value).toBe(false);expect(task.pending.value).toBe(false);expect(insert).not.toHaveBeenCalled();
  }finally{vi.useRealTimers();}
 });
 it('keeps the same request id after unknown commit, inserts only independent URL once',async()=>{
  const copy=vi.fn().mockRejectedValueOnce(Error('response lost')).mockResolvedValue({url:'/attachments/'+attachment,filename:'cat.png'});
  const insert=vi.fn();const task=assets.createProjectAssetCopy({copy,target:()=> 'target',capture:()=>()=>true,insert});
  await task.start(source);expect(insert).not.toHaveBeenCalled();expect(task.pending.value).toBe(true);
  await task.retry();expect(copy.mock.calls[0]).toEqual(copy.mock.calls[1]);expect(insert).toHaveBeenCalledExactlyOnceWith('![cat.png](/attachments/'+attachment+')');
  expect(task.pending.value).toBe(false);await task.retry();expect(insert).toHaveBeenCalledTimes(1);
 });
 it('fences an old response, but explicit same-target retry reconciles via the same id',async()=>{
  let resolve!:(x:any)=>void,epoch=1;const insert=vi.fn();const copy=vi.fn().mockImplementationOnce(()=>new Promise(r=>resolve=r)).mockResolvedValue({url:'/attachments/'+attachment,filename:'cat.png'});
  const task=assets.createProjectAssetCopy({copy,target:()=> 'target',capture:()=>{const v=epoch;return()=>v===epoch;},insert});
  const flight=task.start(source);epoch++;resolve({url:'/attachments/'+attachment,filename:'cat.png'});await flight;expect(insert).not.toHaveBeenCalled();
  await task.retry();expect(copy.mock.calls[0]).toEqual(copy.mock.calls[1]);expect(insert).toHaveBeenCalledTimes(1);
 });
 it('never inserts a private project URL and serializes duplicate drops',async()=>{
  let resolve!:(x:any)=>void;const insert=vi.fn(),copy=vi.fn(()=>new Promise<any>(r=>resolve=r));
  const task=assets.createProjectAssetCopy({copy,target:()=> 'target',capture:()=>()=>true,insert});
  const first=task.start(source);await task.start(source);expect(copy).toHaveBeenCalledTimes(1);
  resolve({url:'/p/private/cat.png',filename:'cat.png'});await first;expect(insert).not.toHaveBeenCalled();expect(task.error.value).toContain('附件');
  task.discard();expect(task.pending.value).toBe(false);
 });
 it('rejects malformed MIME data and refuses non-image payloads',()=>{
  expect(assets.parseProjectAsset('{bad')).toBeNull();expect(assets.parseProjectAsset(JSON.stringify({...source,mime:'text/html'}))).toBeNull();
  expect(assets.parseProjectAsset(JSON.stringify(source))).toEqual(source);
 });
});
