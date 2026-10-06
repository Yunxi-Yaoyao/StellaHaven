"""Standalone: scratch cwd, PYTHONPATH repo, pytest --noconftest.
Only synthetic SQLite and ephemeral real HTTP; application PG connect forbidden.
SQLite verifies rollback/atomic state, NOT PostgreSQL row-lock concurrency.
"""
import os
os.environ.update(STELLA_SECRET_KEY='website-settings-synthetic-signing-key-000000', POSTGRES_HOST='127.0.0.1', POSTGRES_PORT='1', POSTGRES_DB='stella_test_website_settings', POSTGRES_USER='fixture', POSTGRES_PASSWORD='synthetic-only', STELLA_MAIN_ORIGIN='http://stella.test')
import asyncio
import importlib.util
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest

@pytest.fixture
def upstream():
    seen = []
    responses = {}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, dict(self.headers)))
            status, headers, body = responses.get(self.path, (200, [('Content-Type','text/html')], b'<html><head><title>Fixture title</title></head><body>synthetic</body></html>'))
            self.send_response(status)
            for k,v in headers: self.send_header(k,v)
            self.end_headers()
            try: self.wfile.write(body() if callable(body) else body)
            except (BrokenPipeError,ConnectionResetError): pass
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}', responses, seen
    server.shutdown(); server.server_close(); thread.join(3)

def checker():
    assert importlib.util.find_spec('app.services.website_check') is not None, 'draft checker not implemented'
    from app.services import website_check
    return website_check

def run_check(address, **kw):
    return asyncio.run(checker().check_draft(checker().CheckInput(address=address, **kw), parent_origin='http://stella.test'))

def test_unsaved_url_real_http_preserves_path_query_hash_without_database(upstream):
    root, responses, seen = upstream
    result = run_check(root+'/edited?q=1#anchor')
    assert result['normalized_url'] == root+'/edited?q=1#anchor'
    assert result['name_suggestion'] == 'Fixture title'
    assert result['access'] == {'status':'reachable','http_status':200}
    assert result['embedding']['status'] == 'allowed'
    assert '浏览器' in result['embedding']['reason']
    assert result['injection']['status'] == 'supported'
    assert result['can_save'] is True
    assert [v[0] for v in seen] == ['/edited?q=1']
    assert not any(k.lower() in {'cookie','authorization','referer'} for k in seen[0][1])

@pytest.mark.parametrize('headers,body,status,injection', [
    ([('Content-Security-Policy', "frame-ancestors 'none'")], b'', 'blocked','unsupported'),
    ([('Content-Security-Policy', "frame-ancestors 'self'")], b'', 'blocked','unsupported'),
    ([('Content-Security-Policy', 'frame-ancestors http://stella.test')], b'', 'allowed','unsupported'),
    ([('Content-Security-Policy', 'frame-ancestors http://stella.test'),('Content-Security-Policy', "frame-ancestors 'none'")], b'', 'blocked','unsupported'),
    ([('Content-Security-Policy', 'frame-ancestors http://stella.test'),('X-Frame-Options','DENY')], b'', 'allowed','unsupported'),
    ([('Content-Security-Policy', "default-src 'none'")], b'', 'allowed','unsupported'),
    ([('Content-Security-Policy-Report-Only', "frame-ancestors 'none'")], b'', 'allowed','supported'),
    ([('X-Frame-Options','DENY')], b'', 'blocked','unsupported'),
    ([('X-Frame-Options','SAMEORIGIN')], b'', 'blocked','unsupported'),
    ([('X-Frame-Options','ALLOW-FROM http://stella.test')], b'', 'unknown','unsupported'),
    ([], b'<meta http-equiv="Content-Security-Policy" content="frame-ancestors \'none\'">', 'allowed','unsupported'),
])
def test_actual_document_policies_not_http_200_readiness(upstream,headers,body,status,injection):
    root,responses,seen = upstream
    responses['/policy'] = (200, [('Content-Type','text/html')] + headers, body)
    result = run_check(root+'/policy')
    assert result['embedding']['status'] == status
    assert result['injection']['status'] == injection
    assert result['can_save'] == (status == 'allowed')
    if status == 'blocked':
        assert result['help']['location'] is None  # Unknown deployment: no invented filename.
        external = run_check(root+'/policy', open_behavior='external')
        assert external['can_save'] is True

@pytest.mark.parametrize('address', ['http://user:secret@127.0.0.1/', 'http://169.254.169.254/', 'http://[::ffff:169.254.169.254]/', 'http://100.100.100.200/', 'http://metadata.google.internal/', 'file:///etc/passwd', 'https://example.com:0/', 'http://127.0.0.1/../admin', 'http://127.0.0.1/%0d%0aHost:evil'])
def test_dangerous_draft_is_structured_blocked(address):
    result = run_check(address, open_behavior='external')
    assert result['access']['status'] == 'blocked'
    assert result['can_save'] is False
    assert result['embedding']['reason_code'] == 'unsafe_address'
    assert 'secret' not in str(result)

