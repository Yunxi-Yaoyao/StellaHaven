import {test,expect,vi,beforeEach,afterEach} from 'vitest';
import {createApp,nextTick,reactive,h} from 'vue';
import {webcrypto} from 'node:crypto';
import Manager from './AgentManager.vue';
import {auth,refreshAccess} from '../home/auth';
import {readAgentSource} from '../../api/agentSource';
let app:ReturnType<typeof createApp>|undefined,host:HTMLElement;
const text='AGENT_VERSION = "9.8.7"\n# current source';
async function settle(){for(let i=0;i<80;i++)await Promise.resolve();await nextTick();}
function button(text:string){return [...host.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!;}
beforeEach(()=>{auth.me={id:'fix-owner',username:'fix'} as any;auth.suspended=false;auth.sessionClosing=false;vi.stubGlobal('crypto',webcrypto);HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};URL.createObjectURL=vi.fn(()=> 'blob:fix');URL.revokeObjectURL=vi.fn();});
afterEach(()=>{app?.unmount();host?.remove();app=undefined;vi.unstubAllGlobals();vi.useRealTimers();auth.me=null;});
async function mount(nodes=[{id:73,name:'首台节点',status:'online'},{id:902,name:'长名称'.repeat(25),status:'offline'}]){const props=reactive({open:true,nodes});host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(Manager,props)});app.mount(host);await settle();return props;}
function fetchDefault(){vi.stubGlobal('fetch',vi.fn(async(p:string)=>p==='/agent/version'?new Response(JSON.stringify({version:'9.8.7'})):new Response(text)));}
test('node picker uses shared Dropdown, real numeric IDs, first default and removal fallback',async()=>{
 fetchDefault();const props=await mount();expect(host.querySelector('select')).toBeNull();expect(host.querySelector('.node-picker .dd-btn')?.textContent).toContain('首台节点');
 host.querySelector<HTMLButtonElement>('.node-picker .dd-btn')!.click();await settle();const options=host.querySelectorAll<HTMLButtonElement>('.node-picker [role="option"]');expect(options).toHaveLength(2);options[1]!.click();await settle();expect(host.querySelector('section dl:last-child')?.textContent).toContain('离线');expect(host.querySelector('.dd-label')?.textContent).toBe('长名称'.repeat(25));
 props.nodes=[props.nodes[1]!,props.nodes[0]!];await settle();expect(host.querySelector('section dl:last-child')?.textContent).toContain('离线');props.nodes=[props.nodes[1]!];await settle();expect(host.querySelector('.dd-label')?.textContent).toBe('首台节点');props.nodes=[];await settle();expect(host.querySelector('.node-picker')).toBeNull();expect(host.textContent).toContain('还没有纳管节点');
});
test('source explanation is disclosed by HelpHint and complete hash remains viewable and copyable',async()=>{
 fetchDefault();const copied=vi.fn(async()=>{});Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:copied}});await mount();button('源码').click();await settle();expect(host.querySelector('.help-hint')).not.toBeNull();expect(host.querySelector('[role="tooltip"]')).toBeNull();host.querySelector<HTMLButtonElement>('.help-hint')!.click();await settle();expect(host.querySelector('dialog [role="tooltip"]')?.textContent).toContain('仅查看，不执行');button('查看源码').click();await vi.waitFor(()=>expect(host.querySelector('pre')).not.toBeNull());const sha=await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(text));const expected=Buffer.from(sha).toString('hex');expect(host.querySelector('.source-hash code')?.textContent).toBe(expected);button('复制校验值').click();await settle();expect(copied).toHaveBeenCalledWith(expected);
});
test('channel checkbox has its own label target, separate from name detail action',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(p:string)=>p==='/agent/version'?new Response('{}'):new Response(JSON.stringify({revision:0,default_entry_id:'public',entries:[{entry_id:'public',origin:'https://main.test'}],nodes:[{node_id:73,name:'独立详情节点',mode:'default',entry_id:null,state:'pending',online:true}]}))));await mount();button('上报通道').click();await settle();button('批量设置').click();await settle();const check=host.querySelector<HTMLInputElement>('.node-choice input')!,label=check.closest('label');expect(label).not.toBeNull();expect(label?.querySelector('button')).toBeNull();label!.click();await settle();expect(check.checked).toBe(true);host.querySelector<HTMLButtonElement>('.node-name')!.click();await settle();expect(check.checked).toBe(true);expect(host.querySelector('[role="region"]')?.textContent).toContain('独立详情节点');
});
test('15s releases a source stream that never supplies a chunk',async()=>{
 vi.useFakeTimers();const cancel=vi.fn();vi.stubGlobal('fetch',vi.fn(async(p:string)=>p==='/agent/version'?new Response('{}'):new Response(new ReadableStream({cancel}))));await mount();button('源码').click();button('查看源码').click();await settle();await vi.advanceTimersByTimeAsync(15001);await settle();expect(button('重试读取')?.disabled).toBe(false);expect(host.querySelector('[role="alert"]')?.textContent).toContain('超时');expect(cancel).toHaveBeenCalledOnce();
});
test('timed-out refresh stays shared, immediate retry wins, late refresh cannot retry or overwrite source',async()=>{
 vi.useFakeTimers();let finish!:(r:Response)=>void;let scripts=0;let refreshSignal:AbortSignal|null|undefined;
 vi.stubGlobal('fetch',vi.fn(async(p:string,init?:RequestInit)=>p==='/agent/version'?new Response('{}'):p==='/agent/script'?(++scripts===1?new Response('',{status:401}):new Response(text)):(refreshSignal=init?.signal,new Promise<Response>(r=>finish=r))));
 await mount();button('源码').click();button('查看源码').click();await settle();const shared=refreshAccess();expect(refreshSignal).toBeUndefined();await vi.advanceTimersByTimeAsync(15001);await settle();expect(button('重试读取')?.disabled).toBe(false);expect(refreshAccess()).toBe(shared);button('重试读取').click();await settle();await vi.waitFor(()=>expect(host.querySelector('pre')?.textContent).toBe(text));
 finish(new Response(JSON.stringify({id:'fix-owner',username:'fix'})));await shared;await settle();expect(scripts).toBe(2);expect(host.querySelector('pre')?.textContent).toBe(text);expect(host.querySelector('[role="alert"]')).toBeNull();
});
test.each(['resolve','reject'])('aborted source disposes late fetch %s and removes local abort listeners',async mode=>{
 let finish!:(r:Response)=>void,fail!:(e:Error)=>void;vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>((r,j)=>{finish=r;fail=j;})));const c=new AbortController(),add=vi.spyOn(c.signal,'addEventListener'),remove=vi.spyOn(c.signal,'removeEventListener');const pending=readAgentSource(c.signal);c.abort();await expect(pending).rejects.toHaveProperty('name','AbortError');expect(remove.mock.calls.filter(x=>x[0]==='abort')).toHaveLength(add.mock.calls.filter(x=>x[0]==='abort').length);
 if(mode==='resolve'){const cancel=vi.fn();finish(new Response(new ReadableStream({cancel})));await settle();expect(cancel).toHaveBeenCalledOnce();}else{fail(new Error('late network failure'));await settle();}
});
test('successful shared refresh retries this live caller once and returns real source bytes',async()=>{
 let scripts=0;vi.stubGlobal('fetch',vi.fn(async(p:string)=>p==='/agent/script'?(++scripts===1?new Response('',{status:401}):new Response(text)):new Response(JSON.stringify({id:'fix-owner',username:'fix'}))));const value=await readAgentSource(new AbortController().signal);expect(value.text).toBe(text);expect(value.size).toBe(new TextEncoder().encode(text).length);expect(scripts).toBe(2);
});
test.each(['tab','close','auth'])('shared refresh survives source %s cancellation without a late source retry',async action=>{
 let finish!:(r:Response)=>void;let scripts=0;vi.stubGlobal('fetch',vi.fn(async(p:string)=>p==='/agent/version'?new Response('{}'):p==='/agent/script'?(scripts++,new Response('',{status:401})):new Promise<Response>(r=>finish=r)));const props=await mount();button('源码').click();button('查看源码').click();await settle();const shared=refreshAccess();if(action==='tab')button('总览').click();else if(action==='close')props.open=false;else auth.suspended=true;await settle();expect(refreshAccess()===shared||action==='auth').toBe(true);finish(new Response(JSON.stringify({id:'fix-owner',username:'fix'})));await shared;await settle();expect(scripts).toBe(1);expect(host.querySelector('pre')).toBeNull();
});
test('owner epoch change during shared refresh cannot publish source or retry for a new owner',async()=>{
 let finish!:(r:Response)=>void;let scripts=0;vi.stubGlobal('fetch',vi.fn(async(p:string)=>p==='/agent/script'?(scripts++,new Response('',{status:401})):new Promise<Response>(r=>finish=r)));const pending=readAgentSource(new AbortController().signal);await settle();auth.sessionGeneration++;auth.requestEpoch++;auth.me={id:'new-owner'} as any;finish(new Response(JSON.stringify({id:'fix-owner'})));await expect(pending).rejects.toHaveProperty('name','AbortError');expect(auth.me?.id).toBe('new-owner');expect(scripts).toBe(1);
});
