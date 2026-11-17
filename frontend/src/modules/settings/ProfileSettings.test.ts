import { createApp, nextTick, h, ref, type App } from "vue";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock('../home/auth',async()=>{const {reactive,ref}=await import('vue');return {currentAvatar:ref('/default-avatar.png'),auth:reactive({me:{id:'fixture-owner'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false})};});
import {auth} from '../home/auth';
beforeEach(()=>Object.assign(auth,{me:{id:'fixture-owner'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false}));
import ProfileSettings, {type ProfileRecord} from "./ProfileSettings.vue";
import {toasts} from "../../composables/useToast";
let app: App;
afterEach(() => {
  toasts.splice(0);
  app?.unmount();
  document.body.innerHTML = "";
});
const original = {
  id: "fixture-owner",
  display_name: "云曦",
  username: "owner",
  email: "owner@example.test",
  email_verified: true,
  avatar_url: "",
};
async function mount(request: typeof fetch,initialProfile:ProfileRecord=original) {
  const root = document.createElement("div");
  document.body.append(root);
  app = createApp(ProfileSettings, {
    initialProfile,
    avatars: [],
    request,
  });
  app.mount(root);
  await openProfileEditors(root);
  return root;
}
async function openProfileEditors(root:HTMLElement){await nextTick();root.querySelector<HTMLButtonElement>('[aria-label="编辑昵称"]')?.click();root.querySelector<HTMLButtonElement>('[aria-label="编辑用户名"]')?.click();await nextTick();}
async function flush() {
  await new Promise((r) => setTimeout(r, 50));
  await nextTick();
}
function edit(root: HTMLElement, selector: string, value: string) {
  const el = (root.querySelector<HTMLInputElement>(selector) || document.querySelector<HTMLInputElement>(selector))!;
  el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  return el;
}
function button(root: HTMLElement, text: string) {
  if(text==='取消')return root.querySelector<HTMLButtonElement>('.profile-email-actions button')!;
  if(text==='修改邮箱')return root.querySelector<HTMLButtonElement>('[aria-label="编辑邮箱"]')!;
  return [...root.querySelectorAll("button"),...document.querySelectorAll<HTMLButtonElement>(".email-state-popover button")].find(
    (b) => b.textContent?.trim() === text,
  )!;
}
it('replaces the email display in place and saves without SMTP or duplicate explanatory status',async()=>{
 let saved={...original};const paths:string[]=[];
 const root=await mount((async(path:string,init?:RequestInit)=>{paths.push(path);if(path==='/auth/email-service')return new Response('{"ready":false}');if(init?.method==='PATCH')saved={...saved,...JSON.parse(init.body as string),email_verified:false};return new Response(JSON.stringify(saved));}) as typeof fetch);
 await flush();
 expect(root.querySelector('button[aria-label="邮件服务不可用"] svg')).not.toBeNull();
 button(root,'修改邮箱').click();await flush();
 expect(root.querySelector('.profile-email-address')).toBeNull();
 expect(root.querySelector('#profile-email-draft')).not.toBeNull();
 expect(root.querySelector('#profile-email-error')).toBeNull();
 expect(button(root,'发送验证码')).toBeUndefined();
 expect(root.querySelector('button[aria-label="邮件服务不可用"]')).not.toBeNull();
 edit(root,'#profile-email-draft','offline@example.test');await nextTick();button(root,'保存邮箱').click();await flush();
 expect(root.querySelector('.profile-email-address')?.textContent).toBe('offline@example.test');
 expect(root.querySelector('button[aria-label="邮件服务不可用"] svg')).not.toBeNull();
 expect(root.textContent).not.toContain('邮箱已保存，尚未验证');
 expect(paths.filter(p=>p.includes('send')||p.includes('verify'))).toEqual([]);
});
it("confirms name by GET after PATCH and keeps editable draft on failed readback", async () => {
  let fail = true;
  const request = vi.fn(async (_path: string, init?: RequestInit) => {
    if (init?.method === "PATCH")
      return new Response(
        JSON.stringify({ ...original, display_name: "新名称" }),
      );
    if (fail) throw Error("读取失败");
    return new Response(
      JSON.stringify({ ...original, display_name: "新名称" }),
    );
  }) as unknown as typeof fetch;
  const root = await mount(request);
  edit(root, "#profile-name", "新名称");
  await nextTick();
  button(root, "保存昵称").click();
  await flush();
  expect(root.querySelector<HTMLInputElement>("#profile-name")?.value).toBe(
    "新名称",
  );
  expect(root.querySelector("[role=alert]")?.textContent).toContain("读取失败");
  expect(root.textContent).not.toContain("名称已保存");
  fail = false;
  button(root, "保存昵称").click();
  await flush();
  expect(toasts.at(-1)?.text).toBe("昵称已保存");
  expect(root.querySelector(".profile-success")).toBeNull();
  expect(request).toHaveBeenLastCalledWith("/auth/me", expect.objectContaining({signal:expect.any(AbortSignal)}));
  expect(
    root.querySelector<HTMLInputElement>("#profile-username")?.readOnly,
  ).toBe(false);
  expect(root.querySelector("input[type=password]")).toBeNull();
});
it("retains email editor on failed readback; never claims unverified address is verified", async () => {
  let readFail = true;
  let saved = { ...original };
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === "PATCH") {
      saved = {
        ...saved,
        ...JSON.parse(init.body as string),
        email_verified: false,
      };
      return new Response(JSON.stringify(saved));
    }
    if (path === "/auth/me") {
      if (readFail) throw Error("邮箱读取失败");
      return new Response(JSON.stringify(saved));
    }
    return new Response(JSON.stringify({ ready: true }));
  }) as unknown as typeof fetch;
  const root = await mount(request);
  button(root, "修改邮箱").click();
  await flush();
  edit(root, "#profile-email-draft", "new@example.test");
  await nextTick();
  button(root, "保存邮箱").click();
  await flush();
  expect(
    root.querySelector<HTMLInputElement>("#profile-email-draft")?.value,
  ).toBe("new@example.test");
  expect(root.textContent).toContain("邮箱读取失败");
  readFail = false;
  button(root, "保存邮箱").click();
  await flush();
  expect(root.querySelector("#profile-email-draft")).toBeNull();
  expect(root.querySelector('button[aria-label="邮箱待验证"]')).not.toBeNull();
  expect(root.textContent).toContain("new@example.test");
});
it("verifies email with existing send/resend/verify endpoints and reads it back", async () => {
  let saved = { ...original };
  const paths: string[] = [];
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    paths.push(path);
    if (path === "/auth/email/verify")
      saved = {
        ...saved,
        email: JSON.parse(init?.body as string).email,
        email_verified: true,
      };
    return new Response(
      JSON.stringify(path === "/auth/me" ? saved : { ready: true }),
    );
  }) as unknown as typeof fetch;
  const root = await mount(request);
  button(root, "修改邮箱").click();
  await flush();
  edit(root, "#profile-email-draft", "verified@example.test");
  await nextTick();
  root.querySelector<HTMLButtonElement>(".email-state-trigger")!.click();await flush();
  button(root, "发送验证码").click();
  await flush();
  expect(document.body.textContent).toContain("verified@example.test");
  expect(document.querySelector("#profile-email-code")).not.toBeNull();
  expect(document.activeElement).toBe(document.querySelector('#profile-email-code'));
  button(root, "重新发送").click();
  await flush();
  edit(root, "#profile-email-code", "123456");
  await nextTick();
  button(root, "完成验证").click();
  await flush();
  expect(paths).toEqual([
    "/auth/email-service",
    "/auth/email-service",
    "/auth/email-service",
    "/auth/email/send-code",
    "/auth/email-service",
    "/auth/email/resend",
    "/auth/email/verify",
    "/auth/me",
  ]);
  expect(toasts.at(-1)?.text).toBe("邮箱已验证");
});
it("does not submit while composing and preserves a newer name draft during readback", async () => {
  let release!: (r: Response) => void;
  const request = vi.fn(async (_path: string, init?: RequestInit) =>
    init?.method === "PATCH"
      ? new Response("{}")
      : new Promise<Response>((r) => (release = r)),
  ) as unknown as typeof fetch;
  const root = await mount(request);
  const field = edit(root, "#profile-name", "候选名");
  field.dispatchEvent(new CompositionEvent("compositionstart"));
  await nextTick();
  root
    .querySelector("form")!
    .dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
  await flush();
  expect(vi.mocked(request).mock.calls.filter(([path])=>path!=='/auth/email-service')).toEqual([]);
  field.dispatchEvent(new CompositionEvent("compositionend"));
  await nextTick();
  button(root, "保存昵称").click();
  await flush();
  edit(root, "#profile-name", "更新的草稿");
  release(
    new Response(JSON.stringify({ ...original, display_name: "候选名" })),
  );
  await flush();
  expect(field.value).toBe("更新的草稿");
  expect(button(root, "保存昵称").disabled).toBe(false);
});
it("exposes existing avatar editor and readback-confirmed recent avatars", async () => {
  let edited = false;
  const request = vi.fn(
    async (_path: string, init?: RequestInit) =>
      new Response(
        JSON.stringify({
          ...original,
          avatar_url:
            init?.method === "POST" ? "ignored" : "/fixture-avatar.svg",
        }),
      ),
  ) as unknown as typeof fetch;
  const root = document.createElement("div");
  document.body.append(root);
  app = createApp(ProfileSettings, {
    initialProfile: original,
    avatars: ["/fixture-avatar.svg"],
    request,
    onEditAvatar: () => {
      edited = true;
    },
  });
  app.mount(root);
  await nextTick();
  button(root, "更换头像").click();
  expect(edited).toBe(true);
  root
    .querySelector<HTMLButtonElement>('[aria-label="使用最近头像 1"]')!
    .click();
  await flush();
  expect(
    root
      .querySelector<HTMLImageElement>('[alt="当前头像"]')
      ?.getAttribute("src"),
  ).toBe("/fixture-avatar.svg");
  expect(toasts.at(-1)?.text).toBe("头像已更新");
});
it("retries only confirmation after email verification succeeds but GET fails, without reusing the one-time code", async () => {
  let fail = false,
    verifies = 0;
  const request = vi.fn(async (path: string) => {
    if (path === "/auth/email/verify") {
      verifies++;
      fail = true;
      return new Response("{}");
    }
    if (path === "/auth/me") {
      if (fail) {
        fail = false;
        throw Error("读取失败");
      }
      return new Response(
        JSON.stringify({
          ...original,
          email: "once@example.test",
          email_verified: true,
        }),
      );
    }
    return new Response(JSON.stringify({ ready: true }));
  }) as unknown as typeof fetch;
  const root = await mount(request);
  button(root, "修改邮箱").click();
  await flush();
  edit(root, "#profile-email-draft", "once@example.test");
  await nextTick();
  root.querySelector<HTMLButtonElement>(".email-state-trigger")!.click();await flush();
  button(root, "发送验证码").click();
  await flush();
  edit(root, "#profile-email-code", "123456");
  await nextTick();
  button(root, "完成验证").click();
  await flush();
  expect(root.textContent).toContain("读取失败");
  button(root, "完成验证").click();
  await flush();
  expect(verifies).toBe(1);
  expect(toasts.at(-1)?.text).toBe("邮箱已验证");
});
it('refreshes clean account fields without overwriting a newer draft',async()=>{const account=ref({...original});let dirty=false;const request=(async()=>new Response('{"ready":true}')) as typeof fetch;const root=document.createElement('div');document.body.append(root);app=createApp({render:()=>h(ProfileSettings,{initialProfile:account.value,avatars:[],request,onDirty:(v:boolean)=>dirty=v})});app.mount(root);await openProfileEditors(root);account.value={...account.value,email:'refreshed@example.test'};await flush();expect(dirty).toBe(false);button(root,'修改邮箱').click();await flush();expect(root.querySelector<HTMLInputElement>('#profile-email-draft')?.value).toBe('refreshed@example.test');edit(root,'#profile-name','更新草稿');account.value={...account.value,display_name:'别处改名'};await flush();expect(root.querySelector<HTMLInputElement>('#profile-name')?.value).toBe('更新草稿');expect(dirty).toBe(true);});
it('uses the actual account avatar fallback instead of replacing it with initials',async()=>{const root=await mount(vi.fn() as unknown as typeof fetch);expect(root.querySelector<HTMLImageElement>('[alt="当前头像"]')?.getAttribute('src')).toBe('/default-avatar.png');});
it('retains the email draft while its inline editor is collapsed',async()=>{const root=await mount((async()=>new Response('{"ready":true}')) as typeof fetch);button(root,'修改邮箱').click();await flush();edit(root,'#profile-email-draft','draft@example.test');await nextTick();button(root,'取消').click();await flush();button(root,'修改邮箱').click();await flush();expect(root.querySelector<HTMLInputElement>('#profile-email-draft')?.value).toBe('draft@example.test');});
it('edits username separately, readback-only retries and no nickname shadow',async()=>{
 let saved={...original},fail=true,writes=0;
 const root=await mount((async(path:string,init?:RequestInit)=>{
  if(path==='/auth/email-service')return new Response('{"ready":false}');
  if(init?.method==='PATCH'){writes++;saved={...saved,...JSON.parse(init.body as string)};return new Response('{}');}
  if(fail)throw Error('读取失败');return new Response(JSON.stringify(saved));
 }) as typeof fetch);
 expect(root.querySelector<HTMLInputElement>('#profile-username')?.readOnly).toBe(false);
 edit(root,'#profile-username','next-owner');await nextTick();button(root,'保存用户名').click();await flush();[...document.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='确认修改')!.click();await flush();
 expect(toasts).toHaveLength(0);expect(root.querySelector<HTMLInputElement>('#profile-username')?.value).toBe('next-owner');
 fail=false;button(root,'保存用户名').click();await flush();expect(writes).toBe(1);expect(toasts.at(-1)?.text).toBe('用户名已保存');
 expect(root.querySelector<HTMLInputElement>('#profile-name')?.value).toBe(original.display_name);
});
it('accepts a strip-only username no-op on a legacy same-nickname account',async()=>{
 const legacy={...original,display_name:original.username};
 const root=await mount((async(path:string)=>new Response(JSON.stringify(path==='/auth/email-service'?{ready:false}:legacy))) as typeof fetch,legacy);
 edit(root,'#profile-username','  owner  ');await nextTick();button(root,'保存用户名').click();await flush();
 expect(root.querySelector('#profile-username-error')).toBeNull();expect(toasts.at(-1)?.text).toBe('用户名已保存');expect(root.textContent).toContain('owner');
});
it('has one email cancel and bounded independent value/actions regions' ,async()=>{
 const root=await mount((async()=>new Response('{"ready":false}')) as typeof fetch);await flush();button(root,'修改邮箱').click();await flush();
 expect(button(root,'保存邮箱')).toBeDefined();expect(button(root,'取消')).toBeDefined();expect(root.textContent).not.toContain('收起');
 expect(root.querySelectorAll('#profile-email-draft')).toHaveLength(1);
 expect(root.querySelector('.profile-email-value #profile-email-draft')).not.toBeNull();
 expect(root.querySelectorAll('.profile-email-actions button')).toHaveLength(2);
});
it('uses one click-operated mail status entry, refreshed SMTP and no implicit send',async()=>{
 let ready=false;const calls:string[]=[];
 const root=await mount((async(path:string)=>{calls.push(path);return new Response(JSON.stringify(path==='/auth/email-service'?{ready}:original));}) as typeof fetch);
 await flush();
 const state=()=>root.querySelector<HTMLButtonElement>('.email-state-trigger')!;
 expect(state()?.getAttribute('aria-label')).toBe('邮件服务不可用');
 expect(root.querySelectorAll('.email-state-trigger')).toHaveLength(1);
 state().click();await flush();
 expect(document.querySelector('[role=dialog]')?.textContent).toContain('前往站点与服务');
 expect(calls.filter(p=>p.includes('send'))).toEqual([]);
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await nextTick();
 ready=true;state().click();await flush();
 expect(state().getAttribute('aria-label')).toBe('邮箱已验证');
 expect(document.querySelector('[role=dialog]')?.textContent).toContain('已通过验证');
 expect(button(document.body,'发送验证码')).toBeUndefined();
 expect(calls.filter(p=>p==='/auth/email-service')).toHaveLength(3);
});
it('verifies the saved address, not a retained collapsed draft',async()=>{
 const bodies:string[]=[];
 const root=await mount((async(path:string,init?:RequestInit)=>{if(path==='/auth/email/send-code')bodies.push(JSON.parse(init?.body as string).email);return new Response('{"ready":true}');}) as typeof fetch,{...original,email_verified:false});
 await flush();button(root,'修改邮箱').click();await flush();edit(root,'#profile-email-draft','retained@example.test');await nextTick();button(root,'取消').click();await nextTick();
 root.querySelector<HTMLButtonElement>('.email-state-trigger')!.click();await flush();button(root,'发送验证码').click();await flush();
 expect(bodies).toEqual(['owner@example.test']);
});
it('separates pending draft from verified saved address and rejects malformed drafts without writes',async()=>{
 const writes:string[]=[];const root=await mount((async(path:string,init?:RequestInit)=>{if(init?.method)writes.push(path);return new Response('{"ready":true}');}) as typeof fetch);await flush();
 button(root,'修改邮箱').click();await nextTick();expect(root.querySelector('.email-state-trigger')?.getAttribute('aria-label')).toBe('邮箱已验证');
 edit(root,'#profile-email-draft','bad-address');await nextTick();expect(root.querySelector('.email-state-trigger')?.getAttribute('aria-label')).toBe('新邮箱待保存或验证');
 root.querySelector('form.profile-email-row')!.dispatchEvent(new Event('submit',{cancelable:true}));await flush();
 expect(writes).toEqual([]);expect(root.textContent).toContain('请填写有效邮箱地址');
});
it('refreshes service before sending and blocks stale ready without losing input',async()=>{
 let ready=true;const writes:string[]=[];const root=await mount((async(path:string,init?:RequestInit)=>{if(init?.method)writes.push(path);return new Response(JSON.stringify({ready}));}) as typeof fetch,{...original,email_verified:false});await flush();
 button(root,'修改邮箱').click();await nextTick();edit(root,'#profile-email-draft','pending@example.test');await nextTick();root.querySelector<HTMLButtonElement>('.email-state-trigger')!.click();await flush();ready=false;
 button(root,'发送验证码').click();button(root,'发送验证码').click();await flush();expect(writes).toEqual([]);expect(root.querySelector<HTMLInputElement>('#profile-email-draft')?.value).toBe('pending@example.test');expect(root.textContent).toContain('邮件服务不可用');
});
it('resets old verification code when the target address changes',async()=>{
 const root=await mount((async()=>new Response('{"ready":true}')) as typeof fetch,{...original,email_verified:false});await flush();button(root,'修改邮箱').click();await nextTick();root.querySelector<HTMLButtonElement>('.email-state-trigger')!.click();await flush();button(root,'发送验证码').click();await flush();edit(root,'#profile-email-code','123456');await nextTick();edit(root,'#profile-email-draft','other@example.test');await nextTick();expect(document.querySelector('#profile-email-code')).toBeNull();expect(button(root,'发送验证码')).toBeDefined();
});
it('shows loading and read failures separately while preserving drafts; recovery refreshes status',async()=>{
 let fail=true;let release!:(value:Response)=>void;const root=await mount((async()=>new Promise<Response>(r=>release=r)) as typeof fetch);expect(root.querySelector('.email-state-trigger')?.getAttribute('aria-label')).toBe('正在读取邮件服务');
 release(new Response('{"ready":true}'));await flush();expect(root.querySelector('.email-state-trigger')?.getAttribute('aria-label')).toBe('邮箱已验证');
 app.unmount();
 const next=await mount((async()=>{if(fail)throw Error('服务离线');return new Response('{"ready":true}');}) as typeof fetch);await flush();button(next,'修改邮箱').click();await flush();edit(next,'#profile-email-draft','keep@example.test');await nextTick();expect(next.querySelector('.email-state-trigger')?.getAttribute('aria-label')).toBe('邮件服务读取失败');expect(next.textContent).toContain('仍可编辑和保存邮箱');fail=false;button(next,'重试读取').click();await flush();expect(next.querySelector<HTMLInputElement>('#profile-email-draft')?.value).toBe('keep@example.test');expect(next.querySelector('.email-state-trigger')?.getAttribute('aria-label')).toBe('新邮箱待保存或验证');
});
it('updates clean username after an email readback without clobbering its dirty draft',async()=>{
 const saved={...original,email:'fresh@example.test',email_verified:false,username:'server-renamed'};
 const root=await mount((async(path:string)=>new Response(JSON.stringify(path==='/auth/email-service'?{ready:true}:saved))) as typeof fetch);await flush();button(root,'修改邮箱').click();await nextTick();edit(root,'#profile-email-draft','fresh@example.test');await nextTick();button(root,'保存邮箱').click();await flush();expect(root.querySelector<HTMLInputElement>('#profile-username')?.value).toBe('server-renamed');
});
it('blocks email save/send/verify during IME composition and double send is single-shot',async()=>{
 let sends=0;let release!:(value:Response)=>void;const writes:string[]=[];
 const root=await mount((async(path:string,init?:RequestInit)=>{if(init?.method)writes.push(path);if(path==='/auth/email/send-code'){sends++;return new Promise<Response>(r=>release=r);}return new Response('{"ready":true}');}) as typeof fetch,{...original,email_verified:false});await flush();button(root,'修改邮箱').click();await nextTick();
 const field=edit(root,'#profile-email-draft','ime@example.test');field.dispatchEvent(new CompositionEvent('compositionstart'));await nextTick();root.querySelector('form.profile-email-row')!.dispatchEvent(new Event('submit',{cancelable:true}));root.querySelector<HTMLButtonElement>('.email-state-trigger')!.click();await flush();button(root,'发送验证码').click();await flush();expect(writes).toEqual([]);
 field.dispatchEvent(new CompositionEvent('compositionend'));await nextTick();button(root,'发送验证码').click();button(root,'发送验证码').click();await flush();expect(sends).toBe(1);release(new Response('{}'));await flush();
 const code=edit(root,'#profile-email-code','123456');code.dispatchEvent(new CompositionEvent('compositionstart'));await nextTick();button(root,'完成验证').click();await flush();expect(writes).toEqual(['/auth/email/send-code']);
});
it.each(['owner','session','epoch','suspended','closing','unmount'] as const)('drops late email send across %s fence',async kind=>{
 let release!:(value:Response)=>void;const root=await mount((async(path:string)=>path==='/auth/email/send-code'?new Promise<Response>(r=>release=r):new Response('{"ready":true}')) as typeof fetch,{...original,email_verified:false});await flush();root.querySelector<HTMLButtonElement>('.email-state-trigger')!.click();await flush();button(root,'发送验证码').click();await flush();
 if(kind==='owner')auth.me={...auth.me!,id:'other'};if(kind==='session')auth.sessionGeneration++;if(kind==='epoch')auth.requestEpoch++;if(kind==='suspended')auth.suspended=true;if(kind==='closing')auth.sessionClosing=true;if(kind==='unmount')app.unmount();release(new Response('{}'));await flush();expect(toasts).toHaveLength(0);expect(document.querySelector('#profile-email-code')).toBeNull();expect(document.querySelector('.email-state-popover')).toBeNull();
});
it('does not offer a draft code under the saved address after cancel, and retains dirty username',async()=>{
 const root=await mount((async(path:string)=>new Response(JSON.stringify(path==='/auth/email-service'?{ready:true}:{...original,email:'draft@example.test',email_verified:false,username:'server-value'}))) as typeof fetch,{...original,email_verified:false});await flush();
 edit(root,'#profile-username','my-unsaved-login');button(root,'修改邮箱').click();await nextTick();edit(root,'#profile-email-draft','draft@example.test');await nextTick();root.querySelector<HTMLButtonElement>('.email-state-trigger')!.click();await flush();button(root,'发送验证码').click();await flush();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));await nextTick();button(root,'取消').click();await nextTick();root.querySelector<HTMLButtonElement>('.email-state-trigger')!.click();await flush();expect(document.querySelector('#profile-email-code')).toBeNull();expect(button(root,'发送验证码')).toBeDefined();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));await nextTick();button(root,'修改邮箱').click();await nextTick();button(root,'保存邮箱').click();await flush();expect(root.querySelector<HTMLInputElement>('#profile-username')?.value).toBe('my-unsaved-login');
});
it('can confirm an already received code while SMTP is unavailable, without another send',async()=>{
 let ready=true;const writes:string[]=[];const root=await mount((async(path:string,init?:RequestInit)=>{if(init?.method)writes.push(path);return new Response(JSON.stringify(path==='/auth/me'?{...original,email_verified:true}:{ready}));}) as typeof fetch,{...original,email_verified:false});await flush();root.querySelector<HTMLButtonElement>('.email-state-trigger')!.click();await flush();button(root,'发送验证码').click();await flush();edit(root,'#profile-email-code','123456');await nextTick();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));await nextTick();ready=false;root.querySelector<HTMLButtonElement>('.email-state-trigger')!.click();await flush();expect(document.querySelector<HTMLInputElement>('#profile-email-code')?.value).toBe('123456');button(root,'完成验证').click();await flush();expect(writes).toEqual(['/auth/email/send-code','/auth/email/verify']);expect(toasts.at(-1)?.text).toBe('邮箱已验证');
});
it('never treats a missing verification flag as verified',async()=>{
 const root=await mount((async()=>new Response('{"ready":true}')) as typeof fetch,{...original,email_verified:undefined});await flush();expect(root.querySelector('.email-state-trigger')?.getAttribute('aria-label')).toBe('邮箱状态待确认');root.querySelector<HTMLButtonElement>('.email-state-trigger')!.click();await flush();expect(document.querySelector('[role=dialog]')?.textContent).toContain('邮箱验证状态尚未确认');expect(button(root,'发送验证码')).toBeUndefined();
});
it('does not announce verification until readback contains boolean true',async()=>{
 let confirmed=false,verifies=0;const root=await mount((async(path:string)=>{if(path==='/auth/email/verify')verifies++;return new Response(JSON.stringify(path==='/auth/me'?{...original,email_verified:confirmed?true:'false'}:{ready:true}));}) as typeof fetch,{...original,email_verified:false});await flush();root.querySelector<HTMLButtonElement>('.email-state-trigger')!.click();await flush();button(root,'发送验证码').click();await flush();edit(root,'#profile-email-code','123456');await nextTick();button(root,'完成验证').click();await flush();expect(toasts.some(t=>t.text==='邮箱已验证')).toBe(false);expect(root.textContent).toContain('邮箱尚未确认');confirmed=true;button(root,'完成验证').click();await flush();expect(verifies).toBe(1);expect(toasts.at(-1)?.text).toBe('邮箱已验证');
});
it('disables save when an opened name editor is unchanged',async()=>{const root=await mount(vi.fn() as unknown as typeof fetch);expect(button(root,'保存昵称').disabled).toBe(true);});
it.each(['owner','session','epoch','suspended','closing','unmount'] as const)('drops late profile success across %s fence',async kind=>{
 let release!:(r:Response)=>void;let confirms=0;
 const request=vi.fn(async(_path:string,init?:RequestInit)=>init?.method==='PATCH'?new Response('{}'):new Promise<Response>(r=>release=r)) as unknown as typeof fetch;
 const root=document.createElement('div');document.body.append(root);app=createApp(ProfileSettings,{initialProfile:original,avatars:[],request,onConfirmed:()=>confirms++});app.mount(root);await openProfileEditors(root);
 edit(root,'#profile-name','迟到名称');await nextTick();button(root,'保存昵称').click();await flush();
 if(kind==='owner')auth.me={...auth.me!,id:'different'};if(kind==='session')auth.sessionGeneration++;if(kind==='epoch')auth.requestEpoch++;if(kind==='suspended')auth.suspended=true;if(kind==='closing')auth.sessionClosing=true;if(kind==='unmount')app.unmount();
 release(new Response(JSON.stringify({...original,display_name:'迟到名称'})));await flush();expect(confirms).toBe(0);expect(toasts).toHaveLength(0);expect(root.textContent).not.toContain('名称已保存');
});
