"""Independent exact-candidate retention review. Real routers/SQLite/loopback only."""
import copy
import json
import os
from pathlib import Path
import pytest
from fastapi import HTTPException
from tests_website_settings.test_website_settings import api_env, upstream

OUT = None

@pytest.fixture(autouse=True)
def receipt_directory(tmp_path, monkeypatch):
    # Evidence is output, never a prerequisite private host directory.
    target = Path(os.environ['INDEPENDENT_WEBSITE_RECEIPTS']) if os.environ.get('INDEPENDENT_WEBSITE_RECEIPTS') else tmp_path/'receipts'
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setitem(globals(), 'OUT', target)


def snapshot(factory):
    from app.services import integrations as store
    with factory() as db: return copy.deepcopy(store.state(db))


def legacy_probe(factory):
    # Historical records have no checked fingerprint: exercise the full original
    # fetch/recheck race schedule, never fake a fetch on the local-only path.
    from app.services import integrations as store
    with factory() as db:
        with store.edit(db) as config: config.pop('website_target_authority',None)

def setup(api_env, upstream, monkeypatch, transport='proxy', header='X-API-Key', auth=None):
    from app.services import integrations as store, entry_registry
    c,factory,app,_=api_env
    operation=app.openapi()['paths']['/website-settings/{mid}']['patch']
    assert operation['requestBody']['content']['application/json']['schema']['$ref'].endswith('/WebsiteInput')
    assert 'private_address' in app.openapi()['components']['schemas']['WebsiteInput']['properties']
    root,_,seen=upstream
    auth=auth or ('oidc' if transport=='direct' else 'header')
    connection=dict(transport=transport,auth_mode=auth,header_name=header,injection_delivery='loader' if transport=='direct' else 'proxy')
    if auth=='header': connection['token']='independent-fixture-canary-never-export'
    r=c.post('/website-settings',json=dict(address=root+'/library?q=a%2Fb#keep',name='Original',icon='globe',connection=connection,idempotency_key='independent-create'))
    assert r.status_code==201,r.text
    mid=r.json()['id']
    alternate='https://old-private.example.test/library?q=a%2Fb#keep'
    with factory() as db:
        with store.edit(db) as cfg: cfg['modules'][mid]['private_address']=alternate
    before=c.get('/external-modules/'+mid).json()
    rows={'stella':{'public':'http://stella.test','private':'https://stella-private.example.test'},mid:{'public':before['origin'] if before['mode']=='isolated_proxy' else before['browser_url'],'private':'https://old-private.example.test'}}
    monkeypatch.setattr(entry_registry,'records',lambda:copy.deepcopy(rows))
    entry_registry.validate_website_entry(before)
    rows[mid]['private']='https://replacement-private.example.test'
    with pytest.raises(HTTPException): entry_registry.validate_website_entry(before)
    payload=dict(address=before['browser_url'],name='Metadata saved',icon='star',visible=True)
    return c,factory,mid,before,payload,rows,seen


@pytest.mark.parametrize('transport,header',[('direct','Authorization'),('proxy','Authorization'),('proxy','X-API-Key'),('proxy','X-Auth-Token')])
def test_original_four_bad_alternates_metadata_now_preserved(api_env,upstream,monkeypatch,transport,header):
    c,f,mid,before,payload,rows,seen=setup(api_env,upstream,monkeypatch,transport,header)
    old=snapshot(f)
    seen.clear()
    response=c.patch('/website-settings/'+mid,json=payload)
    assert response.status_code==200,response.text
    after=c.get('/external-modules/'+mid).json()
    for field in ('browser_url','origin','mode','target_id','initial_path','connection','private_address','entry_policy','access_adapter','request_policy','injection'):
        assert after.get(field)==before.get(field),field
    saved=snapshot(f)
    assert old['targets']==saved['targets'] and old['tickets']==saved['tickets'] and old['grants']==saved['grants']
    assert seen == []
    assert 'independent-fixture-canary-never-export' not in json.dumps(response.json())
    assert response.json()['check']['access']=={'status':'unknown','http_status':None}
    public=dict(kind='metadata-success',transport=transport,header=header,before=before,request=payload,status=response.status_code,response=response.json(),after=after,targets_exact=True,secret_preserved_not_exported=True,public_upstream_paths=[p for p,_ in seen])
    (OUT/('independent-'+transport+'-'+header+'.json')).write_text(json.dumps(public,indent=2)+'\n')