def test_bare_domain_normalization_preserves_components():
    assert checker().normalize_url('例子.测试/path?q=1#x') == 'https://xn--fsqu00a.xn--0zwm56d/path?q=1#x'

def test_redirects_recheck_destination_and_never_forward_cookies(upstream):
    root, responses, seen = upstream
    responses['/start'] = (302, [('Location','/next'),('Set-Cookie','secret=never')], b'')
    result = run_check(root+'/start')
    assert result['access']['http_status'] == 200
    assert [v[0] for v in seen] == ['/start','/next']
    assert not any(k.lower() == 'cookie' for k in seen[-1][1])
    responses['/next'] = (302, [('Location','http://169.254.169.254/latest?secret=bad')], b'')
    result = run_check(root+'/start')
    assert result['access']['status'] == 'blocked'
    assert result['can_save'] is False
    assert 'secret=bad' not in str(result)

def test_redirect_count_and_body_size_are_bounded(upstream):
    root,responses,seen = upstream
    responses['/loop'] = (302, [('Location','/loop')], b'')
    result = run_check(root+'/loop')
    assert len(seen) == 4  # initial request + 3 redirects
    assert result['embedding']['reason_code'] == 'redirect_limit'
    responses['/large'] = (200, [('Content-Type','text/html')], b'x'*(512*1024+1))
    result = run_check(root+'/large')
    assert result['embedding']['reason_code'] == 'body_limit'
    assert not result['can_save']

@pytest.mark.parametrize('http_status,access', [(401,'login_required'),(403,'blocked'),(500,'unknown')])
def test_authentication_and_error_response_are_not_ready(upstream,http_status,access):
    root,responses,seen = upstream
    responses['/auth'] = (http_status, [('Content-Type','text/html')], b'')
    result = run_check(root+'/auth')
    assert result['access']['status'] == access
    assert result['injection']['status'] != 'supported'
    assert result['can_save'] is False

def test_mixed_content_and_real_dns_failure(upstream):
    root,_,_ = upstream
    result = asyncio.run(checker().check_draft(checker().CheckInput(address=root),parent_origin='https://stella.xiya.live'))
    assert result['embedding']['reason_code'] == 'mixed_content'
    assert not result['can_save']
    result = run_check('https://synthetic-website-settings.invalid/')
    assert result['access']['status'] == 'unknown'
    assert result['embedding']['reason_code'] == 'dns_failed'

def test_known_quota_help_names_only_verified_configuration():
    help = checker().frame_help('https://quota.xiya.live/')
    assert help['location'] == '/etc/nginx/conf.d/quota.conf'
    assert any('LAN' in s and 'ACL' in s for s in help['instructions'])

@pytest.fixture
def api_env():
    import json
    from types import SimpleNamespace
    from uuid import UUID
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db, engine as unused_pg
    from app.models.config import AppConfig
    from app.routers.auth import current_user, admin_user
    from app.routers.integrations import router as legacy
    router = None
    if importlib.util.find_spec('app.routers.website_settings') is not None:
        from app.routers.website_settings import router
    def forbid(*a, **kw): raise AssertionError('Production/development PG connection forbidden')
    event.listen(unused_pg,'do_connect',forbid)
    engine = create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    AppConfig.__table__.create(engine)
    factory = sessionmaker(engine,expire_on_commit=False)
    app=FastAPI()
    if router is not None: app.include_router(router)
    app.include_router(legacy)
    owner=SimpleNamespace(id=UUID('00000000-0000-4000-8000-000000000001'))
    admin_calls=[]
    def admin(): admin_calls.append(True); return owner
    def database():
        with factory() as db:
            try: yield db
            finally: db.rollback()
    app.dependency_overrides.update({get_db:database,current_user:lambda:owner,admin_user:admin})
    with TestClient(app,base_url='http://stella.test') as c:
        yield c,factory,app,admin_calls
    engine.dispose(); event.remove(unused_pg,'do_connect',forbid)

