import {createApp,nextTick} from 'vue';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import Files from './NodeFilesView.vue';
import Docker from './DockerView.vue';
import * as api from '../../api/servers';
vi.mock('../../api/servers',async original=>({...await original<any>(),listNodes:vi.fn(),latestNetTask:vi.fn(),scanDocker:vi.fn()}));
let app:ReturnType<typeof createApp>|undefined,host:HTMLElement;
const settle=async()=>{for(let i=0;i<50;i++){await Promise.resolve();await nextTick();}};
const button=(text:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!;
async function mount(component:any,props={}){host=document.createElement('div');document.body.append(host);app=createApp(component,props);app.mount(host);await settle();}
beforeEach(()=>{vi.useFakeTimers();vi.resetAllMocks();for(const [key,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,key,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});});
afterEach(()=>{app?.unmount();app=undefined;host?.remove();sessionStorage.clear();vi.useRealTimers();vi.unstubAllGlobals();});
test('Docker accepts legacy boolean inventory and clears old selection when last Docker node disappears',async()=>{
 vi.mocked(api.listNodes).mockResolvedValue([{id:1,name:'Docker fixture',status:'online',last_seen_at:new Date().toISOString(),components:{docker:true}}] as any);
 vi.mocked(api.latestNetTask).mockResolvedValue({created_at:new Date().toISOString(),result_json:{containers:[{id:'owned',name:'owned-container',state:'running',status:'Up',image:'fixture'}]}} as any);
 await mount(Docker);expect(host.textContent).toContain('owned-container');
 vi.mocked(api.listNodes).mockResolvedValue([]);await vi.advanceTimersByTimeAsync(15000);await settle();
 expect(host.textContent).not.toContain('owned-container');expect(host.textContent).toContain('没有安装 Docker 的节点');button('刷新').click();await settle();expect(api.scanDocker).not.toHaveBeenCalled();
});
test('file close and refresh use owned draft confirmation; retain does not fetch or lose text',async()=>{
 const calls:string[]=[];
 vi.stubGlobal('confirm',vi.fn(()=>{throw Error('native confirm must never run');}));
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{calls.push(url);if(url==='/node-files/nodes')return Response.json([{id:1,name:'owned',online:true,roots:[{id:'data',label:'data',write:true,blocked:false}]}]);
 const data=JSON.parse(String(init?.body||'{}'));
 return Response.json({id:'owned-request',state:'done',result:data.op==='preview'?{text:'original',etag:'fixture-etag'}:{entries:[{name:'owned.txt',kind:'file',size:8,mtime:1,mode:'0600',uid:0,gid:0}]}});
 }));
 await mount(Files,{scopeKey:'owned:1'});button('owned.txt').click();await settle();button('编辑文本').click();await settle();
 const editor=host.querySelector('textarea')!;editor.value='retained draft';editor.dispatchEvent(new Event('input'));await settle();
 const count=calls.length;button('刷新').click();await settle();expect(host.querySelector('dialog')?.open).toBe(true);button('保留草稿').click();await settle();expect(calls).toHaveLength(count);expect(editor.value).toBe('retained draft');
 button('关闭').click();await settle();expect(host.querySelector('dialog')?.open).toBe(true);host.querySelector('dialog')!.dispatchEvent(new Event('cancel',{cancelable:true}));await settle();expect(host.querySelector('textarea')?.value).toBe('retained draft');
 button('关闭').click();await settle();button('丢弃并继续').click();await settle();expect(host.querySelector('.preview')).toBeNull();
});
