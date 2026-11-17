"""Owner-scoped webpage project files on existing Documents/PG blob storage.

Raw project sources never pass through Markdown conversion. Runtime execution is
handled separately; this module provides transactional import/state/copy services.
"""
import io,json,hashlib,mimetypes,posixpath
from pathlib import PurePosixPath
from uuid import UUID,uuid4
from fastapi import HTTPException
from app.models.config import AppConfig
from app.models.document import Document
from app.models.workspace import Workspace
from app.models.attachment import Attachment
from app.services.notes_lifecycle import lock_workspace,locked_tree,rollback_on_error
from app.services.notes_tools import lock_key
from app.services import blob_store
from app.services.notes_zip import parse_archive,decode_body,MAX_FILE
from app.services.html_note_conversion import pack
TEXT={'.html','.htm','.css','.js','.mjs','.json','.txt','.md','.svg','.xml','.csv'}
PREFIX='web-project:'

def uid(value):
 try:return UUID(str(value))
 except (ValueError,TypeError):raise HTTPException(404,'网页项目不存在') from None

def owned(db,owner,root):
 root=uid(root);doc=db.query(Document).filter_by(id=root).populate_existing().first()
 ws=db.query(Workspace).filter_by(id=doc.workspace_id).populate_existing().first() if doc else None
 row=db.query(AppConfig).filter_by(key=PREFIX+str(root)).populate_existing().first()
 if not doc or doc.deleted_at is not None or not ws or ws.user_id!=owner or not row:raise HTTPException(404,'网页项目不存在')
 try:meta=json.loads(row.value)
 except (ValueError,TypeError):raise HTTPException(409,'网页项目元数据损坏，请检查此项目') from None
 if not isinstance(meta,dict):raise HTTPException(409,'网页项目元数据损坏，请检查此项目')
 if meta.get('owner_id')!=str(owner):raise HTTPException(404,'网页项目不存在')
 if not isinstance(meta.get('files'),dict) or 'entry_file_id' not in meta:raise HTTPException(409,'网页项目元数据损坏，请检查此项目')
 return doc,meta

def new_doc(db,workspace,parent,title,content='',folder=False):
 d=Document(id=uuid4(),workspace_id=workspace,parent_id=parent,title=title,file_path='/web-projects/'+str(uuid4()),content=content,content_hash=hashlib.sha256(content.encode()).hexdigest(),is_folder=folder,visibility='private',status='published')
 db.add(d);db.flush();return d

def attach(db,doc,name,data,mime,*,project_owner=None):
 att=Attachment(id=uuid4(),doc_id=doc.id,owner_id=project_owner,filename=name,mime=mime,size=len(data));db.add(att)
 blob_store.put(db,'attachments/'+str(att.id),io.BytesIO(data),mime,max_bytes=MAX_FILE)
 return att

def unpack(data,filename):
 if not blob_store.enabled():raise HTTPException(409,'网页项目需要数据库附件存储模式')
 if len(data)>MAX_FILE:raise HTTPException(413,'网页项目导入最多25 MiB')
 if filename.lower().endswith('.zip'):
  _,files,_,_=parse_archive(data,require_notes=False);original=data
 elif filename.lower().endswith(('.html','.htm')):
  name=PurePosixPath(filename).name
  files={name:data};original=pack(files);parse_archive(original,require_notes=False)
 else:raise HTTPException(415,'请选择HTML文件或网页ZIP')
 return files,original

