import {expect,type Page} from '@playwright/test';
import {templates,migratedModules,legacyRoutes} from './websiteTemplates';
export const checked=(address:string,blocked=false)=>({normalized_url:new URL(address.includes('://')?address:'https://'+address).href,name_suggestion:'建议网站名',access:{status:'reachable',http_status:200},embedding:{status:blocked?'blocked':'allowed',reason_code:blocked?'csp_none':'no_observed_restriction',reason:blocked?"CSP frame-ancestors 'none' 禁止嵌入":'未发现响应头限制'},injection:{status:'unsupported',reason:'跨域直连不能修改 DOM'},help:blocked?{title:'额度 Nginx 配置',location:'/etc/nginx/conf.d/quota.conf',instructions:['在额度服务允许 Stella 精确 origin，保留其他 CSP 和 LAN ACL'],external_url:null}:null,can_save:!blocked,recommended_behavior:blocked?'external':'embedded',issues:[]});
export async function fixture(page:Page,options:{failNavigation?:boolean;loseCreateResponse?:boolean;full?:boolean;module?:string;external?:boolean;blockedCheck?:boolean;supported?:boolean;previous?:boolean;savedDraft?:boolean;legacyNavigation?:boolean;legacyNavigationIcon?:string;legacyIcon?:boolean;corruptReadback?:boolean;migrated?:boolean;backgroundHome?:boolean}={}){
 const unknown:string[]=[],errors:string[]=[],consoleErrors:string[]=[],requests:any[]=[];
 page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
 const modules:any[]=[{id:'quota',name:'额度',icon:'globe',browser_url:'https://quota.example.test/',mode:'iframe',adapter:'generic',enabled:true,keep_alive:false,injection:{active:null,draft:null,previous:null}},{id:'second',name:'第二网站',icon:'book',browser_url:'https://second.example.test/',mode:'iframe',adapter:'generic',enabled:true,keep_alive:false}];
 if(options.backgroundHome)modules[0].background='home';
 if(options.previous)modules[0].injection={draft:null,active:{enabled:false,css:'current',js:'',timing:'dom_ready',version:'v2'},previous:{enabled:false,css:'previous',js:'',timing:'dom_ready',version:'v1'}};
 if(options.savedDraft)modules[0].injection={draft:{enabled:false,css:'body{color:blue}',js:'window.savedDraft=true',timing:'dom_ready',version:'draft-v3'},active:{enabled:true,css:'body{color:green}',js:'window.activeGreen=true',timing:'dom_ready',version:'v2'},previous:{enabled:true,css:'body{color:red}',js:'window.activeRed=true',timing:'dom_ready',version:'v1'}};
 if(options.legacyIcon)modules[0].icon='heart';
 let writes=0;
 let entries:any[]=[{id:'quota',title:options.legacyNavigation?'原来配置的显示名':'额度',icon:options.legacyNavigation?(options.legacyNavigationIcon||'book'):options.legacyIcon?'heart':'globe',visible:true}];
 if(options.migrated)modules.push(...migratedModules());
 page.on('pageerror',e=>errors.push(e.message));
 await page.routeWebSocket('**/*',ws=>{if(new URL(ws.url()).origin!=='ws://127.0.0.1:15179'||new URL(ws.url()).pathname!=='/'){unknown.push(ws.url());ws.close();}else ws.send(JSON.stringify({type:'connected'}));});
 await page.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname;
  // Only real Vite files on this isolated loopback origin can pass. No API forwarding.
  if(req.method()==='GET'&&u.origin==='http://127.0.0.1:15179'&&(p==='/tests/website-settings.html'||p==='/avatar.png'||p.startsWith('/tests/')||p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')))return route.continue();
  if(u.origin!=='http://127.0.0.1:15179'){unknown.push(req.url());return route.abort('blockedbyclient');}
  const body=req.postData()?req.postDataJSON():null; requests.push({path:p,method:req.method(),body});
  if(p==='/navigation'&&['GET','PUT'].includes(req.method())){if(options.failNavigation&&writes){options.failNavigation=false;return route.fulfill({status:503,json:{detail:'fixture refresh failed'}});}if(body)entries=body.entries;return route.fulfill({json:{entries,legacy_routes:options.migrated?legacyRoutes:{}}});}
  if(req.method()==='GET'&&['/auth/avatars','/auth/sessions','/homebg/'].includes(p))return route.fulfill({json:[]});
  if(p==='/config/public-host'&&req.method()==='GET')return route.fulfill({json:{value:''}});
  if(p==='/auth/email-service'&&req.method()==='GET')return route.fulfill({json:{ready:false}});
  if(p==='/auth/security'&&req.method()==='GET')return route.fulfill({json:{enabled:true,configured:true,elevated:true,setup_required:false,single_user:true}});
  if(p==='/website-templates'&&req.method()==='GET')return route.fulfill({json:templates});
  if(p==='/external-modules'&&req.method()==='GET')return route.fulfill({json:modules});
  if(p==='/website-settings/check'&&req.method()==='POST'){const result=checked(body.address,body.address.includes('blocked')||options.blockedCheck);if(body.open_behavior==='external'&&!body.custom_enabled)result.can_save=true;if(options.supported)result.injection={status:'supported',reason:'测试上游支持隔离注入'};return route.fulfill({json:result});}
  if(p==='/external-modules/quota/injection/rollback'&&req.method()==='POST'){[modules[0].injection.active,modules[0].injection.previous]=[modules[0].injection.previous,modules[0].injection.active];return route.fulfill({json:modules[0].injection});}
  if(p==='/external-modules/quota/launch'&&req.method()==='POST')return route.fulfill({json:{mode:'iframe',method:'GET',url:'http://127.0.0.1:15179/fixture-frame'}});
  if(p==='/owned-bg.svg'&&req.method()==='GET')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="#769"/></svg>'});
  if(p==='/fixture-frame'&&req.method()==='GET')return route.fulfill({contentType:'text/html',body:'<!doctype html><style>body{background:rgb(245,245,245);color:rgb(20,20,20)}</style><h1>Actual isolated iframe content</h1>'});
  if((p==='/website-settings'&&req.method()==='POST')||(req.method()==='PATCH'&&modules.some(x=>p==='/website-settings/'+x.id))){
   if(body.address.includes('race'))return route.fulfill({status:422,json:{detail:{code:'website_check_failed',check:checked(body.address,true)}}});
   writes++; const id=p.split('/')[2]||'created'; let item=modules.find(x=>x.id===id);
   if(!item){item={id,adapter:'generic',enabled:true};modules.push(item);}
   Object.assign(item,{name:body.name||'建议网站名',icon:body.icon,browser_url:checked(body.address).normalized_url,mode:body.open_behavior==='external'?'link':body.connection?.transport==='proxy'?'isolated_proxy':item.mode==='isolated_proxy'&&!body.connection?'isolated_proxy':'iframe',keep_alive:body.keep_alive});
   if(body.connection){const {token,clear_token,...connection}=body.connection;item.connection={...connection,has_token:clear_token?false:!!token||!!item.connection?.has_token};}
   for(const field of ['template_id','background','request_policy'])if(field in body)item[field]=body[field];
   if(body.custom)item.injection={draft:{...body.custom},active:{...body.custom,version:'fixture-active-v2'},previous:item.injection?.active||null};
   entries=entries.filter(x=>x.id!==id);entries.push({id,title:item.name,icon:item.icon,visible:body.visible});
   if(options.loseCreateResponse){options.loseCreateResponse=false;return route.abort('failed');}
   return route.fulfill({json:{...item,check:checked(body.address)}});
  }
  const id=p.split('/')[2];const item=modules.find(x=>p==='/external-modules/'+x.id);if(item&&['GET','DELETE'].includes(req.method())){if(req.method()==='DELETE'){modules.splice(modules.indexOf(item),1);entries=entries.filter(x=>x.id!==id);return route.fulfill({status:204});}return route.fulfill({json:options.corruptReadback&&writes?{...item,injection:{...item.injection,draft:{...item.injection.draft,css:'corrupt'}}}:item});}
  if(['/external-modules/second','/external-modules/created',...Object.values(legacyRoutes).map(id=>'/external-modules/'+id)].includes(p)&&req.method()==='GET')return route.fulfill({status:404,json:{detail:'Module missing'}});
  unknown.push(req.url());return route.abort('blockedbyclient');
 });
 await page.goto('/tests/website-settings.html'+'?'+(options.full?'full=1':'')+(options.module?'&module='+options.module:'')+(options.external?'&external=1':''));
 await expect(page.getByRole('button',{name:'编辑 '+(options.legacyNavigation?'原来配置的显示名':'额度'),exact:true})).toBeVisible();
 return {unknown,errors,consoleErrors,requests,modules};
}