import {afterEach, expect, it, vi} from 'vitest';
import {createApp, nextTick, type App, type Component} from 'vue';
import type {BackupConfig, BackupSnapshot, BackupRecord, BackupJob} from '../../api/backups';
import {elevation,finishElevation} from '../../shell/elevation';
import {toasts} from '../../composables/useToast';
// This suite isolates ZIP management; real preference HTTP/store integration has its own suite.
vi.mock('./clientPreferenceSync',async()=>({clientPreferenceSync:{state:(await import('vue')).reactive({phase:'synced',revision:1,message:'',reloadRequired:false}),ensureConfirmed:vi.fn(async()=>{}),beginRestore:vi.fn(),refreshAfterRestore:vi.fn(async()=>{})}}));
vi.mock('../home/auth', async () => {
  const {reactive, ref} = await import('vue');
  return {auth:reactive({me:{id:'fixture-owner'}, sessionGeneration:0, requestEpoch:0, suspended:false, sessionClosing:false}), isAdmin:ref(true)};
});
const centers = import.meta.glob('./BackupCenter.vue', {eager:true, import:'default'});
let app:App|undefined;
export const configFixture = ():BackupConfig => ({revision:1, enabled:false, scope:'settings', directory:'', frequency:'daily', time:'03:00', timezone:'Asia/Shanghai', weekday:0});
export const snapshotFixture = ():BackupSnapshot => ({config:configFixture(), records:[], job:null, storage:{node:'fixture-node', available:true, free_bytes:10737418240, error:null}, next_run:null, capabilities:{settings_restore:true, full_restore:'maintenance_cli'}});
const jobFixture=(changes:Partial<BackupJob>={}):BackupJob=>({id:'job-fixture',kind:'backup',scope:'settings',state:'queued',stage:'queued',error:null,record_id:null,...changes});
const recordFixture=(changes:Partial<BackupRecord>={}):BackupRecord=>({id:'record-id',filename:'stella-settings-20261017.zip',scope:'settings',created_at:'2026-10-17T12:00:00Z',bytes:4096,sha256:'a'.repeat(64),verified:true,...changes});
const requests:{url:string; options:RequestInit}[]=[];
let responder:(url:string,options:RequestInit)=>Promise<Response>;
const response=(body:unknown,status=200)=>new Response(status===204?null:JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
async function settle(){for(let i=0;i<5;i++){await new Promise(r=>setTimeout(r,0));await nextTick();}}
async function mount(initial?:typeof responder){
  expect(centers['./BackupCenter.vue'], 'backup center component is missing').toBeDefined();
  responder=initial ?? (async()=>response(snapshotFixture()));
  vi.stubGlobal('fetch', vi.fn(async (url:string,options:RequestInit={})=>{requests.push({url,options});return responder(url,options);}));
  const root=document.createElement('div');document.body.append(root);app=createApp(centers['./BackupCenter.vue'] as Component);app.mount(root);await settle();return root;
}
function button(root:ParentNode,label:string){const found=[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()===label);expect(found,`button ${label}`).toBeDefined();return found!;}
function input(root:ParentNode,label:string,value:string){const el=root.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;expect(el).not.toBeNull();el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));return el;}
afterEach(()=>{toasts.splice(0);app?.unmount();app=undefined;finishElevation(false);document.body.innerHTML='';requests.length=0;vi.unstubAllGlobals();vi.restoreAllMocks();vi.useRealTimers();});
it('shows safe diagnostic code, failed stage and job identity, but leaves historical reasons unknown',async()=>{
  const job=jobFixture({id:'diagnostic-job',state:'failed',stage:'failed',error:'备份未完成',reason_code:'configuration_resource_checksum_mismatch',failed_stage:'exporting'});
  const root=await mount(async()=>response({...snapshotFixture(),job}));
  expect(root.textContent).toContain('diagnostic-job');
  expect(root.textContent).toContain('configuration_resource_checksum_mismatch');
  expect(root.textContent).toContain('exporting');
  responder=async()=>response({...snapshotFixture(),job:jobFixture({id:'old-job',state:'failed',stage:'failed',error:'legacy InvalidArchive'})});
  button(root,'刷新备份状态').click();await settle();
  expect(root.textContent).toContain('old-job');
  expect(root.textContent).toContain('原因未记录');
  expect(root.textContent).not.toContain('configuration_resource_checksum_mismatch');
  expect(requests.every(r=>(r.options.method||'GET')==='GET')).toBe(true);
});
it('keeps ZIP integrity disclaimer in keyboard-accessible contextual help, not record body',async()=>{
 const root=await mount(async()=>response({...snapshotFixture(),records:[recordFixture()]}));
 const details=root.querySelector('article.record details') as HTMLDetailsElement;details.open=true;await nextTick();
 expect(root.textContent).not.toContain('校验不等于恢复验证');
 const help=root.querySelector<HTMLButtonElement>('[aria-label="ZIP 校验说明"]');expect(help).not.toBeNull();help!.focus();await settle();
 expect(document.querySelector('[role=tooltip]')?.textContent).toContain('仅核对 ZIP 完整性与清单');
 expect(requests.every(r=>(r.options.method||'GET')==='GET')).toBe(true);
});
it('loads with GET only, default plan off and exactly settings/all scopes; no retention or module selectors',async()=>{
  const root=await mount();
  expect(requests.map(r=>[r.url,r.options.method||'GET'])).toEqual([['/operations/backups','GET']]);
  expect(root.querySelector<HTMLInputElement>('[aria-label="启用自动备份"]')?.checked).toBe(false);
  expect([...root.querySelectorAll<HTMLInputElement>('input[name="backup-scope"]')].map(x=>x.value)).toEqual(['settings','all']);
  expect(root.textContent).toContain('服务器路径');
  const retention=root.querySelector<HTMLButtonElement>('[aria-label="备份保留规则"]')!;retention.focus();await settle();expect(document.querySelector('[role=tooltip]')?.textContent).toContain('最多保留 2 份成功 ZIP');
  expect(root.textContent).toContain('不含笔记正文');
  expect(root.textContent).toContain('不含外部');
  expect(root.querySelector('[aria-label="保留天数"]')).toBeNull();
  expect(root.textContent).toContain('暂无备份记录');
});
it('applies an explicit weekly plan with expected_revision then reads back; never creates a backup',async()=>{
  const root=await mount();
  input(root,'备份目录','/mnt/stella backups');
  const enabled=root.querySelector<HTMLInputElement>('[aria-label="启用自动备份"]')!;enabled.click();
  const frequency=root.querySelector<HTMLSelectElement>('[aria-label="执行频率"]');expect(frequency).not.toBeNull();frequency!.value='weekly';frequency!.dispatchEvent(new Event('change',{bubbles:true}));await nextTick();
  input(root,'执行时间','22:15');input(root,'时区','Asia/Tokyo');
  const weekday=root.querySelector<HTMLSelectElement>('[aria-label="执行星期"]')!;weekday.value='4';weekday.dispatchEvent(new Event('change',{bubbles:true}));
  const scope=root.querySelector<HTMLInputElement>('input[value="all"]')!;scope.click();await nextTick();
  expect(requests).toHaveLength(1);
  const expected={enabled:true,scope:'all',directory:'/mnt/stella backups',frequency:'weekly',time:'22:15',timezone:'Asia/Tokyo',weekday:4,expected_revision:1};
  const saved={...configFixture(),...expected,revision:2};
  responder=async(url)=>url.endsWith('/config')?response(saved):response({...snapshotFixture(),config:saved,next_run:'2026-10-23T13:15:00Z'});
  button(root,'应用目录与计划').click();await settle();
  expect(requests[1]?.url).toBe('/operations/backups/config');expect(requests[1]?.options.method).toBe('PATCH');expect(JSON.parse(requests[1]!.options.body as string)).toEqual(expected);
  expect(requests[2]?.url).toBe('/operations/backups');expect(requests[2]?.options.method).toBe('GET');
  expect(requests.some(r=>r.options.method==='POST')).toBe(false);expect(toasts.map(t=>t.text).join(' ')).toContain('目录与计划已确认');
});
it('retains directory and focused input on a rejected apply, with an actionable permission/space error',async()=>{
  const root=await mount();const directory=input(root,'备份目录','/unwritable/keep-this');directory.focus();
  responder=async()=>response({detail:{message:'目录不可写：权限不足或可用空间不足'}},422);
  button(root,'应用目录与计划').click();await settle();
  expect(directory.value).toBe('/unwritable/keep-this');expect(document.activeElement).toBe(directory);
  expect(root.querySelector('[role="alert"]')?.textContent).toContain('目录不可写');
  expect(requests.filter(r=>r.options.method==='PATCH')).toHaveLength(1);
});
it.each([['settings','备份所有设置'],['all','备份全部数据']] as const)('creates %s only by manual action and uses job readback without enabling the schedule',async(scope,label)=>{
  const root=await mount();
  const job=jobFixture({scope});
  responder=async(_url,options)=>options.method==='POST'?response(job,202):response({...snapshotFixture(),job:{...job,state:'running'}});
  button(root,label).click();button(root,label).click();await settle();
  const posts=requests.filter(r=>r.options.method==='POST');expect(posts).toHaveLength(1);expect(posts[0]?.url).toBe('/operations/backups');expect(JSON.parse(posts[0]!.options.body as string)).toEqual({scope});
  expect(root.textContent).toContain('备份进行中');expect(root.textContent).not.toContain('备份已完成');
  expect(root.querySelector<HTMLInputElement>('[aria-label="启用自动备份"]')?.checked).toBe(false);
  expect(button(root,label).disabled).toBe(true);
});
it('blocks manual writes for an unapplied directory and reports node-local unavailable storage honestly',async()=>{
  const root=await mount();input(root,'备份目录','/other/location');await nextTick();
  expect(button(root,'备份所有设置').disabled).toBe(true);
  expect(root.textContent).toContain('请先应用目录');
  app!.unmount();app=undefined;
  const unavailable={...snapshotFixture(),storage:{node:'fixture-standby',available:false,free_bytes:null,error:'此节点未挂载备份目录'}};
  const second=await mount(async()=>response(unavailable));expect(second.textContent).toContain('fixture-standby');expect(second.textContent).toContain('此节点未挂载备份目录');expect(button(second,'备份全部数据').disabled).toBe(true);
});
it('preserves existing ZIP rows and shows busy409 instead of optimistic backup success',async()=>{
  const record=recordFixture();const root=await mount(async()=>response({...snapshotFixture(),records:[record]}));
  responder=async()=>response({detail:{message:'已有任务正在执行，请刷新状态'}},409);
  button(root,'备份所有设置').click();await settle();expect(root.textContent).toContain(record.filename);expect(root.querySelector('[role="alert"]')?.textContent).toContain('已有任务');expect(root.textContent).not.toContain('备份已完成');
});
it.each(['succeeded','failed','interrupted'] as const)('verifies a ZIP, polls only active jobs, and renders authoritative %s separately from restore',async(finalState)=>{
  const record=recordFixture({id:'zip id/?',verified:false});const root=await mount(async()=>response({...snapshotFixture(),records:[record]}));
  const job=jobFixture({kind:'verify',record_id:record.id});let current:BackupJob={...job,state:'running'};
  responder=async(_url,options)=>options.method==='POST'?response(job,202):response({...snapshotFixture(),records:[{...record,verified:current.state==='succeeded'}],job:current});
  vi.useFakeTimers();button(root,'校验 ZIP').click();await vi.advanceTimersByTimeAsync(0);await nextTick();expect(requests.find(r=>r.options.method==='POST')?.url).toBe('/operations/backups/zip%20id%2F%3F/verify');
  current={...job,state:finalState,error:finalState==='succeeded'?null:'档案校验失败或任务被中断'};await vi.advanceTimersByTimeAsync(2000);await nextTick();
  expect(root.textContent).toContain(finalState==='succeeded'?'ZIP 校验已完成':finalState==='failed'?'ZIP 校验失败':'ZIP 校验已中断');
  expect(root.textContent).not.toContain('恢复已完成');
  const count=requests.length;await vi.advanceTimersByTimeAsync(10000);expect(requests).toHaveLength(count);
});
it.each(['delete','restore'] as const)('%s requires a filename modal confirmation, traps keyboard focus and cancels with no write',async(kind)=>{
  const record=recordFixture();const root=await mount(async()=>response({...snapshotFixture(),records:[record]}));
  const trigger=button(root,kind==='delete'?'删除 ZIP':'恢复设置');trigger.focus();trigger.click();await nextTick();
  const dialog=document.querySelector<HTMLElement>('[role="dialog"]');expect(dialog).not.toBeNull();expect(dialog!.textContent).toContain(record.filename);
  expect(dialog!.getAttribute('aria-modal')).toBe('true');expect(dialog!.contains(document.activeElement)).toBe(true);
  const confirm=button(dialog!,kind==='delete'?'确认删除':'确认恢复设置');expect(confirm.disabled).toBe(true);
  const cancel=button(dialog!,'取消');cancel.focus();cancel.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));expect(dialog!.contains(document.activeElement)).toBe(true);
  dialog!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await nextTick();expect(document.querySelector('[role="dialog"]')).toBeNull();expect(document.activeElement).toBe(trigger);expect(requests).toHaveLength(1);
});
it('restores settings with exact filename confirmation and displays accepted job, never checksum-as-restore',async()=>{
  const record=recordFixture();const root=await mount(async()=>response({...snapshotFixture(),records:[record]}));
  button(root,'恢复设置').click();await nextTick();const dialog=document.querySelector('[role="dialog"]')!;
  expect(dialog.textContent).toContain('保留原笔记正文、附件');input(dialog,'确认 ZIP 文件名',record.filename);await nextTick();
  const job=jobFixture({kind:'restore',record_id:record.id,state:'running'});responder=async(_url,options)=>options.method==='POST'?response(job,202):response({...snapshotFixture(),records:[record],job});
  button(dialog,'确认恢复设置').click();await settle();const post=requests.find(r=>r.options.method==='POST');expect(post?.url).toBe(`/operations/backups/${record.id}/restore`);expect(JSON.parse(post!.options.body as string)).toEqual({confirm:record.filename});expect(root.textContent).toContain('设置恢复进行中');expect(root.textContent).not.toContain('设置恢复已完成');
});
it('deletes only the confirmed owned ZIP and reads exact listing before closing',async()=>{
  const record=recordFixture();const root=await mount(async()=>response({...snapshotFixture(),records:[record]}));button(root,'删除 ZIP').click();await nextTick();const dialog=document.querySelector('[role="dialog"]')!;
  input(dialog,'确认 ZIP 文件名',record.filename);await nextTick();responder=async(_url,options)=>options.method==='DELETE'?response(null,204):response(snapshotFixture());button(dialog,'确认删除').click();await settle();
  const deletion=requests.find(r=>r.options.method==='DELETE');expect(deletion?.url).toBe(`/operations/backups/${record.id}`);expect(JSON.parse(deletion!.options.body as string)).toEqual({confirm:record.filename});expect(requests.at(-1)?.options.method).toBe('GET');expect(document.querySelector('[role="dialog"]')).toBeNull();expect(root.textContent).toContain('暂无备份记录');
});
it('full restore obtains real maintenance_cli instructions from HTTP409 and cannot claim a restored site',async()=>{
  const record=recordFixture({scope:'all',filename:'stella-all.zip'});const root=await mount(async()=>response({...snapshotFixture(),records:[record]}));
  button(root,'离线恢复').click();await nextTick();const dialog=document.querySelector('[role="dialog"]')!;expect(dialog.textContent).toContain('维护模式');input(dialog,'确认 ZIP 文件名',record.filename);await nextTick();
  const command='stella-backup restore --archive /isolated/fixture.zip --target empty-fixture';responder=async()=>response({detail:{code:'maintenance_required',message:'请停止站点写入，并在维护环境执行',command}},409);
  button(dialog,'读取离线恢复指引').click();await settle();expect(document.body.textContent).toContain(command);expect(document.body.textContent).toContain('不会在网页中执行全站恢复');expect(document.body.textContent).not.toContain('设置恢复已完成');expect(requests.filter(r=>r.options.method==='POST')).toHaveLength(1);
});
it('preflights management metadata and dispatches native ZIP download without buffering a Blob',async()=>{
  const record=recordFixture();const root=await mount(async()=>response({...snapshotFixture(),records:[record]}));
  const create=vi.fn(()=> 'blob:must-not-create'),revoke=vi.fn();vi.stubGlobal('URL',class extends URL{static createObjectURL=create;static revokeObjectURL=revoke;});
  let downloaded='',href='';vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function(this:HTMLAnchorElement){downloaded=this.download;href=this.getAttribute('href')!;});
  responder=async()=>new Response(null,{headers:{'Content-Type':'application/zip','Content-Length':'4096','Content-Disposition':`attachment; filename="${record.filename}"`}});
  button(root,'下载 ZIP').click();await settle();expect(requests.at(-1)?.url).toBe(`/operations/backups/${record.id}/download`);expect(requests.at(-1)?.options).toMatchObject({method:'HEAD',credentials:'same-origin',cache:'no-store'});expect(downloaded).toBe(record.filename);expect(href).toBe(`/operations/backups/${record.id}/download`);expect(create).not.toHaveBeenCalled();expect(revoke).not.toHaveBeenCalled();expect(root.textContent).toContain('已交由浏览器下载');expect(root.textContent).not.toContain('下载已完成');
});
it.each(['initial','write'] as const)('403 %s remains visible; explicit GET recovery never replays a mutation',async(mode)=>{
  const forbidden=()=>response({detail:{code:'admin_elevation_required',message:'请先解锁管理权限'}},403);
  const root=await mount(mode==='initial'?async()=>forbidden():undefined);
  if(mode==='write'){input(root,'备份目录','/keep-on-unlock');responder=async()=>forbidden();button(root,'应用目录与计划').click();await settle();}
  const writes=requests.filter(r=>r.options.method!=='GET').length;
  expect(root.textContent).toContain('当前会话无权');expect(elevation.open).toBe(false);expect(root.textContent).not.toContain('解锁管理权限');
  responder=async()=>response(snapshotFixture());button(root,'重新读取状态').click();await settle();expect(requests.filter(r=>r.options.method!=='GET')).toHaveLength(writes);expect(root.textContent).toContain('保存位置与计划');
  if(mode==='write')expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/keep-on-unlock');
});
it('retains newer typed input after a successful save and its late readback',async()=>{
  const root=await mount();input(root,'备份目录','/first-intent');await nextTick();
  let resolve!:(response:Response)=>void;const saved={...configFixture(),directory:'/first-intent',revision:2};
  responder=async(url)=>url.endsWith('/config')?new Promise(r=>{resolve=r;}):response({...snapshotFixture(),config:saved});
  button(root,'应用目录与计划').click();await nextTick();input(root,'备份目录','/newer-intent');resolve(response(saved));await settle();expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/newer-intent');
  expect(root.textContent).toContain('仍有未应用的输入');
});
it('a successful PATCH with failed readback only retries GET and retains the draft',async()=>{
  const root=await mount();input(root,'备份目录','/retained');let saved={...configFixture(),directory:'/retained',revision:2};
  responder=async(url)=>url.endsWith('/config')?response(saved):response({detail:'读取暂时不可用'},503);
  button(root,'应用目录与计划').click();await settle();expect(root.textContent).not.toContain('目录与计划已确认');expect(button(root,'应用目录与计划').disabled).toBe(true);
  responder=async()=>response({...snapshotFixture(),config:saved});button(root,'重新读取状态').click();await settle();expect(requests.filter(r=>r.options.method==='PATCH')).toHaveLength(1);expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/retained');expect(toasts.map(t=>t.text).join(' ')).toContain('目录与计划已确认');
});
it('a revision conflict requires a fresh read and explicit reapply or use-server, never blind PATCH replay',async()=>{
  const root=await mount();input(root,'备份目录','/my-intent');responder=async()=>response({detail:'设置已被其他会话修改'},409);button(root,'应用目录与计划').click();await settle();
  expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/my-intent');
  const remote={...configFixture(),directory:'/other-device',revision:4};responder=async()=>response({...snapshotFixture(),config:remote});button(root,'重新读取状态').click();await settle();
  expect(requests.filter(r=>r.options.method==='PATCH')).toHaveLength(1);expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/my-intent');
  button(root,'使用服务器配置').click();await nextTick();expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/other-device');
});
it('stopping a pending write aborts waiting, preserves intent, and fences late ACK before GET-only recovery',async()=>{
  const root=await mount();input(root,'备份目录','/keep-after-abort');let resolve!:(r:Response)=>void;let signal:AbortSignal|undefined;
  responder=async(_url,options)=>{signal=options.signal as AbortSignal;return new Promise(r=>{resolve=r;});};button(root,'应用目录与计划').click();await nextTick();button(root,'停止等待').click();await nextTick();expect(signal?.aborted).toBe(true);expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/keep-after-abort');
  responder=async()=>response(snapshotFixture());button(root,'重新读取状态').click();await settle();resolve(response({...configFixture(),directory:'/late-ack',revision:2}));await settle();expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/keep-after-abort');expect(requests.filter(r=>r.options.method==='PATCH')).toHaveLength(1);
});
it('an older pending GET cannot replace a configuration write readback',async()=>{
  const root=await mount();let resolve!:(r:Response)=>void;let signal:AbortSignal|undefined;
  responder=async(_url,options)=>{signal=options.signal as AbortSignal;return new Promise(r=>{resolve=r;});};button(root,'刷新备份状态').click();await nextTick();
  input(root,'备份目录','/new-directory');const saved={...configFixture(),directory:'/new-directory',revision:2};responder=async(url)=>url.endsWith('/config')?response(saved):response({...snapshotFixture(),config:saved});button(root,'应用目录与计划').click();await settle();expect(signal?.aborted).toBe(true);resolve(response(snapshotFixture()));await settle();expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/new-directory');
});
it('a DELETE with failed list readback retains filename and offers GET-only recovery inside the modal',async()=>{
  const record=recordFixture();const root=await mount(async()=>response({...snapshotFixture(),records:[record]}));button(root,'删除 ZIP').click();await nextTick();let dialog=document.querySelector('[role="dialog"]')!;input(dialog,'确认 ZIP 文件名',record.filename);await nextTick();
  responder=async(_url,options)=>options.method==='DELETE'?response(null,204):response({detail:'目录读取失败'},503);button(dialog,'确认删除').click();await settle();expect(document.querySelector<HTMLInputElement>('[aria-label="确认 ZIP 文件名"]')?.value).toBe(record.filename);expect(button(dialog,'确认删除').disabled).toBe(true);
  responder=async()=>response(snapshotFixture());button(dialog,'重新读取状态').click();await settle();expect(requests.filter(r=>r.options.method==='DELETE')).toHaveLength(1);expect(document.querySelector('[role="dialog"]')).toBeNull();expect(toasts.map(t=>t.text).join(' ')).toContain('ZIP 删除已确认');
});
it('a failed refresh preserves records but requires successful GET before more writes',async()=>{
  const record=recordFixture();const root=await mount(async()=>response({...snapshotFixture(),records:[record]}));responder=async()=>response({detail:'无法读取当前存储节点'},503);button(root,'刷新备份状态').click();await settle();expect(root.textContent).toContain(record.filename);expect(button(root,'备份所有设置').disabled).toBe(true);expect(button(root,'重新读取状态').disabled).toBe(false);
});
it('settings_restore capability false prevents restore while download remains available',async()=>{
  const root=await mount(async()=>response({...snapshotFixture(),records:[recordFixture()],capabilities:{settings_restore:false,full_restore:'maintenance_cli'}}));expect(button(root,'恢复设置').disabled).toBe(true);expect(button(root,'下载 ZIP').disabled).toBe(false);expect(root.textContent).toContain('此环境暂不提供设置恢复');
});
it('shows archive time, bytes and opt-in checksum details without treating ZIP verification as restore evidence',async()=>{
  const record=recordFixture();const root=await mount(async()=>response({...snapshotFixture(),records:[record]}));expect(root.querySelector('time')?.getAttribute('datetime')).toBe(record.created_at);expect(root.textContent).toContain('4 KiB');expect(root.querySelector('details')?.textContent).toContain(record.sha256);root.querySelector<HTMLButtonElement>('[aria-label="ZIP 校验说明"]')!.focus();await settle();expect(document.querySelector('[role=tooltip]')?.textContent).toContain('校验不等于恢复验证');expect(root.textContent).not.toContain('不代表其他设备的本机设置已同步');document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));root.querySelector<HTMLButtonElement>('[aria-label="备份偏好范围说明"]')!.focus();await settle();expect(document.querySelector('[role=tooltip]')?.textContent).toContain('不代表其他设备的本机设置已同步');
});
it('maintenance instructions keep keyboard focus inside the dialog and Escape remains usable after the form disappears',async()=>{
  const record=recordFixture({scope:'all'});const root=await mount(async()=>response({...snapshotFixture(),records:[record]}));button(root,'离线恢复').focus();button(root,'离线恢复').click();await nextTick();const dialog=document.querySelector<HTMLElement>('[role="dialog"]')!;input(dialog,'确认 ZIP 文件名',record.filename);await nextTick();
  responder=async()=>response({detail:{code:'maintenance_required',message:'进入维护模式',command:'fixture-safe-cli'}},409);button(dialog,'读取离线恢复指引').click();await settle();expect(dialog.contains(document.activeElement)).toBe(true);document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await nextTick();expect(document.querySelector('[role="dialog"]')).toBeNull();expect(document.activeElement).toBe(button(root,'离线恢复'));
});
it('an accepted restore job cannot be replaced by a stale succeeded job readback',async()=>{
  const record=recordFixture();const root=await mount(async()=>response({...snapshotFixture(),records:[record]}));const accepted=jobFixture({kind:'restore',id:'new-restore',record_id:record.id});responder=async(_url,options)=>options.method==='POST'?response(accepted,202):response({...snapshotFixture(),records:[record],job:{...accepted,id:'old-restore',state:'succeeded'}});
  button(root,'恢复设置').click();await nextTick();const dialog=document.querySelector('[role="dialog"]')!;input(dialog,'确认 ZIP 文件名',record.filename);await nextTick();button(dialog,'确认恢复设置').click();await settle();expect(root.textContent).not.toContain('设置恢复已完成');expect(root.textContent).toContain('任务已受理，等待服务器确认进度');expect(button(root,'重新读取状态').disabled).toBe(false);
});
it('an expired401 explains re-login and never replays a privileged configuration write',async()=>{
  const root=await mount();input(root,'备份目录','/keep-on-401');responder=async()=>response({detail:'session expired'},401);button(root,'应用目录与计划').click();await settle();expect(root.querySelector('[role="alert"]')?.textContent).toContain('登录已过期');expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/keep-on-401');expect(requests.filter(r=>r.options.method==='PATCH')).toHaveLength(1);
});
