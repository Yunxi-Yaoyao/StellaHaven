"""Saved template contract: disposable SQLite; no live DB or service writes."""
import copy
import json
import pytest
from tests_website_settings.test_website_settings import api_env, upstream

@pytest.fixture(autouse=True)
def template_origin(monkeypatch):
    monkeypatch.setenv('STELLA_MAIN_ORIGIN', 'https://stella.test')


def client_with_templates(api_env):
    from app.routers.website_settings import assets_router
    c, factory, app, admin = api_env
    app.include_router(assets_router)
    return c, factory, app, admin


def test_save_named_snapshot_redacts_secrets_and_does_not_create_navigation(api_env):
    from app.services import integrations as store
    c, factory, _, admin = client_with_templates(api_env)
    draft = dict(address='https://private.test/?password=fixture-secret', name='Source', icon='globe',
                 custom=dict(enabled=True, css='body{color:red}', js='window.example=1', timing='document_start'),
                 connection=dict(transport='proxy', auth_mode='header', header_name='X-API-Key', token='fixture-secret', injection_delivery='proxy'),
                 request_policy=dict(management_prefixes=['/admin'], read_post_paths=['/write'], protect_other_writes=False),
                 target_id='never-copy', headers={'Authorization':'hidden-secret'})
    response = c.post('/website-templates', json={'name':'DNS console theme', 'draft':draft})
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved['id'].startswith('user_') and saved['provenance'] == 'user'
    assert saved['name'] == 'DNS console theme'
    assert set(saved['draft']) <= {'name','icon','open_behavior','keep_alive','custom','connection','background','request_policy'}
    assert saved['draft']['custom'] == draft['custom']
    assert saved['draft']['connection'] == {k:v for k,v in draft['connection'].items() if k != 'token'}
    assert saved['draft']['request_policy'] == {'management_prefixes':['/admin'],'read_post_paths':[],'protect_other_writes':True}
    assert not any(value in response.text for value in ['fixture-secret','hidden-secret','private.test','never-copy'])
    catalog = c.get('/website-templates')
    assert catalog.status_code == 200 and catalog.headers['cache-control'] == 'no-store'
    assert [t['id'] for t in catalog.json()] == ['openlist','immich',saved['id']]
    assert len(admin) == 1
    with factory() as db:
        state = store.state(db)
        assert not state['modules'] and not state['navigation'] and not state['targets']
        assert len(state['website_templates']) == 1
    assert c.delete('/website-templates/'+saved['id']).status_code == 204
    assert [t['id'] for t in c.get('/website-templates').json()] == ['openlist','immich']
    assert len(admin) == 2


def test_saved_template_id_is_provenance_not_runtime_dependency(api_env, upstream, monkeypatch):
    c, factory, _, _ = client_with_templates(api_env)
    root, _, _ = upstream
    saved = c.post('/website-templates', json={'name':'My theme','draft':{'custom':{'css':'body{color:red}'}}}).json()
    monkeypatch.setenv('STELLA_MAIN_ORIGIN','http://stella.test')
    draft = saved['draft'] | {'address':root+'/', 'template_id':saved['id'], 'idempotency_key':'template-clone-1'}
    one = c.post('/website-settings',json=draft)
    assert one.status_code == 201, one.text
    two = c.post('/website-settings',json=draft | {'idempotency_key':'template-clone-2'})
    assert two.status_code == 201, two.text
    assert one.json()['id'] != two.json()['id']
    before = c.get('/external-modules/'+one.json()['id']).json()
    assert c.delete('/website-templates/'+saved['id']).status_code == 204
    assert c.get('/external-modules/'+one.json()['id']).json() == before
    assert c.patch('/website-settings/'+one.json()['id'],json=draft | {'name':'Still independent','idempotency_key':'template-clone-edit'}).status_code == 200
    from app.services.website_settings import WebsiteInput
    from pydantic import ValidationError
    for value in ('user_bad', 'user_'+'F'*32, '../../targets', 'openlist/other'):
        with pytest.raises(ValidationError): WebsiteInput(address=root+'/',template_id=value)


