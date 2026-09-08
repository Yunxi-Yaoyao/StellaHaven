"""External gallery routes; lifecycle endpoints intentionally removed."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.routers.auth import current_user, admin_user
from app.services import gallery as service
from app.services import external_services as external

router = APIRouter(prefix='/gallery', tags=['gallery'], dependencies=[Depends(current_user)])

@router.get('/status')
def status(db: Session = Depends(get_db)):
    return service.get_status(db)

@router.get('/connection', dependencies=[Depends(admin_user)])
def connection(db: Session = Depends(get_db)):
    return external.masked(external.load(db, 'gallery'))

@router.put('/connection', dependencies=[Depends(admin_user)])
def save_connection(data: external.Connection, db: Session = Depends(get_db)):
    try:
        return external.save(db, 'gallery', data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@router.post('/connection/test', dependencies=[Depends(admin_user)])
async def test_connection(data: external.Connection, db: Session = Depends(get_db)):
    try:
        cfg = external.merge(db, 'gallery', data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await external.probe('gallery', cfg)

@router.get('/connect')
def connect(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse(service.browser_url(db, request.url.hostname or ''), headers={'Cache-Control': 'no-store'})
