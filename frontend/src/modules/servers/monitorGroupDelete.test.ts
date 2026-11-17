import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import Management from './MonitorManagement.vue';
import GroupDelete from './MonitorGroupDelete.vue';
import {reactive} from 'vue';
import * as api from '../../api/servers';
import {auth} from '../home/auth';
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'owner'},suspended:false,sessionClosing:false,requestEpoch:0,sessionGeneration:0})}));
vi.mock('../../api/servers',()=>({listMonitors:vi.fn(),listMonitorGroups:vi.fn(),getMonitorGroupDeletionState:vi.fn(),deleteMonitorGroup:vi.fn(),removeMonitor:vi.fn(),updateMonitor:vi.fn(),saveMonitorGroup:vi.fn(),dissolveMonitorGroup:vi.fn(),listMonitorChecks:vi.fn()}));
const member={id:7,name:'服务 A',node_id:1,type:'tcp' as const,target:'owned.example:443',interval:60,timeout:5,status:'up',visible:true,enabled:true};
const group={id:2,name:'业务组',child_ids:[7],failure_policy:'any',rotation_seconds:0,status:'up',down_count:0,unknown_count:0};
const uuid='11111111-1111-4111-8111-111111111111';
const preview={stable_uuid:uuid,identity_matches:null,group_exists:true,name:group.name,children:[member],protected:false,remaining_child_ids:[]};
const gone={stable_uuid:null,identity_matches:false,group_exists:false,name:null,children:[],protected:false,remaining_child_ids:[]};
let app:ReturnType<typeof createApp>,host:HTMLElement;const changed=vi.fn(),closed=vi.fn();
async function settle(){for(let i=0;i<40;i++)await Promise.resolve();await nextTick();}
async function click(text:string,root:ParentNode=host){const b=[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(b,text).toBeTruthy();b!.click();await settle();}
async function mount(){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(Management,{open:true,onChanged:changed,onClose:closed})});app.mount(host);await settle();}
const confirm=()=>host.querySelector<HTMLDialogElement>('[aria-label="确认删除监控组"]')!;
async function openDelete(){host.querySelector<HTMLButtonElement>('.group-row [aria-haspopup=menu]')!.click();await settle();await click('删除监控组');}
async function start(){await mount();await openDelete();}

