"""Independent contract probes. Expected safety invariants; no product edits.
Run with review_isolation_extra and the immutable source snapshot on PYTHONPATH.
Authentication is fixture-stubbed; only owned loopback HTTP + in-memory SQLite.
"""
import asyncio
import copy
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import pytest
from tests_generic_templates.test_generic_templates import api_env, upstream


@pytest.mark.parametrize('operation', ['check', 'save'])
def test_saved_token_must_remain_bound_to_saved_dns_ips(api_env, upstream, monkeypatch, operation):
    from app.services import integrations as store
    c, factory, _, _ = api_env
    root, _, first_seen = upstream
    port = urlsplit(root).port
    second_seen = []
    class OtherHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            second_seen.append(bool(self.headers.get('Authorization')))
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><head></head><body>second endpoint</body></html>')
        def log_message(self, *args): pass
    other = ThreadingHTTPServer(('127.0.0.2', port), OtherHandler)
    thread = threading.Thread(target=other.serve_forever, daemon=True)
    thread.start()
    actual_dns = socket.getaddrinfo
    current_ip = ['127.0.0.1']
    def synthetic_dns(host, port, *args, **kwargs):
        return actual_dns(current_ip[0] if host == 'saved-target.review.test' else host, port, *args, **kwargs)
    monkeypatch.setattr(socket, 'getaddrinfo', synthetic_dns)
    address = f'http://saved-target.review.test:{port}/base/'
    try:
        initial = c.post('/website-settings', json={'address': address, 'idempotency_key': 'review-dns-'+operation,
            'connection': {'transport': 'proxy', 'auth_mode': 'header', 'token': 'SYNTHETIC-REVIEW-ONLY'}})
        assert initial.status_code == 201, initial.text
        mid = initial.json()['id']
        with factory() as db:
            assert store.state(db)['targets'][initial.json()['target_id']]['allowed_ips'] == ['127.0.0.1']
        first_seen.clear()
        current_ip[0] = '127.0.0.2'
        if operation == 'check':
            result = c.post('/website-settings/check', json={'address': address, 'module_id': mid})
        else:
            result = c.patch('/website-settings/'+mid, json={'address': address, 'name': 'Metadata only'})
        print({'operation':operation,'status':result.status_code,'new_endpoint_received_saved_header':any(second_seen)})
        assert not any(second_seen), 'Saved header was sent to newly resolved IP outside the saved target pin'
    finally:
        other.shutdown(); other.server_close(); thread.join(3)


@pytest.mark.parametrize('different_browser',[False,True])
def test_legacy_proxy_get_to_frontend_patch_keeps_target_authority(api_env, upstream,different_browser):
    from app.services import integrations as store
    c, factory, _, _ = api_env
    root, _, _ = upstream
    saved = c.post('/website-settings', json={'address':root+'/', 'idempotency_key':'review-legacy-quota',
        'connection':{'transport':'proxy','auth_mode':'header','token':'SYNTHETIC-LEGACY-ONLY'}}).json()
    mid, tid = saved['id'], saved['target_id']
    with factory() as db:
        with store.edit(db) as state:
            module = state['modules'][mid]
            for field in ('connection','template_id','background','request_policy'): module.pop(field,None)
            state['targets'][tid]['controlled'] = True
            if different_browser: module['browser_url']='https://visible.quota.test/'
    item = c.get('/external-modules/'+mid).json()
    # Match WebsiteSettings.vue read(): transport/auth/header/delivery are sent
    # explicitly even though the source record never contained connection.
    connection = {k:v for k,v in item['connection'].items() if k != 'has_token'}
    connection.update(token=None, clear_token=False)
    result = c.patch('/website-settings/'+mid, json={'address':item['browser_url'],'name':'Metadata edit',
        'connection':connection,'background':item['background'],'request_policy':item['request_policy']})
    assert result.status_code == 200, result.text
    with factory() as db:
        new_target = store.state(db)['targets'][result.json()['target_id']]
    print({'read_auth_mode':item['connection']['auth_mode'],'read_has_token':item['connection']['has_token'],
        'target_preserved':result.json()['target_id']==tid,'headers_preserved':bool(new_target['headers']),
        'controlled_preserved':new_target['controlled']})
    assert result.json()['target_id'] == tid, 'Unchanged editor roundtrip replaced legacy target and stripped its authority'


def test_disabled_migrated_custom_removes_known_legacy_runtime_wrapper(upstream):
    from app.services import builtin_injection as builtin, integrations_proxy as proxy
    from app.services.website_migration import exact_legacy_signatures
    from starlette.requests import Request
    root, responses, _ = upstream
    old_active = builtin.default_active('drive') | {'enabled':True,'css':'body{--old-owner-code:1}',
        'js':'window.__oldOwnerCode=1;','version':'synthetic-old-version'}
    old_runtime = builtin.transform_html('<html><head></head><body>fixture</body></html>', 'drive',
        active=old_active, appearance={'theme':'stella','simplified':True})
    responses['/'] = (200,[('Content-Type','text/html')],old_runtime.encode())
    module = {'id':'f'*32, 'origin':'https://app-'+('f'*32)+'.xiya.live', 'adapter':'generic',
        'injection':{'active':{'enabled':False,'css':'','js':'','timing':'document_start','version':'off','csp_policy':'reject'}},
        'migration':{'exact_legacy_sha256':exact_legacy_signatures(active=old_active,appearance={'theme':'stella','simplified':True})}}
    target = {'upstream_url':root+'/','allowed_ips':['127.0.0.1'],'headers':{},'controlled':False}
    async def fetch():
        async def receive(): return {'type':'http.request','body':b'','more_body':False}
        request = Request({'type':'http','method':'GET','path':'/','raw_path':b'/','query_string':b'',
            'headers':[],'scheme':'https','server':('fixture',443)}, receive)
        return await proxy.proxy_http(request,module,target)
    html = asyncio.run(fetch()).body.decode()
    print({'disabled':True,'legacy_runtime_script_remains':'__stellaBuiltin_' in html,
        'legacy_owner_js_remains':'window.__oldOwnerCode=1' in html})
    assert '__stellaBuiltin_' not in html, 'Known prior renderer script remains executable after generic custom is disabled'


def test_direct_http_loader_cannot_be_saved_as_https_proxy(api_env, upstream, monkeypatch):
    c, _, _, _ = api_env
    root, _, _ = upstream
    monkeypatch.setenv('STELLA_MAIN_ORIGIN','https://stella.test')
    result = c.post('/website-settings',json={'address':root+'/', 'idempotency_key':'review-direct-mixed',
        'connection':{'transport':'direct','auth_mode':'original','injection_delivery':'loader'},
        'custom':{'enabled':True,'css':'body{color:red}','js':''}})
    data = result.json()
    print({'status':result.status_code,'mode':data.get('mode'),
        'reason':data.get('check',{}).get('embedding',{}).get('reason_code')})
    assert result.status_code == 422, 'HTTPS parent accepts direct HTTP iframe while claiming isolated_https_proxy'