@pytest.mark.parametrize('change',['private_same','private_null','connection_same','connection_transport','address_path','address_query','address_hash','entry_policy','open_behavior','access_adapter','request_policy'])
def test_explicit_nonmetadata_must_revalidate_and_leave_db(api_env,upstream,monkeypatch,change):
    c,f,mid,before,payload,rows,seen=setup(api_env,upstream,monkeypatch)
    changes={
        'private_same':{'private_address':before['private_address']},
        'private_null':{'private_address':None},
        'connection_same':{'connection':{k:v for k,v in before['connection'].items() if k!='has_token'}},
        'connection_transport':{'connection':dict(transport='direct',auth_mode='oidc',injection_delivery='loader')},
        'address_path':{'address':before['browser_url'].replace('/library','/other')},
        'address_query':{'address':before['browser_url'].replace('q=a%2Fb','q=changed')},
        'address_hash':{'address':before['browser_url'].replace('#keep','#changed')},
        'entry_policy':{'entry_policy':'public'},
        'open_behavior':{'open_behavior':'external'},
        'access_adapter':{'access_adapter':'immich'},
        'request_policy':{'request_policy':dict(read_post_paths=['/admin/delete'],management_prefixes=[],protect_other_writes=False)},
    }
    if change=='request_policy':
        from app.services import integrations as store, website_policy
        with f() as db:
            with store.edit(db) as cfg:
                cfg['modules'][mid]['request_policy']=dict(read_post_paths=[],management_prefixes=[],protect_other_writes=True)
        assert website_policy.management_required(snapshot(f)['modules'][mid],'POST','/admin/delete') is True
    old=snapshot(f)
    response=c.patch('/website-settings/'+mid,json=payload|changes[change])
    after=snapshot(f)
    summary=dict(case=change,status=response.status_code,db_unchanged=old==after,mode_before=before['mode'],mode_after=after['modules'][mid]['mode'],access_adapter_after=after['modules'][mid].get('access_adapter'),request_policy_after=after['modules'][mid].get('request_policy'))
    if change=='request_policy': summary['management_required_after']=website_policy.management_required(after['modules'][mid],'POST','/admin/delete')
    (OUT/('strict-'+change+'.json')).write_text(json.dumps(summary,indent=2)+'\n')
    # Explicit removal restores a valid entry and is a permitted original-check path.
    if change=='private_null':
        assert response.status_code==200 and after['modules'][mid]['private_address'] is None
    else:
        assert response.status_code==422,summary
        assert after==old


@pytest.mark.parametrize('drift',['dns_pin','controlled','missing'])
def test_retained_metadata_never_replaces_target(api_env,upstream,monkeypatch,drift):
    from app.services import integrations as store
    c,f,mid,before,payload,rows,seen=setup(api_env,upstream,monkeypatch,auth='original')
    with f() as db:
        with store.edit(db) as cfg:
            tid=cfg['modules'][mid]['target_id']
            if drift=='dns_pin': cfg['targets'][tid]['allowed_ips']=['127.0.0.2']
            elif drift=='controlled': cfg['targets'][tid]['controlled']=True
            else: del cfg['targets'][tid]
    old=snapshot(f)
    response=c.patch('/website-settings/'+mid,json=payload)
    after=snapshot(f)
    summary=dict(case=drift,status=response.status_code,target_id_changed=after['modules'][mid].get('target_id')!=before['target_id'],targets_exact=old['targets']==after['targets'],target_count_before=len(old['targets']),target_count_after=len(after['targets']),db_unchanged=old==after)
    (OUT/('target-'+drift+'.json')).write_text(json.dumps(summary,indent=2)+'\n')
    assert response.status_code==422,summary
    assert after==old


