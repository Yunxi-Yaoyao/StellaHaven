import {test,expect,vi,afterEach,beforeEach} from 'vitest';
import {createApp,nextTick} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
import Nodes from './NodesView.vue';
import {auth,type Me} from '../home/auth';
import {readFileSync} from 'node:fs';
import {createHash,webcrypto} from 'node:crypto';
import {readAgentSource} from '../../api/agentSource';
vi.mock('./NodeComponents.vue',()=>({default:{template:'<div />'}}));
vi.mock('../../api/servers',async importOriginal=>({...await importOriginal<object>(),listNodes:vi.fn(async()=>[{id:1,name:'节点 A',status:'online',agent_version:'0.6.1',platform:'linux',installed:true,token:'fixture-node-a-only'}]),getHost:vi.fn(async()=>null),getPublicHost:vi.fn(async()=>({value:''}))}));
let app:ReturnType<typeof createApp>,host:HTMLElement;
const calls:string[]=[];
const channels={revision:0,default_entry_id:'public',entries:[{entry_id:'public',origin:'https://main.test'}],nodes:[{node_id:1,name:'节点 A',mode:'default',entry_id:null,revision:0,state:'pending',actual_origin:null,http_ms:null,http_origin:null,http_status:null,sampled_at:null,error:null,online:true}]};
async function settle(){for(let i=0;i<50;i++)await Promise.resolve();await nextTick();}
function button(text:string){return [...host.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!;}
beforeEach(()=>{
 auth.me={id:'owner-a',username:'a'} as Me;auth.suspended=false;auth.sessionClosing=false;
 HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
 HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
 calls.length=0;
 vi.stubGlobal('fetch',vi.fn(async(input:string)=>{calls.push(input);if(input==='/agent/version')return new Response(JSON.stringify({version:'0.6.2',sha256:'a'.repeat(64),size:42}));if(input==='/agent/release')return new Response(JSON.stringify({source_version:'0.6.2',source_sha256:'a'.repeat(64),source_size:42,announcement_version:'0.6.2',rollout_policy:'source'}));if(input==='/nodes/report-channels')return new Response(JSON.stringify(channels));throw Error('Unexpected '+input);}));
});
afterEach(()=>{app?.unmount();host?.remove();vi.unstubAllGlobals();vi.useRealTimers();auth.me=null;});
async function mount(){host=document.createElement('div');document.body.append(host);const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:Nodes}]});app=createApp(Nodes);app.use(router);app.mount(host);await settle();}
test('node entry opens one Agent management dialog, reads release and shows actual node version without fetching source',async()=>{
 await mount();expect(button('Agent 管理')).toBeTruthy();button('Agent 管理').click();await settle();
 expect(host.querySelectorAll('dialog[open]')).toHaveLength(1);
 expect(host.querySelector('dialog')?.textContent).toContain('0.6.2');
 expect(host.querySelector('dialog')?.textContent).toContain('0.6.1');
 expect(host.querySelector('dialog')?.textContent).toContain('版本号与下载源码不同');
 expect(host.querySelector('select')).toBeNull();expect(host.querySelector('.node-picker .dd-label')?.textContent).toBe('节点 A');
 expect(calls.filter(x=>x==='/agent/version')).toHaveLength(1);expect(calls).not.toContain('/agent/script');
});

