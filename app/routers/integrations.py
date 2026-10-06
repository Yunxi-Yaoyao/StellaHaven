"""Integration management API; register this router from main (see contract)."""
from fastapi import APIRouter, Depends, Body, Response, Request, HTTPException
from app.database import get_db
from app.routers.auth import current_user, admin_user
from app.services import integrations as service
from app.services import integrations_proxy as proxy
from app.services import integrations_injection as injection

router = APIRouter(tags=['integrations'])

@router.get('/integration-targets', dependencies=[Depends(admin_user)])
def targets(db=Depends(get_db)):
    return [proxy.masked_target(t) for t in service.state(db)['targets'].values()]

@router.post('/integration-targets', status_code=201, dependencies=[Depends(admin_user)])
async def create_target(data: proxy.TargetInput, user=Depends(admin_user), db=Depends(get_db)):
    return await proxy.create_target(db, data, user.id)

@router.post('/integration-targets/resolve', dependencies=[Depends(admin_user)])
async def resolve_target(data: proxy.ResolveTargetInput, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return await proxy.resolve_target_preview(data)


@router.get('/navigation', dependencies=[Depends(current_user)])
def navigation(db=Depends(get_db)):
    return service.navigation(db)

@router.put('/navigation', dependencies=[Depends(admin_user)])
def save_navigation(data: service.NavigationInput, user=Depends(admin_user), db=Depends(get_db)):
    return service.save_navigation(db, data, user.id)

@router.get('/external-modules', dependencies=[Depends(current_user)])
def modules(db=Depends(get_db)):
    config = service.state(db)
    return [service.present(m,config) for m in config['modules'].values()]

@router.post('/external-modules', status_code=201, dependencies=[Depends(admin_user)])
def create(data: service.ModuleInput, user=Depends(admin_user), db=Depends(get_db)):
    return service.create_module(db, data, user.id)

@router.get('/external-modules/{mid}', dependencies=[Depends(current_user)])
def module(mid: str, db=Depends(get_db)):
    config = service.state(db)
    item = config['modules'].get(mid)
    if item is None: raise HTTPException(404,'模块不存在')
    return service.present(item,config)

@router.patch('/external-modules/{mid}', dependencies=[Depends(admin_user)])
def patch(mid: str, data: dict = Body(...), user=Depends(admin_user), db=Depends(get_db)):
    return service.patch_module(db, mid, data, user.id)

@router.delete('/external-modules/{mid}', status_code=204, dependencies=[Depends(admin_user)])
def delete(mid: str, user=Depends(admin_user), db=Depends(get_db)):
    service.delete_module(db, mid, user.id)
    return Response(status_code=204)

@router.post('/external-modules/{mid}/launch')
def launch(mid: str, request: Request, response: Response, user=Depends(current_user), db=Depends(get_db)):
    response.headers['Cache-Control']='no-store'
    response.headers['Referrer-Policy']='no-referrer'
    from app.routers.auth import _presented_session
    from app.services import integrations_sessions as sessions
    module=service.get_module(db,mid)
    if not module['enabled']:
        raise HTTPException(404,'模块已禁用')
    if module['mode']=='isolated_proxy':
        session=_presented_session(request,db)
        if not session or session.user_id!=user.id:
            raise HTTPException(401,'需要有效主站会话')
        return sessions.issue(db,module,str(session.id),str(request.base_url).rstrip('/'))
    if module['mode']=='openlist':
        from app.services.drive import get_login_url
        return dict(mode='openlist',url=get_login_url(db)['url'],method='GET')
    if module['adapter']=='immich' and module['mode']!='link':
        # Preserve original domain, issuer, callbacks and account mapping.
        return dict(mode=module['mode'],url='/gallery/connect',method='GET')
    return dict(mode=module['mode'],url=module['browser_url'],method='GET')

def require_module_injection(db, mid):
    item = service.get_module(db, mid)
    if item.get('adapter') in {'openlist', 'immich'}:
        site = 'drive' if item['adapter'] == 'openlist' else 'gallery'
        raise HTTPException(409, {'message': '内置服务注入统一管理',
                                  'managed_settings': '/settings?section=navigation&module=' + site})


@router.post('/external-modules/{mid}/injection/validate', dependencies=[Depends(admin_user)])
def validate_injection(mid: str, data: injection.InjectionInput, db=Depends(get_db)):
    require_module_injection(db, mid)
    return injection.validate_draft(db,mid,data)

@router.post('/external-modules/{mid}/injection/apply', dependencies=[Depends(admin_user)])
def apply_injection(mid: str, user=Depends(admin_user), db=Depends(get_db)):
    require_module_injection(db, mid)
    return injection.apply(db,mid,user.id)

@router.post('/external-modules/{mid}/injection/rollback', dependencies=[Depends(admin_user)])
def rollback_injection(mid: str, user=Depends(admin_user), db=Depends(get_db)):
    require_module_injection(db, mid)
    return injection.rollback(db,mid,user.id)

@router.get('/integration-presets', dependencies=[Depends(admin_user)])
def presets():
    from app.services.drive import OPENLIST_THEME_CSS, OPENLIST_THEME_JS
    from app.services.builtin_injection import presets as builtin_presets
    gallery_css, gallery_js = builtin_presets('gallery')
    return {
        'openlist': {'css': OPENLIST_THEME_CSS, 'js': OPENLIST_THEME_JS, 'readonly': True,
                     'status': 'builtin_response_loader',
                     'managed_settings': '/settings?section=navigation&module=drive'},
        'immich': {'css': gallery_css, 'js': gallery_js, 'readonly': True,
                   'status': 'owner_session_classic_loader',
                   'managed_settings': '/settings?section=navigation&module=gallery'},
        'generic': {'css': '/* Target origin only */\nbody { color-scheme: dark; }',
                    'js': 'document.documentElement.dataset.stellaInjected = "loaded";',
                    'readonly': True, 'status': 'injection_loaded_is_not_app_ready'},
    }

@router.post('/external-modules/{mid}/check', dependencies=[Depends(current_user)])
async def check(mid: str, db=Depends(get_db)):
    import asyncio, httpx
    module=service.get_module(db,mid)
    active=module['injection']['active']
    result=dict(configuration_valid=True,server_reachable=None,http_status=None,browser_status='unobservable',ready=False,injection_version=active['version'] if active else None,reason='浏览器页面内部状态不可读，不能从服务器探针推断 ready')
    if module['mode']!='isolated_proxy':
        return result
    target=service.state(db)['targets'].get(module['target_id'])
    if target is None:
        return result | dict(configuration_valid=False,reason='固定目标不存在')
    connection=response=None
    try:
        connection,response=await asyncio.wait_for(proxy.open_response(target,'/',method='GET'),8)
        result.update(server_reachable=True,http_status=response.status_code)
        if response.status_code in {401,403}: result['reason']='服务器可达；上游登录未完成；浏览器状态未知'
    except (HTTPException,httpx.HTTPError,OSError,TimeoutError):
        result.update(server_reachable=False,reason='批准目标不可达或解析已变更；浏览器状态未知')
    finally:
        if response is not None: await response.aclose()
        if connection is not None: await connection.aclose()
    return result
