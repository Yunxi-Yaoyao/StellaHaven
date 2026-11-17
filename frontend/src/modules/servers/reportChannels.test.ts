import {test,expect,vi,afterEach} from 'vitest';
import {createApp,nextTick} from 'vue';
import Panel from './ReportChannelManager.vue';
import {ApiError} from '../../api/client';
import {auth} from '../home/auth';
import * as channels from '../../api/reportChannels';
vi.mock('../../api/reportChannels',()=>({getReportChannels:vi.fn(),putReportChannels:vi.fn()}));
let app:ReturnType<typeof createApp>|undefined,host:HTMLElement;
const data={revision:0,default_entry_id:'public' as const,entries:[{entry_id:'public' as const,origin:'https://main.test'},{entry_id:'private' as const,origin:'https://private.test'}],nodes:[{node_id:1,name:'节点 A',mode:'default' as const,entry_id:null,revision:0,state:'pending' as const,actual_origin:null,http_ms:null,http_origin:null,http_status:null,sampled_at:null,error:null,online:false},{node_id:2,name:'节点 B',mode:'default' as const,entry_id:null,revision:0,state:'pending' as const,actual_origin:null,http_ms:null,http_origin:null,http_status:null,sampled_at:null,error:null,online:true}]};
async function settle(){for(let i=0;i<30;i++)await Promise.resolve();await nextTick();}
afterEach(()=>{app?.unmount();host?.remove();auth.suspended=false;vi.resetAllMocks();});
test('bulk uses selected nodes only, default stays default and PUT is not applied receipt',async()=>{
 vi.mocked(channels.getReportChannels).mockResolvedValue(data);
 vi.mocked(channels.putReportChannels).mockResolvedValue({...data,revision:1});
 host=document.createElement('div');document.body.append(host);
 // jsdom lacks the native dialog API; production and browser tests use it.
 HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
 app=createApp(Panel);app.mount(host);await settle();button('批量设置').click();await settle();
 expect(host.textContent).toContain('默认入口');expect(host.textContent).toContain('离线 · 待应用');
 expect(host.querySelector('select')).toBeNull();
 (host.querySelector('[aria-label="选择 节点 A"]') as HTMLInputElement).click();await settle();
 [...host.querySelectorAll('button')].find(b=>b.textContent?.includes('应用到所选'))!.click();await settle();
 expect(channels.putReportChannels).toHaveBeenCalledWith({revision:0,node_ids:[1],mode:'default',entry_id:null},expect.anything());
 expect(host.textContent).not.toContain('已切换');expect(channels.getReportChannels).toHaveBeenCalledTimes(2);
});
test('failure retains selected nodes and gives an inline retry',async()=>{
 vi.mocked(channels.getReportChannels).mockResolvedValue(data);
 vi.mocked(channels.putReportChannels).mockRejectedValue(new Error('offline'));
 host=document.createElement('div');document.body.append(host);app=createApp(Panel);app.mount(host);await settle();button('批量设置').click();await settle();
 (host.querySelector('[aria-label="选择 节点 B"]') as HTMLInputElement).click();await settle();
 [...host.querySelectorAll('button')].find(b=>b.textContent?.includes('应用到所选'))!.click();await settle();
 expect(host.querySelector('[role="alert"]')?.textContent).toContain('保存失败');
 expect((host.querySelector('[aria-label="选择 节点 B"]') as HTMLInputElement).checked).toBe(true);
});

