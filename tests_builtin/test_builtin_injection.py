"""Builtin response ownership proofs; no production/private config reads."""
from app.services import drive
from tests_builtin.pg_fixture import pg_engine, pg_db


def test_openlist_exact_legacy_fragments_become_one_versioned_authority():
    from app.services import builtin_injection as builtin
    legacy = f'<style>{drive.OPENLIST_THEME_CSS}</style><script>{drive.OPENLIST_THEME_JS}</script>'
    html = '<!doctype html><html><head><meta name="color-scheme" content="light dark">' + legacy + legacy + '<script>window.upstreamKept=1;</script></head><body><div id="root"></div></body></html>'
    out = builtin.transform_html(html, 'drive')
    assert out.count('name="stella-builtin-injection"') == 1
    assert out.count('window.upstreamKept=1;') == 1
    assert '<style>'+drive.OPENLIST_THEME_CSS+'</style>' not in out
    assert '<script>'+drive.OPENLIST_THEME_JS+'</script>' not in out
    assert 'content="normal"' in out
    assert builtin.transform_html(out, 'drive') == out
    assert 'clearPathCache' in out  # permanent functional fix


def test_pg_draft_apply_disable_rollback_fresh_worker(pg_db, pg_engine):
    from app.services import builtin_injection as builtin
    from app.services.integrations_injection import InjectionInput
    from sqlalchemy.orm import Session
    from app.models.config import AppConfig
    import json
    html = '<html><head></head><body><h1>target</h1></body></html>'
    draft = InjectionInput(enabled=True, css='h1{color:red}', js='window.customBuiltin=42;')
    assert builtin.validate_draft(pg_db, 'drive', draft)['valid']
    assert 'window.customBuiltin' not in builtin.transform_html(html, 'drive', pg_db)
    applied = builtin.apply(pg_db, 'drive', '00000000-0000-4000-8000-000000000001')
    assert applied['source'] == 'postgres'
    first = applied['active']['version']
    with Session(pg_engine) as worker:
        assert 'window.customBuiltin=42' in builtin.transform_html(html, 'drive', worker)
        assert builtin.read(worker, 'drive')['active']['version'] == first
    builtin.validate_draft(pg_db, 'drive', draft.model_copy(update={'enabled':False}))
    disabled = builtin.apply(pg_db, 'drive', '00000000-0000-4000-8000-000000000001')
    out = builtin.transform_html(html, 'drive', pg_db)
    assert 'window.customBuiltin' not in out
    assert 'clearPathCache' in out and 'mergeSwitchLayout' in out
    assert disabled['previous']['status'] == 'revoked'
    restored = builtin.rollback(pg_db, 'drive', '00000000-0000-4000-8000-000000000001')
    assert restored['active']['version'] == first
    assert restored['active']['status'] == 'active'
    assert restored['previous']['status'] == 'revoked'
    assert 'window.customBuiltin=42' in builtin.transform_html(html, 'drive', pg_db)
    stored = json.loads(pg_db.get(AppConfig, builtin.KEY).value)
    assert stored['drive']['active']['version'] == first


def test_drive_adapter_uses_central_pg_active(pg_db):
    from app.services import builtin_injection as builtin
    from app.services.integrations_injection import InjectionInput
    builtin.validate_draft(pg_db, 'drive', InjectionInput(enabled=True, js='window.centralDrive=92;'))
    builtin.apply(pg_db, 'drive', '00000000-0000-4000-8000-000000000001')
    assert 'centralDrive=92' in drive.inject_theme_html('<head></head><body></body>', db=pg_db)


def test_isolated_openlist_html_gets_builtin_even_when_custom_off(monkeypatch):
    import asyncio
    import httpx
    from starlette.requests import Request
    from app.services import integrations_proxy as proxy
    from app.services.integrations_injection import InjectionInput
    from types import SimpleNamespace
    response = httpx.Response(200, content=b'<html><head></head><body></body></html>', headers={'content-type':'text/html','etag':'old'}, request=httpx.Request('GET','http://127.0.0.1:12345/'))
    class Connection:
        async def aclose(self): pass
    async def open_response(*args): return Connection(), response
    async def response_headers(*args): return list(response.headers.raw)
    monkeypatch.setattr(proxy,'open_response',open_response)
    monkeypatch.setattr(proxy,'response_headers',response_headers)
    module = {'id':'synthetic','adapter':'openlist','origin':'https://synthetic.invalid','injection':{'active':InjectionInput().model_dump()}}
    req = Request({'type':'http','method':'GET','path':'/','raw_path':b'/','query_string':b'','headers':[],'server':('synthetic.invalid',443),'scheme':'https'})
    out = asyncio.run(proxy.proxy_http(req,module,{'controlled':True,'headers':{}}))
    assert 'clearPathCache' in out.body.decode()
    assert out.body.decode().count('name="stella-builtin-injection"') == 1
    assert 'etag' not in out.headers


