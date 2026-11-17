import {it,expect,vi,beforeEach,afterEach} from 'vitest';
import {createApp,nextTick} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
const mocks=vi.hoisted(()=>({api:vi.fn()}));
vi.mock('../../api/client',()=>({api:mocks.api}));
vi.mock('./chartRuntime',()=>({init:()=>({setOption:vi.fn(),resize:vi.fn(),dispose:vi.fn()}),getInstanceByDom:()=>null}));
import Tools from './ToolsView.vue';
let app:ReturnType<typeof createApp>|undefined;
let platform='linux';
let response:any;
let commands:any[]=[];
const flush=async()=>{for(let i=0;i<20;i++){await Promise.resolve();await nextTick();}};
const btn=(text:string)=>[...document.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===text)!;
async function choose(label:string,value:string){const field=[...document.querySelectorAll<HTMLElement>('.form-row')].find(r=>r.querySelector('label')?.textContent?.trim()===label)!;field.querySelector<HTMLButtonElement>('.dd-btn')!.click();await flush();[...field.querySelectorAll<HTMLButtonElement>('[role=option]')].find(b=>b.querySelector('.dd-item-label')?.textContent?.trim()===value)!.click();await flush();}
async function mount(){const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div />'}}]});await router.push('/fixture');const el=document.createElement('div');document.body.append(el);app=createApp(Tools,{tool:'iperf'});app.use(router);app.mount(el);await flush();await choose('模式','公共 speedtest');}
function baseApi(path:string,opts:any={}){
 if(path==='/nodes/')return Promise.resolve([{id:1,name:'Client',platform,status:'online',net_type:'public',last_seen_at:new Date().toISOString()}]);
 if(path==='/commands'&&opts.method==='POST'){commands=[response];return Promise.resolve(response);}
 if(path==='/commands')return Promise.resolve(commands);
 if(['/iperf-tasks','/mtr-tasks?trigger=manual','/component-installs'].includes(path))return Promise.resolve([]);
 throw Error('Unexpected request '+path);
}
beforeEach(()=>{platform='linux';commands=[];response={id:7,status:'done',exit_code:0,stdout:'[ 1345] 1.25km 2.50ms  Trusted local by fixture',stderr:''};vi.useFakeTimers({toFake:['setTimeout','clearTimeout','setInterval','clearInterval']});vi.spyOn(document,'hidden','get').mockReturnValue(false);mocks.api.mockImplementation(baseApi);});
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';vi.useRealTimers();vi.restoreAllMocks();vi.clearAllMocks();});
it('submits only a quoted Agent selector command through the existing command API',async()=>{await mount();btn('获取列表').click();await flush();const call=mocks.api.mock.calls.find(([p,o]:any)=>p==='/commands'&&o?.method==='POST')!;expect(call).toBeTruthy();const payload=JSON.parse(call[1].body);expect(Object.keys(payload).sort()).toEqual(['command','node_id']);expect(payload.node_id).toBe(1);expect(payload.command).toContain('"$STELLA_SPEEDTEST_GO" --list');expect(payload.command).not.toMatch(/\/opt\/|\|\||2>\/dev\/null|speedtest-cli/);await choose('测速服务器','Trusted local by fixture · 2.50ms · #1345');});
it('rejects nonzero list exit even when the real command channel reports done with a valid partial table',async()=>{response={id:7,status:'done',exit_code:23,stdout:'[ 1345] 1.25km 2.50ms  Partial table by fixture',stderr:'dial tcp: synthetic refusal\n'};await mount();btn('获取列表').click();await flush();expect(document.querySelector('.iperf-error')?.textContent).toContain('dial tcp: synthetic refusal');const field=document.querySelector('.st-server-field')!;field.querySelector<HTMLButtonElement>('.dd-btn')!.click();await flush();expect(field.textContent).not.toContain('Partial table');expect(mocks.api.mock.calls.filter(([p,o]:any)=>p==='/commands'&&o?.method==='POST')).toHaveLength(1);});
it('does not send POSIX syntax to a Windows Agent and states the platform limit',async()=>{platform='Windows';await mount();btn('获取列表').click();await flush();expect(mocks.api.mock.calls.filter(([p,o]:any)=>p==='/commands'&&o?.method==='POST')).toHaveLength(0);expect(document.querySelector('.iperf-error')?.textContent).toContain('Windows');expect(document.querySelector('.iperf-error')?.textContent).toContain('Linux');});