function button(text:string){return [...host.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!;}
async function mountPanel(onClose=vi.fn()){
 HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
 host=document.createElement('div');document.body.append(host);app=createApp(Panel,{onClose});app.mount(host);await settle();button('批量设置').click();await settle();
 return onClose;
}
async function chooseAuto(){
 (host.querySelector('.selector .dd-btn') as HTMLButtonElement).click();await settle();
 [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(o=>o.textContent?.includes('自动选择'))!.click();await settle();
}
test.each([401,503])('PUT receipt survives GET %i; retries only read, pending stays pending, dirty tracks new edits',async status=>{
 const receipt={...data,revision:1,nodes:data.nodes.map(n=>({...n,mode:'auto' as const,revision:1}))};
 vi.mocked(channels.getReportChannels).mockResolvedValueOnce(data).mockRejectedValue(new ApiError(status,'read unavailable'));
 vi.mocked(channels.putReportChannels).mockResolvedValue(receipt);
 const closed=await mountPanel();
 HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
 (host.querySelector('[aria-label="选择 节点 A"]') as HTMLInputElement).click();await chooseAuto();
 button('应用到所选').click();button('应用到所选')?.click();await settle();
 expect(channels.putReportChannels).toHaveBeenCalledTimes(1);
 expect(host.querySelector('[role="status"]')?.textContent).toContain('已保存');
 expect(host.querySelector('[role="alert"]')?.textContent).not.toContain('保存失败');
 expect(host.querySelector('.channel-row .state')?.textContent).toContain('待应用');
 expect((host.querySelector('[aria-label="选择 节点 A"]') as HTMLInputElement).checked).toBe(true);
 for(let i=0;i<2;i++){button('重读状态').click();await settle();button('刷新').click();await settle();}
 expect(channels.putReportChannels).toHaveBeenCalledTimes(1);
 expect(host.querySelector('[role="status"]')?.textContent).toContain('已保存');
 // Reauthorization/availability recovery only changes the next GET response.
 if(status===401){
  auth.suspended=true;await settle();expect(host.querySelector('dialog')?.open).toBe(false);
  expect(host.querySelector('[role="status"]')?.textContent).toContain('已保存');
  auth.suspended=false;await settle();expect(host.querySelector('dialog')?.open).toBe(true);
 }
 vi.mocked(channels.getReportChannels).mockResolvedValue(receipt);
 button('刷新').click();await settle();
 expect(host.querySelector('[role="alert"]')).toBeNull();
 expect(button('应用到所选').disabled).toBe(true);
 expect(host.textContent).not.toContain('Agent 已确认');
 // New unsaved selection survives refresh; a changed draft can be submitted once.
 (host.querySelector('[aria-label="选择 节点 B"]') as HTMLInputElement).click();await settle();
 expect(button('应用到所选').disabled).toBe(false);
 button('刷新').click();await settle();expect(button('应用到所选').disabled).toBe(false);
 button('应用到所选').click();await settle();
 expect(channels.putReportChannels).toHaveBeenCalledTimes(2);
 expect(vi.mocked(channels.putReportChannels).mock.calls[1]![0]).toEqual({revision:1,node_ids:[1,2],mode:'auto',entry_id:null});
 (host.querySelector('[aria-label="关闭上报通道"]') as HTMLButtonElement).click();await settle();expect(closed).toHaveBeenCalledTimes(1);
 app!.unmount();host.remove();await mountPanel();
 expect(channels.putReportChannels).toHaveBeenCalledTimes(2);
 expect(host.querySelector('.channel-row .state')?.textContent).toContain('待应用');
});
test.each([403,409,503])('real PUT %i failure retains auto draft and is still saveable',async status=>{
 vi.mocked(channels.getReportChannels).mockResolvedValue(data);
 vi.mocked(channels.putReportChannels).mockRejectedValue(new ApiError(status,'write rejected'));
 await mountPanel();(host.querySelector('[aria-label="选择 节点 B"]') as HTMLInputElement).click();await chooseAuto();
 button('应用到所选').click();await settle();
 expect(channels.putReportChannels).toHaveBeenCalledTimes(1);expect(channels.getReportChannels).toHaveBeenCalledTimes(1);
 expect(host.querySelector('[role="status"]')).toBeNull();expect(host.querySelector('[role="alert"]')).not.toBeNull();
 expect((host.querySelector('[aria-label="选择 节点 B"]') as HTMLInputElement).checked).toBe(true);
 expect(host.querySelector('.selector')?.textContent).toContain('自动选择');
 expect(button('应用到所选').disabled).toBe(false);
 vi.mocked(channels.putReportChannels).mockResolvedValue({...data,revision:1});
 button('应用到所选').click();await settle();
 expect(vi.mocked(channels.putReportChannels).mock.calls[1]![0]).toEqual({revision:0,node_ids:[2],mode:'auto',entry_id:null});
});
test('refresh detecting a competing saved policy makes the retained draft dirty again',async()=>{
 const receipt={...data,revision:1,nodes:data.nodes.map(n=>({...n,mode:'auto' as const,revision:1}))};
 vi.mocked(channels.getReportChannels).mockResolvedValueOnce(data).mockResolvedValue(receipt);
 vi.mocked(channels.putReportChannels).mockResolvedValue(receipt);
 await mountPanel();(host.querySelector('[aria-label="选择 节点 A"]') as HTMLInputElement).click();await chooseAuto();
 button('应用到所选').click();await settle();expect(button('应用到所选').disabled).toBe(true);
 vi.mocked(channels.getReportChannels).mockResolvedValue({...data,revision:2});
 button('刷新').click();await settle();expect(button('应用到所选').disabled).toBe(false);
 expect(host.querySelector('.selector')?.textContent).toContain('自动选择');
 button('应用到所选').click();await settle();
 expect(vi.mocked(channels.putReportChannels).mock.calls[1]![0].revision).toBe(2);
});
