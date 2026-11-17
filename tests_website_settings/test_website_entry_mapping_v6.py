"""Real SQLite routers + two exclusively owned loopback HTTP upstreams.
Run standalone --noconftest from an owned scratch cwd, never app/main.py.
"""
import asyncio
import copy
import json
import pytest
from test_website_settings import upstream, api_env

@pytest.fixture
def other_upstream():
    yield from upstream.__wrapped__()


def test_two_direct_addresses_map_current_lane_and_clear_without_destroying_legacy(upstream, api_env, monkeypatch):
    from app.services.entry_registry import browser_url
    root, _, seen = upstream
    client, factory, _, _ = api_env
    body = dict(address=root+'/first?q=a%2Fb#one', address_mode='ip',
                alternate_address=root+'/second?q=x%2Fy#two', name='双入口',
                connection=dict(transport='direct', injection_delivery='loader'),
                idempotency_key='v6-direct-create')
    response = client.post('/website-settings', json=body)
    assert response.status_code == 201, response.text
    item = response.json()
    assert item['address_mode'] == 'ip'
    assert item['alternate_address'] == body['alternate_address']
    assert item['mapping_configured'] is True
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([dict(service_id='stella', public='https://main.test', private='https://other.test')]))
    assert browser_url(item, 'https://main.test') == body['address']
    assert browser_url(item, 'https://other.test') == body['alternate_address']
    monkeypatch.delenv('STELLA_ENTRY_REGISTRY')
    assert [path for path, _ in seen] == ['/second?q=x%2Fy', '/first?q=a%2Fb']
    # Omission keeps mapping; null explicitly shares the first; empty is invalid.
    response = client.patch('/website-settings/'+item['id'], json=dict(address=body['address'], name='只改名'))
    assert response.status_code == 200, response.text
    assert response.json()['alternate_address'] == body['alternate_address']
    response = client.patch('/website-settings/'+item['id'], json=dict(address=body['address'], alternate_address=''))
    assert response.status_code == 422
    response = client.patch('/website-settings/'+item['id'], json=dict(address=body['address'], alternate_address=None))
    assert response.status_code == 200, response.text
    cleared = response.json()
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([dict(service_id='stella', public='https://main.test', private='https://other.test')]))
    assert browser_url(cleared, 'https://other.test') == body['address']


@pytest.mark.parametrize('mode,address', [('ip','https://domain.test/path'), ('domain','http://127.0.0.1:1234/'), ('ip','http://127.0.0.1:0/'), ('ip','http://169.254.169.254/'), ('ip','http://1:1/')])
def test_mode_rejects_incompatible_or_unsafe_address_without_network(mode,address):
    from app.services.website_settings import WebsiteInput
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        WebsiteInput(address=address,address_mode=mode)


