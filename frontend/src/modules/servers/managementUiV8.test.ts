import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createApp,h,nextTick,ref} from 'vue';
vi.mock('../home/auth',async()=>{const {reactive}=await import('vue');return {auth:reactive({me:{id:'owner'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false})};});
vi.mock('../../api/servers',()=>({listMonitors:vi.fn(),listMonitorGroups:vi.fn(),updateMonitor:vi.fn(),saveMonitorGroup:vi.fn(),listMonitorChecks:vi.fn()}));
import {auth} from '../home/auth';
import * as api from '../../api/servers';
import Management from './MonitorManagement.vue';
let app:ReturnType<typeof createApp>|undefined,host:HTMLElement;const open=ref(true);
const item={id:1,name:'独立监控',node_id:1,type:'ping',target:'owned.test',status:'up',visible:true,enabled:true} as any;
const deferred=()=>{let resolve!:(v:any)=>void;const promise=new Promise<any>(r=>resolve=r);return {promise,resolve};};
async function settle(){for(let i=0;i<15;i++)await nextTick();}
function button(text:string){return [...host.querySelectorAll('button')].find(b=>b.textContent===text)!;}
async function mount(){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(Management,{open:open.value,onClose:()=>open.value=false})});app.mount(host);await settle();button('独立监控 1').click();await settle();}
beforeEach(()=>{vi.resetAllMocks();Object.assign(auth,{me:{id:'owner'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false});open.value=true;vi.mocked(api.listMonitors).mockResolvedValue([item]);vi.mocked(api.listMonitorGroups).mockResolvedValue([]);vi.mocked(api.listMonitorChecks).mockResolvedValue([]);Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(this:HTMLDialogElement){this.open=true;}});Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:function(this:HTMLDialogElement){this.open=false;}});});
afterEach(()=>{app?.unmount();host?.remove();vi.restoreAllMocks();});
it('uses native modal and unified result Dropdown, suspends for login and clears cross-account drafts',async()=>{
 await mount();expect(host.querySelector('dialog')?.open).toBe(true);
 host.querySelector<HTMLButtonElement>('[aria-haspopup=menu]')!.click();await settle();button('查看历史').click();await settle();expect(host.querySelector('select')).toBeNull();expect(host.querySelector('[aria-haspopup="listbox"]')).toBeTruthy();
 const search=host.querySelector('input')!;search.value='private owner search';search.dispatchEvent(new Event('input',{bubbles:true}));
 auth.suspended=true;await settle();expect(host.querySelector('dialog')?.open??false).toBe(false);
 auth.me={id:'other'} as any;auth.suspended=false;auth.sessionGeneration++;await settle();expect(host.querySelector('input')?.value??'').toBe('');expect(host.querySelector('.history')).toBeNull();
});
it('ignores old history across close/reopen and aborts list reads',async()=>{
 await mount();const old=deferred();vi.mocked(api.listMonitorChecks).mockReturnValueOnce(old.promise);host.querySelector<HTMLButtonElement>('[aria-haspopup=menu]')!.click();await settle();button('查看历史').click();await settle();
 const late=deferred();vi.mocked(api.listMonitors).mockReturnValueOnce(late.promise);button('重新读取').click();await settle();const signal=vi.mocked(api.listMonitors).mock.calls.at(-1)?.[0];
 open.value=false;await settle();expect(signal?.aborted).toBe(true);open.value=true;await settle();old.resolve([{id:1,success:false,ts:'2026-01-01',latency_ms:999}]);late.resolve([{...item,name:'STALE'}]);await settle();expect(host.textContent).not.toContain('STALE');expect(host.textContent).not.toContain('999 ms');expect(host.querySelector('.history')).toBeNull();
});
it('retains ACK/readback pending over close/reopen and confirms without replaying mutation',async()=>{
 await mount();vi.mocked(api.updateMonitor).mockResolvedValue({...item,visible:false});vi.mocked(api.listMonitors).mockRejectedValueOnce(new Error('readback failed'));host.querySelector<HTMLButtonElement>('[role=switch][aria-label="总览显示 独立监控"]')!.click();await settle();expect(host.textContent).toContain('操作尚未确认');
 open.value=false;await settle();open.value=true;vi.mocked(api.listMonitors).mockResolvedValue([{...item,visible:false}]);await settle();expect(api.updateMonitor).toHaveBeenCalledTimes(1);expect(host.querySelector<HTMLButtonElement>('[role=switch]')?.disabled).toBe(false);
});
