import { test, expect } from '@playwright/test';
import {createHash} from 'node:crypto';
import {scopeFixture} from './notes-delete-scope-fixture';
import {createClientPreferencesFixture} from '../tests/fixtures/clientPreferences';
const ROOT='http://127.0.0.1:15185';
const ws='11111111-1111-4111-8111-111111111111', id='22222222-2222-4222-8222-222222222222';

export async function fixture(page:any,title='随手记',options:{empty?:boolean;content?:string;ancestor?:boolean}={}) {
 const clientPreferences=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_list_fold:'1',stella_note_edit_mode:'markdown'},allowWrite:true});
 const doc:any={id,title,workspace_id:ws,parent_id:null,content:'# 清爽阅读\n\n第一段正文，保持舒适字号。\n\n## 第二节\n\n'+('这是实际组件渲染的长文。\n\n'.repeat(60)),updated_at:'2026-10-15T00:00:00Z',created_at:'2026-10-14T00:00:00Z',has_draft:false,is_favorite:false,status:'published'};
 if(options.content)doc.content=options.content;
 const parent={...doc,id:'33333333-3333-4333-8333-333333333333',title:'祖先路径',content:''};if(options.ancestor)doc.parent_id=parent.id;
 const clientPreferenceRequests:any[]=[];
 const calls:any[]=[];const errors:string[]=[];const state={failure:0,empty:!!options.empty};
 const preferences:any={revision:0,delete_action:'trash',ask_before_delete:true,font_size:16,line_height:1.8,read_width:800,code_line_numbers:false,code_wrap:true,directory_sort:'updated',hidden_folders:[]};
 const trash:any[]=[];const drafts:any[]=[];const deletedReads:string[]=[];const deletedReadConsole:string[]=[];
 const scopes=scopeFixture(()=>state.empty?[]:[doc],()=>trash);
 page.on('pageerror',(e:any)=>errors.push(e.message));page.on('console',(m:any)=>{
  if(m.type()!=='error')return;
  // The deletion contract verifies absence with one GET -> 404. Keep this
  // expected, exact-target browser diagnostic separate; all others still fail.
  if(deletedReads.length&&m.location().url===ROOT+`/documents/${id}`&&m.text()==='Failed to load resource: the server responded with a status of 404 (Not Found)')deletedReadConsole.push(m.text());
  else errors.push(m.text());
 });
 await page.routeWebSocket('**/*',(socket:any)=>{
  const u=new URL(socket.url());
  if(u.origin!==ROOT.replace('http:','ws:')||![`/ws/${id}`,`/ws/list/${ws}`,'/ws/notifications',...(options.ancestor?[`/ws/${parent.id}`]:[])].includes(u.pathname))throw new Error('Unknown fixture socket '+socket.url());
  socket.onMessage((raw:string)=>{
   const message=JSON.parse(raw);
   if(u.pathname!==`/ws/${id}`||message.type!=='draft')return;
   if(typeof message.request_id!=='string'||!message.request_id||typeof message.content!=='string')throw new Error('Malformed draft request');
   if(state.failure){socket.close({code:1011});return;}
   const receipt={type:'draft_ack',request_id:message.request_id,draft_updated_at:new Date().toISOString(),content_hash:createHash('sha256').update(message.content,'utf8').digest('hex'),base_updated_at:doc.updated_at};
   drafts.push({message,receipt});socket.send(JSON.stringify(receipt));
  });
 });
 await page.route('**/*',async(r:any)=>{
  const q=r.request(),u=new URL(q.url()),p=u.pathname;
  if(u.origin===ROOT&&(p==='/notes'||p==='/'||['/settings','/status','/drive','/gallery','/apps/fixture-external'].includes(p)||p.startsWith('/src/')||p.startsWith('/static/')||p.startsWith('/@')||p.startsWith('/node_modules/')||/\.(svg|woff2|png)$/.test(p)))return r.continue();
  if(q.method()==='GET'&&['https://ipinfo.io/json','https://api.ip.sb/geoip'].includes(u.href))return r.fulfill({json:{ip:'192.0.2.1',region:'Fixture',country:'ZZ'}});
  // Account preference traffic is infrastructure, not a document save.
  if(u.origin===ROOT){const preference=clientPreferences.respond(q.method(),p+u.search,q.method()==='PUT'?q.postDataJSON():undefined);if(preference){clientPreferenceRequests.push({method:q.method(),body:q.postDataJSON(),...preference});return r.fulfill(preference);}}
  calls.push({p,method:q.method(),body:q.postData()});const ok=(json:any)=>r.fulfill({json});
  if(u.origin!==ROOT)throw new Error('Unexpected external request '+q.url());
  if(p==='/auth/status'&&q.method()==='GET')return ok({initialized:true});
  if(p==='/auth/me'||p==='/auth/refresh')return ok({id:'fixture-owner',username:'fixture',is_admin:true});
  if(p==='/auth/security')return ok({enabled:true,configured:true,elevated:false,single_user:true,setup_required:false});
  if(p==='/navigation')return ok({entries:[],legacy_routes:{drive:'fixture-drive',gallery:'fixture-gallery'}});
  if(p==='/external-modules')return ok(['drive','gallery','external'].map(name=>({id:'fixture-'+name,name,icon:'globe',mode:'iframe',adapter:'generic',browser_url:ROOT+'/fixture-frame/'+name,enabled:true})));
  if(p.startsWith('/fixture-frame/'))return r.fulfill({contentType:'text/html',body:'<!doctype html><html><body style="margin:0;background:#14171f;color:white"><h1>Explicit offline website fixture</h1><p>'+p+'</p><div style="height:1800px"></div><button>Frame bottom</button></body></html>'});
  if(/^\/external-modules\/fixture-[a-z]+\/launch$/.test(p))return ok({url:ROOT+'/fixture-frame/'+p.split('/')[2],method:'GET'});
  if(p==='/website-settings/check')return ok({embedding:{status:'allowed'}});
  if(p==='/component-installs')return ok([]);
  if(p==='/nodes/')return ok([]);
  if(p==='/nodes/host')return ok({installed:true});
  if(p==='/nodes/map-topology')return ok({nodes:[],links:[]});
  if(p==='/assets/homebg/default-bg-kimono-1920.webp')return r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="1920" height="1080" fill="#243344"/></svg>'});
  if(p==='/homebg/media')return ok({source:'',poster:''});
  if(p==='/workspaces/')return ok([{id:ws,name:'笔记本',user_id:'fixture-owner'}]);
  if(p==='/documents/'&&q.method()==='GET')return ok(state.empty?[]:options.ancestor?[parent,{...doc,content:undefined}]:[{...doc,content:undefined}]);
  if(p==='/documents/'&&q.method()==='POST'){Object.assign(doc,q.postDataJSON());state.empty=false;return ok(doc);}
  if(p==='/documents/trash'&&q.method()==='GET')return ok(trash);
  if(p==='/documents/delete-preview'&&q.method()==='POST')return ok(scopes.preview(q.postDataJSON()));
  if(options.ancestor&&p===`/documents/${parent.id}`)return ok(parent);
  if(options.ancestor&&p===`/documents/${parent.id}/backlinks`)return ok([]);
  if([`/documents/${id}`,`/documents/${id}/permanent`].includes(p)&&q.method()==='DELETE'){
   const permanent=p.endsWith('/permanent');
   if(!scopes.valid(u.searchParams.get('scope_token'),{workspace_id:ws,doc_id:id,mode:permanent?'permanent':'trash',cascade:u.searchParams.get('cascade')==='true'}))return r.fulfill({status:409,json:{detail:{code:'delete_scope_changed'}}});
   if(!permanent)trash.push({...doc});else trash.splice(0);
   state.empty=true;return r.fulfill({status:204});
  }
  if(p===`/documents/${id}`){if(state.empty){deletedReads.push(q.method());return r.fulfill({status:404,json:{detail:'not found'}});}if(q.method()==='PUT'){if(state.failure)return r.fulfill({status:state.failure,json:{detail:'Injected save failure'}});Object.assign(doc,q.postDataJSON(),{updated_at:'2026-10-15T01:00:00Z'});}return ok(doc);}
  if(q.method()==='GET'&&((p===`/web-projects/workspace/${ws}`&&!u.search)||(p==='/detached-sources'&&u.search===`?workspace_id=${ws}`)))return ok([]);
  if(p==='/notes-preferences'){if(q.method()==='PATCH')Object.assign(preferences,q.postDataJSON(),{revision:preferences.revision+1});return ok(preferences);}
  if(p===`/notes-tools/templates/${ws}`||p===`/notes-tools/templates/${ws}/initialize`)return ok({root_id:null,items:[],recent_ids:[]});
  if(p==='/document-versions/')return ok([]);
  if(p==='/notifications/unread-count')return ok({count:0});
  if(p==='/config/home')return ok({value:JSON.stringify({live2d:false})});
  if(['/config/public-host','/config/site-background'].includes(p))return ok({value:''});
  if(p==='/auth/activity')return ok({ok:true});
  if(p==='/auth/email-service')return ok({ready:false});
  if(p==='/auth/sessions/history')return ok({items:[],total:0,page:1,page_size:20});
  if(['/tags/','/doc-tags/','/attachments/','/document-links/','/documents/recent','/auth/sessions','/auth/avatars','/homebg/',`/documents/${id}/backlinks`].includes(p))return ok([]);
  throw new Error('Unexpected fixture request '+q.method()+' '+p);
 });
 await page.addInitScript(({ws}:any)=>{if(sessionStorage.getItem('notes-fixture'))return;sessionStorage.setItem('notes-fixture','1');localStorage.clear();localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_bootstrap',JSON.stringify({userId:'fixture-owner',workspaceId:ws}));localStorage.setItem('stella_list_fold','1');localStorage.setItem('stella_note_edit_mode','markdown');},{ws});
 await page.goto(options.ancestor?`/notes?doc=${id}`:'/notes');if(!options.empty)await expect(page.locator('.preview h1')).toBeVisible();else await expect(page.locator('.blank')).toContainText('新建');
 return {doc,calls,errors,state,drafts,trash,deletedReads,deletedReadConsole,clientPreferenceRequests,preferences};
}
