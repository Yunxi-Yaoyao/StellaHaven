"""Owner-scoped native navigation. One CAS aggregate keeps reorders atomic."""
import hashlib
import json
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, WebSocket
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.database import get_db
from app.models.native_nav import NavState, NavAsset
from app.models.user import User
from app.routers.auth import current_user
from app.schemas.native_nav import NavData, Write
from app.services.native_nav_budget import check_config_budget

def private_response(response:Response):
    response.headers['Cache-Control']='private, no-store'

router = APIRouter(tags=['native-navigation'],dependencies=[Depends(private_response)])
# Separate router: HTTP Response dependencies do not apply to WebSockets.
events_router = APIRouter()

@events_router.websocket('/ws/native-nav/changes')
async def nav_changes(ws:WebSocket, db=Depends(get_db)):
    """Read-only revision hints, checked against PG across workers every 2s.

    No shared in-memory bus, no payload/body broadcast, no activity extension;
    reconnect always reads the current revision. Release the DB between ticks.
    """
    import asyncio
    from starlette.requests import Request
    from starlette.websockets import WebSocketDisconnect
    from app.services.request_security import trusted_origins
    origins=ws.headers.getlist('origin')
    if len(origins)!=1 or origins[0] not in trusted_origins() or ws.query_params:
        await ws.close(code=1008);return
    accepted=False
    try:
        while True:
            try:
                db.expire_all()
                user=current_user(Request({**ws.scope,'type':'http','method':'GET'}),db)
                row=db.get(NavState,user.id,populate_existing=True)
                revision=row.revision if row else 0
            except HTTPException:
                await ws.close(code=1008);return
            finally:db.rollback()
            if not accepted:await ws.accept();accepted=True
            await ws.send_json({'type':'nav_revision','revision':revision})
            # Client messages cannot cause unbounded DB reads.
            await asyncio.sleep(2)
    except (WebSocketDisconnect,RuntimeError,OSError):pass
    finally:db.rollback()


from pydantic import BaseModel, ConfigDict, Field
class ImportPreview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source:str=Field(max_length=2*1024*1024)

@router.post('/nav-import-preview')
def import_preview(body:ImportPreview,db=Depends(get_db),user:User=Depends(current_user)):
    from app.services.native_nav_import import preview
    return preview(body.source,snapshot(db.get(NavState,user.id))['data'])

@router.get('/nav-export')
def export(db=Depends(get_db),user:User=Depends(current_user)):
    return {'appName':'Stella-Native-Nav','version':1,**snapshot(db.get(NavState,user.id)),
            'assets':[asset_info(r) for r in db.scalars(select(NavAsset).where(NavAsset.owner_id==user.id))],
            'boundary':{'settings':'complete-native-navigation-preferences','asset_bytes':False,'sessions':False,'notes':False,'credentials':False}}


class PackagePreview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source:str=Field(max_length=44*1024*1024)

class PackageImport(PackagePreview):
    revision:int=Field(ge=0,strict=True)
    mutation_id:UUID
    digest:str=Field(pattern=r'^[0-9a-f]{64}$')
    confirmed:bool=Field(strict=True)
    module_bindings:dict[UUID,str|None]=Field(default_factory=dict,max_length=2000)

@router.get('/nav-package')
def export_package(db=Depends(get_db),user:User=Depends(current_user)):
    from app.services.native_nav_package import package
    # Same owner lock as all writers: coherent data and referenced asset bytes.
    try:
        row=lock(db,user.id)
        value=package(row.data,list(db.scalars(select(NavAsset).where(NavAsset.owner_id==user.id).order_by(NavAsset.id))))
        db.rollback()
        return value
    except BaseException:
        db.rollback();raise

@router.post('/nav-package-preview')
def package_preview(body:PackagePreview,db=Depends(get_db),user:User=Depends(current_user)):
    from app.services.native_nav_package import preview,sha
    owned={f'/nav-assets/{a.id}':sha(a.content) for a in db.scalars(select(NavAsset).where(NavAsset.owner_id==user.id))}
    result=preview(body.source,user.id,snapshot(db.get(NavState,user.id))['data'],owned)
    result['revision']=snapshot(db.get(NavState,user.id))['revision']
    return result