@rollback_on_error
def create(db,owner,workspace,parent,import_id,data,filename,entry):
 workspace=uid(workspace);parent=uid(parent) if parent else None;import_id=uid(import_id)
 files,original=unpack(data,filename)
 if any(p.split('/')[0]=='__stella_storage.js' for p in files):raise HTTPException(409,'归档使用了保留的网页运行文件名')
 if entry not in files or PurePosixPath(entry).suffix.lower() not in {'.html','.htm'}:raise HTTPException(400,'请选择归档内HTML入口')
 decoded={p:decode_body(b,'auto') for p,b in files.items() if PurePosixPath(p).suffix.lower() in TEXT}
 if any(len(v.encode())>5*1024*1024 for v in decoded.values()):raise HTTPException(413,'单个源码文件超过5 MiB')
 ws=lock_workspace(db,workspace)
 if ws.user_id!=owner:raise HTTPException(404,'工作区不存在')
 if parent:
  d=db.get(Document,parent)
  if not d or d.workspace_id!=workspace or d.deleted_at is not None:raise HTTPException(404,'目标目录不存在')
 key=hashlib.sha256(f'web-project-import:{owner}:{import_id}'.encode()).hexdigest();lock_key(db,key)
 digest=hashlib.sha256(data).hexdigest();scope=[str(workspace),str(parent),entry,digest]
 prior=db.get(AppConfig,key)
 if prior:
  r=json.loads(prior.value)
  if r['scope']!=scope:raise HTTPException(409,'导入标识已经用于其他内容')
  owned(db,owner,r['id']);db.commit();return {'id':uid(r['id']),'reused':True}
 root=new_doc(db,workspace,parent,PurePosixPath(filename).stem,folder=True)
 nodes={'':root};directories=set()
 for p in files:
  parts=p.split('/')
  for n in range(1,len(parts)):directories.add('/'.join(parts[:n]))
 for p in sorted(directories,key=lambda x:(x.count('/'),x)):
  nodes[p]=new_doc(db,workspace,nodes[posixpath.dirname(p)].id,posixpath.basename(p),folder=True)
 records={}
 for p,b in sorted(files.items()):
  mime=mimetypes.guess_type(p)[0] or 'application/octet-stream'
  doc=new_doc(db,workspace,nodes[posixpath.dirname(p)].id,posixpath.basename(p),decoded.get(p,''));nodes[p]=doc
  rec={'original_path':p,'kind':'text' if p in decoded else 'binary','mime':mime}
  if p not in decoded:
   att=attach(db,doc,posixpath.basename(p),b,mime,project_owner=owner);rec['attachment_id']=str(att.id)
   doc.content=f'[原文件](/attachments/{att.id})';doc.content_hash=hashlib.sha256(doc.content.encode()).hexdigest()
  records[str(doc.id)]=rec
 source=attach(db,root,'original.zip',original,'application/zip',project_owner=owner);root.content=f'[原始网页归档](/attachments/{source.id})';root.content_hash=hashlib.sha256(root.content.encode()).hexdigest()
 meta={'owner_id':str(owner),'entry_file_id':str(nodes[entry].id),'files':records,'original_attachment':str(source.id)}
 db.add(AppConfig(key=PREFIX+str(root.id),value=json.dumps(meta)))
 db.add(AppConfig(key=key,value=json.dumps({'scope':scope,'id':str(root.id)})))
 result={'id':root.id,'reused':False};db.commit();return result

def identities(db,workspace):
 """Authoritative ancestry only, never parse/validate unrelated manifests.

 The owning workspace is authorized by the route. A root marker protects all
 live descendants, including unregistered files; nearest roots win. Missing,
 deleted and cyclic ancestry cannot confer membership across workspace bounds.
 """
 from sqlalchemy.orm import load_only
 tree={d.id:d for d in db.query(Document).options(load_only(Document.id,Document.parent_id,Document.title,Document.workspace_id)).filter_by(workspace_id=workspace).filter(Document.deleted_at.is_(None)).all()}
 keys={row.key:row.value for row in db.query(AppConfig.key,AppConfig.value).filter(AppConfig.key.in_([PREFIX+str(i) for i in tree])).all()} if tree else {}
 owner=str(db.get(Workspace,workspace).user_id)
 roots={i:[] for i in tree if PREFIX+str(i) in keys}
 for ident in tree:
  current=ident;seen=set()
  while current in tree and current not in seen:
   if current in roots:
    roots[current].append(str(ident));break
   seen.add(current);current=tree[current].parent_id
 result=[]
 for root,members in sorted(roots.items(),key=lambda item:str(item[0])):
  item={'id':str(root),'workspace_id':str(workspace),'members':sorted(members)};assets=[]
  # Optional drag hints are not identity authority or a valid manifest. A bad
  # record/path suppresses only its hint; copy-asset still validates the manifest.
  try:meta=json.loads(keys[PREFIX+str(root)])
  except (ValueError,TypeError):meta=None
  records=meta.get('files') if isinstance(meta,dict) and meta.get('owner_id')==owner else None
  if isinstance(records,dict):
   for ident in members:
    record=records.get(ident)
    if not isinstance(record,dict) or record.get('kind')!='binary' or not isinstance(record.get('mime'),str) or not record['mime'].startswith('image/'):continue
    parts=[];current=tree[UUID(ident)]
    while current.id!=root:
     parts.append(current.title);current=tree[current.parent_id]
    if len(parts)>32 or any(not name or name in {'.','..'} or any(c in name for c in ['/','\\','\x00']) for name in parts):continue
    assets.append({'root':str(root),'file':ident,'path':'/'.join(reversed(parts)),'mime':record['mime']})
  if assets:item['assets']=assets
  result.append(item)
 return result

