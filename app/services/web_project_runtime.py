"""Credential-free opaque-sandbox webpage resource grants.

Origins are operator registered. No arbitrary upstream proxy or execution on
Stella's origin. Raw script access is bounded by a revocable project/session grant.
"""
import hashlib,json,re,secrets,time
from urllib.parse import urlsplit
from fastapi import HTTPException
from app.models.config import AppConfig
from app.services import web_projects as projects
from app.services.integrations_sessions import session_alive
from app.services.entry_registry import records,parent_context
from app.services.notes_tools import lock_key
from app.services.notes_lifecycle import rollback_on_error
TTL=900
# Expiry denies all resource/write access; only the original live SID can renew
# a retained row for another 900s. Grace is not resource authorization.
RENEW_GRACE=300
RENEW_AFTER=840

@rollback_on_error
def renew(db,owner,root,sid,source,cap,epoch):
 from app.models.user import AuthSession,User
 if not re.fullmatch(r'[A-Za-z0-9_-]{43}',cap):raise HTTPException(403,'网页运行授权无效')
 project,_=projects.owned(db,owner,root)
 # Same ordering as state writes/reset. Never take the admin-security lock:
 # logout can hold it while waiting for SID. All row snapshots are refreshed.
 projects.lock_workspace(db,project.workspace_id)
 db.expire_all()
 projects.owned(db,owner,root)
 lock_key(db,projects.state_key(root))
 state_row=db.query(AppConfig).filter_by(key=projects.state_key(root)).populate_existing().with_for_update().first()
 session=db.query(AuthSession).filter_by(id=sid).populate_existing().with_for_update().first()
 user=db.query(User).filter_by(id=owner).populate_existing().with_for_update().first()
 row=db.query(AppConfig).filter_by(key=key(cap)).populate_existing().with_for_update().first()
 # Revalidate after EVERY blocking lock; a removed/replaced row is never inserted.
 if not session or not user or session.user_id!=owner or not row or not session_alive(db,str(sid)):
  raise HTTPException(403,'网页续期授权已失效，请保留本地进度后重新打开')
 grant=json.loads(row.value);now=time.time();target=grant['target'];deployed_grant_destination(source,target)
 if (grant['owner']!=str(owner) or grant['root']!=str(root) or grant['sid']!=str(sid)
     or grant['source']!=source or grant['target']!=target or grant['expires']+RENEW_GRACE<=now):
  raise HTTPException(403,'网页续期授权不匹配或已超过恢复期限')
 state=json.loads(state_row.value) if state_row else projects.initial()
 if grant['epoch']!=epoch or state['epoch']!=epoch:raise HTTPException(409,'网页运行状态已重置')
 grant['expires']=now+TTL
 row.value=json.dumps(grant);db.commit()
 return {'capability':cap,'epoch':epoch,'expires_in':TTL,'renew_after':RENEW_AFTER}

def key(cap):return 'wp-grant:'+hashlib.sha256(cap.encode()).hexdigest()[:55]

def destination(source):
 from app.services.access_entries import lane as selection_lane
 lane=selection_lane(source);r=records().get('web-project-runtime',{})
 if lane not in r:raise HTTPException(503,'网页执行入口尚未配置')
 if r[lane] in records()['stella'].values():raise HTTPException(503,'网页执行入口不能与主站同源')
 return r[lane]

@rollback_on_error
def launch(db,owner,root,sid,source):
 info=projects.manifest(db,owner,root)
 if not info['entry']:raise HTTPException(409,'网页入口文件已不存在，请重新选择')
 if not session_alive(db,str(sid)):raise HTTPException(401,'会话已失效')
 target=destination(source);state=projects.read_state(db,owner,root);cap=secrets.token_urlsafe(32)
 lock_key(db,'wp-runtime-grants')
 # Lock/refresh before pruning: an in-flight renewal may have extended expiry.
 rows=db.query(AppConfig).filter(AppConfig.key.like('wp-grant:%')).populate_existing().with_for_update().all()
 now=time.time();live=0
 for row in rows:
  data=json.loads(row.value)
  if data['expires']+RENEW_GRACE<=now or (data['sid']==str(sid) and data['root']==str(root)):db.delete(row)
  else:live+=1
 if live>=512:raise HTTPException(429,'网页运行实例过多')
 grant={'owner':str(owner),'root':str(root),'sid':str(sid),'source':source,'target':target,'epoch':state['epoch'],'expires':now+TTL}
 db.add(AppConfig(key=key(cap),value=json.dumps(grant)));db.commit()
 from urllib.parse import quote
 return {'url':target+'/p/'+cap+'/'+quote(info['entry'],safe='/'),'capability':cap,'source_origin':source,'target_origin':target,'state':state,'expires_in':TTL}

def deployed_grant_destination(source,target):
 # Selection affects NEW launches only. An issued capability remains bound to
 # its exact source/target while those deployment capabilities still exist.
 source_lane=parent_context(source);topology=records();pair=topology.get('web-project-runtime',{})
 if target not in {pair.get('public'),pair.get(source_lane)} or target in topology['stella'].values():
  raise HTTPException(403,'网页运行入口已不在部署登记中')
 return target

def authorize(db,cap,target=None,*,source=None):
 if not re.fullmatch(r'[A-Za-z0-9_-]{43}',cap):raise HTTPException(403,'网页运行授权无效')
 row=db.get(AppConfig,key(cap));grant=json.loads(row.value) if row else None
 if (target is None and source is None) or not grant or grant['expires']<=time.time() or (target is not None and grant['target']!=target) or (source is not None and grant['source']!=source) or not session_alive(db,grant['sid']):raise HTTPException(403,'网页运行授权已失效，请重新打开')
 owner=projects.uid(grant['owner']);root=projects.uid(grant['root'])
 state=projects.read_state(db,owner,root)
 if state['epoch']!=grant['epoch']:raise HTTPException(403,'网页运行状态已重置')
 deployed_grant_destination(grant['source'],grant['target'])
 return grant,state