def test_template_accepts_unnamed_website_draft_without_requiring_a_target(api_env):
    c, _, _, _ = client_with_templates(api_env)
    response = c.post('/website-templates',json={'name':'Reusable blank','draft':{'name':'','address':'','custom':{'enabled':False,'css':'body{color:teal}'}}})
    assert response.status_code == 201, response.text
    assert 'name' not in response.json()['draft']
    assert 'address' not in response.json()['draft']


def test_template_auth_owner_scope_limits_and_private_errors(api_env):
    from app.routers.auth import admin_user, current_user
    from fastapi import HTTPException
    from types import SimpleNamespace
    from app.services import integrations as store
    c, factory, app, admin = client_with_templates(api_env)
    saved = c.post('/website-templates',json={'name':'Owned','draft':{}}).json()
    def denied(): raise HTTPException(403, 'admin required')
    app.dependency_overrides[admin_user] = denied
    assert c.get('/website-templates').status_code == 200
    assert c.post('/website-templates',json={'name':'Denied','draft':{}}).status_code == 403
    assert c.delete('/website-templates/'+saved['id']).status_code == 403
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id='another-owner')
    assert [t['id'] for t in c.get('/website-templates').json()] == ['openlist','immich']
    app.dependency_overrides[admin_user] = lambda: SimpleNamespace(id='another-owner')
    assert c.delete('/website-templates/'+saved['id']).status_code == 404
    assert c.delete('/website-templates/openlist').status_code == 404
    for body in ({'name':'  ','draft':{}},{'name':'Bad','draft':{'custom':{'css':'x'*65537}}},{'name':'Bad','draft':{'custom':{'js':'x'*131073}}},{'name':'Bad','draft':{'connection':{'token':'fixture-secret'},'custom':{'js':'fixture-secret'}}}):
        response = c.post('/website-templates',json=body)
        assert response.status_code == 422, response.text
        assert 'fixture-secret' not in response.text
    assert c.post('/website-templates',content=b' '*1048577,headers={'content-type':'application/json'}).status_code == 413
    with factory() as db:
        with store.edit(db) as state:
            state['website_templates'].update({'user_'+f'{i:032x}':dict(id='user_'+f'{i:032x}',owner_id='another-owner',name='Bounded',draft={}) for i in range(127)})
    assert c.post('/website-templates',json={'name':'Overflow','draft':{}}).status_code == 422
    with factory() as db: assert len(store.state(db)['website_templates']) == 128


def test_keyed_template_retry_is_atomic_owner_scoped_and_conflict_guarded(api_env, monkeypatch):
    from app.services import integrations as store
    from app.routers.auth import current_user, admin_user
    from types import SimpleNamespace
    c, factory, app, _ = client_with_templates(api_env)
    payload = {'name':'Retry snapshot','draft':{'custom':{'css':'body{color:teal}'}},'idempotency_key':'template-operation-1'}
    one = c.post('/website-templates',json=payload)
    assert one.status_code == 201, one.text
    # A stale pre-lock read must not decide deduplication; store.edit owns it.
    with monkeypatch.context() as patch:
        patch.setattr(store, 'state', lambda db: (_ for _ in ()).throw(AssertionError('outside edit read')))
        retry = c.post('/website-templates',json=payload)
    assert retry.status_code == 201 and retry.json() == one.json()
    with factory() as db:
        before = copy.deepcopy(store.state(db))
    for changed in ({'name':'Different'}, {'draft':{'custom':{'css':'body{color:red}'}}}):
        assert c.post('/website-templates',json=payload | changed).status_code == 409
    with factory() as db: assert store.state(db) == before
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id='another-owner')
    app.dependency_overrides[admin_user] = lambda: SimpleNamespace(id='another-owner')
    two = c.post('/website-templates',json=payload)
    assert two.status_code == 201 and two.json()['id'] != one.json()['id']
    assert [t['id'] for t in c.get('/website-templates').json() if t['provenance']=='user'] == [two.json()['id']]
    assert c.delete('/website-templates/'+one.json()['id']).status_code == 404
    assert c.delete('/website-templates/'+two.json()['id']).status_code == 204
    assert c.post('/website-templates',json=payload).status_code == 409  # never resurrect a deleted retry
    with factory() as db:
        state = store.state(db)
        assert len(state['website_templates']) == 1
        assert not state['modules'] and not state['navigation'] and not state['targets']


