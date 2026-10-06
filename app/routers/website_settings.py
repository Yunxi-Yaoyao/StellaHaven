"""User-facing website drafts/saves; parent registers before SPA fallback."""
import os
from fastapi import APIRouter, Depends, Response, Request, HTTPException
from app.database import get_db
from app.routers.auth import current_user, admin_user
from app.services.website_check import CheckInput, check_draft
from app.services.website_settings import WebsiteInput, save_website

router = APIRouter(prefix='/website-settings',tags=['website-settings'])

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

@router.post('/check',dependencies=[Depends(require_persisted_owner)])
async def check(data: CheckInput, response: Response, user=Depends(current_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    db.rollback()  # Authentication is complete; no DB connection across upstream I/O.
    return await check_draft(data,parent_origin=os.environ.get('STELLA_MAIN_ORIGIN','https://stella.xiya.live'))

@router.post('',status_code=201)
async def create(data: WebsiteInput, response: Response, user=Depends(admin_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    return await save_website(db,data,user.id,parent_origin=os.environ.get('STELLA_MAIN_ORIGIN','https://stella.xiya.live'))

@router.patch('/{mid}')
async def update(mid: str, data: WebsiteInput, response: Response, user=Depends(admin_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    return await save_website(db,data,user.id,parent_origin=os.environ.get('STELLA_MAIN_ORIGIN','https://stella.xiya.live'),mid=mid)
