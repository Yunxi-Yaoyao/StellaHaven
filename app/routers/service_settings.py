"""Daily reads/checks and elevated atomic writes; no secrets in projections."""
from fastapi import APIRouter, Depends, Response, Body
from app.database import get_db
from app.routers.auth import current_user, admin_user
from app.routers.website_settings import require_persisted_owner
from app.services import service_settings as service

router = APIRouter(prefix='/service-settings', tags=['service-settings'],
                   dependencies=[Depends(require_persisted_owner)])


@router.get('/{site}')
def read(site: str, response: Response, user=Depends(current_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    return service.read(db, site)


@router.put('/{site}')
def save(site: str, response: Response, data: dict = Body(...), user=Depends(admin_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    return service.save(db, site, data, user.id)


@router.post('/{site}/check')
async def check(site: str, response: Response, data: dict = Body(...), user=Depends(current_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    return await service.check(db, site, data)
