import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createApp, nextTick, h } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import Overview from './OverviewView.vue';
import * as api from '../../api/servers';
import { overviewInterfaces, overviewDefaultInterface } from './interfaceSelection';
const charts = vi.hoisted(() => ({ init: vi.fn(), setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }));
vi.mock('./chartRuntime', () => ({ init: charts.init, getInstanceByDom: () => undefined }));
vi.mock('./ServerWorldMap.vue', () => ({ __esModule: true, default: { render: () => null } }));
vi.mock('../../shell/Dropdown.vue', () => ({ default: { props: ['modelValue','options'], emits:['update:modelValue'], render(this:any) { return h('select', { value: this.modelValue, onChange: (e:any) => this.$emit('update:modelValue', this.options.find((o:any) => String(o.value) === e.target.value)?.value) }, this.options.map((o:any) => h('option', {value:o.value}, o.label))); } } }));
vi.mock('../../api/servers', () => ({ listNodes: vi.fn(), getNodeDetail: vi.fn(), getNodeMetrics: vi.fn(), listMonitors: vi.fn(async()=>[]), getMonitorSeries: vi.fn(async()=>[]), createMonitor: vi.fn(), removeMonitor: vi.fn() }));
let app: ReturnType<typeof createApp> | undefined, host: HTMLElement;
let width = 942;
let observers: { callback: ResizeObserverCallback; disconnect: ReturnType<typeof vi.fn> }[];
const node = (id:number) => ({ id, name:id===57?'5060':id===60?'NAS':'Stella', status:'online', platform:'Windows' });
const detail = (id=54, interfaces:any={eth0:{up:true,is_physical:true,is_default:true}}, extra:any={}) => ({...node(id), interfaces, latest_metrics:[], ...extra});
const points = (iface='eth0', delta=625000, age=0) => [{iface, ts:new Date(Date.now()-age).toISOString(), rx_delta:delta, tx_delta:1250}];
async function settle() { for(let i=0;i<40;i++) { await Promise.resolve(); await nextTick(); } }
async function mount() {
  host=document.createElement('div'); document.body.append(host);
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}}]}); await router.push('/'); await router.isReady();
  app=createApp(Overview); app.use(router); app.mount(host); await settle();
}
async function choose(selector:string,value:string) { const el=host.querySelector(selector) as HTMLSelectElement; el.value=value; el.dispatchEvent(new Event('change')); await settle(); }
beforeEach(()=>{
  vi.useFakeTimers(); vi.clearAllMocks(); width=942; observers=[];
  Object.defineProperty(document,'hidden',{configurable:true,value:false});
  vi.stubGlobal('ResizeObserver', class { entry:any; constructor(callback:ResizeObserverCallback) { this.entry={callback,disconnect:vi.fn()}; observers.push(this.entry); } observe() {} disconnect(){this.entry.disconnect();} });
  vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockImplementation(function(this:HTMLElement){ return {width:this.classList.contains('ov-chart')?width:100,height:200,x:0,y:0,top:0,left:0,right:width,bottom:200,toJSON(){}} as DOMRect; });
  charts.init.mockImplementation(()=>({setOption:charts.setOption,resize:charts.resize,dispose:charts.dispose}));
  vi.mocked(api.listNodes).mockResolvedValue([node(54)] as any);
  vi.mocked(api.getNodeDetail).mockImplementation(async id=>detail(id) as any);
  vi.mocked(api.getNodeMetrics).mockResolvedValue(points() as any);
});
afterEach(()=>{app?.unmount();app=undefined;host?.remove();vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers();});
test('never initializes a zero-width chart and ResizeObserver paints its pending real points after reveal',async()=>{
  width=0; await mount(); expect(api.getNodeMetrics).toHaveBeenCalled(); expect(charts.init).not.toHaveBeenCalled();
  width=942; for(const observer of observers) observer.callback([] as any,{} as any); await settle();
  expect(charts.init).toHaveBeenCalledTimes(1); expect(charts.resize).toHaveBeenCalled();
  expect(charts.setOption.mock.lastCall?.[0].series[0].data).toEqual([1000000]);
  app!.unmount();app=undefined;expect(observers[0].disconnect).toHaveBeenCalled();expect(charts.dispose).toHaveBeenCalled();
});
test('Windows up WLAN without a physical flag is selectable and queried once when its delayed details arrive',async()=>{
  vi.mocked(api.listNodes).mockResolvedValue([node(54),node(57)] as any);
  vi.mocked(api.getNodeDetail).mockImplementation(async id=>detail(id,id===57?{WLAN:{up:true,is_physical:false},lo:{up:true},'docker0':{up:true}}:undefined,{latest_metrics:points('WLAN')}) as any);
  await mount(); await choose('select.ov-drop','57');
  expect(host.querySelector('.iface-drop')?.textContent).toContain('WLAN');
  expect(api.getNodeMetrics).toHaveBeenLastCalledWith(57,expect.objectContaining({iface:'WLAN'}));
  expect(vi.mocked(api.getNodeMetrics).mock.calls.filter(([id])=>id===57)).toHaveLength(1);
});
test('query failure is visible, retains the old curve and retries explicitly',async()=>{
  await mount(); vi.mocked(api.getNodeMetrics).mockRejectedValue(new Error('offline'));
  await vi.advanceTimersByTimeAsync(3000);await settle();
  expect(host.textContent).toContain('流量加载失败');
  expect(charts.setOption.mock.lastCall?.[0].series[0].data).toEqual([1000000]);
  vi.mocked(api.getNodeMetrics).mockResolvedValue(points('eth0',0) as any);
  (host.querySelector('.traffic-retry') as HTMLElement).click();await settle();
  expect(host.textContent).not.toContain('流量加载失败');
  expect(charts.setOption.mock.lastCall?.[0].series[0].data).toEqual([0]);
});
test('initial metrics loading and confirmed empty response are distinct',async()=>{
  let resolve:any;vi.mocked(api.getNodeMetrics).mockReturnValue(new Promise(r=>resolve=r));
  await mount(); expect(host.textContent).toContain('流量加载中');expect(host.textContent).not.toContain('暂无流量数据');
  resolve([]);await settle();expect(host.textContent).toContain('暂无流量数据');
});
test('missing detail inventory is collecting, not a confirmed no-interface or empty query',async()=>{
  vi.mocked(api.getNodeDetail).mockResolvedValue(detail(54,null) as any);
  await mount();expect(host.textContent).toContain('等待网卡上报');expect(api.getNodeMetrics).not.toHaveBeenCalled();
});
test('confirmed inventory with only loopback has a no-interface hint',async()=>{
  vi.mocked(api.getNodeDetail).mockResolvedValue(detail(54,{lo:{up:true}}) as any);
  await mount();expect(host.textContent).toContain('暂无可用网卡');expect(api.getNodeMetrics).not.toHaveBeenCalled();
});
test('a stale successful sample has a stale hint but zero samples remain valid data',async()=>{
  vi.mocked(api.getNodeMetrics).mockResolvedValue(points('eth0',0,120000) as any);
  await mount();expect(host.textContent).toContain('流量采样已过期');expect(host.textContent).not.toContain('暂无流量数据');
  expect(charts.setOption.mock.lastCall?.[0].series[0].data).toEqual([0]);
});
test('detail failure is distinct and next status refresh restores selection and fetches',async()=>{
  vi.mocked(api.getNodeDetail).mockRejectedValueOnce(new Error('detail unavailable'));
  await mount();expect(host.textContent).toContain('节点详情加载失败');expect(api.getNodeMetrics).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(5000);await settle();expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
});
test('selection is available during slow detail loading with no false empty state',async()=>{
  let resolve:any;vi.mocked(api.getNodeDetail).mockReturnValue(new Promise(r=>resolve=r));
  await mount();expect((host.querySelector('select.ov-drop') as HTMLSelectElement).value).toBe('54');
  expect(host.textContent).toContain('节点详情加载中');expect(host.textContent).not.toContain('暂无可用网卡');
  resolve(detail());await settle();expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
});
test('window changes send one full request without an immediate duplicate live query',async()=>{
  await mount();vi.mocked(api.getNodeMetrics).mockClear();
  (host.querySelector('.win-btn') as HTMLElement).click();await settle();
  ([...host.querySelectorAll('.pop-item')].find(el=>el.textContent==='1小时') as HTMLElement).click();await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  expect(api.getNodeMetrics).toHaveBeenLastCalledWith(54,expect.objectContaining({limit:740}));
});
test('manual interface survives refresh and return to node but removed interface falls back',async()=>{
  let ifaces:any={eth0:{up:true,is_physical:true,is_default:true},wg0:{up:true}};
  vi.mocked(api.listNodes).mockResolvedValue([node(54),node(57)] as any);
  vi.mocked(api.getNodeDetail).mockImplementation(async id=>detail(id,ifaces) as any);
  await mount();await choose('.iface-drop','wg0');
  await vi.advanceTimersByTimeAsync(5000);await settle();expect((host.querySelector('.iface-drop') as HTMLSelectElement).value).toBe('wg0');
  await choose('select.ov-drop','57');await choose('select.ov-drop','54');expect((host.querySelector('.iface-drop') as HTMLSelectElement).value).toBe('wg0');
  ifaces={eth0:{up:true,is_default:true,is_physical:true}};await vi.advanceTimersByTimeAsync(5000);await settle();
  expect((host.querySelector('.iface-drop') as HTMLSelectElement).value).toBe('eth0');
});
test('pausing an initial in-flight query shows paused rather than indefinite loading and offers retry',async()=>{
  vi.mocked(api.getNodeMetrics).mockReturnValue(new Promise(()=>{}));
  await mount();(host.querySelector('.live-btn') as HTMLElement).click();await settle();
  expect(host.textContent).toContain('流量已暂停');expect(host.textContent).not.toContain('流量加载中');expect(host.querySelector('.traffic-retry')).not.toBeNull();
});
test('configured selection only uses live selectable inventory; physical/default and sampled WLAN fallbacks are deterministic',()=>{
  const d=detail(54,{lo:{up:true},docker0:{up:true},cni0:{up:true},veth1:{up:true},br0:{up:true},wg0:{up:true},eth0:{up:true,is_physical:true,is_default:true},WLAN:{up:true,is_physical:false},down:{up:false}}, {monitored_ifaces:{missing:{},down:{},WLAN:{}},latest_metrics:points('WLAN')}) as any;
  expect(overviewInterfaces(d)).toEqual(['wg0','eth0','WLAN']);
  expect(overviewDefaultInterface(d)).toBe('WLAN');d.monitored_ifaces={missing:{}};expect(overviewDefaultInterface(d)).toBe('eth0');
  delete d.interfaces.eth0;expect(overviewDefaultInterface(d)).toBe('WLAN');
  d.latest_metrics=[];expect(overviewDefaultInterface(d)).toBe('WLAN');
});
test('automatic default route changes requery once and late old-interface failure cannot override the curve',async()=>{
  let interfaces:any={eth0:{up:true,is_default:true},WLAN:{up:true}};
  vi.mocked(api.getNodeDetail).mockImplementation(async()=>detail(54,interfaces) as any);
  let reject:any;vi.mocked(api.getNodeMetrics).mockImplementation((_id,opts)=>opts?.iface==='eth0'?new Promise((_r,j)=>reject=j):Promise.resolve(points('WLAN',1250) as any));
  await mount();interfaces={eth0:{up:true},WLAN:{up:true,is_default:true}};
  await vi.advanceTimersByTimeAsync(5000);await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);expect(api.getNodeMetrics).toHaveBeenLastCalledWith(54,expect.objectContaining({iface:'WLAN'}));
  reject(new Error('old interface failed'));await settle();expect(host.textContent).not.toContain('流量加载失败');
  expect(charts.setOption.mock.lastCall?.[0].series[0].data).toEqual([2000]);
});
test('turning live off aborts its slow query without starting a replacement or late poller',async()=>{
  await mount();let resolve:any;
  vi.mocked(api.getNodeMetrics).mockReturnValue(new Promise(r=>resolve=r));
  await vi.advanceTimersByTimeAsync(3000);await settle();
  const before=vi.mocked(api.getNodeMetrics).mock.calls.length;
  const signal=vi.mocked(api.getNodeMetrics).mock.lastCall?.[1]?.signal;
  (host.querySelector('.live-btn') as HTMLElement).click();await settle();expect(signal?.aborted).toBe(true);
  resolve([]);await vi.advanceTimersByTimeAsync(15000);await settle();expect(api.getNodeMetrics).toHaveBeenCalledTimes(before);
});
test('late old-node response cannot replace current curve; hidden and unmount never restart polling',async()=>{
  vi.mocked(api.listNodes).mockResolvedValue([node(54),node(57)] as any);
  let resolve:any;let oldSignal:AbortSignal|undefined;
  vi.mocked(api.getNodeMetrics).mockImplementation((id,opts)=>id===54 ? (oldSignal=opts?.signal,new Promise(r=>resolve=r)) : Promise.resolve(points('eth0',1250) as any));
  await mount();await choose('select.ov-drop','57');expect(oldSignal?.aborted).toBe(true);
  resolve(points('eth0',999999));await settle();expect(charts.setOption.mock.lastCall?.[0].series[0].data).toEqual([2000]);
  const before=vi.mocked(api.getNodeMetrics).mock.calls.length;
  Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));await settle();
  await vi.advanceTimersByTimeAsync(15000);await settle();expect(api.getNodeMetrics).toHaveBeenCalledTimes(before);
  app!.unmount();app=undefined;Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));
  await vi.advanceTimersByTimeAsync(15000);await settle();expect(api.getNodeMetrics).toHaveBeenCalledTimes(before);
});
