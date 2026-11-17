// Synthetic isolated HTTP responses for the actual built App. No real backend.
export function createRound2WebsiteFixture(){
 const code={enabled:true,css:'/* 活动注释 */body{color:teal}',js:'/* 活动脚本 */window.syntheticWebsite=1',timing:'dom_ready',version:'synthetic-v2'};
 let item:any={id:'owned',name:'合并验收网站',icon:'globe',browser_url:'https://child.example.test/',origin:'https://isolated.example.test',mode:'isolated_proxy',adapter:'generic',target_id:'synthetic-target',enabled:true,background:'solid',access_adapter:'auto',private_address:null,entry_policy:'follow',template_id:null,keep_alive:false,connection:{transport:'proxy',auth_mode:'header',header_name:'Authorization',injection_delivery:'proxy',has_token:true},injection:{active:{...code},draft:{...code,css:'/* 服务器旧独立草稿 */'},previous:{...code,css:'/* 上一版 */'}}};
 let entries:any[]=[],agentHost='agent.example.test';
 let access={revision:4,enabled:true,public_origin:'https://stella.example.test',private_origin:'https://stella.private.test'};
 const summary=()=>({settings:{...access},issuer:'https://identity.example.test',deployed:{public:'https://stella.example.test',private:'https://stella.private.test'},websites:[{id:item.id,name:item.name,mode:item.mode,public_address:item.browser_url,private_address:item.private_address,entry_policy:item.entry_policy}]});
 const check=(b:any)=>({normalized_url:new URL(b.address).href,name_suggestion:item.name,access:{status:'reachable',http_status:200},embedding:{status:'allowed',reason_code:'no_observed_restriction',reason:'合成上游允许嵌入，真实登录仍须另验'},injection:{status:'supported',reason:'合成上游支持代码'},software:{type:'unknown',source:null},help:null,can_save:true,recommended_behavior:b.open_behavior,issues:[]});
 function respond(method:string,path:string,body?:any):{json:any,status?:number}|undefined{
  if(path==='/external-modules'&&method==='GET')return {json:[item]};
  if(path==='/external-modules/owned'&&method==='GET')return {json:item};
  if(path==='/navigation'&&method==='GET')return {json:{entries,legacy_routes:{}}};
  if(path==='/config/public-host'&&method==='GET')return {json:{value:agentHost}};
  if(path==='/config/public-host'&&method==='PUT'){agentHost=body.value;return {json:{value:agentHost}};}
  if(path==='/config/access-entries'&&method==='GET')return {json:summary()};
  if(path==='/config/access-entries/check'&&method==='POST')return {json:{can_apply:true,digest:'a'.repeat(64),checks:[{name:'主站入口',status:'configured',reason:'合成部署配置精确匹配'}],network:{dns:'unknown',tls:'unknown',browser:'unknown'},behavior:'跟随当前入口'}};
  if(path==='/config/access-entries'&&method==='PUT'){access={revision:body.revision+1,enabled:body.enabled,public_origin:body.public_origin,private_origin:body.private_origin};return {json:summary()};}
  if(path==='/website-settings/check'&&method==='POST')return {json:check(body)};
  if(path==='/website-settings/owned'&&method==='PATCH'){
   if(body.connection?.token||body.connection?.clear_token)return {status:422,json:{detail:'此验收禁止凭据变更'}};
   item={...item,name:body.name||item.name,icon:body.icon,browser_url:check(body).normalized_url,keep_alive:body.keep_alive,mode:body.open_behavior==='external'?'link':item.mode};
   for(const f of ['template_id','background','private_address','entry_policy','access_adapter'])if(f in body)item[f]=body[f];
   if(body.connection){const {token,clear_token,...connection}=body.connection;item.connection={...connection,has_token:true};}
   if(body.custom)item.injection={active:{...body.custom,version:'synthetic-v3'},draft:body.preserve_saved_draft?item.injection.draft:{...body.custom},previous:item.injection.active};
   entries=[{id:item.id,visible:body.visible,title:item.name,icon:item.icon}];return {json:{...item,check:check(body)}};
  }
 }
 return {respond,snapshot:()=>JSON.parse(JSON.stringify({item,access,agentHost}))};
}