def adapter(grant,state,cap):
 payload=json.dumps({'cap':cap,'source':grant['source'],'data':state['data']},ensure_ascii=True).replace('<','\\u003c')
 return ('''(()=>{'use strict';const init='''+payload+''';let data=Object.assign(Object.create(null),init.data),sequence=0;
const notify=()=>{parent.postMessage({type:'stella-project-storage',capability:init.cap,id:++sequence,data:{...data}},init.source);};
const put=(key,value)=>{const next={...data,[String(key)]:String(value)};if(Object.keys(next).length>1000||new TextEncoder().encode(JSON.stringify(next)).length>1048576)throw new DOMException('Project storage quota exceeded','QuotaExceededError');data=Object.assign(Object.create(null),next);notify();};
const methods={getItem:key=>Object.prototype.hasOwnProperty.call(data,String(key))?data[String(key)]:null,setItem:put,removeItem:key=>{delete data[String(key)];notify();},clear:()=>{data=Object.create(null);notify();},key:index=>Object.keys(data)[Number(index)]??null};
const storage=new Proxy(Object.create(null),{get:(_,p)=>p==='length'?Object.keys(data).length:p===Symbol.toStringTag?'Storage':Object.prototype.hasOwnProperty.call(methods,p)?methods[p]:data[p],set:(_,p,v)=>{put(p,v);return true;},deleteProperty:(_,p)=>{methods.removeItem(p);return true;},ownKeys:()=>Object.keys(data),getOwnPropertyDescriptor:(_,p)=>Object.prototype.hasOwnProperty.call(data,p)?{value:data[p],enumerable:true,configurable:true,writable:true}:undefined,defineProperty:(_,p,d)=>{if(!('value'in d))return false;put(p,d.value);return true;}});
Object.defineProperty(window,'localStorage',{get:()=>storage,configurable:false});
parent.postMessage({type:'stella-project-ready',capability:init.cap},init.source);
})();''').encode()

def resource(db,cap,target,path):
 grant,state=authorize(db,cap,target)
 if any(p in {'','..','.'} for p in path.split('/')) or '\\' in path:raise HTTPException(400,'非法项目路径')
 headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','Access-Control-Allow-Origin':'*','Cross-Origin-Resource-Policy':'cross-origin','Content-Security-Policy':f"sandbox allow-scripts; frame-ancestors {grant['source']}; base-uri 'none'; form-action 'none'"}
 if path=='__stella_storage.js':return adapter(grant,state,cap),'text/javascript; charset=utf-8',headers
 data,mime=projects.read_file(db,projects.uid(grant['owner']),projects.uid(grant['root']),path)
 if mime=='text/html':
  # Inspect only the inert document prologue, never reserialize owner HTML.
  # A later explicit head may follow a script; a textual head may be a comment.
  # Keep BOM/doctype before the bootstrap so standards mode is unchanged.
  from html.parser import HTMLParser
  script=f'<script src="{target}/p/{cap}/__stella_storage.js"></script>'
  source=data.decode('utf-8')
  bom=1 if source.startswith('\ufeff') else 0
  prologue=source[bom:]
  lines=[0]+[match.end() for match in re.finditer('\n',prologue)]
  class BoundaryFound(Exception):pass
  class Prologue(HTMLParser):
   offset=len(prologue)
   def position(self):
    line,column=self.getpos()
    return lines[line-1]+column
   def stop(self,extra=0):
    self.offset=self.position()+extra
    raise BoundaryFound
   def handle_starttag(self,tag,attrs):
    if tag=='head':
     opening=self.get_starttag_text()
     assert opening is not None
     self.stop(len(opening))
    if tag!='html':self.stop()
   handle_startendtag=handle_starttag
   def handle_endtag(self,tag):self.stop()
   def handle_data(self,data):
    whitespace=len(data)-len(data.lstrip(' \t\r\n\f'))
    if whitespace<len(data):self.stop(whitespace)
   def handle_comment(self,data):
    # HTMLParser can emit an EOF-terminated comment. Appending inside it
    # would hide the bootstrap, so insert before that unfinished token.
    start=self.position()
    if prologue.startswith('<!--',start):
     if not (prologue.startswith(('>','->'),start+4) or re.compile(r'--!?>').search(prologue,start+4)):self.stop()
    elif prologue.find('>',start)<0:self.stop()
   def handle_decl(self,decl):
    if not re.match(r'doctype(?:[ \t\r\n\f]|$)',decl,re.I):self.stop()
   def handle_pi(self,data):self.stop()
   def unknown_decl(self,data):self.stop()
   def handle_entityref(self,name):self.stop()
   def handle_charref(self,name):self.stop()
  parser=Prologue(convert_charrefs=False)
  try:
   parser.feed(prologue)
   parser.close()
  except BoundaryFound:pass
  offset=bom+parser.offset
  data=(source[:offset]+script+source[offset:]).encode('utf-8')
  headers['Content-Security-Policy']=(f"sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' https: {target}; style-src 'unsafe-inline' https: {target}; img-src data: blob: https: {target}; font-src data: https: {target}; media-src blob: https: {target}; connect-src https: {target}; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri {target}; form-action 'none'; frame-ancestors {grant['source']}")
 return data,mime+('; charset=utf-8' if mime.startswith('text/') else ''),headers