def test_new_save_check_is_readonly_and_idempotent_atomic_nav(upstream,api_env):
    import json
    from app.models.config import AppConfig
    from app.services import integrations as store
    root,responses,seen=upstream
    c,f,app,admin_calls=api_env
    with f() as db: before=db.query(AppConfig).count()
    result=c.post('/website-settings/check',json={'address':root+'/new?q=1#hash'})
    assert result.status_code==200,result.text
    with f() as db: assert db.query(AppConfig).count()==before
    assert admin_calls == []
    data=dict(address=root+'/new?q=1#hash',name='New website',icon='star',visible=False,keep_alive=True,idempotency_key='synthetic-new-001')
    saved=c.post('/website-settings',json=data)
    assert saved.status_code==201,saved.text
    website=saved.json(); mid=website['id']
    assert website['browser_url']==data['address']
    assert website['check']['normalized_url']==data['address']
    assert len(admin_calls)==1
    reread=c.get('/external-modules/'+mid).json()
    assert reread=={k:v for k,v in website.items() if k!='check'}
    nav=next(e for e in c.get('/navigation').json()['entries'] if e['id']==mid)
    assert (nav['title'],nav['icon'],nav['visible'])==('New website','star',False)
    retry=c.post('/website-settings',json=data)
    assert retry.status_code==201,retry.text
    assert retry.json()==website
    assert c.post('/website-settings',json=data|{'name':'collision'}).status_code==409
    with f() as db:
        config=store.state(db)
        assert len(config['modules'])==1 and config['targets']=={}
        assert str(db.query(AppConfig).all())  # persistent read from separate session

def test_edited_url_fresh_check_blocks_save_without_any_partial_state(upstream,api_env):
    from app.models.config import AppConfig
    root,responses,seen=upstream
    c,f,_,_=api_env
    original=c.post('/website-settings',json=dict(address=root+'/old',name='Original',icon='globe',idempotency_key='edit-test-001')).json()
    mid=original['id']
    with f() as db: before=db.get(AppConfig,'integrations_v1').value
    responses['/blocked']=(200,[('Content-Type','text/html'),('Content-Security-Policy',"frame-ancestors 'none'")],b'')
    seen.clear()
    draft=c.post('/website-settings/check',json={'address':root+'/blocked'})
    assert draft.json()['embedding']['status']=='blocked'
    edited=dict(address=root+'/blocked',name='Edited',icon='book',visible=False)
    result=c.patch('/website-settings/'+mid,json=edited)
    assert result.status_code==422,result.text
    assert result.json()['detail']['code']=='website_check_failed'
    assert result.json()['detail']['check']['normalized_url']==root+'/blocked'
    assert [s[0] for s in seen]==['/blocked','/blocked']
    with f() as db: assert db.get(AppConfig,'integrations_v1').value==before
    result=c.patch('/website-settings/'+mid,json=edited|{'open_behavior':'external'})
    assert result.status_code==200,result.text
    assert result.json()['id']==mid and result.json()['mode']=='link'
    assert c.get('/external-modules/'+mid).json()['browser_url']==root+'/blocked'

def test_edit_preserves_id_revokes_identity_grants_and_syncs_legacy_overrides(upstream,api_env):
    from app.services import integrations as store
    from uuid import UUID
    root,_,_=upstream
    c,f,_,_=api_env
    old=c.post('/website-settings',json=dict(address=root+'/old',idempotency_key='revocation-test-001')).json();mid=old['id']
    with f() as db:
        with store.edit(db) as config:
            config['tickets']['old-ticket']={'id':mid}
            config['grants']['old-grant']={'id':mid}
            config['navigation'][0].update(title='Stale navigation',icon='heart')
    result=c.patch('/website-settings/'+mid,json=dict(address=root+'/edited?q=2#new',name='One authority',icon='book',visible=False,keep_alive=True))
    assert result.status_code==200,result.text
    assert result.json()['id']==mid and result.json()['keep_alive'] is True
    nav=next(e for e in c.get('/navigation').json()['entries'] if e['id']==mid)
    assert (nav['title'],nav['icon'],nav['visible'])==('One authority','book',False)
    with f() as db:
        state=store.state(db)
        assert not state['grants'] and not state['tickets']
    # Legacy rename must not reintroduce shadow names/icons either.
    r=c.patch('/external-modules/'+mid,json={'name':'Legacy rename','icon':'star'})
    assert r.status_code==200,r.text
    nav=next(e for e in c.get('/navigation').json()['entries'] if e['id']==mid)
    assert (nav['title'],nav['icon'],nav['visible'])==('Legacy rename','star',False)

