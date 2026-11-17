import type {Plugin} from 'vite';
import {templates} from './fixtures/websiteTemplates.ts';
export function websiteUiHttp():Plugin {
 let modules:any[],requests:any[],entries:any[],token:string,failRead=false,corrupt=false;
 function reset(){token='synthetic-server-only';requests=[];entries=[];failRead=false;corrupt=false;const code={enabled:true,css:'/* 用户注释保留 */ body{color:teal}',js:'/* 原有活动代码 */window.retained=1',timing:'dom_ready',version:'v2'};modules=[{id:'owned',name:'我的网站',icon:'globe',browser_url:'https://child.example.test/',origin:'https://isolated.example.test',mode:'isolated_proxy',adapter:'generic',target_id:'original-target',enabled:true,background:'solid',access_adapter:'auto',private_address:null,entry_policy:'follow',template_id:'user_'+'a'.repeat(32),keep_alive:false,request_policy:{management_prefixes:['/private/admin'],read_post_paths:[],protect_other_writes:true},connection:{transport:'proxy',auth_mode:'header',header_name:'Authorization',injection_delivery:'proxy',has_token:true},injection:{active:code,draft:{...code,css:'/* 未发布独立草稿 */'},previous:{...code,css:'/* 上一版备份 */',version:'v1'}}}];}
 reset();
 const checked=(body:any)=>({normalized_url:new URL(body.address.includes('://')?body.address:'https://'+body.address).href,name_suggestion:'新网站',access:{status:'reachable',http_status:200},embedding:{status:'allowed',reason_code:'no_observed_restriction',reason:'未发现响应策略阻断，浏览器内容及登录仍需验证'},injection:{status:'supported',reason:'当前页面允许加载外观代码'},compatibility:body.address.includes('/confirmed-openlist')?{enabled:true,css:'html[data-bg-mode="image"]{background:transparent}',js:'/* stella:background-ready:v1 */window.__fixtureAppearanceOnly=true;',timing:'document_start'}:null,software:{type:body.address.includes('/confirmed-openlist')?'openlist':body.address.includes('/confirmed-immich')?'immich':'unknown',source:body.address.includes('/confirmed-')?'html:generator':null},help:null,can_save:true,recommended_behavior:body.open_behavior,issues:[]});
 let access={revision:4,enabled:true,public_origin:'https://stella.example.test',private_origin:'https://stella.private.test'},agentHost='agent.example.test';
 const accessSummary=()=>({settings:{...access},issuer:'https://identity.example.test',deployed:{public:'https://stella.example.test',private:'https://stella.private.test'},websites:modules.map(m=>({id:m.id,name:m.name,mode:m.mode,public_address:m.browser_url,private_address:m.private_address,entry_policy:m.entry_policy}))});
 return {name:'isolated-website-http',configureServer(server){server.middlewares.use(async(req,res,next)=>{
  const path=(req.url||'').split('?')[0]!;
  if(!/^\/(?:__website-ui|external-modules|navigation|website-templates|website-settings|config|auth|admin)(?:\/|$)/.test(path))return next();
  const url=new URL(req.url||'','http://127.0.0.1:15189');
  const methods:Record<string,string[]>={'/__website-ui/reset':['POST'],'/__website-ui/state':['GET'],'/config/public-host':['GET','PUT'],'/config/access-entries/check':['POST'],'/config/access-entries':['GET','PUT'],'/auth/sessions':['GET'],'/admin/email/config':['GET'],'/navigation':['GET'],'/external-modules':['GET'],'/website-templates':['GET'],'/website-settings/check':['POST'],'/website-settings':['POST']};
  const allowed=methods[path]||(path.startsWith('/website-settings/')?['PATCH']:path.startsWith('/external-modules/')?['GET','DELETE']:[]);
  if(url.search||!allowed.includes(req.method||'')){res.statusCode=405;res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({detail:'Unknown fixture method/query'}));}
  let raw='';for await(const chunk of req)raw+=chunk;const body=raw?JSON.parse(raw):null;
  const json=(data:any,status=200)=>{res.statusCode=status;res.setHeader('Content-Type','application/json');res.end(JSON.stringify(data));};
  if(path==='/__website-ui/reset'){reset();access={revision:4,enabled:true,public_origin:'https://stella.example.test',private_origin:'https://stella.private.test'};agentHost='agent.example.test';corrupt=!!body?.corrupt;return json({ok:true});}
  if(path==='/__website-ui/state')return json({modules,requests,access,agentHost,tokenUnchanged:token==='synthetic-server-only',templateRecordsUnchanged:true});
  requests.push({path,method:req.method,body});
  if(path==='/config/public-host'){if(req.method==='PUT')agentHost=body.value;return json({ok:true,value:agentHost});}
  if(path==='/config/access-entries/check')return json({can_apply:true,digest:'a'.repeat(64),checks:[{name:'公网主站',status:'configured',reason:'已配置精确入口'}],network:{dns:'unknown',tls:'unknown',browser:'unknown'},behavior:'跟随当前入口'});
  if(path==='/config/access-entries'){if(req.method==='PUT')access={revision:body.revision+1,enabled:body.enabled,public_origin:body.public_origin,private_origin:body.private_origin};return json(accessSummary());}
  if(path==='/auth/sessions')return json([]);
  if(path==='/admin/email/config'&&req.method==='GET')return json({host:'smtp.example.test',port:465,username:'mailer',password:'••••••',from_name:'Stella',enabled:false});
  if(path==='/navigation')return json({entries,legacy_routes:{}});
  if(path==='/external-modules')return json(modules);
  if(path==='/website-templates'){if(req.method!=='GET')return json({detail:'No template writes allowed'},405);return json(templates);}
  if(path==='/website-settings/check')return json(checked(body));
  if(path==='/website-settings'||path.startsWith('/website-settings/')){
   const id=path.split('/')[2]||'created';let item=modules.find(x=>x.id===id);if(!item){item={id,mode:'iframe',adapter:'generic',enabled:true,origin:'https://fresh.example.test'};modules.push(item);}
   const {token:newToken,clear_token,...connection}=body.connection||{};if(newToken)token=newToken;if(clear_token)token='';
   Object.assign(item,{name:body.name||'新网站',icon:body.icon,browser_url:checked(body).normalized_url,keep_alive:body.keep_alive,mode:body.open_behavior==='external'?'link':item.mode});
   for(const field of ['template_id','background','request_policy','private_address','entry_policy','access_adapter'])if(field in body)item[field]=body[field];
   if(body.connection)item.connection={...connection,has_token:!!token};
   if(body.custom)item.injection={draft:body.preserve_saved_draft?item.injection?.draft:{...body.custom},active:{...body.custom,version:'v3'},previous:item.injection?.active||null};
   entries=entries.filter(x=>x.id!==id);entries.push({id,visible:body.visible,title:item.name,icon:item.icon});failRead=corrupt;
   return json({...item,check:checked(body)});
  }
  const item=modules.find(x=>path==='/external-modules/'+x.id);
  if(item){if(req.method==='DELETE'){modules=modules.filter(x=>x!==item);entries=entries.filter(x=>x.id!==item.id);return json(null,204);}if(failRead)return json({...item,connection:{...item.connection,header_name:'wrong'}});return json(item);}
  return json({detail:'Missing fixture module'},404);
 });}};
}
