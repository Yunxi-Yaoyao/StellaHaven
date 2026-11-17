import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createApp, nextTick, h } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import Tools from './ToolsView.vue';
import Records from './RecordsView.vue';
import MonitorDetail from './MonitorDetailModal.vue';
import * as chart from './chartRuntime';
import * as api from '../../api/servers';
vi.mock('./chartRuntime', () => ({ init: vi.fn(), getInstanceByDom: () => undefined }));
vi.mock('./NodeComponents.vue', () => ({ default: { render: () => null } }));
vi.mock('../../shell/Dropdown.vue', () => ({ default: { props: ['modelValue','options'], emits: ['update:modelValue'], render(this:any) { return h('select', { value: this.modelValue, onChange: (e:any) => this.$emit('update:modelValue', this.options.find((o:any) => String(o.value) === e.target.value)?.value) }, this.options.map((o:any) => h('option', {value:o.value}, o.label))); } } }));
vi.mock('../../api/servers', async importOriginal => ({ ...(await importOriginal<any>()), listNodes: vi.fn(), listIperfTasks: vi.fn(async()=>[]), listCommands: vi.fn(async()=>[]), listMtrTasks: vi.fn(async()=>[]), createMtrTask: vi.fn(), createMtrJob: vi.fn(), getMtrTask: vi.fn() }));
let app: ReturnType<typeof createApp> | undefined, host: HTMLElement;
const row = (id=11,status='pending',node_id=1) => ({ id, node_id, target:'example.com', protocol:'icmp', trigger:'manual', status, created_at:new Date().toISOString(), params_json:{count:10}, result_json:status==='done'?{hubs:[{host:'192.0.2.1',loss:0,avg:3.2}]}:null });
async function settle() { for(let i=0;i<35;i++) {await Promise.resolve();await nextTick();} }
async function mount(component:any=Tools) {
  host=document.createElement('div');document.body.append(host);
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}}]}); await router.push('/');await router.isReady();
  app=createApp(component,component===Tools?{tool:'mtr'}:{});app.use(router);app.mount(host);await settle();
}
function start() { (Array.from(host.querySelectorAll('button')).find(b=>b.textContent?.includes('开始 MTR')) as HTMLButtonElement)?.click(); }
function hostInput() { return host.querySelector('input[placeholder="如 8.8.8.8 或 example.com"]') as HTMLInputElement; }
async function inputHost() {hostInput().value='example.com';hostInput().dispatchEvent(new Event('input'));await settle();}
beforeEach(()=>{vi.useFakeTimers();vi.clearAllMocks();Object.defineProperty(document,'hidden',{configurable:true,value:false});vi.mocked(api.listNodes).mockResolvedValue([{id:1,name:'fixture-1',status:'online'},{id:2,name:'fixture-2',status:'online'}] as any);vi.mocked(api.listMtrTasks).mockResolvedValue([]);vi.mocked(api.createMtrTask).mockResolvedValue(row() as any);vi.mocked(api.createMtrJob).mockResolvedValue([row()] as any);});
afterEach(()=>{app?.unmount();app=undefined;host?.remove();vi.useRealTimers();vi.restoreAllMocks();});
test('submission keeps target and completed result moves into expandable manual history',async()=>{
  await mount();await inputHost();start();await settle();
  expect(hostInput().value).toBe('example.com');
  vi.mocked(api.listMtrTasks).mockResolvedValue([row(11,'done')] as any);
  vi.mocked(api.getMtrTask).mockResolvedValue(row(11,'done') as any);
  await vi.advanceTimersByTimeAsync(5000);await settle();
  expect(host.querySelector('.task-row')?.textContent).toContain('完成');
  (host.querySelector('.task-row') as HTMLElement).click();await settle();
  expect(host.querySelector('.task-expand')?.textContent).toContain('192.0.2.1');
});
test('double-click admits only once and busy job cannot accept another run',async()=>{
  let release:any;vi.mocked(api.createMtrJob).mockReturnValue(new Promise(r=>release=r));
  await mount();await inputHost();start();start();await settle();
  expect(api.createMtrJob).toHaveBeenCalledTimes(1);
  release([row()]);await settle();start();await settle();expect(api.createMtrJob).toHaveBeenCalledTimes(1);
  expect(host.querySelector('[role="progressbar"]')?.hasAttribute('aria-valuenow')).toBe(false);
});
test('multi-node operation switches real results without admitting another task',async()=>{
  vi.mocked(api.createMtrJob).mockResolvedValue([row(11,'running',1),row(12,'pending',2)] as any);
  await mount();await inputHost();
  vi.mocked(api.listMtrTasks).mockResolvedValue([row(12,'pending',2),row(11,'running',1)] as any);
  const checkbox=host.querySelector('.mtr-nodes input[value="2"]') as HTMLInputElement;
  expect(checkbox).not.toBeNull();checkbox.checked=true;checkbox.dispatchEvent(new Event('change'));await settle();
  start();await settle();
  expect(api.createMtrJob).toHaveBeenCalledWith(expect.objectContaining({node_ids:[1,2],target:'example.com'}));
  expect(host.querySelector('.mtr-live')?.textContent).toContain('fixture-1');
  (host.querySelector('button[aria-label="下一个节点"]') as HTMLButtonElement).click();await settle();
  await vi.advanceTimersByTimeAsync(350);await settle();
  expect(host.querySelector('.mtr-live')?.textContent).toContain('fixture-2');expect(api.createMtrJob).toHaveBeenCalledTimes(1);
});
test('monitor chart never converts connection failure into packet loss',async()=>{
 const setOption=vi.fn();vi.mocked(chart.init).mockReturnValue({setOption,dispose:vi.fn(),resize:vi.fn()} as any);
 vi.spyOn(api,'getMonitorSeries').mockResolvedValue([
  {ts:'2026-10-19T00:00:00Z',success:false,latency_ms:null,loss_pct:null},
  {ts:'2026-10-19T00:01:00Z',success:true,latency_ms:1,loss_pct:0},
  {ts:'2026-10-19T00:02:00Z',success:false,latency_ms:null,loss_pct:25},
 ]);
 host=document.createElement('div');document.body.append(host);
 app=createApp(MonitorDetail,{monitor:{id:7,name:'own controlled endpoint',node_id:1,type:'tcp',target:'192.0.2.1:8081',interval:30,timeout:1,status:'down'},nodeName:'fixture'});app.mount(host);await settle();
 expect(setOption).toHaveBeenCalled();const options=setOption.mock.calls.at(-1)![0];
 expect(options.series.find((s:any)=>s.name==='丢包率').data).toEqual([null,0,25]);
 expect(host.querySelector('.stat-row')?.textContent).toContain('12.5%');
});

test('tools retain targets on status failure, expose retry and recover on success',async()=>{
 await mount();await inputHost();vi.mocked(api.listNodes).mockRejectedValueOnce(new Error('fixture offline'));
 await vi.advanceTimersByTimeAsync(5000);await settle();expect(host.textContent).toContain('节点与任务刷新失败');expect(hostInput().value).toBe('example.com');
 [...host.querySelectorAll('button')].find(b=>b.textContent?.trim()==='重试')!.click();await settle();expect(host.textContent).not.toContain('节点与任务刷新失败');expect(hostInput().value).toBe('example.com');
});
test('failed history refresh preserves old manual results and displays a local error',async()=>{
  vi.mocked(api.listMtrTasks).mockResolvedValue([row(11,'done')] as any);await mount(Records);
  expect(host.textContent).toContain('example.com');
  vi.mocked(api.listMtrTasks).mockRejectedValue(new Error('offline'));
  await vi.advanceTimersByTimeAsync(5000);await settle();
  expect(host.textContent).toContain('example.com');expect(host.textContent).toContain('记录刷新失败');
});