def test_custom_first_save_and_edit_versions_are_atomic_headerfree_uncontrolled(upstream,api_env):
    from app.services import integrations as store
    root,_,_=upstream
    c,f,_,_=api_env
    data=dict(address=root+'/custom?q=1#hash',name='Custom',icon='star',idempotency_key='custom-first-001',custom={'enabled':True,'css':'body { color: red; }','js':'document.body.dataset.test="one"','timing':'dom_ready'})
    r=c.post('/website-settings',json=data)
    assert r.status_code==201,r.text
    saved=r.json();mid=saved['id']
    assert saved['mode']=='isolated_proxy'
    assert saved['injection']['active']['js']==data['custom']['js']
    assert saved['injection']['active']['version']
    with f() as db:
        state=store.state(db);target=state['targets'][saved['target_id']]
        assert target['headers']=={} and target['controlled'] is False
        assert target['allowed_ips']==['127.0.0.1']
        assert saved['initial_path']=='/custom?q=1#hash'
    r=c.patch('/website-settings/'+mid,json={k:v for k,v in data.items() if k!='idempotency_key'}|{'name':'V2','custom':data['custom']|{'css':'body { color: blue; }'}})
    assert r.status_code==200,r.text
    current=r.json()
    assert current['id']==mid and current['target_id']==saved['target_id']
    assert current['injection']['previous']==saved['injection']['active']
    assert current['injection']['active']['version']!=saved['injection']['active']['version']
    rollback=c.post('/external-modules/'+mid+'/injection/rollback')
    assert rollback.status_code==200,rollback.text
    assert rollback.json()['active']==saved['injection']['active']

def test_invalid_custom_syntax_never_creates_module_target_or_audit(upstream,api_env):
    from app.models.config import AppConfig
    root,_,_=upstream;c,f,_,_=api_env
    bad=dict(address=root,icon='globe',idempotency_key='invalid-code-001',custom={'enabled':True,'js':'function {'})
    r=c.post('/website-settings',json=bad)
    assert r.status_code==422,r.text
    with f() as db: assert db.query(AppConfig).count()==0

def test_origin_change_never_transfers_credentials_or_active_scripts(upstream,api_env):
    from app.services import integrations as store
    root,_,_=upstream;c,f,_,_=api_env
    old=c.post('/website-settings',json=dict(address=root, idempotency_key='cross-origin-001',custom={'enabled':True,'css':'body {color:red}'})).json()
    assert old['mode']=='isolated_proxy'
    mid=old['id'];tid=old['target_id']
    with f() as db:
        with store.edit(db) as config:
            config['targets'][tid]['headers']={'authorization':'SYNTHETIC-DO-NOT-TRANSFER'}
            config['targets'][tid]['controlled']=True
    changed=root.replace('127.0.0.1','localhost')+'/new'
    r=c.patch('/website-settings/'+mid,json=dict(address=changed,name='New identity',icon='book'))
    assert r.status_code==200,r.text
    assert r.json()['injection']['active'] is None
    assert r.json()['injection']['draft']['css']==old['injection']['active']['css']
    assert r.json()['injection']['draft']['enabled'] is False
    assert r.json()['injection']['previous']['version']==old['injection']['active']['version']
    assert c.post('/external-modules/'+mid+'/injection/rollback').status_code==409
    r=c.patch('/website-settings/'+mid,json=dict(address=changed,name='Explicit new apply',icon='book',custom={'enabled':True,'css':'body {color:blue}'}))
    assert r.status_code==200,r.text
    with f() as db:
        state=store.state(db);target=state['targets'][r.json()['target_id']]
        assert r.json()['target_id']!=tid
        assert target['headers']=={} and target['controlled'] is False
        assert state['targets'][tid]['headers']=={'authorization':'SYNTHETIC-DO-NOT-TRANSFER'}
    assert c.post('/external-modules/'+mid+'/injection/rollback').status_code==409

def test_navigation_write_is_the_same_module_name_icon_authority(upstream,api_env):
    root,_,_=upstream;c,_,_,_=api_env
    saved=c.post('/website-settings',json=dict(address=root,idempotency_key='nav-authority-001')).json();mid=saved['id']
    result=c.put('/navigation',json={'entries':[{'id':mid,'title':'Navigation edit','icon':'heart','visible':False}]})
    assert result.status_code==200,result.text
    reread=c.get('/external-modules/'+mid).json()
    assert (reread['name'],reread['icon'])==('Navigation edit','heart')

def test_custom_disable_retains_same_identity_proxy_for_version_rollback(upstream,api_env):
    root,_,_=upstream;c,_,_,_=api_env
    old=c.post('/website-settings',json=dict(address=root,idempotency_key='disable-001',custom={'enabled':True,'css':'body{color:red}'})).json()
    r=c.patch('/website-settings/'+old['id'],json=dict(address=root,custom={'enabled':False,'css':'body{color:blue}'}))
    assert r.status_code==200,r.text
    assert r.json()['mode']=='isolated_proxy'
    assert r.json()['target_id']==old['target_id']
    assert r.json()['injection']['active']['enabled'] is False
    r=c.post('/external-modules/'+old['id']+'/injection/rollback')
    assert r.status_code==200,r.text
    assert r.json()['active']==old['injection']['active']