def test_proxy_two_owned_upstreams_use_registered_hosts_pins_and_revoke_old_grants(upstream, other_upstream, api_env, monkeypatch):
    from fastapi.testclient import TestClient
    from app.routers.integrations_host import IntegrationsHostMiddleware
    from app.services import integrations as store, integrations_sessions as sessions
    from app.services.website_mapping import initial_path
    primary, _, seen_primary = upstream
    other, _, seen_other = other_upstream
    client, factory, app, _ = api_env
    payload = dict(address=primary+'/primary?q=first#one', alternate_address=other+'/other?q=second#two',
                   address_mode='ip', name='代理双入口', idempotency_key='v6-proxy-create',
                   connection=dict(transport='proxy', auth_mode='header', token='SYNTHETIC_V6_MAPPING_CANARY'))
    response = client.post('/website-settings', json=payload)
    assert response.status_code == 201, response.text
    item = response.json()
    assert 'SYNTHETIC_V6_MAPPING_CANARY' not in response.text
    mid = item['id']
    with factory() as db:
        state = store.state(db)
        saved = state['modules'][mid]
        assert saved['alternate_binding']['target_id'] != saved['target_id']
        assert state['targets'][saved['alternate_binding']['target_id']]['upstream_url'] == other+'/'
        assert state['targets'][saved['alternate_binding']['target_id']]['allowed_ips'] == ['127.0.0.1']
    alternate_origin = 'https://alt-app.test'
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([
        dict(service_id='stella',public='https://main.test',private='https://other.test'),
        dict(service_id=mid, public=item['origin'],private=alternate_origin)]))
    monkeypatch.setattr(sessions, 'session_alive', lambda db,sid: True)  # synthetic auth only
    proxy_client = TestClient(IntegrationsHostMiddleware(app,db_factory=factory),base_url='https://main.test')
    cookies = {}
    for parent, target, path, marker in [('https://main.test', item['origin'], initial_path(payload['address']), 'primary'),
                                         ('https://other.test', alternate_origin, initial_path(payload['alternate_address']), 'other')]:
        with factory() as db: ticket = sessions.issue(db, saved, 'fixture-session', parent)
        assert ticket['target_origin'] == target
        boot = proxy_client.post(target+'/__stella/bootstrap',data=ticket['fields'],headers={'Origin':parent},follow_redirects=False)
        assert boot.status_code == 303, boot.text
        assert boot.headers['location'] == path
        assert 'Secure' in boot.headers['set-cookie'] and 'Domain=' not in boot.headers['set-cookie']
        cookie = boot.cookies.get(sessions.COOKIE)
        cookies[target] = cookie
        loaded = proxy_client.get(target+path.split('#')[0],headers={'Cookie':sessions.COOKIE+'='+cookie})
        assert loaded.status_code == 200, loaded.text
    assert seen_primary[-1][0] == '/primary?q=first'
    assert seen_other[-1][0] == '/other?q=second'
    assert {k.lower():v for k,v in seen_primary[-1][1].items()}['authorization'] == 'SYNTHETIC_V6_MAPPING_CANARY'
    assert {k.lower():v for k,v in seen_other[-1][1].items()}['authorization'] == 'SYNTHETIC_V6_MAPPING_CANARY'
    wrong = proxy_client.get(alternate_origin+'/wrong', headers={'Cookie':sessions.COOKIE+'='+cookies[item['origin']]})
    assert wrong.status_code == 401
    # Explicit other-upstream URL changes must never inherit a saved secret.
    monkeypatch.delenv('STELLA_ENTRY_REGISTRY')
    rejected = client.patch('/website-settings/'+mid,json=dict(address=payload['address'],alternate_address=other+'/changed'))
    assert rejected.status_code == 422, rejected.text
    # A fresh explicit credential authorizes new binding, and invalidates both grants.
    changed = client.patch('/website-settings/'+mid,json=dict(address=payload['address'],alternate_address=other+'/changed', connection=payload['connection']))
    assert changed.status_code == 200, changed.text
    with factory() as db:
        state = store.state(db)
        assert not [g for g in state['grants'].values() if g['id']==mid]
    proxy_client.close()


def test_ip_http_https_parent_uses_safe_auto_proxy_and_checks_second_draft(upstream, other_upstream, api_env, monkeypatch):
    root, _, _ = upstream
    other, responses, _ = other_upstream
    client, _, _, _ = api_env
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([dict(service_id='stella',public='https://main.test',private='https://other.test')]))
    draft=dict(address=root+'/a',address_mode='ip',alternate_address=other+'/b',connection=dict(transport='auto'))
    checked=client.post('https://main.test/website-settings/check',json=draft)
    assert checked.status_code==200, checked.text
    assert checked.json()['can_save'] is True
    saved=client.post('https://main.test/website-settings',json=draft|dict(idempotency_key='v6-auto-http'))
    assert saved.status_code==201,saved.text
    assert saved.json()['mode']=='isolated_proxy'
    responses['/b']=(403, [('Content-Type','text/html')], b'blocked second')
    checked=client.post('https://main.test/website-settings/check',json=draft)
    assert checked.status_code==200,checked.text
    assert checked.json()['can_save'] is False
    assert checked.json()['normalized_url']==draft['address']
    assert any('其他入口' in issue for issue in checked.json()['issues'])


