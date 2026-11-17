import type {Page} from '@playwright/test';
import {createClientPreferencesFixture} from '../../tests/fixtures/clientPreferences';
export async function fixture(page:Page){
 const storage={stella_home_theme:'daybreak',stella_live2d:'off',stella_home_particles:'none'},preferences=createClientPreferencesFixture({storage});
 let ready:boolean|null=false,serviceError=false,sessionFailure=false,locationFailure=false;
 const me={id:'fixture-owner',username:'fixture-owner',display_name:'云曦',is_admin:true,avatar_url:'',home_bg:'/assets/fixture.svg',email:'owner@example.test',email_verified:false};
 const requests:{path:string;method:string}[]=[],unknown:string[]=[],errors:string[]=[];
 const base={remember:true,created_at:'2026-10-21T01:00:00Z',last_seen:'2026-10-21T01:05:00Z',expires_at:'2026-10-22T01:35:00Z',mine:true,owner:'云曦'};
 const current={...base,id:'current',device:'Chromium on Linux',browser_name:'Chrome',os_name:'Linux',current:true,ip:'192.168.3.8',login_origin:'https://stella.example.test'};
 const others=[{...base,id:'other',device:'Unknown-Browser-User-Agent-'.repeat(18),browser_name:'Firefox',os_name:'Android',current:false,ip:'2001:db8:1234:5678:abcd:ef01:2345:6789',ip_location:'地点未知',login_origin:'https://a-very-long-but-valid-stella-entry.example.test:5060'},{...base,id:'legacy',device:'UnrecognisedBrowserWithoutAnySpaces'.repeat(12),current:false,ip:'203.0.113.8',login_origin:null}];
 page.on('pageerror',e=>errors.push(e.message));
 await page.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin!=='ws://127.0.0.1:15386'||u.pathname!=='/ws/notifications'||u.search)unknown.push('WS '+ws.url());ws.close();});
 await page.addInitScript(storage=>{for(const [k,v] of Object.entries(storage))localStorage.setItem(k,v);},storage);
 await page.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method(),ok=(json:unknown,status=200)=>route.fulfill({status,json});
  if(u.origin!=='http://127.0.0.1:15386'){unknown.push(m+' '+req.url());return route.abort();}
  if(m!=='GET'||!/^\/(static|assets)\//.test(p))requests.push({path:p+u.search,method:m});
  const queries:Record<string,string[]>={'/settings':['?section=profile','?section=authentication','?section=services'],'/auth/sessions':['?current_only=true','?page=1&page_size=20&exclude_current=true','?page=21&page_size=1&exclude_current=true'],'/auth/sessions/history':['?page=1&page_size=20']};
  if(u.search&&!(m==='GET'&&queries[p]?.includes(u.search))){unknown.push(m+' '+p+u.search);return ok({detail:'unsupported isolated query'},501);}
  const pref=preferences.respond(m,p+u.search);if(pref)return route.fulfill(pref);
  if(p==='/auth/status'&&m==='GET')return ok({initialized:true,email_enabled:true});
  if((p==='/auth/me'&&m==='GET')||(p==='/auth/refresh'&&m==='POST'))return ok(me);
  if(p==='/auth/email-service'&&m==='GET')return ok(serviceError?{detail:'邮件状态读取失败'}:ready===null?{}:{ready},serviceError?503:200);
  if(p==='/auth/sessions'&&m==='GET')return sessionFailure?ok({detail:'fixture offline'},503):ok(u.searchParams.has('current_only')?[current]:u.searchParams.get('page_size')==='1'?[]:others);
  if(p==='/auth/sessions/history'&&m==='GET')return ok({items:[{...others[0],id:'revoked',state:'revoked'},{...others[1],id:'expired',state:'expired',created_at:'invalid',expires_at:null}],total:2,page:1,page_size:20});
  if(p==='/auth/sessions/legacy/location'&&m==='GET')return locationFailure?ok({detail:'归属地暂时不可用，请稍后重试'},503):ok({ip:'203.0.113.8',ip_location:'测试地区'});
  if(p==='/auth/provider/config'&&m==='GET')return ok({issuer:'https://stella.example.test',discovery_url:'https://stella.example.test/.well-known/openid-configuration',authorization_endpoint:'https://stella.example.test/auth/oidc/authorize',token_endpoint:'https://stella.example.test/auth/oidc/token',userinfo_endpoint:'https://stella.example.test/auth/oidc/userinfo',jwks_uri:'https://stella.example.test/auth/oidc/jwks',clients:[],capabilities:{}});
  if(p==='/admin/email/config'&&m==='GET')return ok({enabled:false,host:'',port:465,username:'',password:'',from_name:''});
  if(p==='/config/access-entries'&&m==='GET')return ok({settings:{enabled:true,public_origin:'https://stella.example.test',private_origin:null,revision:1}});
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
 return {requests,unknown,errors,ready:(v:boolean|null)=>ready=v,serviceError:(v:boolean)=>serviceError=v,failSessions:(v:boolean)=>sessionFailure=v,failLocation:(v:boolean)=>locationFailure=v};
}