def test_explicit_external_never_preserves_active_proxy_mode(upstream,api_env):
    root,_,_=upstream;c,_,_,_=api_env
    old=c.post('/website-settings',json=dict(address=root,idempotency_key='external-mode-001',custom={'enabled':True,'css':'body{color:red}'})).json()
    r=c.patch('/website-settings/'+old['id'],json=dict(address=root,open_behavior='external'))
    assert r.status_code==200,r.text
    assert r.json()['mode']=='link' and r.json()['target_id'] is None
    assert r.json()['injection']['active'] is None

def test_real_transaction_fault_rolls_back_module_target_nav_keys_and_audit(upstream,api_env,monkeypatch):
    from app.services import integrations as store
    from app.models.config import AppConfig
    root,_,_=upstream;c,f,_,_=api_env
    def fail(*a,**k): raise RuntimeError('synthetic audit fault inside transaction')
    monkeypatch.setattr(store,'record_change',fail)
    with pytest.raises(RuntimeError,match='synthetic audit fault'):
        c.post('/website-settings',json=dict(address=root,idempotency_key='rollback-001',custom={'enabled':True,'css':'body{color:red}'}))
    with f() as db: assert db.query(AppConfig).count()==0

def test_checker_standalone_does_not_import_database_or_create_pg_engine(upstream):
    import subprocess,sys
    root,_,seen=upstream
    # Existing app.services.__init__ eagerly imports unrelated ORM services.
    # Isolate its package namespace, not the checker/transport under test.
    source = 'import sys,types,pathlib,asyncio; package=types.ModuleType("app.services"); package.__path__=[str(pathlib.Path(__import__("app").__file__).parent/"services")]; sys.modules["app.services"]=package; from app.services.website_check import check_draft,CheckInput; r=asyncio.run(check_draft(CheckInput(address=sys.argv[1]),parent_origin="http://stella.test")); assert r["access"]["status"]=="reachable",r; assert "app.database" not in sys.modules, "pure checker imported PG"'
    result=subprocess.run([sys.executable,'-c',source,root+'/standalone'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert [path for path,_ in seen]==['/standalone']

@pytest.mark.parametrize('address',['http://192.0.0.8/','http://198.18.0.1/','http://192.0.2.1/','http://[2001:db8::1]/'])
def test_special_reserved_ranges_are_not_mistaken_for_self_hosted_private(address):
    result=run_check(address,open_behavior='external')
    assert result['access']['status']=='blocked'
    assert result['can_save'] is False

def test_global_probe_capacity_is_bounded(upstream):
    import time
    root,responses,seen=upstream
    responses['/capacity']=(200,[('Content-Type','text/html')],lambda: (time.sleep(.4),b'<html/>')[1])
    async def concurrent():
        return await asyncio.gather(*(checker().check_draft(checker().CheckInput(address=root+'/capacity'),parent_origin='http://stella.test') for _ in range(6)))
    results=asyncio.run(concurrent())
    assert len(seen)<=4
    assert sum(r['embedding']['reason_code']=='busy' for r in results)>=2

def test_invalid_css_is_rejected_before_transaction(upstream,api_env):
    from app.models.config import AppConfig
    root,_,_=upstream;c,f,_,_=api_env
    r=c.post('/website-settings',json=dict(address=root,idempotency_key='invalid-css-001',custom={'enabled':True,'css':')'}))
    assert r.status_code==422,r.text
    assert any('CSS' in issue for issue in r.json()['detail']['check']['issues'])
    with f() as db: assert db.query(AppConfig).count()==0

def test_dns_change_between_check_and_target_commit_is_rejected(upstream,api_env,monkeypatch):
    from app.services import integrations_proxy as proxy
    from app.models.config import AppConfig
    root,_,_=upstream;c,f,_,_=api_env
    real = proxy._preview_addresses;calls=[]
    def changing(root):
        calls.append(root)
        return real(root) if len(calls)==1 else ['127.0.0.2']
    monkeypatch.setattr(proxy,'_preview_addresses',changing)
    r=c.post('/website-settings',json=dict(address=root,idempotency_key='changed-dns-001',custom={'enabled':True,'css':'body{color:red}'}))
    assert r.status_code==422,r.text
    with f() as db: assert db.query(AppConfig).count()==0

def test_real_socket_pin_rebinding_and_no_secret_forwarding(upstream,monkeypatch):
    from app.services import integrations_proxy as proxy
    root,_,seen=upstream
    real=proxy.socket.getaddrinfo;lookups=[]
    def dns(host,port,*args,**kwargs):
        if host=='pin.website.test':
            lookups.append(host)
            return real('127.0.0.1',port,*args,**kwargs)
        return real(host,port,*args,**kwargs)
    monkeypatch.setattr(proxy.socket,'getaddrinfo',dns)
    result=run_check(root.replace('127.0.0.1','pin.website.test')+'/pinned')
    assert result['access']['status']=='reachable'
    assert len(lookups)==2
    assert seen[0][1]['Host'].startswith('pin.website.test:')
    seen.clear();lookups.clear()
    def rebinding(host,port,*args,**kwargs):
        if host=='pin.website.test':
            lookups.append(host)
            return real('127.0.0.1' if len(lookups)==1 else '169.254.169.254',port,*args,**kwargs)
        return real(host,port,*args,**kwargs)
    monkeypatch.setattr(proxy.socket,'getaddrinfo',rebinding)
    result=run_check(root.replace('127.0.0.1','pin.website.test')+'/pinned')
    assert result['access']['status']=='blocked'
    assert result['can_save'] is False and not seen

def test_real_slow_body_stops_at_eight_second_total_budget(upstream):
    import time
    root,responses,_=upstream
    responses['/slow']=(200,[('Content-Type','text/html')],lambda:(time.sleep(9),b'<html/>')[1])
    begin=time.monotonic();result=run_check(root+'/slow');elapsed=time.monotonic()-begin
    assert result['embedding']['reason_code']=='timeout'
    assert 7.8<=elapsed<8.8
    assert result['can_save'] is False

def test_real_tls_self_signed_certificate_is_not_bypassed(tmp_path):
    import subprocess,ssl
    cert=tmp_path/'cert.pem';key=tmp_path/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-keyout',str(key),'-out',str(cert)],check=True,capture_output=True)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200);self.end_headers();self.wfile.write(b'<html/>')
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        result=run_check(f'https://localhost:{server.server_port}/')
        assert result['embedding']['reason_code']=='certificate_failed'
        assert result['can_save'] is False
    finally: server.shutdown();server.server_close();thread.join(3)

def test_real_auth_identity_elevation_expiry_revoke_and_readonly_check(upstream,api_env,monkeypatch):
    import json,time
    from datetime import datetime,timedelta,timezone
    from sqlalchemy import event
    from app.routers.auth import current_user,admin_user
    from app.models.user import User,AuthSession
    from app.models.config import AppConfig
    from app.services.admin_security import STATE_KEY
    from app.security import make_access_token,hash_password
    root,_,seen=upstream;c,f,app,_=api_env
    monkeypatch.delenv('STELLA_OWNER_ID',raising=False)
    app.dependency_overrides.pop(current_user);app.dependency_overrides.pop(admin_user)
    engine=f.kw['bind']
    User.__table__.create(engine);AuthSession.__table__.create(engine)
    with f() as db:
        owner=User(username='synthetic-owner',display_name='Synthetic owner',is_active=True,password_hash=hash_password('synthetic-daily-only'))
        db.add(owner);db.flush();uid=owner.id
        session=AuthSession(user_id=uid,refresh_hash='synthetic-refresh',remember=True);db.add(session);db.flush();sid=session.id
        state=dict(owner_id=str(uid),enabled=True,password_hash=hash_password('synthetic-independent-admin'),version=1,grants={})
        db.add(AppConfig(key=STATE_KEY,value=json.dumps(state)));db.commit()
    payload=dict(address=root,idempotency_key='actual-auth-001')
    assert c.post('/website-settings/check',json={'address':root}).status_code==401
    c.cookies.set('stella_at',make_access_token(str(uid),str(sid)))
    statements=[]
    def record(conn,cursor,sql,*args): statements.append(sql.lower())
    event.listen(engine,'before_cursor_execute',record)
    try:
        r=c.post('/website-settings/check',json={'address':root})
        assert r.status_code==200,r.text
    finally: event.remove(engine,'before_cursor_execute',record)
    assert statements and not any(any(word in sql for word in ['insert ','update ','delete ','for update','advisory']) for sql in statements)
    seen.clear()
    denied=c.post('/website-settings',json=payload)
    assert denied.status_code==403 and denied.json()['detail']['code']=='admin_elevation_required'
    assert not seen
    with f() as db:
        row=db.get(AppConfig,STATE_KEY);state=json.loads(row.value)
        state['grants'][str(sid)]={'version':1,'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        row.value=json.dumps(state);db.commit()
    r=c.post('/website-settings',json=payload)
    assert r.status_code==201,r.text
    with f() as db:
        assert db.get(User,uid).id==uid
        row=db.get(AppConfig,STATE_KEY);state=json.loads(row.value);assert state['owner_id']==str(uid)
        state['grants'][str(sid)]['expires_at']='2000-01-01T00:00:00+00:00';row.value=json.dumps(state);db.commit()
    assert c.patch('/website-settings/'+r.json()['id'],json={'address':root}).status_code==403
    with f() as db: db.get(AuthSession,sid).revoked=True;db.commit()
    seen.clear()
    assert c.post('/website-settings/check',json={'address':root}).status_code==401
    assert not seen
    # Missing persisted identity must fail closed without initializing it during a draft check.
    with f() as db:
        db.get(AuthSession,sid).revoked=False
        row=db.get(AppConfig,STATE_KEY);state=json.loads(row.value);state.pop('owner_id');row.value=json.dumps(state);db.commit();before=row.value
    r=c.post('/website-settings/check',json={'address':root})
    assert r.status_code==503,r.text
    with f() as db: assert db.get(AppConfig,STATE_KEY).value==before

def test_null_meta_attribute_is_untrusted_html_not_a_server_error(upstream):
    root,responses,_=upstream
    responses['/meta-null']=(200,[('Content-Type','text/html')],b'<html><meta http-equiv><meta http-equiv="content-security-policy" content="default-src self"></html>')
    result=run_check(root+'/meta-null')
    assert result['access']['status']=='reachable'
    assert result['injection']['status']=='unsupported'

def test_disabled_custom_edit_uses_the_edited_start_path(upstream,api_env):
    root,_,_=upstream;c,_,_,_=api_env
    old=c.post('/website-settings',json=dict(address=root+'/old',idempotency_key='disabled-path-001',custom={'enabled':True,'css':'body{color:red}'})).json()
    r=c.patch('/website-settings/'+old['id'],json=dict(address=root+'/new?q=2#hash',custom={'enabled':False,'css':'body{color:red}'}))
    assert r.status_code==200,r.text
    assert r.json()['initial_path']=='/new?q=2#hash'

def test_known_lan_quota_network_failure_still_has_verified_help(monkeypatch):
    import socket
    from app.services import integrations_proxy as proxy
    def no_dns(*a,**k): raise socket.gaierror('synthetic DNS failure')
    monkeypatch.setattr(proxy.socket,'getaddrinfo',no_dns)
    result=run_check('https://quota.xiya.live/')
    assert result['access']['status']=='unknown'
    assert result['help']['location']=='/etc/nginx/conf.d/quota.conf'

def test_actual_downstream_wire_save_readback_retry_and_edited_block(upstream,api_env):
    import socket,time,httpx,uvicorn
    root,responses,seen=upstream;_,f,app,_=api_env
    sock=socket.socket();sock.bind(('127.0.0.1',0))
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try:
        deadline=time.monotonic()+5
        while not server.started and thread.is_alive() and time.monotonic()<deadline: time.sleep(.01)
        assert server.started
        with httpx.Client(base_url=f'http://127.0.0.1:{sock.getsockname()[1]}',trust_env=False,timeout=12) as wire:
            body=dict(address=root+'/wire?q=1#hash',name='Actual wire',icon='book',visible=False,idempotency_key='wire-save-001')
            checked=wire.post('/website-settings/check',json={'address':body['address']},headers={'Cookie':'synthetic-main-only=never','Authorization':'SYNTHETIC-MAIN-ONLY'})
            assert checked.status_code==200,checked.text
            saved=wire.post('/website-settings',json=body)
            assert saved.status_code==201,saved.text
            mid=saved.json()['id']
            reread=wire.get('/external-modules/'+mid)
            assert reread.status_code==200 and reread.json()=={k:v for k,v in saved.json().items() if k!='check'}
            assert wire.post('/website-settings',json=body).json()==saved.json()
            responses['/wire-blocked']=(200,[('Content-Type','text/html'),('X-Frame-Options','DENY')],b'<html/>')
            rejected=wire.patch('/website-settings/'+mid,json={'address':root+'/wire-blocked','name':'not committed'})
            assert rejected.status_code==422 and rejected.json()['detail']['code']=='website_check_failed'
            assert wire.get('/external-modules/'+mid).json()==reread.json()
            assert not any(k.lower() in {'cookie','authorization','referer'} for _,headers in seen for k in headers)
    finally:
        server.should_exit=True;thread.join(5);sock.close()
    assert not thread.is_alive()


def test_version_binding_is_internal_not_a_new_frontend_response_field(upstream,api_env):
    root,_,_=upstream;c,_,_,_=api_env
    saved=c.post('/website-settings',json=dict(address=root,idempotency_key='binding-shape-001',custom={'enabled':True,'css':'body{color:red}'})).json()
    assert set(saved['injection']['active'])=={'enabled','css','js','timing','csp_policy','version'}

def test_new_icon_values_match_frontend_navigation_allowlist(upstream,api_env):
    root,_,seen=upstream;c,_,_,_=api_env
    r=c.post('/website-settings',json=dict(address=root,idempotency_key='unsupported-icon-001',icon='music'))
    assert r.status_code==422,r.text
    assert not seen

def test_partial_edit_preserves_existing_display_and_behavior(upstream,api_env):
    root,_,_=upstream;c,_,_,_=api_env
    old=c.post('/website-settings',json=dict(address=root+'/old',name='Keep name',icon='book',visible=False,keep_alive=True,open_behavior='external',idempotency_key='partial-patch-001')).json()
    r=c.patch('/website-settings/'+old['id'],json={'address':root+'/new'})
    assert r.status_code==200,r.text
    assert (r.json()['name'],r.json()['icon'],r.json()['keep_alive'],r.json()['mode'])==('Keep name','book',True,'link')
    row=next(e for e in c.get('/navigation').json()['entries'] if e['id']==old['id'])
    assert row['visible'] is False

def test_persisted_custom_version_transforms_real_upstream_only_in_isolated_response(upstream,api_env):
    from starlette.requests import Request
    from app.services import integrations as store,integrations_proxy as proxy
    root,_,seen=upstream;c,f,_,_=api_env
    saved=c.post('/website-settings',json=dict(address=root+'/rendered',idempotency_key='real-injection-001',custom={'enabled':True,'css':'body{color:red}','js':'document.body.dataset.test="saved"'})).json()
    with f() as db:
        config=store.state(db);module=config['modules'][saved['id']];target=config['targets'][saved['target_id']]
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','scheme':'https','method':'GET','path':'/rendered','raw_path':b'/rendered','query_string':b'','headers':[(b'host',module['origin'].removeprefix('https://').encode())],'server':('synthetic',443),'client':('127.0.0.1',1)}
    async def receive(): return {'type':'http.request','body':b'','more_body':False}
    response=asyncio.run(proxy.proxy_http(Request(scope,receive),module,target))
    assert response.status_code==200
    html=response.body.decode()
    assert f'content="{module["id"]}:{module["injection"]["active"]["version"]}"' in html
    assert 'document.body.dataset.test' in html
    assert 'content-security-policy' not in response.headers  # Uncontrolled/header-free stays header-free.
    assert response.headers['cache-control']=='private, no-store'
    assert target['headers']=={} and target['controlled'] is False

def test_patch_idempotency_preserves_applied_version(upstream,api_env):
    root,_,_=upstream;c,_,_,_=api_env
    first=c.post('/website-settings',json=dict(address=root,idempotency_key='patch-key-first-001')).json()
    body=dict(address=root+'/edited',name='Patch',icon='star',visible=False,idempotency_key='patch-key-second-001',custom={'enabled':True,'css':'body{color:red}'})
    applied=c.patch('/website-settings/'+first['id'],json=body)
    assert applied.status_code==200,applied.text
    retry=c.patch('/website-settings/'+first['id'],json=body)
    assert retry.status_code==200 and retry.json()==applied.json()
    assert c.patch('/website-settings/'+first['id'],json=body|{'name':'collision'}).status_code==409

def test_utf16_html_cannot_be_declared_injectable(upstream):
    root,responses,_=upstream
    responses['/utf16']=(200,[('Content-Type','text/html; charset=utf-16')],'<html><meta http-equiv="Content-Security-Policy" content="default-src self"></html>'.encode('utf-16'))
    result=run_check(root+'/utf16',custom_enabled=True)
    assert result['injection']['status']=='unsupported'
    assert result['can_save'] is False

def test_malformed_csp_port_is_uncertain_not_a_500(upstream):
    root,responses,_=upstream
    responses['/port']=(200,[('Content-Type','text/html'),('Content-Security-Policy','frame-ancestors http://stella.test:'+('9'*5000))],b'<html/>')
    result=run_check(root+'/port')
    assert result['embedding']['status']=='unknown'
    assert result['can_save'] is False

def test_delete_entry_cleans_private_version_metadata_but_keeps_retry_tombstone(upstream,api_env):
    from app.services import integrations as store
    root,_,_=upstream;c,f,_,_=api_env
    body=dict(address=root,idempotency_key='metadata-delete-001',custom={'enabled':True,'css':'body{color:red}'})
    saved=c.post('/website-settings',json=body).json();mid=saved['id']
    assert c.patch('/website-settings/'+mid,json={'address':root.replace('127.0.0.1','localhost')}).status_code==200
    assert c.delete('/external-modules/'+mid).status_code==204
    with f() as db:
        config=store.state(db)
        assert mid not in config.get('website_version_origins',{})
        assert mid not in config.get('website_retired_versions',{})
    assert c.post('/website-settings',json=body).status_code==409
