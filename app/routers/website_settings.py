"""User-facing website drafts/saves; parent registers before SPA fallback."""
import os
from fastapi import APIRouter, Depends, Response, Request, HTTPException
from app.database import get_db
from app.routers.auth import current_user, admin_user
from app.services.website_check import CheckInput, check_draft
from app.services.website_settings import WebsiteInput, save_website

from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

class PrivateInputRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def private_handler(request):
            try: return await handler(request)
            except RequestValidationError as exc:
                return JSONResponse({'detail':[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()]},status_code=422)
        return private_handler

router = APIRouter(prefix='/website-settings',tags=['website-settings'],route_class=PrivateInputRoute)
assets_router = APIRouter(tags=['websites'])

@assets_router.get('/website-templates')
def templates(response: Response, user=Depends(current_user)):
    from app.services.website_templates import catalog
    response.headers['Cache-Control'] = 'no-store'
    return catalog()


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
    return Response(asset_code(db,mid,custom_allowed=allowed),media_type='application/javascript',headers={
        'Cache-Control':'no-store','Vary':'Cookie','X-Content-Type-Options':'nosniff',
        'Cross-Origin-Resource-Policy':'cross-origin','Referrer-Policy':'no-referrer'})

@router.post('/check',dependencies=[Depends(require_persisted_owner)])
async def check(data: CheckInput, response: Response, user=Depends(current_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    from app.services.website_check import check_saved_draft
    return await check_saved_draft(db,data,parent_origin=os.environ.get('STELLA_MAIN_ORIGIN','https://stella.xiya.live'))

@router.post('',status_code=201)
async def create(data: WebsiteInput, response: Response, user=Depends(admin_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    return await save_website(db,data,user.id,parent_origin=os.environ.get('STELLA_MAIN_ORIGIN','https://stella.xiya.live'))

@router.patch('/{mid}')
async def update(mid: str, data: WebsiteInput, response: Response, user=Depends(admin_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    return await save_website(db,data,user.id,parent_origin=os.environ.get('STELLA_MAIN_ORIGIN','https://stella.xiya.live'),mid=mid)