beforeEach(()=>{vi.resetAllMocks();Object.assign(auth,{me:{id:'owner'},suspended:false,sessionClosing:false,requestEpoch:0,sessionGeneration:0});vi.mocked(api.listMonitors).mockResolvedValue([member] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([group] as any);vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue(preview as any);for(const [name,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,name,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});});
afterEach(()=>{app?.unmount();host?.remove();});
test('group-list directly confirms named whole-group scope, cancel writes nothing, delete is atomic API not dissolve',async()=>{
 await mount();await openDelete();expect(confirm().open).toBe(true);expect(confirm().textContent).toContain('业务组');expect(confirm().textContent).toContain('1 个监控项');expect(confirm().textContent).toContain('服务 A');expect(confirm().textContent).toContain('MTR');await click('取消',confirm());expect(api.deleteMonitorGroup).not.toHaveBeenCalled();expect(api.removeMonitor).not.toHaveBeenCalled();
 await openDelete();vi.mocked(api.deleteMonitorGroup).mockResolvedValue();vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue(gone);await click('确认删除整组',confirm());expect(api.deleteMonitorGroup).toHaveBeenCalledExactlyOnceWith(2,[7],uuid);expect(api.dissolveMonitorGroup).not.toHaveBeenCalled();expect(api.removeMonitor).not.toHaveBeenCalled();expect(changed).toHaveBeenCalledOnce();
});

test.each(['ack-read-failed','ack-lost'])('%s keeps pending task, cancel/Escape locked, GET-only retry verifies both group and members',async(mode)=>{
 await start();if(mode==='ack-lost')vi.mocked(api.deleteMonitorGroup).mockRejectedValue(new Error('ACK lost'));else{vi.mocked(api.deleteMonitorGroup).mockResolvedValue();vi.mocked(api.getMonitorGroupDeletionState).mockRejectedValueOnce(new Error('GET failed'));}
 await click('确认删除整组',confirm());expect(changed).not.toHaveBeenCalled();expect(confirm().textContent).toContain('删除尚未确认');expect([...confirm().querySelectorAll('button')].find(b=>b.textContent==='取消')!.disabled).toBe(true);confirm().dispatchEvent(new Event('cancel',{cancelable:true}));await settle();expect(confirm().open).toBe(true);
 vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue({...gone,remaining_child_ids:[7]});await click('重新读取确认',confirm());expect(changed).not.toHaveBeenCalled();expect(api.getMonitorGroupDeletionState).toHaveBeenLastCalledWith(2,[7],expect.any(AbortSignal),uuid);
 vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue(gone);await click('重新读取确认',confirm());expect(api.deleteMonitorGroup).toHaveBeenCalledOnce();expect(changed).toHaveBeenCalledOnce();
});
test('409 clears old scope and requires fresh displayed confirmation, not automatic replay',async()=>{
 await start();vi.mocked(api.deleteMonitorGroup).mockRejectedValue({status:409});await click('确认删除整组',confirm());expect(confirm().textContent).toContain('成员范围已变化');expect([...confirm().querySelectorAll('button')].some(b=>b.textContent==='确认删除整组')).toBe(false);
 const expanded={...preview,children:[member,{...member,id:8,name:'新增成员'}]};vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue(expanded as any);await click('重新读取范围',confirm());expect(confirm().textContent).toContain('新增成员');expect(confirm().textContent).toContain('2 个监控项');expect(api.deleteMonitorGroup).toHaveBeenCalledOnce();vi.mocked(api.deleteMonitorGroup).mockResolvedValue();vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue(gone);await click('确认删除整组',confirm());expect(api.deleteMonitorGroup).toHaveBeenLastCalledWith(2,[7,8],uuid);expect(changed).toHaveBeenCalledOnce();
});
test('empty group is directly deletable; management requests empty groups explicitly',async()=>{
 vi.mocked(api.listMonitorGroups).mockResolvedValue([{...group,child_ids:[]}] as any);vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue({...preview,children:[]});await start();expect(api.listMonitorGroups).toHaveBeenCalledWith(expect.any(AbortSignal),true);expect(confirm().textContent).toContain('0 个监控项');vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue(gone);await click('确认删除整组',confirm());expect(api.deleteMonitorGroup).toHaveBeenCalledExactlyOnceWith(2,[],uuid);expect(changed).toHaveBeenCalledOnce();
});
test('automatic group has no destructive button and protected preview blocks a manual-looking group',async()=>{
 vi.mocked(api.listMonitorGroups).mockResolvedValue([{...group,automatic:true}] as any);await mount();expect(host.querySelector('[aria-label="删除监控组 业务组"]')).toBeNull();app.unmount();host.remove();vi.mocked(api.listMonitorGroups).mockResolvedValue([group] as any);vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue({...preview,protected:true});await start();expect(confirm().textContent).toContain('不可手动删除');expect([...confirm().querySelectorAll('button')].some(b=>b.textContent==='确认删除整组')).toBe(false);expect(api.deleteMonitorGroup).not.toHaveBeenCalled();
});
test('same-owner session rotation fences old ACK but retains GET-only verification',async()=>{
 let finish!:()=>void;vi.mocked(api.deleteMonitorGroup).mockImplementation(()=>new Promise<void>(r=>{finish=r;}));await start();await click('确认删除整组',confirm());auth.suspended=true;await settle();expect(confirm().open).toBe(false);auth.suspended=false;auth.sessionGeneration++;await settle();expect(confirm().open).toBe(true);finish();await settle();expect(changed).not.toHaveBeenCalled();vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue(gone);await click('重新读取确认',confirm());expect(api.deleteMonitorGroup).toHaveBeenCalledOnce();expect(changed).toHaveBeenCalledOnce();
});
test('new owner fences late deletion completion and clears private confirmation',async()=>{
 let finish!:()=>void;vi.mocked(api.deleteMonitorGroup).mockImplementation(()=>new Promise<void>(r=>{finish=r;}));await start();await click('确认删除整组',confirm());auth.me={id:'another'} as any;await settle();const reads=vi.mocked(api.getMonitorGroupDeletionState).mock.calls.length;finish();await settle();expect(changed).not.toHaveBeenCalled();expect(confirm()).toBeNull();expect(api.getMonitorGroupDeletionState).toHaveBeenCalledTimes(reads);
});
test('unmount aborts preview and drops a late preview without mutation',async()=>{
 let finish!:(value:any)=>void;vi.mocked(api.getMonitorGroupDeletionState).mockImplementation(()=>new Promise(r=>{finish=r;}));await start();const signal=vi.mocked(api.getMonitorGroupDeletionState).mock.calls[0]![2]!;app.unmount();expect(signal.aborted).toBe(true);finish(preview);await settle();expect(api.deleteMonitorGroup).not.toHaveBeenCalled();expect(changed).not.toHaveBeenCalled();
});
test('cancel during preview aborts read with zero writes and restores exact group action',async()=>{
 let finish!:(value:any)=>void;vi.mocked(api.getMonitorGroupDeletionState).mockImplementation(()=>new Promise(r=>{finish=r;}));await start();const signal=vi.mocked(api.getMonitorGroupDeletionState).mock.calls[0]![2]!;await click('取消',confirm());expect(confirm()).toBeNull();expect(signal.aborted).toBe(true);expect(document.activeElement).toBe(host.querySelector('.group-row [aria-haspopup=menu]'));finish(preview);await settle();expect(api.deleteMonitorGroup).not.toHaveBeenCalled();expect(changed).not.toHaveBeenCalled();
});
test('unmount fences an already admitted deletion completion without new reads or success',async()=>{
 let finish!:()=>void;vi.mocked(api.deleteMonitorGroup).mockImplementation(()=>new Promise<void>(r=>{finish=r;}));await start();await click('确认删除整组',confirm());const reads=vi.mocked(api.getMonitorGroupDeletionState).mock.calls.length;app.unmount();finish();await settle();expect(changed).not.toHaveBeenCalled();expect(api.getMonitorGroupDeletionState).toHaveBeenCalledTimes(reads);expect(api.deleteMonitorGroup).toHaveBeenCalledOnce();
});

test.each([{remaining:[]},{remaining:[7]}])('replacement identity GET-only readback retains confirmed UUID; surviving children %j never imply whole-batch deleted',async ({remaining})=>{
 await start();vi.mocked(api.deleteMonitorGroup).mockRejectedValue(new Error('lost ACK'));await click('确认删除整组',confirm());
 vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue({...preview,stable_uuid:'22222222-2222-4222-8222-222222222222',identity_matches:false,remaining_child_ids:remaining} as any);
 await click('重新读取确认',confirm());expect(api.getMonitorGroupDeletionState).toHaveBeenLastCalledWith(2,[7],expect.any(AbortSignal),uuid);expect(api.deleteMonitorGroup).toHaveBeenCalledExactlyOnceWith(2,[7],uuid);
 if(remaining.length){expect(changed).not.toHaveBeenCalled();expect(confirm().textContent).toContain('原确认监控组已消失，但仍有 1 个确认成员存在');}else expect(changed).toHaveBeenCalledOnce();
});

test('pending scope freezes numeric ID and UUID across prop changes and same-owner reauthentication',async()=>{
 const props=reactive({groupId:2,open:true});host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(GroupDelete,{...props,onDeleted:changed})});app.mount(host);await settle();
 vi.mocked(api.deleteMonitorGroup).mockRejectedValue(new Error('lost'));await click('确认删除整组',confirm());
 props.groupId=999;auth.suspended=true;await settle();auth.suspended=false;auth.sessionGeneration++;await settle();
 vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue(gone);await click('重新读取确认',confirm());
 expect(api.deleteMonitorGroup).toHaveBeenCalledExactlyOnceWith(2,[7],uuid);expect(api.getMonitorGroupDeletionState).toHaveBeenLastCalledWith(2,[7],expect.any(AbortSignal),uuid);expect(changed).toHaveBeenCalledOnce();
});
test('cancel/reopen captures a fresh displayed UUID; late old preview cannot replace it',async()=>{
 let finish!:(value:any)=>void;vi.mocked(api.getMonitorGroupDeletionState).mockImplementationOnce(()=>new Promise(r=>{finish=r;}));await start();await click('取消',confirm());
 const nextUuid='33333333-3333-4333-8333-333333333333';vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue({...preview,stable_uuid:nextUuid});await openDelete();
 finish(preview);await settle();vi.mocked(api.deleteMonitorGroup).mockRejectedValue(new Error('lost'));await click('确认删除整组',confirm());expect(api.deleteMonitorGroup).toHaveBeenCalledExactlyOnceWith(2,[7],nextUuid);
});
test('missing preview identity fails closed, never silently defaults to a UUID',async()=>{
 vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue({...preview,stable_uuid:null});await start();expect(confirm().textContent).toContain('读取删除范围失败');expect(confirm().textContent).not.toContain('确认删除整组');expect(api.deleteMonitorGroup).not.toHaveBeenCalled();
});
