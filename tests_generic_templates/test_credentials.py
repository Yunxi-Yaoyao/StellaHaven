import copy
import json
import pytest
from tests_generic_templates.test_generic_templates import api_env, upstream


def test_check_binds_header_to_saved_exact_snapshot_and_never_leaks_input(api_env, upstream):
    c,factory,_,_=api_env
    root,responses,seen=upstream
    payload={'address':root+'/base/','idempotency_key':'secret-save','connection':{'transport':'proxy','auth_mode':'header','token':'SYNTHETIC-PRIVATE'},'custom':{'enabled':True,'css':'body{color:red}'}}
    saved=c.post('/website-settings',json=payload)
    assert saved.status_code==201,saved.text
    mid=saved.json()['id']; seen.clear()
    check=c.post('/website-settings/check',json={'address':root+'/base/','module_id':mid,'connection':{'transport':'proxy','auth_mode':'header'}})
    assert check.status_code==200,check.text
    assert seen and seen[0][1].get('authorization')=='SYNTHETIC-PRIVATE'
    assert 'SYNTHETIC-PRIVATE' not in check.text
    seen.clear()
    changed=c.post('/website-settings/check',json={'address':root+'/other/','module_id':mid,'connection':{'transport':'proxy','auth_mode':'header'}})
    assert changed.status_code==422,changed.text
    assert not seen
    invalid=c.post('/website-settings',json=payload|{'connection':payload['connection']|{'header_name':'Cookie'}})
    assert invalid.status_code==422
    assert 'SYNTHETIC-PRIVATE' not in invalid.text
    responses['/redirect/']=(302,[('Location',root+'/other/')],b'')
    seen.clear()
    redirected=c.post('/website-settings/check',json={'address':root+'/redirect/','connection':payload['connection']})
    assert redirected.status_code==200
    assert [p for p,_ in seen]==['/redirect/']
    assert redirected.json()['embedding']['reason_code']=='credential_redirect'


def test_external_link_cannot_claim_backend_header_auth(api_env,upstream):
    c,_,_,_=api_env
    root,_,seen=upstream
    response=c.post('/website-settings',json={'address':root+'/','open_behavior':'external','connection':{'transport':'proxy','auth_mode':'header','token':'SYNTHETIC-HEADER'},'idempotency_key':'header-external'})
    assert response.status_code==422,response.text
    assert 'SYNTHETIC-HEADER' not in response.text
    assert not seen


def test_unsafe_address_edit_or_saved_check_stays_structured(api_env,upstream):
    c,_,_,_=api_env
    root,_,seen=upstream
    saved=c.post('/website-settings',json={'address':root+'/','idempotency_key':'unsafe-edit'}).json()
    seen.clear()
    edited=c.patch('/website-settings/'+saved['id'],json={'address':'http://169.254.169.254/latest'})
    assert edited.status_code==422,edited.text
    checked=c.post('/website-settings/check',json={'address':'file:///secret','module_id':saved['id']})
    assert checked.status_code==200 and checked.json()['can_save'] is False
    assert not seen


def test_token_change_and_clear_with_disabled_custom_are_not_reverted(api_env,upstream):
    from app.services import integrations as store
    c,factory,_,_=api_env
    root,_,_=upstream
    payload={'address':root+'/','idempotency_key':'token-edit','connection':{'transport':'proxy','auth_mode':'header','token':'SYNTHETIC-FIRST'},'custom':{'enabled':True,'css':'body{color:red}'}}
    saved=c.post('/website-settings',json=payload).json();mid=saved['id']
    changed=c.patch('/website-settings/'+mid,json={'address':root+'/','connection':{'transport':'proxy','auth_mode':'header','token':'SYNTHETIC-SECOND'},'custom':{'enabled':False}})
    assert changed.status_code==200,changed.text
    with factory() as db: assert store.state(db)['targets'][changed.json()['target_id']]['headers']=={'authorization':'SYNTHETIC-SECOND'}
    cleared=c.patch('/website-settings/'+mid,json={'address':root+'/','connection':{'transport':'proxy','auth_mode':'original','clear_token':True}})
    assert cleared.status_code==200,cleared.text
    with factory() as db: assert store.state(db)['targets'][cleared.json()['target_id']]['headers']=={}


def test_saved_credentials_not_selected_again_during_slow_probe(api_env, upstream, monkeypatch):
    from app.services import integrations as store, website_check
    c,factory,_,_=api_env
    root,_,seen=upstream
    data={'address':root+'/','idempotency_key':'race-check','connection':{'transport':'proxy','auth_mode':'header','token':'SYNTHETIC-FIRST'}}
    saved=c.post('/website-settings',json=data).json();mid=saved['id']
    real=website_check.check_draft
    async def racing(*a,**kw):
        with factory() as db:
            with store.edit(db) as state:
                state['targets'][saved['target_id']]['headers']={'authorization':'SYNTHETIC-SECOND'}
        return await real(*a,**kw)
    monkeypatch.setattr(website_check,'check_draft',racing)
    seen.clear()
    result=c.post('/website-settings/check',json={'address':root+'/','module_id':mid,'connection':{'transport':'proxy','auth_mode':'header'}})
    assert result.status_code==409,result.text
    assert seen[0][1].get('authorization')=='SYNTHETIC-FIRST'