def test_management_notice_points_to_existing_security_settings_section():
    from app.services import builtin_injection as builtin
    assert '/settings?section=profile' in builtin.admin_notice_code()
    assert '/settings?section=security' not in builtin.admin_notice_code()


def test_public_probe_reports_only_exact_match_counts_and_hashes():
    from app.services import builtin_injection as builtin
    html='<head><style>'+drive.OPENLIST_THEME_CSS+'</style><script>'+drive.OPENLIST_THEME_JS+'</script><script>window.other="SYNTHETIC-PRIVATE";</script></head><body></body>'
    report=builtin.probe_public_html(html,'drive')
    assert report['legacy_matches']=={'css':1,'js':1}
    assert report['authorities_after']==1 and report['idempotent'] is True
    assert len(report['before_sha256'])==64
    assert 'SYNTHETIC-PRIVATE' not in str(report)


def test_readback_refreshes_a_retained_orm_row_after_other_worker_publish(pg_db,pg_engine):
    from app.services import builtin_injection as builtin
    from app.services.integrations_injection import InjectionInput
    from app.models.config import AppConfig
    from sqlalchemy.orm import Session
    builtin.validate_draft(pg_db,'gallery',InjectionInput(enabled=True,js='window.worker=1;'))
    retained=pg_db.get(AppConfig,builtin.KEY)
    assert builtin.read(pg_db,'gallery')['active']['version']=='preset-v1'
    with Session(pg_engine) as other:
        version=builtin.apply(other,'gallery','00000000-0000-4000-8000-000000000001')['active']['version']
    assert builtin.read(pg_db,'gallery')['active']['version']==version


def test_pg_concurrent_sites_do_not_lose_each_others_draft(pg_db,pg_engine):
    from app.services import builtin_injection as builtin
    from app.services.integrations_injection import InjectionInput
    from sqlalchemy.orm import Session
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier=Barrier(2)
    def update(site):
        with Session(pg_engine) as worker:
            barrier.wait(timeout=5)
            return builtin.validate_draft(worker,site,InjectionInput(css=site))['valid']
    with ThreadPoolExecutor(max_workers=2) as pool: assert all(pool.map(update,['drive','gallery']))
    assert builtin.read(pg_db,'drive')['draft']['css']=='drive'
    assert builtin.read(pg_db,'gallery')['draft']['css']=='gallery'


def test_builtin_nonhtml_stream_never_reads_injection_state(monkeypatch):
    import asyncio,gzip,httpx
    from starlette.requests import Request
    from app.services import builtin_injection as builtin,integrations_proxy as proxy
    raw=gzip.compress(b'window.nativeAsset=true;')
    response=httpx.Response(200,stream=httpx.ByteStream(raw),headers={'content-type':'application/javascript','content-encoding':'gzip','etag':'unchanged'},request=httpx.Request('GET','http://127.0.0.1:12345/asset.js'))
    class Connection:
        async def aclose(self):pass
    async def open_response(*args):return Connection(),response
    async def response_headers(*args):return list(response.headers.raw)
    monkeypatch.setattr(proxy,'open_response',open_response);monkeypatch.setattr(proxy,'response_headers',response_headers)
    def no_db(*args):raise AssertionError('non-HTML must not read builtin AppConfig')
    monkeypatch.setattr(builtin,'read',no_db)
    module={'id':'synthetic','adapter':'openlist','origin':'https://synthetic.invalid','injection':{'active':None}}
    req=Request({'type':'http','method':'GET','path':'/asset.js','raw_path':b'/asset.js','query_string':b'','headers':[],'server':('synthetic.invalid',443),'scheme':'https'})
    async def collect():
        out=await proxy.proxy_http(req,module,{'controlled':True,'headers':{}})
        return b''.join([part async for part in out.body_iterator]),out.headers
    result,headers=asyncio.run(collect())
    assert result==raw and headers['content-encoding']=='gzip' and headers['etag']=='unchanged'