def manifest(db,owner,root):
 doc,meta=owned(db,owner,root);tree={d.id:d for d in db.query(Document).filter(Document.workspace_id==doc.workspace_id).all()};files=[];directories=[]
 # Directories are structural members, including legacy imports without a directory table.
 records={str(d.id):{'kind':'directory'} for d in tree.values() if d.is_folder and d.id!=doc.id}
 records.update(meta['files'])
 project_roots={d.id for d in tree.values() if d.is_folder and d.id!=doc.id and db.get(AppConfig,PREFIX+str(d.id))}
 for ident,record in records.items():
  current=tree.get(uid(ident));ancestors=[];seen=set()
  # Establish live project membership before applying project-relative path rules.
  # Ordinary ancestors/siblings may have arbitrary names/depth; cycles, deleted
  # ancestors and other project roots must never admit files into this project.
  while current and current.id!=doc.id and current.id not in seen and current.deleted_at is None:
   if current.id in project_roots:break
   seen.add(current.id);ancestors.append(current);current=tree.get(current.parent_id)
  if current and current.id==doc.id:
   parts=[]
   for ancestor in reversed(ancestors):
    name=ancestor.title
    if not name or name in {'.','..'} or any(x in name for x in ['/','\\','\x00']):raise HTTPException(409,'网页文件名不符合路径规则')
    parts.append(name)
    if len(parts)>32:raise HTTPException(409,'网页文件层级过深')
   item=tree[uid(ident)]
   if record['kind']=='directory':
    directories.append({'id':ident,'path':'/'.join(parts),'kind':'directory'});continue
   if record['kind']=='text':size=len((item.content or '').encode('utf-8'))
   else:
    att=db.get(Attachment,uid(record['attachment_id']))
    if not att or att.doc_id!=item.id:raise HTTPException(409,'网页资源附件缺失')
    size=att.size
   files.append({'id':ident,'path':'/'.join(parts),'kind':record['kind'],'mime':record['mime'],'size':size,'updated_at':item.updated_at.isoformat()})
 paths=[f['path'] for f in files+directories]
 if any(p.split('/')[0]=='__stella_storage.js' for p in paths):raise HTTPException(409,'网页项目使用了保留的运行路径')
 if len(paths)!=len(set(paths)):raise HTTPException(409,'网页项目存在重名路径')
 entry=next((f['path'] for f in files if f['id']==meta['entry_file_id']),None)
 return {'id':str(doc.id),'workspace_id':str(doc.workspace_id),'title':doc.title,'entry':entry,'entry_file_id':meta['entry_file_id'],'files':files,'directories':directories}

def project_ancestor(db,ident):
 """Graph/workspace lock is held by the caller for mutations."""
 seen=set()
 while ident and ident not in seen:
  seen.add(ident);current=db.get(Document,ident)
  if not current:return None
  if db.get(AppConfig,PREFIX+str(ident)):return ident
  ident=current.parent_id
 return None

DETACHED_PREFIX='web-project-source:'

