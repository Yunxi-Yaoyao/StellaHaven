import asyncio
import copy
import hashlib
import pytest
from starlette.requests import Request
from tests_generic_templates.test_generic_templates import api_env, upstream


def test_proxy_exact_migration_dedup_active_only_even_when_disabled(upstream):
    from app.services import integrations_proxy as proxy, integrations_injection as injection
    from app.services.website_templates import export_code
    from app.services.drive import OPENLIST_THEME_CSS, OPENLIST_THEME_JS
    from app.services.website_migration import exact_legacy_signatures
    root,responses,_=upstream
    original='<html><head><style>'+OPENLIST_THEME_CSS+'</style><script>'+OPENLIST_THEME_JS+'</script><script>window.keepMe=1</script><style>body{--untouched:1}</style></head><body>fixture</body></html>'
    responses['/drive/openlist/']=(200,[('Content-Type','text/html')],original.encode())
    active=export_code('drive',main_origin='https://stella.test')|{'version':'fixture-v1','csp_policy':'reject'}
    module={'id':'b'*32,'adapter':'generic','origin':'https://app-'+('b'*32)+'.xiya.live','injection':{'active':active},'migration':{'exact_legacy_sha256':exact_legacy_signatures()}}
    target={'upstream_url':root+'/','allowed_ips':['127.0.0.1'],'headers':{},'controlled':False}
    async def request():
        async def receive():return {'type':'http.request','body':b'','more_body':False}
        req=Request({'type':'http','method':'GET','path':'/drive/openlist/','raw_path':b'/drive/openlist/','query_string':b'','headers':[],'scheme':'https','server':('fixture',443)},receive)
        return await proxy.proxy_http(req,module,target)
    response=asyncio.run(request()); html=response.body.decode()
    assert '<style>'+OPENLIST_THEME_CSS+'</style>' not in html
    assert '<script>'+OPENLIST_THEME_JS+'</script>' not in html
    assert '<script>window.keepMe=1</script>' in html and '--untouched' in html
    assert html.count('name="stella-injection"')==1
    assert 'base_css' not in html and 'base_js' not in html
    assert injection.inject_html(html,module['id'],active)[0]==html
    active['enabled']=False
    response=asyncio.run(request());html=response.body.decode()
    assert 'stella-injection' not in html
    assert '<script>'+OPENLIST_THEME_JS+'</script>' not in html
    assert 'window.keepMe=1' in html


def test_proxy_never_reads_hidden_builtin_code_even_for_legacy_adapter(upstream):
    from app.services import integrations_proxy as proxy
    root,_,_=upstream
    module={'id':'d'*32,'origin':'https://app-'+('d'*32)+'.xiya.live','adapter':'openlist','injection':{'active':None}}
    target={'upstream_url':root+'/','allowed_ips':['127.0.0.1'],'headers':{},'controlled':False}
    def forbidden(site):raise AssertionError('hidden builtin runtime read')
    async def fetch():
        async def receive():return {'type':'http.request','body':b'','more_body':False}
        request=Request({'type':'http','method':'GET','path':'/','raw_path':b'/','query_string':b'','headers':[],'scheme':'https','server':('fixture',443)},receive)
        response=await proxy.proxy_http(request,module,target,builtin_reader=forbidden)
        body=b''.join([chunk async for chunk in response.body_iterator])
        assert b'stella-builtin' not in body
    asyncio.run(fetch())


def test_attachment_html_is_streamed_without_executing_customization(upstream):
    from app.services import integrations_proxy as proxy
    root,responses,_=upstream
    body=b'<html><head></head><body>download</body></html>'
    responses['/download']=(200,[('Content-Type','text/html'),('Content-Disposition','attachment; filename="page.html"'),('ETag','"unchanged"')],body)
    target={'upstream_url':root+'/','allowed_ips':['127.0.0.1'],'headers':{},'controlled':False}
    active={'enabled':True,'version':'v1','css':'body{color:red}','js':'window.no=1','timing':'dom_ready','csp_policy':'reject'}
    module={'id':'c'*32,'origin':'https://app-'+('c'*32)+'.xiya.live','adapter':'generic','injection':{'active':active}}
    async def fetch():
        async def receive():return {'type':'http.request','body':b'','more_body':False}
        request=Request({'type':'http','method':'GET','path':'/download','raw_path':b'/download','query_string':b'','headers':[],'scheme':'https','server':('fixture',443)},receive)
        response=await proxy.proxy_http(request,module,target)
        data=b''.join([chunk async for chunk in response.body_iterator]) if hasattr(response,'body_iterator') else response.body
        assert data==body
        assert response.headers['etag']=='"unchanged"'
        assert response.headers['content-disposition']=='attachment; filename="page.html"'
    asyncio.run(fetch())


def test_migrated_legacy_backend_cannot_write_or_inject(api_env):
    from tests_generic_templates.test_migration import seed
    from app.services.website_migration import migrate_legacy
    from app.routers.drive import router as drive_router
    from app.routers.gallery import router as gallery_router
    from app.routers.builtin_injection import router as builtin_router, assets_router
    from app.routers.service_settings import router as service_router
    c,factory,app,_=api_env
    seed(factory)
    with factory() as db: migrate_legacy(db,approved_ips=['127.0.0.1'],actor_id='00000000-0000-4000-8000-000000000001')
    for router in (drive_router,gallery_router,builtin_router,service_router,assets_router): app.include_router(router)
    for url in ['/drive/openlist/','/drive/connection','/gallery/connection','/builtin-injections/drive','/service-settings/drive','/integration-assets/gallery.js']:
        response=c.get(url)
        assert response.status_code==410,(url,response.text)
