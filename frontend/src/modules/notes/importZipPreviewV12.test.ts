import {createApp,nextTick} from 'vue';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import JSZip from 'jszip';
const mocks=vi.hoisted(()=>({api:vi.fn(),refresh:vi.fn()}));
vi.mock('../../api/client',()=>({api:mocks.api,ApiError:class extends Error{}}));
vi.mock('../../stores/notes',()=>({useNotesStore:()=>({refreshList:mocks.refresh})}));
vi.mock('../home/auth',async()=>{const {reactive}=await import('vue');return {auth:reactive({me:{id:'owner'},requestEpoch:1,sessionGeneration:1,suspended:false,sessionClosing:false})};});
import ZipImportDialog from './ZipImportDialog.vue';
let app:ReturnType<typeof createApp>|undefined;
const flush=async()=>{for(let i=0;i<25;i++){await Promise.resolve();await nextTick();}};
const button=(name:string)=>[...document.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===name)!;
async function mount(content='# 正文\n\n段落') {
 const bytes=await new JSZip().file('body.md',content).generateAsync({type:'arraybuffer',compression:'DEFLATE'});
 const el=document.createElement('div');document.body.append(el);const complete=vi.fn();
 app=createApp(ZipImportDialog,{file:{name:'sample.zip',size:bytes.byteLength,arrayBuffer:async()=>bytes},target:{workspaceId:'workspace',parentId:null},disabled:false,onComplete:complete});app.mount(el);await flush();button('自动').click();
 await vi.waitFor(()=>expect(button('body · 阅读预览')).toBeTruthy());button('body · 阅读预览').click();
 await vi.waitFor(()=>expect(document.querySelector('.preview-body')).not.toBeNull());return {complete};
}
beforeEach(()=>{mocks.api.mockImplementation((p:string)=>Promise.resolve(p.endsWith('/preview')?{entries:[{path:'body.md',title:'body',kind:'document',parent_path:null}],warnings:[],counts:{documents:1,attachments:0}}:{documents:[{id:'created',title:'body'}],attachments:0,warnings:[]}));mocks.refresh.mockResolvedValue(undefined);});
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';vi.clearAllMocks();});
it('does not let local reading cancel an in-flight import receipt',async()=>{
 const {complete}=await mount();let resolve!:(v:any)=>void;const receipt=new Promise(r=>resolve=r);mocks.api.mockReturnValue(receipt);button('导入此 ZIP').click();await flush();
 const previewChoice=button('body · 阅读预览');expect(previewChoice.disabled).toBe(true);previewChoice.click();
 resolve({documents:[{id:'created',title:'body'}],attachments:0,warnings:[]});await flush();expect(complete).toHaveBeenCalledWith(1);expect(document.body.textContent).not.toContain('导入已暂停');
});
it('stops the local ZIP preview stream at its byte cap and labels truncation',async()=>{
 await mount('A'.repeat(300000));expect(document.body.textContent).toContain('256 KiB');expect(document.body.textContent).toContain('截断');button('源码').click();await flush();expect(document.querySelector('.preview-source')!.textContent!.length).toBe(256*1024);expect(mocks.api).toHaveBeenCalledTimes(1);
});
