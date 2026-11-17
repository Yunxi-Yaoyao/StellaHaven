"""Actual v22 routes and real owner/session auth; DB wiring is memory-only.
No main/lifespan/PG/proxy/browser claim. Reuses the file-owned native DB fence.
"""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
import uuid
import pytest
from jsonschema import Draft202012Validator
from test_api_response_v6_runtime import runtime_boundary,auth_env,installed,owner,upstream,validate,DAILY


def saved(installed,upstream):
    c,db,app=installed;uid=owner(c);origin,_,seen=upstream
    body={'address':origin+'/site','name':'v22 site','idempotency_key':'create-v22-fixture','background':'home'}
    created=c.post('/website-settings',json=body)
    assert created.status_code==201,created.text
    validate('POST','/website-settings',created)
    mid=created.json()['id'];revision=created.json()['navigation']['revision']
    patched=c.patch('/website-settings/'+mid,json={'address':origin+'/site','name':'renamed','idempotency_key':'patch-v22-fixture','expected_revision':revision})
    assert patched.status_code==200,patched.text
    validate('PATCH','/website-settings/{mid}',patched)
    return c,db,app,uid,mid,patched


def test_real_http_save_receipt_navigation_etag_and_input_constraints(installed,upstream,record_property):
    c,db,app,uid,mid,saved_response=saved(installed,upstream)
    from private_remediation_evidence_fixture import review as v22_review
    schema=c.get('/openapi.json').json()
    for key,signature in v22_review()['request_signatures'].items():
        method,path=key.split(' ',1)
        request=schema['paths'][path][method.lower()]['requestBody']
        assert request==signature['request_body']
        assert schema['components']['schemas'][signature['model']]==signature['schema']
    receipt=c.get('/website-settings/'+mid+'/receipt',params={'idempotency_key':'patch-v22-fixture'})
    assert receipt.status_code==200,receipt.text
    assert receipt.json()==saved_response.json()
    from app.api_response_contracts import MODELS
    validator=Draft202012Validator(MODELS['V22NavigationSnapshot'])
    for missing in ('modules','revision','mutation_id'):
        damaged=deepcopy(receipt.json()['navigation']);damaged.pop(missing)
        assert not validator.is_valid(damaged)
    damaged=deepcopy(receipt.json()['navigation']);damaged['modules'][0]['injection']={}
    assert not validator.is_valid(damaged)
    assert receipt.json()['idempotency_key']=='patch-v22-fixture'
    assert receipt.headers['cache-control']=='no-store'
    validate('GET','/website-settings/{mid}/receipt',receipt)
    navigation=c.get('/navigation');assert navigation.status_code==200;validate('GET','/navigation',navigation)
    assert navigation.json()==receipt.json()['navigation']
    summary,=[m for m in navigation.json()['modules'] if m['id']==mid]
    assert set(summary)=={'id','name','icon','mode','adapter','browser_url','enabled','keep_alive','template_id','route','runtime_revision','background'}
    assert summary['background']=='home'
    detail=c.get('/external-modules/'+mid);assert detail.status_code==200
    validate('GET','/external-modules/{mid}',detail)
    assert 'runtime_revision' not in detail.json()
    assert detail.headers['etag']=='"'+str(navigation.json()['revision'])+'"'
    assert detail.headers['cache-control']=='no-store'
    unchanged=c.get('/external-modules/'+mid,headers={'If-None-Match':detail.headers['etag']})
    assert unchanged.status_code==200 and unchanged.json()==detail.json()
    assert c.get('/website-settings/'+mid+'/receipt',params={'idempotency_key':'not-found-v22'}).status_code==404
    for key in ('bad','invalid key','x'*129):
        response=c.get('/website-settings/'+mid+'/receipt',params={'idempotency_key':key})
        assert response.status_code==422;validate('GET','/website-settings/{mid}/receipt',response)
    for value in (-1,True,'3'):
        response=c.patch('/website-settings/'+mid,json={'address':upstream[0]+'/site','expected_revision':value})
        assert response.status_code==422;validate('PATCH','/website-settings/{mid}',response)
    entries=[{'id':x['id']} for x in navigation.json()['entries']]
    conflict=c.put('/navigation',json={'entries':entries,'expected_revision':navigation.json()['revision']+1,'mutation_id':'stale-v22'})
    assert conflict.status_code==409;validate('PUT','/navigation',conflict)
    for value in (-1,True,'3'):
        response=c.put('/navigation',json={'entries':entries,'expected_revision':value,'mutation_id':'invalid-v22'})
        assert response.status_code==422;validate('PUT','/navigation',response)
    record_property('v22_actual_http',json.dumps({'receipt':receipt.json(),'navigation':navigation.json(),'detail':detail.json(),'detail_headers':dict(detail.headers)},ensure_ascii=False))