def test_legacy_digest_and_unmapped_direct_metadata_remain_unchanged(upstream, api_env):
    import hashlib
    from app.services.website_settings import WebsiteInput,fingerprint
    root,_,_=upstream
    data=WebsiteInput(address=root+'/legacy')
    # The absent CAS field must retain the approved pre-CAS fingerprint.
    old_body=data.model_dump(exclude={'address_mode','alternate_address','idempotency_key','preserve_saved_draft','expected_revision'})
    expected=hashlib.sha256(json.dumps(old_body,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
    assert fingerprint(data)==expected
    client,factory,_,_=api_env
    from app.services import integrations as store
    response=client.post('/website-settings',json=dict(address=root+'/legacy',private_address=None,idempotency_key='v6-unmapped-direct'))
    assert response.status_code==201,response.text
    mid=response.json()['id']
    # Existing direct legacy second URL, not new upstream mapping.
    with factory() as db:
        with store.edit(db) as state: state['modules'][mid]['private_address']='https://old.invalid/path?q=old#saved'
    before=client.get('/external-modules/'+mid).json()
    updated=client.patch('/website-settings/'+mid,json=dict(address=root+'/legacy',name='仅改名称'))
    assert updated.status_code==200,updated.text
    after=client.get('/external-modules/'+mid).json()
    assert after['private_address']==before['private_address']
    assert after['alternate_address'] is None and after['mapping_configured'] is False


@pytest.mark.parametrize('damage',['missing','invalid','dns_pin'])
def test_metadata_cannot_repair_or_reauthorize_other_proxy_target(upstream,other_upstream,api_env,damage):
    from app.services import integrations as store
    first,_,_=upstream;second,_,seen=other_upstream
    client,factory,_,_=api_env
    created=client.post('/website-settings',json=dict(address=first+'/a',alternate_address=second+'/b',address_mode='ip',connection=dict(transport='proxy'),idempotency_key='v6-damaged-'+damage))
    assert created.status_code==201,created.text
    mid=created.json()['id']
    with factory() as db:
        with store.edit(db) as config:
            tid=config['modules'][mid]['alternate_binding']['target_id']
            if damage=='missing': del config['targets'][tid]
            elif damage=='invalid': del config['targets'][tid]['allowed_ips']
            else: config['targets'][tid]['allowed_ips']=['127.0.0.2']
        before=copy.deepcopy(store.state(db))
    seen.clear()
    response=client.patch('/website-settings/'+mid,json=dict(address=first+'/a',name='metadata-only'))
    assert response.status_code==422,response.text
    with factory() as db: assert store.state(db)==before
    assert seen==[]


def test_new_direct_mapping_does_not_consume_a_preserved_retired_browser_alias(monkeypatch):
    from app.services.entry_registry import browser_url
    module=dict(id='a'*32,mode='iframe',browser_url='https://first.test/base?q=1#x',origin='https://first.test',entry_policy='follow',
                private_address='https://retired.test/old',mapping_configured=True,alternate_address=None)
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([dict(service_id='stella',public='https://main.test',private='https://other.test'),dict(service_id=module['id'],public='https://first.test',private='https://newly-deployed.test')]))
    assert browser_url(module,'https://other.test')==module['browser_url']
    assert module['private_address']=='https://retired.test/old'


def test_omitted_active_code_is_still_checked_against_second_proxy_policy(upstream,other_upstream,api_env):
    from app.services import integrations as store
    first,_,seen_first=upstream;second,responses,seen_second=other_upstream
    client,factory,_,_=api_env
    code=dict(enabled=True,css='body{color:teal}',js='')
    created=client.post('/website-settings',json=dict(address=first+'/a',alternate_address=second+'/b',address_mode='ip',connection=dict(transport='proxy'),custom=code,idempotency_key='v6-active-code-policy'))
    assert created.status_code==201,created.text
    mid=created.json()['id']
    with factory() as db: before=copy.deepcopy(store.state(db))
    responses['/b']=(200,[('Content-Type','text/html'),('Content-Security-Policy',"script-src 'none'")],b'<html>policy changed</html>')
    seen_first.clear();seen_second.clear()
    # Approved local-only edit: omitted active code retains authority, and a
    # name change must not depend on current remote reachability or CSP.
    response=client.patch('/website-settings/'+mid,json=dict(address=first+'/a',name='metadata-only'))
    assert response.status_code==200,response.text
    assert seen_first==[] and seen_second==[]
    with factory() as db: saved=copy.deepcopy(store.state(db))
    authority=['mode','origin','browser_url','target_id','alternate_address','alternate_binding','connection','request_policy','entry_policy','access_adapter','injection']
    assert {k:saved['modules'][mid].get(k) for k in authority}=={k:before['modules'][mid].get(k) for k in authority}
    for field in ['targets','tickets','grants']:
        assert saved[field]==before[field],field
    assert client.get('/external-modules/'+mid).json()['name']=='metadata-only'
    # Keep the original CSP rejection on a genuine address authority transition.
    changed=client.patch('/website-settings/'+mid,json=dict(address=first+'/changed',name='not committed'))
    assert changed.status_code==422,changed.text
    assert seen_second and seen_second[-1][0]=='/b'
    with factory() as db: assert store.state(db)==saved
    # First enable is a second genuine transition, even at the same address.
    disabled=client.patch('/website-settings/'+mid,json=dict(address=first+'/a',custom=code|dict(enabled=False)))
    assert disabled.status_code==200,disabled.text
    with factory() as db: disabled_state=copy.deepcopy(store.state(db))
    seen_first.clear();seen_second.clear()
    enabled=client.patch('/website-settings/'+mid,json=dict(address=first+'/a',custom=code))
    assert enabled.status_code==422,enabled.text
    assert seen_second and seen_second[-1][0]=='/b'
    with factory() as db: assert store.state(db)==disabled_state


def test_omitted_mode_still_validates_edits_against_saved_product_mode(upstream,api_env):
    root,_,seen=upstream;client,factory,_,_=api_env
    created=client.post('/website-settings',json=dict(address=root+'/a',address_mode='ip',alternate_address=None,idempotency_key='v6-mode-retained'))
    assert created.status_code==201,created.text
    mid=created.json()['id'];seen.clear()
    changed=root.replace('127.0.0.1','localhost')+'/a'
    checked=client.post('/website-settings/check',json=dict(address=changed,module_id=mid))
    assert checked.status_code==422,checked.text
    rejected=client.patch('/website-settings/'+mid,json=dict(address=changed,name='wrong mode'))
    assert rejected.status_code==422,rejected.text
    assert seen==[]
    assert client.get('/external-modules/'+mid).json()['browser_url']==root+'/a'


def test_equivalent_alternate_pin_order_does_not_replace_target_on_metadata_save(upstream,other_upstream,api_env,monkeypatch):
    from app.services import integrations as store,integrations_proxy as proxy
    first,_,_=upstream;second,_,_=other_upstream;client,factory,_,_=api_env
    dns=proxy._preview_addresses
    monkeypatch.setattr(proxy,'_preview_addresses',lambda url:['127.0.0.1','127.0.0.2'] if url.rstrip('/')==second else dns(url))
    created=client.post('/website-settings',json=dict(address=first+'/a',alternate_address=second+'/b',connection=dict(transport='proxy'),idempotency_key='v6-pin-order'))
    assert created.status_code==201,created.text
    mid=created.json()['id']
    with factory() as db:
        with store.edit(db) as config:
            tid=config['modules'][mid]['alternate_binding']['target_id'];config['targets'][tid]['allowed_ips'].reverse()
        before=copy.deepcopy(store.state(db)['targets'])
    updated=client.patch('/website-settings/'+mid,json=dict(address=first+'/a',name='pin order retained'))
    assert updated.status_code==200,updated.text
    with factory() as db:
        config=store.state(db)
        assert config['modules'][mid]['alternate_binding']['target_id']==tid
        assert config['targets']==before
