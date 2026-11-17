"""Project HTTP APIs. Owner auth precedes every file/state operation."""
from uuid import UUID
from fastapi import APIRouter,Depends,File,Form,UploadFile,Request,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from app.database import get_db
from app.routers.auth import current_user,require_ws_owner,require_doc_owner
from app.services import web_projects as service
from app.routers.web_project_renew_limits import ProjectRuntimeRoute
router=APIRouter(prefix='/web-projects',tags=['web_projects'],dependencies=[Depends(current_user)],route_class=ProjectRuntimeRoute)

@router.get('/workspace/{workspace_id}')
def catalog(workspace_id:UUID,db=Depends(get_db),user=Depends(current_user)):
 require_ws_owner(db,workspace_id,user)
 from app.models.config import AppConfig
 from app.models.document import Document
 docs=db.query(Document).filter_by(workspace_id=workspace_id).filter(Document.deleted_at.is_(None)).all();result=[]
 for doc in docs:
  if db.get(AppConfig,service.PREFIX+str(doc.id)):
   result.append(service.manifest(db,user.id,doc.id))
 return result

@router.get('/workspace/{workspace_id}/identities')
def identities(workspace_id:UUID,db=Depends(get_db),user=Depends(current_user)):
 require_ws_owner(db,workspace_id,user)
 return service.identities(db,workspace_id)

@router.post('/import/preview')
def preview(file:UploadFile=File(...),workspace_id:UUID=Form(...),db=Depends(get_db),user=Depends(current_user)):
 require_ws_owner(db,workspace_id,user)
 files,_=service.unpack(file.file.read(service.MAX_FILE+1),file.filename or '')
 entries=[{'path':p,'size':len(b),'kind':'text' if service.PurePosixPath(p).suffix.lower() in service.TEXT else 'binary'} for p,b in sorted(files.items())]
 candidates=[p for p in files if p.lower().endswith(('.html','.htm'))]
 if not candidates:raise HTTPException(400,'网页项目缺少HTML入口')
 entry='index.html' if 'index.html' in candidates else candidates[0] if len(candidates)==1 else None
 return {'files':entries,'entries':candidates,'suggested_entry':entry,'warnings':['原网页使用浏览器数据库等未适配能力时，不能保证原样持久化。']}

@router.post('/import')
def import_project(file:UploadFile=File(...),workspace_id:UUID=Form(...),import_id:UUID=Form(...),entry:str=Form(...),parent_id:UUID|None=Form(None),db=Depends(get_db),user=Depends(current_user)):
 require_ws_owner(db,workspace_id,user)
 result=service.create(db,user.id,workspace_id,parent_id,import_id,file.file.read(service.MAX_FILE+1),file.filename or '',entry)
 from app.routers.document import notify_list
 notify_list(workspace_id,result['id']);return result

@router.get('/{root_id}')
def manifest(root_id:UUID,db=Depends(get_db),user=Depends(current_user)):
 return service.manifest(db,user.id,root_id)

class SourcePatch(BaseModel):
 model_config=ConfigDict(extra='forbid')
 updated_at:str
 content:str=Field(max_length=5*1024*1024)

@router.get('/{root_id}/files/{file_id}')
def source(root_id:UUID,file_id:UUID,db=Depends(get_db),user=Depends(current_user)):
 info=service.manifest(db,user.id,root_id);file=next((f for f in info['files'] if f['id']==str(file_id)),None)
 if not file:raise HTTPException(404,'项目文件不存在')
 doc=require_doc_owner(db,file_id,user)
 if file['kind']!='text':
  _,meta=service.owned(db,user.id,root_id)
  return {**file,'url':'/attachments/'+meta['files'][str(file_id)]['attachment_id'],'content':None}
 return {**file,'content':doc.content or '','url':None}

