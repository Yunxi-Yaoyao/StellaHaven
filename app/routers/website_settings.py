"""User-facing website drafts/saves; parent registers before SPA fallback."""
import os
from fastapi import APIRouter, Depends, Response, Request, HTTPException, Query
from app.database import get_db
from app.routers.auth import current_user, admin_user
from app.services.website_check import CheckInput, check_draft
from app.services.website_settings import WebsiteInput, save_website
from dataclasses import dataclass
from uuid import UUID
from sqlalchemy.engine import Engine
from app.services.saved_website_templates import TemplateInput
from app.services.entry_registry import request_origin

from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from app.validation_errors import validation_error_response

class PrivateInputRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def private_handler(request):
            try:
                if request.method == 'POST' and request.url.path == '/website-templates':
                    body = bytearray()
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 1048576: raise HTTPException(413, '模板内容过大')
                    request._body = bytes(body)
                return await handler(request)
            except RequestValidationError as exc:
                return validation_error_response(request, exc)
        return private_handler

router = APIRouter(prefix='/website-settings',tags=['website-settings'],route_class=PrivateInputRoute)
assets_router = APIRouter(tags=['websites'],route_class=PrivateInputRoute)

@assets_router.get('/website-templates')
def templates(response: Response, user=Depends(current_user), db=Depends(get_db)):
    from app.services.saved_website_templates import list_templates
    response.headers['Cache-Control'] = 'no-store'
    return list_templates(db,user.id)

@assets_router.post('/website-templates',status_code=201)
def create_template(data: TemplateInput, response: Response, user=Depends(admin_user), db=Depends(get_db)):
    from pydantic import ValidationError
    from app.services.saved_website_templates import save_template
    response.headers['Cache-Control'] = 'no-store'
    try: return save_template(db,data,user.id)
    except (ValidationError,TypeError,AttributeError):
        raise HTTPException(422,'模板参数无效或代码超出限制；请检查配置')

@assets_router.delete('/website-templates/{tid}',status_code=204)
def remove_template(tid: str, user=Depends(admin_user), db=Depends(get_db)):
    from app.services.saved_website_templates import delete_template
    delete_template(db,tid,user.id)
    return Response(status_code=204,headers={'Cache-Control':'no-store'})


def require_persisted_owner(request: Request, db=Depends(get_db)):
    # Ordinary draft checks must not trigger legacy lazy owner initialization.
    # Authentication still runs through the unchanged current_user dependency.
    if not request.cookies.get('stella_at'): return
    from app.services.admin_security import read_state
    from uuid import UUID
    _, identity = read_state(db)
    try: UUID(identity.get('owner_id',''))
    except (ValueError,TypeError,AttributeError):
        raise HTTPException(503,'网站草稿检测要求已固定的 owner 身份，不会在检测时初始化安全配置')

@assets_router.get('/website-assets/{mid}.js')
def website_asset(mid: str, request: Request, db=Depends(get_db)):
    from app.services.website_assets import asset_code
    allowed = False
    if request.cookies.get('stella_at'):
        try:
            require_persisted_owner(request,db)
            current_user(request,db)
            allowed = True
        except HTTPException as exc:
            if exc.status_code not in {401,403,503}: raise
    return Response(asset_code(db,mid,custom_allowed=allowed,parent_origin=request_origin(request) if allowed else None),media_type='application/javascript',headers={
        'Cache-Control':'no-store','Vary':'Cookie','X-Content-Type-Options':'nosniff',
        'Cross-Origin-Resource-Policy':'cross-origin','Referrer-Policy':'no-referrer'})

@router.post('/check',dependencies=[Depends(require_persisted_owner)])
async def check(data: CheckInput, response: Response, request: Request, user=Depends(current_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    from app.services.website_check import check_saved_draft
    return await check_saved_draft(db,data,parent_origin=request_origin(request))

@dataclass(frozen=True)
class WebsiteWriteContext:
    engine: Engine
    actor_id: UUID


def website_write_context(user=Depends(admin_user), db=Depends(get_db)):
    """Finish only this route's dependency-owned authentication transaction.

    This synchronous dependency follows the existing get_db/admin_user threadpool
    lifecycle. No live ORM object or Session crosses into the async save. Reject
    custom Connection ownership or pending writes rather than silently discarding
    a caller's transaction; direct service callers must supply an Engine instead.
    """
    engine = db.get_bind()
    if not isinstance(engine, Engine):
        raise TypeError('Website saves require an Engine-bound request auth Session')
    if db.new or db.dirty or db.deleted or db.in_nested_transaction():
        raise RuntimeError('Website auth transaction must not contain pending writes or savepoints')
    # rollback expires ORM instances: capture identity while auth is still live.
    context = WebsiteWriteContext(engine=engine, actor_id=user.id)
    db.rollback()
    return context


@router.post('',status_code=201)
async def create(data: WebsiteInput, response: Response, request: Request, context=Depends(website_write_context)):
    response.headers['Cache-Control'] = 'no-store'
    return await save_website(context.engine,data,context.actor_id,parent_origin=request_origin(request))

@router.patch('/{mid}')
async def update(mid: str, data: WebsiteInput, response: Response, request: Request, context=Depends(website_write_context)):
    response.headers['Cache-Control'] = 'no-store'
    return await save_website(context.engine,data,context.actor_id,parent_origin=request_origin(request),mid=mid)

@router.get('/{mid}/receipt')
def receipt(mid: str, response: Response, idempotency_key: str = Query(min_length=8,max_length=128,pattern=r'^[A-Za-z0-9_.:-]+$'), user=Depends(admin_user), db=Depends(get_db)):
    from app.services import integrations as store
    from app.services.website_settings import retry_result
    response.headers['Cache-Control']='no-store'
    config=store.state(db)
    slot=str(user.id)+':'+mid+':'+idempotency_key
    entry=config.get('website_save_keys',{}).get(slot)
    result=retry_result(config,slot,entry['digest'],idempotency_key) if entry else None
    if result is None: raise HTTPException(404,'未找到可确认的保存回执，请保留草稿')
    return result
