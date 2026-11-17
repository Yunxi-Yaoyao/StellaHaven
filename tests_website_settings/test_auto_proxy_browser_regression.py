"""Regression for browser-observed HTTPS/HTTP auto-proxy edits (no live PG)."""
import pytest
from test_website_settings import api_env,upstream

@pytest.mark.parametrize('operation',['metadata','disable','draft_check'])
def test_saved_auto_proxy_http_edit_uses_effective_transport(api_env,upstream,monkeypatch,operation):
    c,_,_,_=api_env;root,_,_=upstream
    monkeypatch.setenv('STELLA_MAIN_ORIGIN','https://stella.xiya.live')
    c.base_url = 'https://stella.xiya.live'  # Match the real request origin to this scenario's registry.
    payload={'address':root+'/first','name':'Owned proxy','idempotency_key':'owned-proxy-create','connection':{'transport':'auto','injection_delivery':'proxy'},'custom':{'enabled':True,'css':'body {color: blue}','js':''}}
    created=c.post('/website-settings',json=payload)
    assert created.status_code==201,created.text
    before=created.json();mid=before['id'];assert before['mode']=='isolated_proxy'
    if operation=='draft_check':
        r=c.post('/website-settings/check',json={'address':root+'/second','module_id':mid,'custom_enabled':False,'connection':payload['connection']})
        assert r.status_code==200 and r.json()['can_save'],r.text
        assert r.json()['embedding']['reason_code']=='isolated_https_proxy'
        return
    patch={'address':root+'/second','name':'Updated','connection':payload['connection']}
    if operation=='disable':patch['custom']={'enabled':False,'css':'body {color: blue}','js':''}
    r=c.patch('/website-settings/'+mid,json=patch)
    assert r.status_code==200,r.text
    read=c.get('/external-modules/'+mid).json()
    assert read['mode']=='isolated_proxy' and read['browser_url']==root+'/second'
    assert read['connection']['transport']=='auto'
    assert read['injection']['active']['enabled']==(operation=='metadata')
    if operation=='metadata':assert read['injection']==before['injection']

@pytest.mark.parametrize('connection',[{'transport':'direct','injection_delivery':'loader'},{'transport':'auto','injection_delivery':'loader'}])
def test_explicit_direct_still_rejects_mixed_content(api_env,upstream,monkeypatch,connection):
    c,_,_,_=api_env;root,_,_=upstream
    monkeypatch.setenv('STELLA_MAIN_ORIGIN','https://stella.xiya.live')
    c.base_url = 'https://stella.xiya.live'  # Match the real request origin to this scenario's registry.
    r=c.post('/website-settings/check',json={'address':root,'connection':connection})
    assert r.status_code==200 and not r.json()['can_save']
    assert r.json()['embedding']['reason_code']=='mixed_content'
