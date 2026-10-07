"""Behavioral guards: policies independent of adapter/template names."""
import importlib.util
import pytest
from tests_generic_templates.test_generic_templates import api_env, upstream


def test_policy_edit_revokes_existing_tickets_and_live_grants(api_env,upstream):
    from app.services import integrations as store
    c,factory,_,_=api_env
    root,_,_=upstream
    saved=c.post('/website-settings',json={'address':root+'/','connection':{'transport':'proxy'},'idempotency_key':'policy-change'}).json()
    mid=saved['id']
    with factory() as db:
        with store.edit(db) as state:
            state['grants']['old']={'id':mid}
            state['tickets']['old']={'id':mid}
    result=c.patch('/website-settings/'+mid,json={'address':root+'/','request_policy':{'protect_other_writes':True}})
    assert result.status_code==200,result.text
    with factory() as db:
        assert store.state(db)['grants']=={} and store.state(db)['tickets']=={}


def test_generic_policy_applies_to_actual_basepath_before_upstream(api_env, upstream, monkeypatch):
    assert importlib.util.find_spec('app.services.website_policy'), 'generic path policy missing'
    from app.services.website_policy import management_required
    from app.services.website_templates import catalog
    policy = catalog(main_origin='https://stella.test')[0]['draft']['request_policy']
    module = {'request_policy':policy, 'initial_path':'/drive/openlist/', 'adapter':'generic'}
    assert management_required(module,'GET','/drive/openlist/api/admin/settings')
    assert management_required(module,'POST','/drive/openlist/api/fs/other')
    assert management_required(module,'DELETE','/drive/openlist/api/fs/remove')
    assert not management_required(module,'POST','/drive/openlist/api/fs/list')
    assert not management_required(module,'GET','/drive/openlist/assets/a.js')
    assert not management_required(module,'GET','/drive/openlist/d/%E4%B8%AD%E6%96%87%20file.txt')
    assert management_required(module,'GET','/api/admin/settings')
    from fastapi import HTTPException
    for path in ['/drive/openlist/api/%61dmin','//api/admin','/drive/openlist/../api/admin']:
        with pytest.raises(HTTPException): management_required(module,'GET',path)
    from app.services import integrations as store, integrations_sessions as sessions
    from app.routers.integrations_host import IntegrationsHostMiddleware
    from fastapi.testclient import TestClient
    from starlette.responses import Response
    c, factory, app, _ = api_env
    root, _, seen = upstream
    draft = catalog(main_origin='https://stella.test')[0]['draft'] | {'address':root+'/drive/openlist/','idempotency_key':'policy-live'}
    saved = c.post('/website-settings',json=draft)
    assert saved.status_code == 201,saved.text
    mid = saved.json()['id']; seen.clear()
    monkeypatch.setattr(sessions,'authorize',lambda *a: {'sid':'bad-session'})
    host = IntegrationsHostMiddleware(app,db_factory=factory)
    with TestClient(host,base_url='https://app-'+mid+'.xiya.live') as browser:
        denied = browser.get('/drive/openlist/api/admin/settings')
        assert denied.status_code == 401,denied.text
        assert not seen
        allowed = browser.get('/drive/openlist/assets/a.js')
        assert allowed.status_code == 200,allowed.text
        assert len(seen) == 1
        with factory() as db:
            with store.edit(db) as state: state['modules'][mid]['adapter']='openlist'
        seen.clear()
        assert browser.get('/drive/openlist/').status_code == 410
        assert not seen