@router.post('/nav-package-import')
def package_import(body:PackageImport,db=Depends(get_db),user:User=Depends(current_user)):
    from app.services.native_nav_package import parse,sha,MAX_BYTES,MAX_ASSETS
    if not body.confirmed or sha(body.source.encode())!=body.digest: raise HTTPException(422,'必须确认当前完整包的预览')
    bindings={str(k):v for k,v in body.module_bindings.items()}
    # The same receipt cannot change a binding, including after a lost ACK.
    digest=sha(json.dumps([body.digest,bindings],sort_keys=True,separators=(',',':')).encode()) if bindings else body.digest
    try:
        row=lock(db,user.id)
        if row.mutation_id==str(body.mutation_id):
            if row.mutation_hash!=digest: raise HTTPException(409,'同一次导入不能更换文件或模块绑定')
            return snapshot(row)
        if row.revision!=body.revision: raise HTTPException(409,'导航已变化，请重新预览后确认；未写入任何素材')
        existing={a.id:a for a in db.scalars(select(NavAsset).where(NavAsset.owner_id==user.id))}
        owned={f'/nav-assets/{a.id}':sha(a.content) for a in existing.values()}
        data,assets,counts,warnings=parse(body.source,user.id,owned)
        cards={c['id']:c for g in data['groups'] for c in g['items']}
        if not set(bindings)<=set(cards):raise HTTPException(422,'模块绑定必须属于当前预览的网站')
        for key,value in bindings.items():cards[key]['module_id']=value
        from pydantic import ValidationError
        try:data=NavData.model_validate(data).model_dump(mode='json')
        except ValidationError:raise HTTPException(422,'模块绑定或目标地址无效') from None
        check_config_budget(data)
        from app.services.homebg_references import validate_new
        validate_new(db, data, row.data)
        additions=[]
        for a in assets:
            found=db.get(NavAsset,a['id'])
            if found and (found.owner_id!=user.id or found.content!=a['content']): raise HTTPException(409,'素材身份冲突')
            if not found: additions.append(a)
        if len(existing)+len(additions)>MAX_ASSETS or sum(a.size for a in existing.values())+sum(a['size'] for a in additions)>MAX_BYTES: raise HTTPException(413,'导入后将超过素材上限（100项 / 30 MiB）')
        modules=[i['module_id'] for g in data['groups'] for i in g['items'] if i.get('module_id')]
        if modules:
            from app.services.integrations import state
            if not set(modules)<=set(state(db)['modules']): raise HTTPException(422,'模块引用需先在平台重新绑定')
        for a in additions: db.add(NavAsset(**{k:a[k] for k in ('id','name','mime','size','content','category')},owner_id=user.id))
        for a in assets:
            if a['id'] in existing:
                existing[a['id']].name=a['name'];existing[a['id']].category=a['category']
        row.data=data;row.revision+=1;row.mutation_id=str(body.mutation_id);row.mutation_hash=digest
        db.commit();db.refresh(row)
        return snapshot(row)
    except BaseException:
        db.rollback();raise


def snapshot(row):
    return {'revision':row.revision,'data':row.data} if row else {'revision':0,'data':NavData().model_dump(mode='json')}

def lock(db, owner):
    from app.services.homebg_references import lock_library
    lock_library(db)  # shared media -> nav aggregate, including package/restore
    db.execute(insert(NavState).values(owner_id=owner,revision=0,data=NavData().model_dump(mode='json'),mutation_id='',mutation_hash='').on_conflict_do_nothing())
    return db.scalar(select(NavState).where(NavState.owner_id==owner).with_for_update().execution_options(populate_existing=True))

def asset_refs(data):
    if isinstance(data,dict):
        for value in data.values(): yield from asset_refs(value)
    elif isinstance(data,list):
        for value in data: yield from asset_refs(value)
    elif isinstance(data,str) and data.startswith('/nav-assets/'):
        try: yield UUID(data.removeprefix('/nav-assets/'))
        except ValueError: raise HTTPException(422,'素材地址无效') from None

@router.get('/nav-data')
def read(db=Depends(get_db), user:User=Depends(current_user)):
    return snapshot(db.get(NavState,user.id,populate_existing=True))

@router.put('/nav-data')
def write(body:Write,db=Depends(get_db),user:User=Depends(current_user)):
    data=body.data.model_dump(mode='json')
    check_config_budget(data)
    digest=hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    try:
        row=lock(db,user.id)
        if row.mutation_id==str(body.mutation_id):
            if row.mutation_hash!=digest: raise HTTPException(409,'同一次保存不能更换内容')
            return snapshot(row)
        if row.revision!=body.revision: raise HTTPException(409,'其他窗口已修改；请重新读取后比较草稿')
        from app.services.homebg_references import validate_new
        validate_new(db, data, row.data)
        ids=set(asset_refs(data))
        found=set(db.scalars(select(NavAsset.id).where(NavAsset.owner_id==user.id,NavAsset.id.in_(ids)))) if ids else set()
        if ids!=found: raise HTTPException(422,'素材已删除或不属于当前账号')
        if any(i.module_id for g in body.data.groups for i in g.items):
            from app.services.integrations import state
            modules=state(db)['modules']
            if any(i.module_id and i.module_id not in modules for g in body.data.groups for i in g.items): raise HTTPException(422,'接入网站引用不存在')
        row.data=data; row.revision+=1; row.mutation_id=str(body.mutation_id); row.mutation_hash=digest
        db.commit()
        db.refresh(row)
        return snapshot(row)
    except BaseException:
        db.rollback(); raise


