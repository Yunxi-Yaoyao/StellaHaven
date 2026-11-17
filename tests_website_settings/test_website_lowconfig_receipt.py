"""Unchanged backend contract: real router + SQLite + ephemeral loopback HTTP.
Never connects to application PG; optional receipt export is synthetic only.
"""
import json
import os
from pathlib import Path
from tests_website_settings.test_website_settings import api_env, upstream


def test_proxy_metadata_omits_generated_address_and_retains_registry_mapping(api_env, upstream, monkeypatch):
    from app.services import integrations as store
    c, factory, _, _ = api_env
    root, _, _ = upstream
    parent='https://stella.test'
    alternate='https://stella.alt.test'
    rows=[dict(service_id='stella',public=parent,private=alternate)]
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps(rows))
    body=dict(address=root+'/library?q=1#section',name='原网站',icon='globe',keep_alive=False,
              connection=dict(transport='proxy',auth_mode='original',header_name='Authorization',injection_delivery='proxy'),idempotency_key='lowconfig-proxy-create')
    response=c.post(parent+'/website-settings',json=body)
    assert response.status_code==201,response.text
    created=response.json();mid=created['id'];generated='https://app-alt-'+mid+'.test'
    rows.append(dict(service_id=mid,public=created['origin'],private=generated))
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps(rows))
    seed=c.patch(parent+'/website-settings/'+mid,json=body|dict(private_address=generated+'/',entry_policy='public'))
    assert seed.status_code==200,seed.text
    before=c.get(parent+'/external-modules/'+mid).json()
    with factory() as db: target_before=store.state(db)['targets'][before['target_id']]
    request=dict(address=before['browser_url'],name='仅修改网站名称',icon=before['icon'],visible=True,open_behavior='embedded',entry_policy='public',access_adapter=before['access_adapter'],template_id=before['template_id'],connection=before['connection']|dict(token=None,clear_token=False),request_policy=before['request_policy'],idempotency_key='lowconfig-proxy-edit')
    request['connection'].pop('has_token',None)
    assert 'private_address' not in request
    updated=c.patch(parent+'/website-settings/'+mid,json=request)
    assert updated.status_code==200,updated.text
    after=c.get(parent+'/external-modules/'+mid).json()
    # Independently freeze the complete detail contract, not a server-shaped expected.
    expected=before|dict(name=request['name'])
    ack=updated.json()
    assert {'check','navigation','idempotency_key'} <= ack.keys()
    assert ack['idempotency_key']==request['idempotency_key']
    assert ack['check']['can_save'] is True
    assert next(e for e in ack['navigation']['entries'] if e['id']==mid)['title']==request['name']
    assert {k:v for k,v in ack.items() if k not in {'check','navigation','idempotency_key'}}==expected
    assert after==expected
    assert after['private_address']==generated+'/' and after['entry_policy']=='public'
    assert after['name']==request['name'] and after['browser_url']==root+'/library?q=1#section'
    assert after['initial_path']=='/library?q=1#section'
    for field in ['origin','target_id','injection','keep_alive','connection']:
        assert after[field]==before[field],field
    with factory() as db: assert store.state(db)['targets'][before['target_id']]==target_before
    from app.services.entry_registry import module_context
    assert module_context(after,parent)==created['origin']
    assert module_context(after,alternate)==created['origin']
    follow=c.patch(parent+'/website-settings/'+mid,json=request|dict(entry_policy='follow',idempotency_key='lowconfig-follow'))
    assert follow.status_code==200,follow.text
    followed=c.get(parent+'/external-modules/'+mid).json()
    assert followed['private_address']==generated+'/'
    assert module_context(followed,alternate)==generated
    receipt=dict(provenance='Actual FastAPI TestClient HTTP / in-memory SQLite / ephemeral real loopback upstream; no live backend',before=before,request=request,response=updated.json(),after=after,follow=followed)
    if os.getenv('STELLA_WEBSITE_RECEIPT'):
        Path(os.environ['STELLA_WEBSITE_RECEIPT']).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