def guard_project_move(db,doc,parent):
 """Transfer leaf text identity under the caller's graph/workspace transaction.

 Ordinary moves and whole-root moves stay intact. Cross-project adoption and
 directory/binary export remain explicit conflicts, never partial transfers.
 """
 if parent==doc.parent_id:return
 source=project_ancestor(db,doc.id);target=project_ancestor(db,parent)
 if source==doc.id:
  if target is None:return
 elif source==target:return
 if source and target is None and not doc.is_folder:
  row=db.get(AppConfig,PREFIX+str(source));meta=json.loads(row.value)
  record=meta['files'].get(str(doc.id))
  if record and record['kind']=='text':
   # Do not silently carry nested pages across a project boundary.
   if any(d.parent_id==doc.id for d in db.query(Document).filter(Document.workspace_id==doc.workspace_id).all()):
    raise HTTPException(409,'请先移动子页，再单独移出文本源码。')
   key=DETACHED_PREFIX+str(doc.id)
   if db.get(AppConfig,key):raise HTTPException(409,'源码身份冲突，未移动文件')
   db.add(AppConfig(key=key,value=json.dumps({**record,'owner_id':meta['owner_id'],'source_root_id':str(source)})))
   del meta['files'][str(doc.id)]
   if meta['entry_file_id']==str(doc.id):meta['entry_file_id']=None
   row.value=json.dumps(meta);doc.visibility='private'
   return
  raise HTTPException(409,'二进制资源暂不支持移出项目；文件未改变。图片请拖到普通笔记正文以独立复制。')
 raise HTTPException(409,'暂不支持跨项目移入或整目录移出；文件未改变。文本文件可单独移到项目外，保留私有源码编辑。')

def guard_detached_update(db,doc,data,*,source_edit=False):
 if not db.get(AppConfig,DETACHED_PREFIX+str(doc.id)):return
 fields=data.model_fields_set
 if ('visibility' in fields and data.visibility!='private') or ('is_folder' in fields and data.is_folder is not False):
  raise HTTPException(409,'独立源码保持私有文件身份，不能发布或转换为目录')
 if not source_edit and fields & {'content','content_hash','frontmatter','word_count','consumed_draft'}:
  raise HTTPException(409,'请使用独立源码编辑器保存，不能按普通笔记转换')

@rollback_on_error
def set_entry(db,owner,root,file_id,expected_entry_file_id):
 project,_=owned(db,owner,root);lock_workspace(db,project.workspace_id)
 project,meta=owned(db,owner,root)
 if meta['entry_file_id']!=expected_entry_file_id:raise HTTPException(409,'入口已被其他页面修改，请重新读取')
 info=manifest(db,owner,root)
 item=next((f for f in info['files'] if f['id']==str(file_id)),None)
 if not item or item['kind']!='text' or PurePosixPath(item['path']).suffix.lower() not in {'.html','.htm'}:raise HTTPException(409,'入口必须是项目内有效的HTML源码文件')
 meta['entry_file_id']=str(file_id)
 db.get(AppConfig,PREFIX+str(project.id)).value=json.dumps(meta)
 db.flush();result=manifest(db,owner,root);db.commit();return result

def validate_ancestor_projects(db,doc):
 """Called inside document update transaction, before commit, never repair data."""
 current=doc;seen=set();parts=[]
 while current and current.id not in seen:
  seen.add(current.id)
  row=db.get(AppConfig,PREFIX+str(current.id))
  if row and current.deleted_at is None:
   if parts and parts[-1]=='__stella_storage.js':raise HTTPException(409,'网页项目使用了保留的运行路径')
   meta=json.loads(row.value);manifest(db,uid(meta['owner_id']),current.id)
  parts.append(current.title);current=db.get(Document,current.parent_id) if current.parent_id else None

def read_file(db,owner,root,path):
 info=manifest(db,owner,root);item=next((f for f in info['files'] if f['path']==path),None)
 if not item:raise HTTPException(404,'网页文件不存在')
 doc=db.get(Document,uid(item['id']))
 if item['kind']=='text':return (doc.content or '').encode('utf-8'),item['mime']
 _,meta=owned(db,owner,root);aid=meta['files'][item['id']]['attachment_id'];att=db.get(Attachment,uid(aid))
 if not att or att.doc_id!=doc.id:raise HTTPException(404,'网页资源不存在')
 return b''.join(blob_store.read_range(db,'attachments/'+aid,0,att.size)),att.mime

