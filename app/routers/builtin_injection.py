"""Privileged builtin control API plus session-scoped gallery client code.

Register router with ordinary API routers, assets_router without /api prefix.
Anonymous gets only the public appearance selection; a real daily owner session
may read its actively published target-site code. Neither response contains
private connection configuration.
"""
from fastapi import APIRouter, Depends, Response, Request, HTTPException
from app.database import get_db
from app.routers.auth import admin_user, current_user, AT_COOKIE
from app.services import builtin_injection as service
from app.services.integrations_injection import InjectionInput

router = APIRouter(prefix='/builtin-injections', tags=['builtin-injections'])
assets_router = APIRouter(tags=['integration-assets'])


@router.get('/{site}')
def read(site: str, response: Response, user=Depends(admin_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    css, js = service.presets(site)
    return service.read(db, site) | {'preset': {'css': css, 'js': js}, 'base_required': True}


@router.post('/{site}/validate')
def validate(site: str, data: InjectionInput, response: Response, user=Depends(admin_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    return service.validate_draft(db, site, data)


@router.post('/{site}/apply')
def apply(site: str, response: Response, user=Depends(admin_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    return service.apply(db, site, user.id)


@router.post('/{site}/rollback')
def rollback(site: str, response: Response, user=Depends(admin_user), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    return service.rollback(db, site, user.id)


@assets_router.get('/integration-assets/gallery.js')
def gallery_asset(request: Request, db=Depends(get_db)):
    allowed = False
    if request.cookies.get(AT_COOKIE):
        try:
            from app.routers.website_settings import require_persisted_owner
            require_persisted_owner(request, db)
            current_user(request, db)
            allowed = True
        except HTTPException as exc:
            if exc.status_code not in {401, 403, 503}: raise
    code, version = service.gallery_asset(db, custom_allowed=allowed)
    return Response(code, media_type='application/javascript', headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'X-Stella-Injection-Version': version,
        'Cross-Origin-Resource-Policy': 'cross-origin',
        'Vary': 'Cookie',
        'Referrer-Policy': 'no-referrer',
    })