@router.patch('/{root_id}/files/{file_id}')
def update_source(root_id:UUID,file_id:UUID,data:SourcePatch,db=Depends(get_db),user=Depends(current_user)):
 item=source(root_id,file_id,db,user)
 if item['kind']!='text':raise HTTPException(409,'二进制文件不能按源码保存')
 from app.schemas.document import DocumentUpdate
 from app.services.document import update_document
 from datetime import datetime
 try:stamp=datetime.fromisoformat(data.updated_at)
 except ValueError:raise HTTPException(422,'非法保存版本') from None
 try:doc=update_document(db,file_id,DocumentUpdate(updated_at=stamp,content=data.content))
 except ValueError:raise HTTPException(409,'源码已被其他页面修改，请重新读取') from None
 return {'id':str(doc.id),'updated_at':doc.updated_at.isoformat(),'content':doc.content}

@router.get('/{root_id}/state')
def state(root_id:UUID,db=Depends(get_db),user=Depends(current_user)):
 return service.read_state(db,user.id,root_id)

@router.post('/{root_id}/launch')
def launch(root_id:UUID,request:Request,db=Depends(get_db),user=Depends(current_user)):
 from app.services.entry_registry import request_origin
 from app.routers.auth import _presented_session
 from app.services import web_project_runtime
 source=request_origin(request)
 if request.headers.getlist('origin')!=[source]:raise HTTPException(403,'网页启动来源不匹配')
 session=_presented_session(request,db)
 if not session or session.user_id!=user.id:raise HTTPException(401,'需要有效登录会话')
 return web_project_runtime.launch(db,user.id,root_id,session.id,source)

class Renewal(BaseModel):
 model_config=ConfigDict(extra='forbid')
 capability:str=Field(min_length=43,max_length=43,pattern=r'^[A-Za-z0-9_-]{43}$')
 epoch:int=Field(ge=0,le=9007199254740991,strict=True)

@router.post('/{root_id}/renew')
def renew(root_id:UUID,data:Renewal,request:Request,db=Depends(get_db),user=Depends(current_user)):
 from app.services.entry_registry import request_origin
 from app.services import web_project_runtime
 source=request_origin(request)
 if request.headers.getlist('origin')!=[source]:raise HTTPException(403,'网页续期来源不匹配')
 session=getattr(request.state,'auth_session',None)
 if not session or session.user_id!=user.id:raise HTTPException(401,'需要有效登录会话')
 return web_project_runtime.renew(db,user.id,root_id,session.id,source,data.capability,data.epoch)

class StatePatch(BaseModel):
 model_config=ConfigDict(extra='forbid')
 revision:int=Field(ge=0,strict=True)
 epoch:int=Field(ge=0,strict=True)
 write_id:UUID
 data:dict[str,str]
 capability:str=Field(min_length=43,max_length=43)

@router.put('/{root_id}/state')
def write_state(root_id:UUID,data:StatePatch,request:Request,db=Depends(get_db),user=Depends(current_user)):
 from app.services.entry_registry import request_origin
 from app.services import web_project_runtime as runtime
 source=request_origin(request)
 if request.headers.getlist('origin')!=[source]:raise HTTPException(403,'网页保存来源不匹配')
 grant,_=runtime.authorize(db,data.capability,source=source)
 session=getattr(request.state,'auth_session',None)
 if not session or grant['owner']!=str(user.id) or grant['root']!=str(root_id) or grant['sid']!=str(session.id):raise HTTPException(403,'网页保存授权不匹配')
 from app.services.web_project_write_auth import authorize_locked_write
 return service.write_state(db,user.id,root_id,data.revision,data.epoch,str(data.write_id),data.data,
  authorize_write=lambda:authorize_locked_write(db,user.id,root_id,session.id,data.capability,source))

@router.delete('/{root_id}/state')
def reset(root_id:UUID,db=Depends(get_db),user=Depends(current_user)):
 return service.reset_state(db,user.id,root_id)

class CopyAsset(BaseModel):
 model_config=ConfigDict(extra='forbid')
 target_doc_id:UUID
 request_id:UUID
 path:str=Field(max_length=1024)

@router.post('/{root_id}/copy-asset')
def copy_asset(root_id:UUID,data:CopyAsset,db=Depends(get_db),user=Depends(current_user)):
 return service.copy_asset(db,user.id,root_id,data.path,data.target_doc_id,data.request_id)