@rollback_on_error
def copy_asset(db,owner,root,path,target_doc,request_id):
 project,meta=owned(db,owner,root);lock_workspace(db,project.workspace_id)
 target=db.get(Document,uid(target_doc));ws=db.get(Workspace,target.workspace_id) if target else None
 if not target or target.deleted_at is not None or not ws or ws.user_id!=owner:raise HTTPException(404,'目标笔记不存在')
 key=hashlib.sha256(f'web-project-copy:{owner}:{uid(request_id)}'.encode()).hexdigest();lock_key(db,key);scope=[str(root),path,str(target.id)];prior=db.get(AppConfig,key)
 if prior:
  row=json.loads(prior.value)
  if row['scope']!=scope:raise HTTPException(409,'复制标识冲突')
  att=db.get(Attachment,uid(row['id']))
  if not att or att.doc_id!=target.id:raise HTTPException(409,'原复制附件已不存在')
 else:
  data,mime=read_file(db,owner,root,path);att=attach(db,target,PurePosixPath(path).name,data,mime)
  db.add(AppConfig(key=key,value=json.dumps({'scope':scope,'id':str(att.id)})))
 result={'id':att.id,'url':'/attachments/'+str(att.id),'filename':att.filename};db.commit();return result

def state_key(root):return 'web-project-state:'+str(uid(root))
def initial():return {'revision':0,'epoch':0,'data':{}}
def read_state(db,owner,root):
 owned(db,owner,root);row=db.get(AppConfig,state_key(root));r=json.loads(row.value) if row else initial()
 return {k:r[k] for k in ['revision','epoch','data']}

def serialized_state(data):
 if not isinstance(data,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in data.items()) or len(data)>1000:raise HTTPException(422,'运行状态必须是有界字符串键值')
 try:encoded=json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
 except UnicodeEncodeError:raise HTTPException(422,'运行状态包含非法 Unicode 字符') from None
 if len(encoded)>1024*1024:raise HTTPException(413,'项目运行数据超过1 MiB')
 return encoded.decode('utf-8')

@rollback_on_error
def write_state(db,owner,root,revision,epoch,write_id,data,*,authorize_write=None):
 # Validate before acquiring graph/workspace locks; no state is changed on failure.
 serialized=serialized_state(data)
 project,_=owned(db,owner,root);lock_workspace(db,project.workspace_id);owned(db,owner,root)
 key=state_key(root);lock_key(db,key);row=db.query(AppConfig).filter_by(key=key).populate_existing().with_for_update().first();current=json.loads(row.value) if row else initial()
 if authorize_write is not None:authorize_write()
 digest=hashlib.sha256(serialized.encode()).hexdigest();write_id=str(uid(write_id))
 if current.get('write_id')==write_id and current['epoch']==epoch:
  if current.get('digest')!=digest:raise HTTPException(409,'运行状态写入标识冲突')
 elif current['revision']!=revision or current['epoch']!=epoch:raise HTTPException(409,'项目状态已更新，请重新打开网页')
 else:
  current={'revision':revision+1,'epoch':epoch,'data':data,'write_id':write_id,'digest':digest}
  if row:row.value=json.dumps(current)
  else:db.add(AppConfig(key=key,value=json.dumps(current)))
 db.commit();return {k:current[k] for k in ['revision','epoch','data']}

@rollback_on_error
def reset_state(db,owner,root):
 project,_=owned(db,owner,root);lock_workspace(db,project.workspace_id);owned(db,owner,root);key=state_key(root);lock_key(db,key)
 row=db.query(AppConfig).filter_by(key=key).populate_existing().with_for_update().first();current=json.loads(row.value) if row else initial()
 result={'revision':current['revision']+1,'epoch':current['epoch']+1,'data':{}}
 if row:row.value=json.dumps(result)
 else:db.add(AppConfig(key=key,value=json.dumps(result)))
 db.commit();return result
