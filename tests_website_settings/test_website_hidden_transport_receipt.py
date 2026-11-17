"""Synthetic router / SQLite receipts; no live account, configuration or PG access."""
import copy
import json
import os
from pathlib import Path
import pytest
from tests_website_settings.test_website_settings import api_env, upstream


@pytest.mark.parametrize('unknown',[False,True])
@pytest.mark.parametrize('transport,auth,header',[
    ('direct','oidc','Authorization'),
    ('proxy','header','Authorization'),
    ('proxy','header','X-API-Key'),
    ('proxy','header','X-Auth-Token'),
])
def test_hidden_transport_and_legacy_alternate_preservation_boundary(api_env,upstream,transport,auth,header,unknown):
    from app.services import integrations as store
    c,factory,_,_=api_env
    root,_,_=upstream
    body=dict(address=root+'/library?q=a%2Fb#keep',name='Prior site fixture',icon='globe',open_behavior='embedded',
              connection=dict(transport=transport,auth_mode=auth,header_name=header,injection_delivery='loader' if transport=='direct' else 'proxy',token='fixture-only-secret' if auth=='header' else None),
              custom=dict(enabled=False,css='/* original comment */body{}',js='',timing='dom_ready'),idempotency_key='hidden-create-'+header)
    response=c.post('/website-settings',json=body)
    assert response.status_code==201,response.text
    mid=response.json()['id']
    # Unknown historical addresses are currently rejected by the backend even
    # when omitted. This is an observed blocker, not a successful metadata save.
    legacy='https://unknown-legacy-alternate.example.test/library?q=a%2Fb#keep' if unknown else None
    with factory() as db:
        with store.edit(db) as config:
            config['modules'][mid]['private_address']=legacy
    before=c.get('/external-modules/'+mid).json()
    with factory() as db: targets_before=copy.deepcopy(store.state(db)['targets'])
    request=dict(address=before['browser_url'],name='Metadata only',icon=before['icon'],visible=True,open_behavior='embedded',entry_policy='public',idempotency_key='hidden-edit-'+header)
    assert not {'private_address','connection','custom'} & request.keys()
    updated=c.patch('/website-settings/'+mid,json=request)
    if unknown:
        assert updated.status_code==422,updated.text
        assert c.get('/external-modules/'+mid).json()==before
        with factory() as db: assert store.state(db)['targets']==targets_before
        if os.getenv('STELLA_HIDDEN_RECEIPT_DIR'):
            directory=Path(os.environ['STELLA_HIDDEN_RECEIPT_DIR']);directory.mkdir(parents=True,exist_ok=True)
            (directory/(transport+'-'+header+'-unknown-blocked.json')).write_text(json.dumps(dict(provenance='Actual isolated SQLite / HTTP rejection; not successful metadata save',before=before,request=request,response=updated.json(),status=422,after=c.get('/external-modules/'+mid).json()),ensure_ascii=False,indent=2)+'\n')
        return
    assert updated.status_code==200,updated.text
    after=c.get('/external-modules/'+mid).json()
    # The save acknowledgement is not the detail DTO. Keep a closed,
    # independently constructed detail oracle, including every hidden field.
    expected=copy.deepcopy(before)|dict(name=request['name'],entry_policy='public')
    ack=updated.json()
    assert {'check','navigation','idempotency_key'} <= ack.keys()
    assert ack['idempotency_key']==request['idempotency_key']
    assert ack['check']['can_save'] is True
    assert next(e for e in ack['navigation']['entries'] if e['id']==mid)['title']==request['name']
    assert {k:v for k,v in ack.items() if k not in {'check','navigation','idempotency_key'}}==expected
    assert after==expected
    assert after['private_address']==legacy and after['entry_policy']=='public'
    assert after['name']=='Metadata only' and after['browser_url']==body['address']
    for field in ['connection','injection','mode','origin','target_id','initial_path']:
        assert after.get(field)==before.get(field),field
    with factory() as db: assert store.state(db)['targets']==targets_before
    if auth=='header':
        assert after['connection']['header_name']==header and after['connection']['has_token']
        assert 'fixture-only-secret' not in json.dumps(after)
    receipt=dict(provenance='Actual FastAPI TestClient HTTP + isolated in-memory SQLite + ephemeral real loopback HTTP; NOT real PG or user data',before=before,request=request,response=updated.json(),after=after)
    if os.getenv('STELLA_HIDDEN_RECEIPT_DIR'):
        directory=Path(os.environ['STELLA_HIDDEN_RECEIPT_DIR']);directory.mkdir(parents=True,exist_ok=True)
        (directory/(transport+'-'+header+'.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')


def test_new_auto_header_uses_default_authorization_with_valid_proxy_delivery(api_env,upstream):
    c,_,_,_=api_env
    root,_,_=upstream
    payload=dict(address=root+'/new',name='New fixture',icon='globe',connection=dict(transport='auto',auth_mode='header',header_name='Authorization',token='Bearer fixture-only',injection_delivery='proxy'),idempotency_key='new-auto-header')
    response=c.post('/website-settings',json=payload)
    assert response.status_code==201,response.text
    saved=c.get('/external-modules/'+response.json()['id']).json()
    assert saved['mode']=='isolated_proxy'
    assert saved['connection']==dict(transport='auto',auth_mode='header',header_name='Authorization',injection_delivery='proxy',has_token=True)
