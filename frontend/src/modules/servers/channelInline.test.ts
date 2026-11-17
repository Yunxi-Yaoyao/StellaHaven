import {test,expect,vi,afterEach} from 'vitest';
import {createApp,nextTick,reactive,h} from 'vue';
import Panel from './ReportChannelManager.vue';
import {auth} from '../home/auth';
import {ApiError} from '../../api/client';
import * as channels from '../../api/reportChannels';
vi.mock('../../api/reportChannels',()=>({getReportChannels:vi.fn(),putReportChannels:vi.fn()}));
const fixture=()=>({revision:0,default_entry_id:'public' as const,entries:[{entry_id:'public' as const,origin:'https://main.test'},{entry_id:'private' as const,origin:'https://private.test'}],nodes:[1,2].map(id=>({node_id:id,name:'节点 '+id,mode:'default' as const,entry_id:null,revision:0,state:'pending' as const,actual_origin:null,http_ms:null,http_origin:null,http_status:null,sampled_at:null,error:null,online:true}))});
let app:ReturnType<typeof createApp>,host:HTMLElement;
async function settle(){for(let i=0;i<30;i++)await Promise.resolve();await nextTick();}
const button=(text:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===text)!;
async function mount(){HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};host=document.createElement('div');document.body.append(host);const props=reactive({embedded:true,active:true});app=createApp({render:()=>h(Panel,props)});app.mount(host);await settle();return props;}
afterEach(()=>{app?.unmount();host?.remove();auth.suspended=false;vi.resetAllMocks();});
async function choose(text:string){(host.querySelector('.row-editor .dd-btn') as HTMLButtonElement).click();await settle();[...host.querySelectorAll<HTMLButtonElement>('[role="option"]')].find(o=>o.textContent?.includes(text))!.click();await settle();}
test('row settings opens an editor inside that row without selecting bulk or sending a write; repeated click retains draft',async()=>{
 vi.mocked(channels.getReportChannels).mockResolvedValue(fixture());await mount();
 (host.querySelector('[aria-label="设置 节点 1 上报通道"]') as HTMLButtonElement).click();await settle();
 expect(host.querySelector('.channel-row .row-editor')).not.toBeNull();
 expect(host.querySelector('.channel-tools .selector')).toBeNull();
 await choose('自动选择');(host.querySelector('[aria-label="设置 节点 1 上报通道"]') as HTMLButtonElement).click();await settle();
 expect(host.querySelector('.row-editor')?.textContent).toContain('自动选择');
 expect(channels.putReportChannels).not.toHaveBeenCalled();
 button('应用此节点').click();await settle();
 expect(channels.putReportChannels).toHaveBeenCalledWith({revision:0,node_ids:[1],mode:'auto',entry_id:null},expect.anything());
});
test('registry validation failure explains the exact prerequisite and links site settings without fabricating entries',async()=>{
 vi.mocked(channels.getReportChannels).mockRejectedValue(new ApiError(503,'上报通道需要已登记的精确 HTTPS 入口'));await mount();
 expect(host.querySelector('[role="alert"]')?.textContent).toContain('上报通道需要已登记的精确 HTTPS 入口');
 expect(host.querySelector('a[href="/settings?section=services"]')).not.toBeNull();expect(host.querySelector('.row-editor')).toBeNull();expect(channels.putReportChannels).not.toHaveBeenCalled();
});
test('removed registry options cannot be applied from a retained draft',async()=>{
 vi.mocked(channels.getReportChannels).mockResolvedValue(fixture());await mount();
 (host.querySelector('.row-edit') as HTMLButtonElement).click();await settle();await choose('自动选择');
 const single=fixture();single.entries=single.entries.slice(0,1);vi.mocked(channels.getReportChannels).mockResolvedValue(single);
 button('刷新').click();await settle();
 expect(button('应用此节点').disabled).toBe(true);
 expect(host.textContent).toContain('草稿入口已不可用');
});
test('row and bulk drafts survive switching without overwriting each other; cancel never writes',async()=>{
 vi.mocked(channels.getReportChannels).mockResolvedValue(fixture());await mount();
 button('批量设置').click();await settle();(host.querySelector('[aria-label="选择 节点 2"]') as HTMLInputElement).click();
 (host.querySelector('.bulk-tools .dd-btn') as HTMLButtonElement).click();await settle();
 [...host.querySelectorAll<HTMLButtonElement>('[role="option"]')].find(o=>o.textContent?.includes('自动选择'))!.click();await settle();
 (host.querySelector('.row-edit') as HTMLButtonElement).click();await settle();await choose('固定入口');
 button('批量设置').click();await settle();expect(host.querySelector('.bulk-tools')?.textContent).toContain('自动选择');
 expect((host.querySelector('[aria-label="选择 节点 2"]') as HTMLInputElement).checked).toBe(true);
 (host.querySelector('.row-edit') as HTMLButtonElement).click();await settle();expect(host.querySelector('.row-editor')?.textContent).toContain('固定入口');
 button('取消').click();await settle();expect(host.querySelector('.row-editor')).toBeNull();expect(channels.putReportChannels).not.toHaveBeenCalled();
});
test.each([401,503])('inline PUT receipt survives failed ACK GET %i and repeated clicks only reread',async status=>{
 const data=fixture(),receipt={...data,revision:1,nodes:data.nodes.map(n=>n.node_id===1?{...n,mode:'auto' as const,revision:1}:n)};
 vi.mocked(channels.getReportChannels).mockResolvedValueOnce(data).mockRejectedValue(new ApiError(status,'read failed'));
 vi.mocked(channels.putReportChannels).mockResolvedValue(receipt);await mount();
 (host.querySelector('.row-edit') as HTMLButtonElement).click();await settle();await choose('自动选择');button('应用此节点').click();await settle();
 expect(host.querySelector('.row-editor [role="status"]')?.textContent).toContain('已保存');
 expect(host.textContent).toContain('状态读取失败');expect(host.textContent).not.toContain('Agent 已确认');
 (host.querySelector('.row-edit') as HTMLButtonElement).click();await settle();button('重读状态').click();await settle();
 expect(channels.putReportChannels).toHaveBeenCalledTimes(1);
 vi.mocked(channels.getReportChannels).mockResolvedValue(receipt);button('刷新').click();await settle();
 expect(button('应用此节点').disabled).toBe(true);expect(channels.putReportChannels).toHaveBeenCalledTimes(1);
});
test('saved status follows actual ACK instead of keeping a waiting claim after ACK',async()=>{
 const data=fixture(),receipt={...data,revision:1,nodes:data.nodes.map(n=>({...n,mode:'auto' as const,revision:1}))};
 vi.mocked(channels.getReportChannels).mockResolvedValueOnce(data).mockResolvedValue(receipt);vi.mocked(channels.putReportChannels).mockResolvedValue(receipt);await mount();
 (host.querySelector('.row-edit') as HTMLButtonElement).click();await settle();await choose('自动选择');button('应用此节点').click();await settle();
 expect(host.querySelector('.row-editor [role="status"]')?.textContent).toContain('等待 Agent 确认');
 vi.mocked(channels.getReportChannels).mockResolvedValue({...receipt,nodes:receipt.nodes.map(n=>({...n,state:'applied' as const}))});button('刷新').click();await settle();
 expect(host.querySelector('.row-editor [role="status"]')?.textContent).not.toContain('等待');
 expect(host.querySelector('.channel-row .state')?.textContent).toContain('Agent 已确认');
});
test('inline conflict preserves private draft and refresh uses newest CAS; inactive/auth actions do not write',async()=>{
 vi.mocked(channels.getReportChannels).mockResolvedValue(fixture());vi.mocked(channels.putReportChannels).mockRejectedValue(new ApiError(409,'conflict'));const props=await mount();
 (host.querySelector('.row-edit') as HTMLButtonElement).click();await settle();await choose('固定入口');button('应用此节点').click();await settle();
 expect(host.querySelector('.row-editor [role="alert"]')?.textContent).toContain('配置已变化');
 vi.mocked(channels.getReportChannels).mockResolvedValue({...fixture(),revision:8});button('刷新').click();await settle();
 expect(host.querySelector('.row-editor .dd-btn')?.textContent).toContain('private.test');
 props.active=false;await settle();button('应用此节点').click();await settle();expect(channels.putReportChannels).toHaveBeenCalledTimes(1);
 props.active=true;auth.suspended=true;await settle();button('应用此节点').click();await settle();expect(channels.putReportChannels).toHaveBeenCalledTimes(1);
 auth.suspended=false;await settle();button('应用此节点').click();await settle();
 expect(vi.mocked(channels.putReportChannels).mock.calls[1]![0]).toEqual({revision:8,node_ids:[1],mode:'fixed',entry_id:'private'});
});