def asset_info(row):
    from app.services.native_nav_package import dimensions,sha
    try: _,width,height=dimensions(row.content)
    except HTTPException: width=height=None
    return {'id':str(row.id),'url':f'/nav-assets/{row.id}','name':row.name,'mime':row.mime,'size':row.size,'category':row.category,'width':width,'height':height,'sha256':sha(row.content)}


from typing import Literal
class AssetBatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ids:list[UUID]=Field(min_length=1,max_length=100)

class AssetCategory(AssetBatch):
    category:Literal['uncategorized','icon','background','logo','other']

def owned_asset_batch(db,owner,ids):
    if len(ids)!=len(set(ids)): raise HTTPException(422,'素材标识重复')
    rows=list(db.scalars(select(NavAsset).where(NavAsset.owner_id==owner,NavAsset.id.in_(ids))))
    if {a.id for a in rows}!=set(ids): raise HTTPException(404,'整批素材不存在或不属于当前账号，未写入')
    return rows

@router.post('/nav-assets-batch-delete')
def delete_assets(body:AssetBatch,db=Depends(get_db),user:User=Depends(current_user)):
    try:
        row=lock(db,user.id);assets=owned_asset_batch(db,user.id,body.ids)
        if set(body.ids)&set(asset_refs(row.data)): raise HTTPException(409,'整批中有素材仍被使用，未删除任何素材')
        for a in assets: db.delete(a)
        db.commit();return {'deleted':[str(i) for i in body.ids]}
    except BaseException:
        db.rollback();raise

@router.post('/nav-assets-category')
def categorize_assets(body:AssetCategory,db=Depends(get_db),user:User=Depends(current_user)):
    try:
        lock(db,user.id);assets=owned_asset_batch(db,user.id,body.ids)
        for a in assets: a.category=body.category
        db.commit();return {'updated':[str(i) for i in body.ids],'category':body.category}
    except BaseException:
        db.rollback();raise

@router.get('/nav-assets')
def assets(db=Depends(get_db), user:User=Depends(current_user)):
    return [asset_info(r) for r in db.scalars(select(NavAsset).where(NavAsset.owner_id==user.id).order_by(NavAsset.name,NavAsset.id))]

@router.post('/nav-assets')
async def upload(file:UploadFile, db=Depends(get_db), user:User=Depends(current_user)):
    content=await file.read(3*1024*1024+1)
    if len(content)>3*1024*1024: raise HTTPException(413,'图片不能超过 3 MiB')
    # No SVG/HTML, content sniffing rather than the caller's Content-Type. Bytes
    # are never decoded/executed by the server and are served with nosniff+sandbox.
    from app.services.native_nav_package import dimensions
    mime,_,_=dimensions(content)
    try:
        lock(db,user.id)
        sizes=list(db.scalars(select(NavAsset.size).where(NavAsset.owner_id==user.id)))
        if len(sizes)>=100 or sum(sizes)+len(content)>30*1024*1024: raise HTTPException(413,'导航素材达到账号上限（100 项 / 30 MiB）')
        row=NavAsset(id=uuid4(),owner_id=user.id,name=(file.filename or '图片')[:120],mime=mime,size=len(content),content=content)
        db.add(row);db.commit();db.refresh(row)
        return asset_info(row)
    except BaseException:
        db.rollback();raise

@router.get('/nav-assets/{asset_id}')
def asset(asset_id:UUID, db=Depends(get_db),user:User=Depends(current_user)):
    row=db.scalar(select(NavAsset).where(NavAsset.id==asset_id,NavAsset.owner_id==user.id))
    if not row: raise HTTPException(404,'素材不存在')
    return Response(row.content,media_type=row.mime,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"})

@router.delete('/nav-assets/{asset_id}')
def delete_asset(asset_id:UUID,db=Depends(get_db),user:User=Depends(current_user)):
    try:
        state=lock(db,user.id)
        row=db.scalar(select(NavAsset).where(NavAsset.id==asset_id,NavAsset.owner_id==user.id))
        if not row: raise HTTPException(404,'素材不存在')
        if asset_id in set(asset_refs(state.data)): raise HTTPException(409,'素材仍被网站、引擎或背景使用')
        db.delete(row);db.commit()
        return {'deleted':str(asset_id)}
    except BaseException:
        db.rollback();raise
