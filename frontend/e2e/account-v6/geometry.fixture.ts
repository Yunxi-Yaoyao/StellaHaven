import {expect,type Page} from '@playwright/test';
import {createClientPreferencesFixture} from '../../tests/fixtures/clientPreferences';
import {mkdirSync} from 'node:fs';
const out=process.env.STELLA_ACCOUNT_OUTPUT||'/root/.hermes/cache/scratch/account-polish-v6/browser';mkdirSync(out,{recursive:true});
export async function fixture(page:Page, long=false){
 const storage={stella_home_theme:'daybreak',stella_live2d:'off',stella_home_particles:'none'};const preferences=createClientPreferencesFixture({storage});
 let me={id:'fixture-owner',username:'fixture-owner',display_name:'云曦',is_admin:true,avatar_url:'',home_bg:'/assets/fixture.svg',email:'owner@example.test',email_verified:false as boolean|undefined};
 if(long)me={...me,display_name:'很长且必须完整可读的昵称'.repeat(5),email:'a-very-long-unbroken-email-local-part-with-full-value@long-subdomain.example.test'};
 let ready:boolean|null=false,serviceError=false,profileFailure=false,sessionFailure=false;let serviceHold:((value:unknown)=>void)|null=null;
 const requests:{path:string;method:string;body:unknown}[]=[],unknown:string[]=[],errors:string[]=[];
 const base={remember:false,created_at:'2026-10-21T01:00:00Z',last_seen:'2026-10-21T01:05:00Z',expires_at:'2026-10-21T01:35:00Z',mine:true,owner:'云曦'};
 const current={...base,id:'current',device:'Chromium',browser_name:'Chrome',os_name:'Linux',current:true,ip:'192.168.3.8',login_origin:'https://stella.example.test'};
 const others=[{...base,id:'other',device:'Android',browser_name:'Firefox',os_name:'Android',current:false,ip:'2001:db8:1234:5678:abcd:ef01:2345:6789',ip_location:'地点未知',login_origin:'https://a-very-long-but-valid-stella-entry.example.test:5060'},{...base,id:'legacy',device:'旧浏览器',current:false,ip:'203.0.113.8',login_origin:null}];
 page.on('pageerror',e=>errors.push(e.message));await page.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin!=='ws://127.0.0.1:15487'||u.pathname!=='/ws/notifications'||u.search)unknown.push('WS '+ws.url());ws.close();});await page.addInitScript(storage=>{for(const [k,v] of Object.entries(storage))localStorage.setItem(k,v);},storage);
 await page.route('**/*',async route=>{const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method();const ok=(json:unknown,status=200)=>route.fulfill({status,json});
  if(u.origin!=='http://127.0.0.1:15487'){unknown.push(m+' '+req.url());return route.abort();}
  if(m!=='GET'||!/^\/(static|assets)\//.test(p))requests.push({path:p+u.search,method:m,body:m==='GET'?null:req.postDataJSON()});
  const allowedQueries:Record<string,string[]>={'/settings':['?section=profile','?section=authentication'],'/auth/sessions':['?current_only=true','?page=1&page_size=20&exclude_current=true','?page=21&page_size=1&exclude_current=true'],'/auth/sessions/history':['?page=1&page_size=20']};
  if(u.search&&!(m==='GET'&&allowedQueries[p]?.includes(u.search))){unknown.push(m+' '+p+u.search);return ok({detail:'unsupported isolated query'},501);}
  const pref=preferences.respond(m,p+u.search);if(pref)return route.fulfill(pref);
  if(process.env.STELLA_OLD_BUILD==='1'&&p==='/auth/security'&&m==='GET')return ok({enabled:false,configured:false,elevated:false,expires_at:null,single_user:true,setup_required:false});
  if(p==='/auth/status'&&m==='GET')return ok({initialized:true,email_enabled:true});
  if((p==='/auth/me'&&m==='GET')||(p==='/auth/refresh'&&m==='POST'))return ok(me);
  if(p==='/auth/me'&&m==='PATCH'){if(profileFailure)return ok({detail:'此值暂时无法保存，请稍后重试。草稿已保留。'},409);const b=req.postDataJSON();me={...me,...b,...(b.email?{email_verified:false}:{})};return ok(me);}
  if(p==='/auth/email-service'&&m==='GET'){if(serviceHold)await new Promise(r=>serviceHold=r);if(serviceError)return ok({detail:'邮件状态读取失败'},503);return ok(ready===null?{}:{ready});}
  if(['/auth/email/send-code','/auth/email/resend'].includes(p)&&m==='POST')return ok({ok:true});
  if(p==='/auth/email/verify'&&m==='POST'){me={...me,email:req.postDataJSON().email,email_verified:true};return ok({ok:true});}
  if(p==='/auth/sessions'&&m==='GET'){if(sessionFailure)return ok({detail:'fixture offline'},503);return ok(u.searchParams.has('current_only')?[current]:u.searchParams.get('page_size')==='1'?[]:others);}
  if(p==='/auth/sessions/history'&&m==='GET')return ok({items:[{...others[0],id:'historic',state:'revoked'}],total:1,page:1,page_size:20});
  if(p==='/auth/provider/config'&&m==='GET')return ok({issuer:'https://stella.example.test',discovery_url:'https://stella.example.test/.well-known/openid-configuration',authorization_endpoint:'https://stella.example.test/auth/oidc/authorize',token_endpoint:'https://stella.example.test/auth/oidc/token',userinfo_endpoint:'https://stella.example.test/auth/oidc/userinfo',jwks_uri:'https://stella.example.test/auth/oidc/jwks',clients:[],capabilities:{}});
  if(p==='/auth/activity'&&m==='POST')return ok({ok:true});
  if(p==='/auth/avatars'&&m==='GET')return ok([]);
  if(p==='/navigation'&&m==='GET')return ok({entries:[],settings_route:'/settings'});
  if(['/external-modules','/notifications','/notifications/'].includes(p)&&m==='GET')return ok([]);
  if(p==='/notifications/unread-count'&&m==='GET')return ok({count:0});
  if(p==='/config/site-background'&&m==='GET')return ok({value:'/assets/fixture.svg'});
  if(p==='/config/public-host'&&m==='GET')return ok({value:''});
  if(p==='/homebg/media'&&m==='GET')return ok({url:'/assets/fixture.svg',status:'ready',poster:null,variants:{original:'/assets/fixture.svg'}});
  if(p.startsWith('/assets/')&&m==='GET')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><path fill="#161b24" d="M0 0h1920v1080H0z"/></svg>'});
  if(m==='GET'&&(req.isNavigationRequest()||p.startsWith('/static/')||['/favicon.ico','/favicon.svg','/avatar.png','/live2dcubismcore.min.js'].includes(p)))return route.continue();
  unknown.push(m+' '+p+u.search);return ok({detail:'unhandled isolated fixture request'},501);
 });
 return {requests,unknown,errors,verification:(v:boolean|undefined)=>{me={...me,email_verified:v};},ready:(v:boolean|null)=>{ready=v;},serviceError:(v:boolean)=>serviceError=v,failProfile:(v:boolean)=>profileFailure=v,failSessions:(v:boolean)=>sessionFailure=v,holdService:()=>{serviceHold=()=>{};},releaseService:()=>{const release=serviceHold;serviceHold=null;release?.({});}};
}
export async function shot(page:Page,label:string){await page.mouse.move(1,1);await page.screenshot({path:`${out}/${label}.png`,animations:'disabled'});}
export async function aligned(page:Page,edit=false){const values=await page.locator('.profile-data-row .profile-value').evaluateAll(nodes=>nodes.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,w:r.width};}));expect(values).toHaveLength(3);for(const v of values){expect(Math.abs(v.x-values[0]!.x)).toBeLessThan(1);expect(Math.abs(v.w-values[0]!.w)).toBeLessThan(1);}if(edit){const widths=await page.locator('.profile-data-row input').evaluateAll(nodes=>nodes.map(e=>e.getBoundingClientRect().width));expect(widths).toHaveLength(3);expect(new Set(widths.map(x=>Math.round(x))).size).toBe(1);}return values;}