test('channel drafts survive tabs, close and same-owner auth; a different owner starts clean in one dialog',async()=>{
 await mount();button('Agent 管理').click();await settle();button('上报通道').click();await settle();
 button('批量设置').click();await settle();
 expect(host.querySelectorAll('dialog')).toHaveLength(1);
 const check=()=>host.querySelector<HTMLInputElement>('[aria-label="选择 节点 A"]')!;check().click();await settle();expect(check().checked).toBe(true);
 button('总览').click();await settle();button('上报通道').click();await settle();expect(check().checked).toBe(true);
 host.querySelector<HTMLButtonElement>('[aria-label="关闭 Agent 管理"]')!.click();await settle();button('Agent 管理').click();await settle();expect(check().checked).toBe(true);
 auth.suspended=true;await settle();expect(host.querySelector('dialog')?.open).toBe(false);auth.suspended=false;await settle();expect(host.querySelector('dialog')?.open).toBe(true);expect(check().checked).toBe(true);
 auth.me={id:'owner-b',username:'b'} as Me;await settle();button('上报通道').click();await settle();button('批量设置').click();await settle();expect(check().checked).toBe(false);
});
test('source is explicitly requested once, hashes exact served bytes and preserves them for copy/download',async()=>{
 const bytes=readFileSync('../agent/stella_agent.py');
 vi.stubGlobal('crypto',webcrypto);
 const original=fetch;
 vi.stubGlobal('fetch',vi.fn(async(input:string,init?:RequestInit)=>input==='/agent/script'?(calls.push(input),new Response(bytes)):original(input,init)));
 const copied=vi.fn(async()=>{});Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:copied}});
 URL.createObjectURL=vi.fn(()=> 'blob:source');URL.revokeObjectURL=vi.fn();
 await mount();button('Agent 管理').click();await settle();button('源码').click();await settle();expect(calls).not.toContain('/agent/script');
 expect(button('查看源码')).toBeTruthy();button('查看源码').click();await vi.waitFor(()=>expect(host.querySelector('pre')?.textContent).toBe(bytes.toString('utf8')));
 expect(host.textContent).toContain(createHash('sha256').update(bytes).digest('hex'));expect(host.textContent).toContain(bytes.length.toLocaleString()+' bytes');
 expect(host.textContent).toContain('与下载源码信息不一致');
 button('复制源码').click();await settle();expect(copied).toHaveBeenCalledWith(bytes.toString('utf8'));
 button('总览').click();await settle();button('源码').click();await settle();expect(calls.filter(p=>p==='/agent/script')).toHaveLength(1);
 expect(host.querySelector('a[download="stella_agent.py"]')).not.toBeNull();
});
test.each([401,503])('source GET %i keeps the source panel available and retries only on request',async status=>{
 const original=fetch;let count=0;
 vi.stubGlobal('fetch',vi.fn(async(input:string,init?:RequestInit)=>input==='/agent/script'?(count++,new Response('',{status})):original(input,init)));
 await mount();button('Agent 管理').click();await settle();button('源码').click();button('查看源码').click();await settle();
 expect(host.querySelector('[role="alert"]')?.textContent).toContain('读取失败');expect(count).toBe(1);
 button('总览').click();await settle();button('源码').click();await settle();expect(count).toBe(1);
 button('重试读取').click();await settle();expect(count).toBe(2);expect(host.querySelector('pre')).toBeNull();
});
test('leaving the source panel aborts the in-flight read and ignores late responses',async()=>{
 const original=fetch;let resolve!:(r:Response)=>void,signal:AbortSignal|undefined;
 vi.stubGlobal('fetch',vi.fn(async(input:string,init?:RequestInit)=>{if(input==='/agent/script'){signal=init?.signal??undefined;return new Promise<Response>(r=>resolve=r);}return original(input,init);}));
 await mount();button('Agent 管理').click();await settle();button('源码').click();button('查看源码').click();await settle();
 button('总览').click();await settle();expect(signal?.aborted).toBe(true);
 resolve(new Response(readFileSync('../agent/stella_agent.py')));await settle();expect(host.querySelector('pre')).toBeNull();button('源码').click();await settle();expect(button('查看源码').disabled).toBe(false);
});
test('same-owner authentication does not replace the original close-return focus',async()=>{
 await mount();const trigger=button('Agent 管理');trigger.focus();trigger.click();await settle();
 auth.suspended=true;await settle();const login=document.createElement('input');document.body.append(login);login.focus();auth.suspended=false;await settle();
 host.querySelector<HTMLButtonElement>('[aria-label="关闭 Agent 管理"]')!.click();await settle();expect(document.activeElement).toBe(trigger);login.remove();
});
test('release read times out with an explicit retry instead of an unbounded loading state',async()=>{
 vi.useFakeTimers();const original=fetch;let signal:AbortSignal|undefined;
 vi.stubGlobal('fetch',vi.fn(async(input:string,init?:RequestInit)=>{if(input==='/agent/version'){signal=init?.signal??undefined;return new Promise<Response>((_,reject)=>signal!.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError'))));}return original(input,init);}));
 await mount();button('Agent 管理').click();await settle();await vi.advanceTimersByTimeAsync(15001);await settle();expect(signal?.aborted).toBe(true);expect(host.querySelector('[role="alert"]')?.textContent).toContain('超时');expect(button('重试').disabled).toBe(false);
});
test.each(['declared','streamed'])('source rejects %s over 1 MiB rather than rendering or downloading it',async mode=>{
 vi.stubGlobal('fetch',vi.fn(async()=>mode==='declared'?new Response('',{headers:{'content-length':String(1024*1024+1)}}):new Response(new Uint8Array(1024*1024+1))));
 await expect(readAgentSource(new AbortController().signal)).rejects.toThrow('超过 1 MiB');
});
test('source rejects an HTML fallback instead of treating a failed download as valid code',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response('<html>sign in</html>')));await expect(readAgentSource(new AbortController().signal)).rejects.toThrow('有效的 Agent 源码');
});
test('an alternate owner cannot receive a late source body',async()=>{
 let resolve!:(r:Response)=>void;vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(r=>resolve=r)));
 const pending=readAgentSource(new AbortController().signal);auth.me={id:'owner-b'} as Me;resolve(new Response(readFileSync('../agent/stella_agent.py')));await expect(pending).rejects.toHaveProperty('name','AbortError');
});
test('an explicit release refresh reads a new parked announcement without inventing sha or bytes',async()=>{
 await mount();button('Agent 管理').click();await settle();expect(button('刷新发行')).toBeTruthy();
 const original=fetch;vi.stubGlobal('fetch',vi.fn(async(input:string,init?:RequestInit)=>input==='/agent/version'?new Response(JSON.stringify({version:'0.6.9'})):original(input,init)));
 button('刷新发行').click();await settle();expect(host.querySelector('dialog')?.textContent).toContain('0.6.9');expect(host.querySelector('.version')?.textContent).toBe('暂未读取');expect(host.textContent).toContain('下载源码信息暂不可用');expect(host.querySelector('dialog')?.textContent).not.toContain('42 bytes');
});
test('management is credential-free and existing uninstall still requires confirmation for the precise node',async()=>{
 const writes:RequestInit[]=[];const original=fetch;vi.stubGlobal('fetch',vi.fn(async(input:string,init?:RequestInit)=>{if(input==='/nodes/1/uninstall'){writes.push(init!);return new Response('{}');}return original(input,init);}));
 await mount();button('Agent 管理').click();await settle();expect(host.querySelector('dialog')?.textContent).not.toContain('fixture-node-a-only');
 host.querySelector<HTMLButtonElement>('[aria-label="关闭 Agent 管理"]')!.click();await settle();host.querySelector<HTMLButtonElement>('[title="agent"]')!.click();await settle();
 expect(host.querySelector('.cmd')?.textContent).toContain('fixture-node-a-only');button('卸载 agent').click();await settle();expect(writes).toHaveLength(0);expect(host.textContent).toContain('卸载「节点 A」');
 button('确认卸载').click();await settle();expect(writes).toHaveLength(1);expect(writes[0]?.method).toBe('POST');
});