@pytest.mark.parametrize('transport',['direct','proxy'])
@pytest.mark.parametrize('custom_case',['disabled','enabled','invalid_css','invalid_js','csp'])
def test_code_path_keeps_original_execution_boundaries(api_env,upstream,monkeypatch,transport,custom_case):
    from app.services import integrations_injection as inject, website_assets
    c,f,mid,before,payload,rows,seen=setup(api_env,upstream,monkeypatch,transport)
    _,responses,_=upstream
    custom=dict(enabled=custom_case!='disabled',css='body{color:teal}',js='window.independentCanary=1',timing='dom_ready')
    if custom_case=='invalid_css': custom['css']='body{ color: ; broken'
    if custom_case=='invalid_js': custom['js']='function {'
    if custom_case=='csp': responses['/library?q=a%2Fb']=(200,[('Content-Type','text/html'),('Content-Security-Policy',"default-src 'none'")],b'<html></html>')
    old=snapshot(f)
    response=c.patch('/website-settings/'+mid,json=payload|{'custom':custom})
    expect=422 if custom_case in {'invalid_css','invalid_js'} or (custom_case=='csp' and transport=='proxy') else 200
    assert response.status_code==expect,dict(case=custom_case,transport=transport,status=response.status_code)
    saved=snapshot(f)
    if expect==422: assert saved==old; return
    after=c.get('/external-modules/'+mid).json()
    assert saved['targets']==old['targets'] and after['connection']==before['connection']
    active=saved['modules'][mid]['injection']['active']
    assert active['enabled']==custom['enabled'] and active['csp_policy']=='reject'
    assert saved['website_version_origins'][mid][active['version']]==before['browser_url']
    text,did=inject.inject_html('<html><head></head></html>',mid,active)
    assert did==custom['enabled']
    if transport=='direct':
        # A retired alternate never becomes a loader source origin: resolver rejects.
        with f() as db:
            if custom['enabled']:
                with pytest.raises(HTTPException): website_assets.asset_code(db,mid,custom_allowed=True,parent_origin='http://stella.test')
            else:
                assert website_assets.asset_code(db,mid,custom_allowed=True,parent_origin='http://stella.test')=='/* Website customization disabled. */'


@pytest.mark.parametrize('drift',['module','target','navigation','navigation_visible','entry_revision'])
def test_lock_recheck_rejects_concurrent_change(api_env,upstream,monkeypatch,drift):
    from app.services import website_settings as service, integrations as store, access_entries
    from app.models.config import AppConfig
    c,f,mid,before,payload,rows,seen=setup(api_env,upstream,monkeypatch)
    legacy_probe(f)
    real=service.check_draft
    expected=[]
    if drift=='entry_revision':
        monkeypatch.setattr(access_entries,'pinned_owner',lambda db:'00000000-0000-4000-8000-000000000001')
        old_snapshot=dict(revision=0,enabled=True,public_origin='https://stella-public.example.test',private_origin='https://stella-private.example.test')
        monkeypatch.setattr(access_entries,'current',lambda:copy.deepcopy(old_snapshot))
    async def checked(*args,**kwargs):
        result=await real(*args,**kwargs)
        with f() as db:
            if drift=='entry_revision':
                db.add(AppConfig(key=access_entries.KEY,value=json.dumps(dict(owner_id='00000000-0000-4000-8000-000000000001',settings=old_snapshot|{'revision':1}))))
                db.commit()
            else:
                with store.edit(db) as cfg:
                    if drift=='module': cfg['modules'][mid]['name']='Concurrent writer'
                    elif drift=='target': cfg['targets'][before['target_id']]['name']='Concurrent target writer'
                    elif drift=='navigation_visible': next(row for row in cfg['navigation'] if row['id']==mid)['visible']=False
                    else: next(row for row in cfg['navigation'] if row['id']==mid)['title']='Concurrent navigation writer'
        expected.append(snapshot(f))
        return result
    monkeypatch.setattr(service,'check_draft',checked)
    response=c.patch('/website-settings/'+mid,json=payload)
    observed=snapshot(f)
    summary=dict(case=drift,status=response.status_code,concurrent_state_preserved=observed==expected[-1],navigation_visible_after=next(row for row in observed['navigation'] if row['id']==mid)['visible'],navigation_visible_concurrent=next(row for row in expected[-1]['navigation'] if row['id']==mid)['visible'])
    (OUT/('race-'+drift+'.json')).write_text(json.dumps(summary,indent=2)+'\n')
    assert response.status_code==409,summary
    assert observed==expected[-1]


@pytest.mark.parametrize('transport',['direct','proxy'])
def test_origin_template_drift_and_stale_launch_are_still_denied(api_env,upstream,monkeypatch,transport):
    from types import SimpleNamespace
    from uuid import UUID
    from app.routers import auth as auth_router
    c,f,mid,before,payload,rows,seen=setup(api_env,upstream,monkeypatch,transport)
    old=snapshot(f)
    monkeypatch.setenv('STELLA_APP_ORIGIN_TEMPLATE','https://changed-{id}.example.test')
    response=c.patch('/website-settings/'+mid,json=payload)
    assert response.status_code==422,response.text
    assert snapshot(f)==old
    rows[mid]['public']='https://stale-public.example.test'
    monkeypatch.setattr(auth_router,'_presented_session',lambda *_:SimpleNamespace(user_id=UUID('00000000-0000-4000-8000-000000000001'),id=UUID('00000000-0000-4000-8000-000000000002')))
    response=c.post('/external-modules/'+mid+'/launch')
    assert response.status_code==(403 if transport=='proxy' else 422)
    assert snapshot(f)==old
