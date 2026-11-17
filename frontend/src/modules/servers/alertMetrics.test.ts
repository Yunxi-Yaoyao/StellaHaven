import { describe,it,expect,vi,afterEach } from 'vitest';
import { createApp,nextTick } from 'vue';
const mocks=vi.hoisted(()=>({api:vi.fn()}));
vi.mock('../../api/client',()=>({api:mocks.api}));
import { toBase,fromBase } from './alertMetricUnits';
import Panel from './MetricAlertsPanel.vue';
import publicRules from '../../../tests/fixtures/publicAlertProjection.json';
import {resolveLocal,localTime} from './alertMetricTime';
describe('IANA wall time to absolute instant',()=>{
 it('converts Shanghai and fractional seconds without the machine zone',()=>{
  expect(resolveLocal('2026-10-01T08:00:12.345','Asia/Shanghai')).toBe('2026-10-01T00:00:12.345Z');
  expect(localTime('2026-10-01T00:00:00Z','Asia/Kathmandu')).toBe('2026-10-01T05:45:00');
 });
 it('rejects DST gaps and requires an explicit fold instant',()=>{
  expect(()=>resolveLocal('2026-03-08T02:30','America/New_York')).toThrow(/不存在/);
  expect(()=>resolveLocal('2026-11-01T01:30','America/New_York')).toThrow(/重复/);
  expect(resolveLocal('2026-11-01T01:30','America/New_York',undefined,'2026-11-01T06:30:00.000Z')).toBe('2026-11-01T06:30:00.000Z');
  expect(()=>resolveLocal('2026-11-01T01:30','America/New_York',undefined,'2026-11-01T07:30:00.000Z')).toThrow(/重复/);
 });
 it('handles a half-hour fold and a skipped calendar day',()=>{
  expect(()=>resolveLocal('2026-04-05T01:45','Australia/Lord_Howe')).toThrow(/重复/);
  expect(()=>resolveLocal('2011-12-30T12:00','Pacific/Apia')).toThrow(/不存在/);
 });
 it('rejects invalid dates and unknown zones',()=>{
  expect(()=>resolveLocal('2026-02-30T12:00','UTC')).toThrow();
  expect(()=>resolveLocal('2026-01-01T12:00','Mars/Nowhere')).toThrow();
 });
});
let app:ReturnType<typeof createApp>|undefined;
async function flush(){for(let i=0;i<8;i++){await Promise.resolve();await nextTick();}}
async function mountRules(rules:unknown[]=[]){
 mocks.api.mockResolvedValue(rules);
 const host=document.createElement('div');document.body.append(host);
 app=createApp(Panel,{nodes:[{id:1,name:'节点',interfaces:{eth0:{}}}]});app.mount(host);await flush();return host;
}
function button(host:HTMLElement,text:string){return [...host.querySelectorAll('button')].find(b=>b.textContent===text)!;}
async function input(el:HTMLInputElement|HTMLSelectElement,value:string){el.value=value;el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));await flush();}
it('renders real PG public null projection without hiding healthy rules or enabling invalid edits',async()=>{
 const host=await mountRules(publicRules);
 const articles=[...host.querySelectorAll('article')];expect(articles).toHaveLength(3);
 const bad=articles.find(a=>a.textContent?.includes('invalid retained')) as HTMLElement;
 expect(bad.textContent).toContain('规则数据无效');expect(bad.textContent).toContain('仍启用');
 expect(bad.textContent).toContain('告警未确认恢复');expect(button(bad,'编辑').disabled).toBe(true);
 expect(button(bad,'删除').disabled).toBe(false);
 const good=articles.find(a=>a.textContent?.includes('healthy firing')) as HTMLElement;
 expect(good.textContent).toContain('85 %');expect(button(good,'编辑').disabled).toBe(false);
 button(good,'编辑').click();await flush();expect(host.querySelector('form')).not.toBeNull();
 expect(mocks.api).toHaveBeenCalledTimes(1);
});
function fixedRule(){return {id:7,revision:2,node_id:1,label:'月流量',condition:{metric:'network.volume',interface:'eth0',direction:'out',threshold:'9007199254740993',window:{kind:'fixed',start:'2026-10-01T00:00:00.123456Z',end:'2026-10-31T00:00:00.654321Z',timezone:'Asia/Shanghai'}},severity:'warning',debounce:2,repeat_minutes:0,email:false,enabled:false,state:'ok',preview:null,evaluated_at:null};}
it('edits UTC endpoints in the display zone with native controls and preserves untouched precision on save/readback',async()=>{
 const rule=fixedRule();const host=await mountRules([rule]);button(host,'编辑').click();await flush();
 const dates=host.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]');
 expect(dates).toHaveLength(2);expect(dates[0]!.value).toBe('2026-10-01T08:00:00.123');
 expect(host.textContent).toContain('Asia/Shanghai');expect(host.textContent).toContain('2026-10-01T00:00:00.123456Z');
 mocks.api.mockImplementation((_path:string,opts?:{method:string;body:string})=>opts?.method==='PUT'?Promise.resolve({id:7,revision:3}):Promise.resolve([{...rule,revision:3}]));
 host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await flush();
 const call=mocks.api.mock.calls.find(c=>c[1]?.method==='PUT')!;expect(JSON.parse(call[1].body).condition.window).toEqual(rule.condition.window);
 button(host,'编辑').click();await flush();expect(host.querySelector<HTMLInputElement>('input[type="datetime-local"]')!.value).toBe('2026-10-01T08:00:00.123');
});
it('changes display zones without moving instants; edits produce UTC payload and preserve bytes',async()=>{
 const rule=fixedRule();const host=await mountRules([rule]);button(host,'编辑').click();await flush();
 const zone=host.querySelector<HTMLSelectElement>('[data-zone]');expect(zone).toBeTruthy();
 await input(zone!,'America/New_York');
 const dates=host.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]');
 expect(dates[0]!.value).toBe('2026-09-30T20:00:00.123');
 await input(dates[0]!,'2026-10-02T10:11:12.345');
 mocks.api.mockRejectedValue(new Error('保存失败'));
 host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await flush();
 const data=JSON.parse(mocks.api.mock.calls.find(c=>c[1]?.method==='PUT')![1].body);
 expect(data.condition.window).toEqual({kind:'fixed',start:'2026-10-02T14:11:12.345Z',end:rule.condition.window.end,timezone:'America/New_York'});
 expect(data.condition.threshold).toBe('9007199254740993');expect(host.textContent).toContain('草稿已保留');
 expect(dates[0]!.value).toBe('2026-10-02T10:11:12.345');
});
it('blocks gaps, folds until explicit choice, and ranges exceeding 31 absolute days',async()=>{
 const rule=fixedRule();const host=await mountRules([rule]);button(host,'编辑').click();await flush();
 const zone=host.querySelector<HTMLSelectElement>('[data-zone]');expect(zone).toBeTruthy();await input(zone!,'America/New_York');
 const dates=host.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]');
 await input(dates[0]!,'2026-03-08T02:30');expect(host.textContent).toContain('不存在');
 expect(button(host,'保存规则').disabled).toBe(true);
 await input(dates[1]!,'2026-11-02T01:30');await input(dates[0]!,'2026-11-01T01:30');
 expect(host.textContent).toContain('重复');expect(button(host,'保存规则').disabled).toBe(true);
 await input(host.querySelector<HTMLSelectElement>('[data-fold="start"]')!,'2026-11-01T06:30:00.000Z');
 expect(button(host,'保存规则').disabled).toBe(false);expect(host.textContent).toContain('2026-11-01T06:30:00.000Z');
 await input(dates[1]!,'2026-12-03T01:30');expect(host.textContent).toContain('不超过31天');expect(button(host,'保存规则').disabled).toBe(true);
});
const now='2026-10-16T00:00:00Z';
function observedRule(metric='network.rate',age=0,evaluationAge=0){const r=fixedRule();return {...r,enabled:true,condition:{metric,threshold:'100',interface:'eth0',direction:'out'},preview:{value:'12',lower:null,upper:null,quality:'valid',reason:'',unit:'bit/s',watermark:new Date(Date.parse(now)-age*1000).toISOString(),bad:false},evaluated_at:new Date(Date.parse(now)-evaluationAge*1000).toISOString()};}
it('ages a valid network observation without polling and retains it only as previous evidence',async()=>{
 vi.useFakeTimers();vi.setSystemTime(now);const host=await mountRules([observedRule()]);
 expect(host.textContent).toContain('当前未超限');await vi.advanceTimersByTimeAsync(46000);await flush();
 expect(host.textContent).not.toContain('当前未超限');expect(host.textContent).toContain('数据已过期');expect(host.textContent).toContain('上次观测');expect(host.textContent).toContain('12 bit/s');
 expect(mocks.api).toHaveBeenCalledTimes(1);app!.unmount();app=undefined;expect(vi.getTimerCount()).toBe(0);
});
it.each([
 ['cpu',179,0,'当前未超限'],['cpu',181,0,'数据已过期'],['network.utilization',46,0,'数据已过期'],
 ['network.rate',0,46,'数据已过期'],['network.rate',-6,0,'时钟异常'],['network.rate',0,-6,'时钟异常'],
])('uses metric-specific sample and evaluation ages: %s %s %s',async(metric,age,evaluationAge,text)=>{
 vi.useFakeTimers();vi.setSystemTime(now);const host=await mountRules([observedRule(metric,age,evaluationAge)]);expect(host.textContent).toContain(text);
});
it('separates disabled, scheduled, ended, missing history and unresolved firing',async()=>{
 vi.useFakeTimers();vi.setSystemTime(now);
 const base=fixedRule();const rule=observedRule('network.rate',100);
 const host=await mountRules([
  {...base,id:1,label:'停用'},
  {...base,id:2,enabled:true,condition:{...base.condition,window:{...base.condition.window,start:'2026-10-17T00:00:00Z'}}},
  {...base,id:3,enabled:true,condition:{...base.condition,window:{...base.condition.window,end:now}}},
  {...rule,id:4,state:'firing'},
  {...rule,id:5,preview:{...rule.preview,value:null,watermark:null,quality:'unknown',reason:'history_missing'}},
  {...rule,id:6,preview:{...rule.preview,watermark:null},evaluated_at:null},
 ]);
 expect(host.textContent).toContain('已停用');expect(host.textContent).toContain('等待开始日期');expect(host.textContent).toContain('已结束');
 expect(host.textContent).toContain('告警未确认恢复');expect(host.textContent).toContain('所选范围没有可用历史');expect(host.textContent).toContain('等待新有效样本');expect(host.textContent).not.toContain('当前未超限');
});
it('ages a read-only preview and keeps unknown history distinct from zero',async()=>{
 vi.useFakeTimers();vi.setSystemTime(now);const host=await mountRules([observedRule()]);button(host,'编辑').click();await flush();
 mocks.api.mockResolvedValue(observedRule().preview);button(host,'只读预览').click();await flush();
 await vi.advanceTimersByTimeAsync(46000);await flush();
 expect(host.querySelector('.preview')!.textContent).toContain('数据已过期');expect(host.querySelector('.preview')!.textContent).toContain('上次观测');
 mocks.api.mockResolvedValue({...observedRule().preview,value:null,watermark:null,quality:'unknown',reason:'history_missing'});button(host,'只读预览').click();await flush();
 expect(host.querySelector('.preview')!.textContent).toContain('所选范围没有可用历史');expect(host.querySelector('.preview')!.textContent).not.toContain('0 bit/s');
});
it('traps Tab, ignores composing Escape, restores focus and resumes a cancelled draft',async()=>{
 const host=await mountRules([fixedRule()]);const edit=button(host,'编辑');edit.focus();edit.click();await flush();
 const form=host.querySelector('form')!;expect(form.contains(document.activeElement)).toBe(true);
 const save=button(host,'保存规则');save.focus();save.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));
 expect(document.activeElement).toBe(form.querySelector('select:not(:disabled)'));
 document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));expect(document.activeElement).toBe(save);
 const date=host.querySelector<HTMLInputElement>('input[type="datetime-local"]')!;await input(date,'2026-10-03T09:12:13');
 date.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true}));await flush();expect(host.querySelector('form')).toBeTruthy();
 date.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await flush();expect(host.querySelector('form')).toBeNull();expect(document.activeElement).toBe(edit);
 edit.click();await flush();expect(host.querySelector<HTMLInputElement>('input[type="datetime-local"]')!.value).toBe('2026-10-03T09:12:13.000');
});
it('fences late preview errors on cancellation and restores independent drafts',async()=>{
 const host=await mountRules([fixedRule()]);button(host,'编辑').click();await flush();
 let reject!:(value:unknown)=>void;mocks.api.mockImplementation(()=>new Promise((_,r)=>reject=r));
 button(host,'只读预览').click();await flush();button(host,'取消').click();await flush();
 reject(new Error('迟到的错误'));await flush();expect(host.textContent).not.toContain('迟到的错误');
 button(host,'添加指标规则').click();await flush();
 expect(host.querySelector<HTMLInputElement>('input[inputmode="decimal"]')!.value).toBe('80');
 expect(host.querySelector<HTMLSelectElement>('select')!.value).toBe('0');
});
it('shows UTC for offset endpoints and preserves sub-millisecond window durations',async()=>{
 const rule=fixedRule();rule.condition.window.start='2026-10-01T08:00:00.123456+08:00';rule.condition.window.end='2026-10-01T08:00:00.123457+08:00';
 const host=await mountRules([rule]);button(host,'编辑').click();await flush();
 expect(button(host,'保存规则').disabled).toBe(false);expect(host.textContent).toContain('2026-10-01T00:00:00.123456Z');expect(host.textContent).toContain('实际 UTC 时段');
});
it('does not reset original precision on a native no-op input event',async()=>{
 const rule=fixedRule();const host=await mountRules([rule]);button(host,'编辑').click();await flush();
 const date=host.querySelector<HTMLInputElement>('input[type="datetime-local"]')!;await input(date,date.value);
 mocks.api.mockRejectedValue(new Error('save probe'));host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await flush();
 expect(JSON.parse(mocks.api.mock.calls.find(c=>c[1]?.method==='PUT')![1].body).condition.window.start).toBe(rule.condition.window.start);
});
it('uses a conservative fixed-volume freshness budget and distinguishes threshold crossing from OK',async()=>{
 vi.useFakeTimers();vi.setSystemTime(now);const base=fixedRule();const r=observedRule('network.volume',121,0);
 const host=await mountRules([{...r,condition:base.condition},{...observedRule(),id:8,preview:{...observedRule().preview,bad:true}}]);
 expect(host.querySelector('article')!.textContent).toContain('数据已过期');expect(host.textContent).toContain('最新观测已达阈值');expect(host.textContent).not.toContain('当前未超限');
});
it('defaults new windows to the browser zone and never supplies line capacity',async()=>{
 const host=await mountRules();button(host,'添加指标规则').click();await flush();
 await input(host.querySelectorAll('select')[1]!,'network.volume');expect(host.querySelector<HTMLSelectElement>('[data-zone]')!.value).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
 expect([...host.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]')].map(e=>e.value)).toEqual(['','']);
 await input(host.querySelectorAll('select')[1]!,'network.utilization');
 expect([...host.querySelectorAll<HTMLInputElement>('fieldset input')].map(e=>e.value)).toEqual(['','']);
});
it('previews and saves a newly configured local window as explicit UTC instants',async()=>{
 const host=await mountRules();button(host,'添加指标规则').click();await flush();
 await input(host.querySelectorAll('select')[0]!,'1');await input(host.querySelectorAll('select')[1]!,'network.volume');await input(host.querySelectorAll('select')[3]!,'eth0');await input(host.querySelector<HTMLSelectElement>('[data-zone]')!,'Asia/Shanghai');
 const dates=host.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]');await input(dates[0]!,'2026-10-01T00:00:01');await input(dates[1]!,'2026-10-31T23:59:59');
 mocks.api.mockRejectedValue(new Error('probe'));button(host,'只读预览').click();await flush();
 const payload=JSON.parse(mocks.api.mock.calls.find(c=>c[0].endsWith('/preview'))![1].body);
 expect(payload.condition.window).toEqual({kind:'fixed',start:'2026-09-30T16:00:01.000Z',end:'2026-10-31T15:59:59.000Z',timezone:'Asia/Shanghai'});
 host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await flush();
 expect(JSON.parse(mocks.api.mock.calls.find(c=>c[0].endsWith('/rules')&&c[1]?.method==='POST')![1].body).condition).toEqual(payload.condition);
});
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';vi.resetAllMocks();vi.useRealTimers();});
describe('exact alert units',()=>{
 it('keeps large byte thresholds exact through GB/GiB display',()=>{
  expect(toBase('1','GB')).toBe('1000000000');expect(toBase('1','GiB')).toBe('1073741824');
  const value='9007199254740993';expect(toBase(fromBase(value,'GiB'),'GiB')).toBe(value);
  expect(toBase('80','Mbps')).toBe('80000000');
 });
 it('rejects fractional bytes',()=>{expect(()=>toBase('0.1','byte')).toThrow();});
});
it('has compact labelled metric controls and explains unknown without zero',async()=>{
 mocks.api.mockResolvedValue([]);
 const host=document.createElement('div');document.body.append(host);
 app=createApp(Panel,{nodes:[{id:1,name:'合成节点',interfaces:{eth0:{}}}]});app.mount(host);
 await nextTick();await Promise.resolve();
 (host.querySelector('[data-add-metric]') as HTMLButtonElement).click();await nextTick();
 expect(host.textContent).toContain('单一计量接口');
 expect(host.textContent).toContain('不代表运营商账单');
 expect(host.querySelector('label')).toBeTruthy();
 expect(host.textContent).toContain('预览');
});