def test_template_receipts_are_bounded_private_and_retry_even_at_catalog_capacity(api_env):
    from app.services import integrations as store
    c, factory, _, _ = client_with_templates(api_env)
    body = {'name':'Bounded receipt','draft':{'connection':{'token':'synthetic-not-exported'}},'idempotency_key':'template-bounded-1'}
    first = c.post('/website-templates',json=body)
    assert first.status_code == 201
    with factory() as db:
        with store.edit(db) as state:
            receipt = next(iter(state['website_template_save_keys'].values()))
            assert set(receipt) == {'id','digest','expires'}
            assert 'synthetic-not-exported' not in json.dumps(state)
            for i in range(127):
                tid = 'user_'+f'{i:032x}'
                state['website_templates'][tid] = dict(id=tid,owner_id='other',name='Full',draft={})
            state['grants']['unrelated'] = {'keep':True}
        before = copy.deepcopy(store.state(db))
    assert c.post('/website-templates',json=body).json() == first.json()
    assert c.post('/website-templates',json=body | {'idempotency_key':'another-operation'}).status_code == 422
    with factory() as db: assert store.state(db) == before
    assert 'idempotency_key' not in c.get('/website-templates').text


def test_template_receipt_expiry_and_eviction_follow_website_save_bounds(api_env, monkeypatch):
    from app.services import integrations as store
    from app.services import saved_website_templates as service
    c, factory, _, _ = client_with_templates(api_env)
    monkeypatch.setattr(service.time, 'time', lambda: 2000000000)
    with factory() as db:
        with store.edit(db) as state:
            state['website_template_save_keys'] = {f'fixture:{i}':dict(id='gone',digest='synthetic',expires=2000000001+i) for i in range(128)}
            state['website_template_save_keys']['expired'] = dict(id='gone',digest='synthetic',expires=1999999999)
    response = c.post('/website-templates',json={'name':'Bounded','draft':{},'idempotency_key':'template-bounded-new'})
    assert response.status_code == 201
    with factory() as db:
        keys = store.state(db)['website_template_save_keys']
        assert len(keys) == 128 and 'expired' not in keys and 'fixture:0' not in keys
        receipt = next(v for v in keys.values() if v['id']==response.json()['id'])
        assert receipt['expires'] == 2000086400


@pytest.mark.parametrize('key', ['short', 'x'*129, 'invalid/key', 'line\nbreak'])
def test_template_operation_key_validation_is_private(api_env, key):
    c, _, _, _ = client_with_templates(api_env)
    result = c.post('/website-templates',json={'name':'Bad key','draft':{'connection':{'token':'synthetic-private-input'}},'idempotency_key':key})
    assert result.status_code == 422 and 'synthetic-private-input' not in result.text


def test_template_failed_commit_rolls_back_without_changing_other_registry_data(api_env, monkeypatch):
    from app.services import integrations as store
    c, factory, _, _ = client_with_templates(api_env)
    with factory() as db:
        with store.edit(db) as state: state['grants']['unrelated'] = {'keep':True}
        before = copy.deepcopy(store.state(db))
    def broken_commit(self): raise RuntimeError('synthetic commit failure')
    with monkeypatch.context() as patch:
        patch.setattr(factory.class_, 'commit', broken_commit)
        with pytest.raises(RuntimeError,match='synthetic commit failure'):
            c.post('/website-templates',json={'name':'Fail atomic','draft':{},'idempotency_key':'rollback-template-operation'})
    with factory() as db: assert store.state(db) == before
