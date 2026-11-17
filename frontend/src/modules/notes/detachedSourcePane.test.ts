import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {createApp,defineComponent,h,nextTick,reactive,type App} from 'vue';
const mocks=vi.hoisted(()=>({read:vi.fn(),save:vi.fn()}));
vi.mock('../../api/detachedSources',()=>({getDetachedSource:mocks.read,saveDetachedSource:mocks.save}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false})}));
vi.mock('./ProjectSourceEditor.vue',()=>({default:defineComponent({props:['modelValue','filename','readonly'],emits:['update:modelValue'],setup:(p,{emit})=>()=>h('textarea',{value:p.modelValue,readonly:p.readonly,onInput:(e:Event)=>emit('update:modelValue',(e.target as HTMLTextAreaElement).value)})})}));
import DetachedSourcePane from './DetachedSourcePane.vue';
import {auth} from '../home/auth';
const raw='<script>const x = "**not markdown**";</script>\r\n';
const data={id:'file',workspace_id:'ws',kind:'detached-source',title:'renamed',mime:'text/html',content:raw,updated_at:'v1'};
let app:App,host:HTMLElement,pane:any;
const state=reactive({active:true});
const settle=async()=>{for(let i=0;i<15;i++){await Promise.resolve();await nextTick();}};
async function mount(){state.active=true;host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(DetachedSourcePane,{ref:(v:any)=>pane=v,fileId:'file',active:state.active})});app.mount(host);await settle();}
function edit(text:string){const el=host.querySelector('textarea')!;el.value=text;el.dispatchEvent(new Event('input',{bubbles:true}));}
function deferred<T>(){let resolve!:(v:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};}
beforeEach(()=>{vi.clearAllMocks();Object.assign(auth,{me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});mocks.read.mockResolvedValue({...data});mocks.save.mockImplementation(async(_id:string,_version:string,content:string)=>({...data,updated_at:'v2',content}));});
afterEach(()=>{app?.unmount();host?.remove();});
it('saves raw code through independent source API, no iframe or Markdown',async()=>{
 await mount();expect(pane.body).toBeUndefined();expect(host.querySelector('iframe')).toBeNull();expect(host.textContent).toContain('独立源码');
 edit('<h1>**raw**</h1>');await nextTick();expect(await pane.prepareNavigation()).toBe(true);
 expect(mocks.save).toHaveBeenCalledWith('file','v1','<h1>**raw**</h1>');
});
it('failed save retains the draft and blocks deletion',async()=>{
 mocks.save.mockRejectedValue(Error('offline'));await mount();edit('local');await nextTick();expect(await pane.prepareDeletion()).toBe(false);expect(host.querySelector('textarea')!.value).toBe('local');expect(host.textContent).toContain('offline');
});
it('unknown commit is read back before retry and newer local text is preserved',async()=>{
 const flight=deferred<any>();mocks.save.mockReturnValueOnce(flight.promise);await mount();edit('first');await nextTick();const pending=pane.prepareNavigation();await settle();auth.suspended=true;auth.requestEpoch++;await settle();flight.resolve({...data,content:'first',updated_at:'v2'});await pending;auth.suspended=false;mocks.read.mockResolvedValue({...data,content:'first',updated_at:'v2'});await settle();edit('second');await nextTick();expect(await pane.prepareNavigation()).toBe(true);expect(mocks.save).toHaveBeenLastCalledWith('file','v2','second');
});
it('a divergent unknown commit retains local source and never blindly overwrites remote',async()=>{
 mocks.save.mockRejectedValueOnce(Error('lost acknowledgement'));await mount();edit('local');await nextTick();expect(await pane.prepareNavigation()).toBe(false);
 mocks.read.mockResolvedValue({...data,content:'remote edit',updated_at:'v9'});expect(await pane.prepareNavigation()).toBe(false);
 expect(mocks.save).toHaveBeenCalledTimes(1);expect(host.querySelector('textarea')!.value).toBe('local');expect(host.textContent).toContain('源码冲突');
});
it('a clean pre-deletion freeze can pass confirmation without acquiring new writes',async()=>{
 await mount();expect(await pane.prepareDeletion()).toBe(true);state.active=false;await settle();expect(await pane.prepareDeletion()).toBe(true);expect(mocks.save).not.toHaveBeenCalled();
 auth.suspended=true;await settle();expect(await pane.prepareDeletion()).toBe(false);
});
it('identity ABA cannot revive a stale response',async()=>{
 const read=deferred<any>();mocks.read.mockReturnValue(read.promise);await mount();auth.me={id:'bob'} as any;await settle();auth.me={id:'alice'} as any;read.resolve(data);await settle();expect(host.querySelector('textarea')).toBeNull();expect(await pane.prepareNavigation()).toBe(false);
});