it('discards a late preview after direction changes and keeps field errors readable',async()=>{
 let resolve!:(value:unknown)=>void;
 mocks.api.mockImplementation((path:string)=>path.endsWith('/preview')?new Promise(r=>resolve=r):Promise.resolve([]));
 const host=document.createElement('div');document.body.append(host);app=createApp(Panel,{nodes:[{id:1,name:'节点',interfaces:{eth0:{}}}]});app.mount(host);
 await nextTick();(host.querySelector('[data-add-metric]') as HTMLButtonElement).click();await nextTick();
 const selects=host.querySelectorAll('select');
 async function select(el:HTMLSelectElement,value:string){el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));await nextTick();}
 await select(selects[0]!, '1');await select(selects[3]!, 'eth0');
 const button=[...host.querySelectorAll('button')].find(b=>b.textContent==='只读预览')!;button.click();await nextTick();
 await select(selects[2]!, 'in');resolve({value:'999999',unit:'bit/s',quality:'valid'});await Promise.resolve();await nextTick();
 expect(host.textContent).not.toContain('999999');
 mocks.api.mockRejectedValue({detail:[{loc:['body','condition','threshold'],msg:'阈值必须为有限非负数'}]});
 button.click();await Promise.resolve();await nextTick();
 expect(host.textContent).toContain('阈值必须为有限非负数');
});