@pytest.mark.parametrize('boundary',['anonymous','revoked','expired','deactivated','owner-pin','foreign'])
def test_receipt_rechecks_real_owner_sid_and_retained_state(installed,upstream,monkeypatch,boundary):
    from app.models.user import User,AuthSession
    from app.security import make_access_token,hash_password
    from app.services import integrations as store
    c,db,app,uid,mid,response=saved(installed,upstream)
    url='/website-settings/'+mid+'/receipt?idempotency_key=patch-v22-fixture'
    assert c.get(url).status_code==200
    before=deepcopy(store.state(db));db.rollback()
    user=db.get(User,uuid.UUID(str(uid)))
    session=db.query(AuthSession).filter_by(user_id=user.id,revoked=False).one()
    if boundary=='anonymous':c.cookies.clear()
    elif boundary=='revoked':session.revoked=True
    elif boundary=='expired':session.remember=False;session.created_at=session.last_seen=datetime.now(timezone.utc)-timedelta(days=366)
    elif boundary=='deactivated':user.is_active=False
    elif boundary=='owner-pin':monkeypatch.setenv('STELLA_OWNER_ID',str(uuid.uuid4()))
    else:
        foreign=User(username='foreign',display_name='foreign',password_hash=hash_password(DAILY),is_admin=True)
        db.add(foreign);db.flush();sid=AuthSession(user_id=foreign.id,refresh_hash='v22-foreign',remember=True,last_seen=datetime.now(timezone.utc),created_at=datetime.now(timezone.utc));db.add(sid);db.flush()
        c.cookies.clear();c.cookies.set('stella_at',make_access_token(str(foreign.id),str(sid.id)))
    db.commit()
    rejected=c.get(url)
    assert rejected.status_code in ({401} if boundary in {'anonymous','revoked','expired','deactivated'} else {403,503}),rejected.text
    validate('GET','/website-settings/{mid}/receipt',rejected)
    assert store.state(db)==before
    db.rollback()


@pytest.mark.parametrize('change,expected',[('expired',404),('module',409),('navigation',409)])
def test_actual_receipt_expiry_and_supersession_are_read_only(installed,upstream,change,expected):
    from app.models.config import AppConfig
    from app.services import integrations as store
    c,db,app,uid,mid,response=saved(installed,upstream)
    row=db.get(AppConfig,store.KEY);config=json.loads(row.value)
    slot=str(uid)+':'+mid+':patch-v22-fixture'
    if change=='expired':config['website_save_keys'][slot]['expires']=0
    elif change=='module':config['modules'][mid]['name']='later edit'
    else:config['navigation_revision']+=1
    row.value=json.dumps(config,ensure_ascii=False);db.commit()
    before=row.value
    result=c.get('/website-settings/'+mid+'/receipt',params={'idempotency_key':'patch-v22-fixture'})
    assert result.status_code==expected,result.text
    validate('GET','/website-settings/{mid}/receipt',result)
    db.expire_all();assert db.get(AppConfig,store.KEY).value==before
