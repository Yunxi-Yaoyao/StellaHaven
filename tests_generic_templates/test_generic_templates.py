"""Owned loopback + synthetic SQLite only; run with --noconftest."""
import os
os.environ.update(STELLA_SECRET_KEY='website-settings-synthetic-signing-key-000000', POSTGRES_HOST='127.0.0.1', POSTGRES_PORT='1', POSTGRES_DB='stella_test_generic', POSTGRES_USER='fixture', POSTGRES_PASSWORD='synthetic-only', STELLA_MAIN_ORIGIN='http://stella.test')
import copy
import json
import pytest
from tests_website_settings.test_website_settings import upstream, api_env


def test_catalog_exposes_complete_editable_code(api_env, monkeypatch):
    monkeypatch.setenv('STELLA_MAIN_ORIGIN', 'https://stella.test')
    client, _, app, admin_calls = api_env
    from app.routers import website_settings
    if hasattr(website_settings, 'assets_router'):
        app.include_router(website_settings.assets_router)
    response = client.get('/website-templates')
    assert response.status_code == 200, response.text
    templates = {t['id']: t for t in response.json()}
    assert set(templates) == {'openlist', 'immich'}
    drive = templates['openlist']['draft']
    assert drive['custom']['enabled']
    assert len(drive['custom']['css']) > 1000
    assert '__stellaCacheFix' in drive['custom']['js']
    assert 'stella-admin-required' in drive['custom']['js']
    assert 'event.source!==window.parent' in drive['custom']['js']
    assert 'event.origin!==location.origin' not in drive['custom']['js']
    assert 'Immich logo' in templates['immich']['draft']['custom']['css']
    assert not admin_calls


def test_template_saves_independent_generic_proxy_with_masked_credentials(upstream, api_env):
    from app.services.website_templates import catalog
    from app.services import integrations as store
    root, _, seen = upstream
    c, factory, _, _ = api_env
    draft = catalog(main_origin='https://stella.test')[0]['draft']
    draft.update(address=root+'/drive/openlist/', template_id='openlist', idempotency_key='template-one')
    draft['connection'].update(auth_mode='header', token='synthetic-header')
    response = c.post('/website-settings', json=draft)
    assert response.status_code == 201, response.text
    one = response.json()
    assert one['adapter'] == 'generic' and one['mode'] == 'isolated_proxy'
    assert one['initial_path'] == '/drive/openlist/'
    assert one['connection']['has_token'] and 'token' not in one['connection']
    assert one['injection']['active']['css'] == draft['custom']['css']
    assert c.get('/external-modules/'+one['id']).json()['template_id'] == 'openlist'
    with factory() as db:
        target = store.state(db)['targets'][one['target_id']]
        assert target['upstream_url'] == root+'/'
        assert target['headers'] == {'authorization':'synthetic-header'}
    draft['idempotency_key'] = 'template-two'
    draft['custom']['css'] += '\nbody{color:red}'
    two = c.post('/website-settings', json=draft)
    assert two.status_code == 201, two.text
    assert two.json()['id'] != one['id']
    assert c.get('/external-modules/'+one['id']).json()['injection']['active']['css'] == one['injection']['active']['css']
    assert c.delete('/external-modules/'+two.json()['id']).status_code == 204
    # Quota/legacy proxy edits with omitted code must retain transport and target.
    edit = c.patch('/website-settings/'+one['id'], json={'address':draft['address'], 'custom':{'enabled':False}})
    assert edit.status_code == 200, edit.text
    assert edit.json()['target_id'] == one['target_id']
    assert edit.json()['mode'] == 'isolated_proxy'
    assert all('cookie' not in {k.lower() for k in h} for _, h in seen)


def test_direct_loader_save_publish_disable_rollback_without_proxy(upstream, api_env):
    from app.services.website_templates import catalog
    from app.services import integrations as store
    c, factory, app, _ = api_env
    root, responses, _ = upstream
    draft = catalog(main_origin='https://stella.test')[1]['draft']
    draft.update(address=root+'/', template_id='immich', idempotency_key='loader-first')
    response = c.post('/website-settings', json=draft)
    assert response.status_code == 201, response.text
    module = response.json(); mid = module['id']
    assert module['mode'] == 'iframe' and module['target_id'] is None
    assert module['connection']['auth_mode'] == 'oidc'
    assert module['check']['injection']['status'] == 'loader_required'
    assert module['capabilities']['injection']
    from app.services.website_assets import asset_code
    with factory() as db:
        assert store.state(db)['targets'] == {}
        assert 'Immich logo' in asset_code(db, mid, custom_allowed=True)
        assert root in asset_code(db, mid, custom_allowed=True)
        assert 'Immich logo' not in asset_code(db, mid, custom_allowed=False)
    disabled = c.patch('/website-settings/'+mid, json={'address':root+'/', 'custom':{'enabled':False,'css':'body{color:blue}'}})
    assert disabled.status_code == 200, disabled.text
    with factory() as db: assert 'Immich logo' not in asset_code(db,mid,custom_allowed=True)
    rolled = c.post('/external-modules/'+mid+'/injection/rollback')
    assert rolled.status_code == 200, rolled.text
    with factory() as db: assert 'Immich logo' in asset_code(db,mid,custom_allowed=True)
    from app.routers.website_settings import assets_router
    app.include_router(assets_router)
    anonymous = c.get('/website-assets/'+mid+'.js')
    assert anonymous.status_code == 200
    assert 'Immich logo' not in anonymous.text
    assert anonymous.headers['cache-control'] == 'no-store'
    assert 'access-control-allow-origin' not in anonymous.headers


def test_legacy_quota_without_new_fields_keeps_original_target_on_empty_edit(upstream,api_env):
    from app.services import integrations as store
    c,factory,_,_=api_env
    root,_,_=upstream
    saved=c.post('/website-settings',json={'address':root+'/','idempotency_key':'quota-legacy','custom':{'enabled':True,'css':'body{color:red}'}}).json()
    with factory() as db:
        with store.edit(db) as state:
            module=state['modules'][saved['id']]
            for field in ('connection','template_id','background','request_policy'):module.pop(field,None)
            module['injection']={'active':None,'draft':None,'previous':None}
            state['targets'][saved['target_id']]['controlled']=True
    edited=c.patch('/website-settings/'+saved['id'],json={'address':root+'/','name':'Quota kept'})
    assert edited.status_code==200,edited.text
    assert edited.json()['target_id']==saved['target_id']
    assert edited.json()['mode']=='isolated_proxy'
    with factory() as db:
        assert len(store.state(db)['targets'])==1
        assert store.state(db)['targets'][saved['target_id']]['controlled'] is True


def test_loader_uses_browser_canonical_origin_including_default_ports(api_env):
    from app.services import integrations as store
    from app.services.website_assets import asset_code
    _,factory,_,_=api_env
    mid='e'*32
    with factory() as db:
        with store.edit(db) as state:
            state['modules'][mid]={'id':mid,'enabled':True,'mode':'iframe','browser_url':'https://immich.test:443/','connection':{'injection_delivery':'loader'},'injection':{'active':{'enabled':True,'css':'body{color:red}','js':'','version':'v1','timing':'dom_ready'}}}
        code=asset_code(db,mid,custom_allowed=True)
        assert '"origin": "https://immich.test"' in code


def test_new_low_level_modules_cannot_reintroduce_special_adapters(api_env):
    c,_,_,_=api_env
    for adapter in ('openlist','immich'):
        response=c.post('/external-modules',json={'name':'Legacy','browser_url':'https://example.test/','adapter':adapter})
        assert response.status_code==422,response.text
