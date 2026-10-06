import type {Page} from '@playwright/test';
export async function mock(page:Page, configured=true) {
 const state={enabled:true,configured,elevated:false,expires_at:null,single_user:true,setup_required:!configured};
 const requests:{path:string;method:string;body:any}[]=[];
 const me={id:'mock-owner',username:'demo',display_name:'Mock Owner',is_admin:true,avatar_url:'/avatar.png',home_bg:'',email:'',email_verified:false};
 const unknown:string[]=[];
 let entries:any[]=[];
 let modules:any[]=[];let sequence=0;
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url()),p=url.pathname,method=req.method();
  if(url.origin==='http://127.0.0.1:15173' && (p==='/settings'||p==='/missing-stella-page'||p==='/login'||p==='/'||p.startsWith('/apps/')||p==='/drive'||p==='/gallery'||p.startsWith('/status/')||p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')||p.endsWith('.svg')||p.endsWith('.png')||p.endsWith('.woff2'))) return route.continue();
  const body=req.postDataJSON(); requests.push({path:p,method,body});
  const ok=(json:any)=>route.fulfill({json});
  if(p==='/auth/me'||p==='/auth/refresh')return ok(me);
  if(p==='/auth/security') {if(method==='PUT'){if(!body.password)return route.fulfill({status:403,json:{detail:{code:'admin_password_required'}}});state.enabled=body.enabled;state.elevated=false;}return ok(state);}
  if(p==='/auth/admin/setup'){state.configured=true;state.setup_required=false;return ok(state);}
  if(p==='/auth/admin/unlock'){state.elevated=true;return ok(state);}
  if(p==='/auth/admin/lock'){state.elevated=false;return ok(state);}
  if(p==='/navigation') {if(method==='PUT'&&!state.elevated)return route.fulfill({status:403,json:{detail:{code:state.configured?'admin_elevation_required':'admin_setup_required'}}});if(method==='PUT') entries=body.reset?[]:body.entries;return ok({entries,settings_route:'/settings'});}
  if(p==='/builtin-injections/drive'||p==='/builtin-injections/gallery') {
   if(!state.elevated&&state.enabled)return route.fulfill({status:403,json:{detail:{code:'admin_elevation_required'}}});
   return ok({site:p.split('/').at(-1),source:'preset',base_required:true,active:{enabled:false,css:'',js:'',timing:'dom_ready',csp_policy:'reject',version:'preset-v1',status:'active'},draft:null,previous:null,preset:{css:'/* Mock builtin theme */',js:'/* Mock compatibility */'}});
  }
  if(p==='/integration-presets')return ok({generic:{css:'body { color-scheme: dark; }',js:'/* Mock preset */',readonly:true,status:'injection_loaded_is_not_app_ready'},openlist:{css:'/* Mock OpenList theme */',js:'/* Mock cache repair */',readonly:true,status:'existing_upstream_migration_pending'}});
  if(p==='/integration-targets')return ok([{id:'target1',name:'Mock approved upstream',controlled:true,upstream_url:'http://10.0.0.1:8080/'}]);
  if(p==='/external-modules'){if(method==='POST'){modules.push({...body,id:'demo'+(++sequence),origin:'https://mock-embed.test',injection:{draft:null,active:null,previous:null},capabilities:{injection:body.mode==='isolated_proxy'}});return ok(modules.at(-1));}return ok(modules);}
  if(p.startsWith('/external-modules/')){
   const id=p.split('/')[2];const item=modules.find(x=>x.id===id);
   if(!item)return route.fulfill({status:404,json:{detail:'Module not found'}});
   if(p.endsWith('/launch'))return ok(item.mode==='isolated_proxy'?{mode:item.mode,url:'https://mock-embed.test/__stella/bootstrap',method:'POST',fields:{ticket:'MOCK_SINGLE_USE_TICKET'},expires_in:30}:{mode:item.mode,url:'http://127.0.0.1:15173/mock-site',method:'GET'});
   if(p.endsWith('/check'))return ok({configuration_valid:true,browser_status:'unobservable',reason:'内部状态不可读',ready:false});
   if(p.endsWith('/validate')){item.injection.draft=body;return ok({valid:true,errors:[],draft:body});}
   if(p.endsWith('/apply')){item.injection.previous=item.injection.active;item.injection.active={...item.injection.draft,version:'opaque-'+Date.now()};return ok(item.injection);}
   if(p.endsWith('/rollback')){[item.injection.active,item.injection.previous]=[item.injection.previous,item.injection.active];return ok(item.injection);}
   if(method==='DELETE'){modules=modules.filter(x=>x.id!==id);return route.fulfill({status:204});}
   if(method==='PATCH')Object.assign(item,body);
   return ok(item);
  }
  if(p==='/__stella/bootstrap' && url.hostname==='mock-embed.test')return route.fulfill({contentType:'text/html',body:'<h1>Mock website</h1>'});
  if(p==='/mock-site')return route.fulfill({contentType:'text/html',body:'<h1>Mock website</h1>'});
  if(p==='/auth/sessions')return ok([{id:'mock-session',device:'Mock desktop',current:true,mine:true,created_at:'2026-10-01T00:00:00Z',last_seen:'2026-10-06T00:00:00Z',remember:true}]);
  if(p==='/auth/sessions/history')return ok({items:[],total:0,page:1,page_size:20});
  if(p==='/auth/avatars')return ok([]);
  if(p==='/auth/email-service')return ok({ready:false,configured:false,enabled:false});
  if(p==='/notifications/unread-count')return ok({count:0});
  if(p==='/notifications/'||p==='/notifications')return ok([]);
  if(p==='/operations/backup-health')return ok({timestamp:'2026-10-06T00:00:00Z',status:'verified',checksumverified:true,restoreverified:false,source:'postgres-dump'});
  if(p==='/auth/activity')return ok({ok:true});
  if(p==='/config/public-host'||p==='/config/site-background')return ok({value:''});
  if(p==='/assets/homebg/default-bg-kimono-1920.webp')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"><rect width="100" height="60" fill="#14171f"/></svg>'});
  if(p==='/homebg/')return ok([]);
  if(p==='/homebg/media')return ok({url:'/assets/homebg/default-bg-kimono-1920.webp',status:'ready',variants:{original:'/avatar.png'}});
  if(p==='/admin/email/config'){if(!state.elevated&&state.enabled)return route.fulfill({status:403,json:{detail:{code:'admin_elevation_required'}}});return ok({host:'smtp.mock.test',port:465,username:'mock@example.test',password:'••••••',enabled:false,from_name:'Stella'});}
  if(p==='/drive/connection')return ok({service_url:'http://mock.test:5244/drive/openlist',auth_mode:'manual',has_token:false});
  if(p==='/gallery/connection')return ok({browser_url:'https://mock-gallery.test',auth_mode:'oidc'});
  if(p==='/drive/status'||p==='/gallery/status')return ok({configured:true});
  if(p==='/drive/login-url')return ok({url:'/drive/openlist/'});
  if(p==='/drive/openlist/'||p==='/gallery/connect')return route.fulfill({contentType:'text/html',body:'<h1>Mock service content</h1>'});
  unknown.push(p);return route.fulfill({status:501,json:{detail:'Unmocked endpoint blocked'}});
 });
 return {state,requests,unknown,addModule:(item:any)=>modules.push(item)};
}
