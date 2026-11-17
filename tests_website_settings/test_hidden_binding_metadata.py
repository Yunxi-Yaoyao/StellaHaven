"""Metadata edits retain an unchanged historical binding, never authorize it.
Real router + SQLite + loopback fixture; no production state or network.
"""
import copy
import pytest
from fastapi import HTTPException
from tests_website_settings.test_website_settings import api_env, upstream


@pytest.mark.parametrize('transport', ['direct', 'proxy'])
@pytest.mark.parametrize('edit_code', [False, True])
def test_unchanged_hidden_binding_does_not_trap_metadata_edits(api_env, upstream, monkeypatch, transport, edit_code):
    from app.services import integrations as store, entry_registry
    c, factory, _, _ = api_env
    root, _, seen = upstream
    created = c.post('/website-settings', json=dict(address=root+'/library?q=a%2Fb#keep', name='Original', icon='globe',
        connection=dict(transport=transport, auth_mode='header' if transport=='proxy' else 'oidc', header_name='X-API-Key',
                        injection_delivery='proxy' if transport=='proxy' else 'loader', token='fixture-only' if transport=='proxy' else None),
        idempotency_key='create-hidden-'+transport))
    assert created.status_code == 201, created.text
    mid = created.json()['id']
    alternate = 'https://retired-entry.example.test/library?q=a%2Fb#keep'
    with factory() as db:
        with store.edit(db) as config:
            config['modules'][mid]['private_address'] = alternate
    before = c.get('/external-modules/'+mid).json()
    # Prove this exact historical value was valid under the former registry.
    rows = {'stella': {'public':'http://stella.test', 'private':'https://stella-private.example.test'},
            mid: {'public': (before['origin'] if before['mode'] == 'isolated_proxy' else before['browser_url']), 'private':'https://retired-entry.example.test'}}
    monkeypatch.setattr(entry_registry, 'records', lambda: copy.deepcopy(rows))
    entry_registry.validate_website_entry(before)
    # Now the operator registry no longer authorizes the stored binding.
    rows[mid] = {'public':'https://replacement.example.test', 'private':'https://new-private.example.test'}
    with pytest.raises(HTTPException): entry_registry.validate_website_entry(before)
    with factory() as db: targets_before = copy.deepcopy(store.state(db)['targets'])
    payload = dict(address=before['browser_url'], name='Metadata saved', icon='star', visible=True,
                   open_behavior='embedded', entry_policy=before['entry_policy'], idempotency_key='edit-hidden-'+transport)
    if edit_code: payload['custom'] = dict(enabled=False, css='/* preserved user edit */body{}', js='', timing='dom_ready')
    seen.clear()
    updated = c.patch('/website-settings/'+mid, json=payload)
    assert updated.status_code == 200, updated.text
    after = c.get('/external-modules/'+mid).json()
    assert after['name'] == 'Metadata saved'
    for field in ['private_address','entry_policy','browser_url','mode','origin','target_id','initial_path','connection']:
        assert after.get(field) == before.get(field), field
    with factory() as db: assert store.state(db)['targets'] == targets_before
    assert seen == [], 'Unchanged local metadata/code must not probe retained upstream'
    assert updated.json()['check']['access'] == {'status':'unknown','http_status':None}
    assert updated.json()['check']['embedding']['reason_code'] == ('code_only' if edit_code else 'metadata_only')
    if edit_code: assert after['injection']['active']['css'] == payload['custom']['css']
    else: assert after['injection'] == before['injection']
    # Metadata retention is not permission to launch a stale origin.
    with pytest.raises(HTTPException):
        if transport == 'proxy': entry_registry.module_context(after, 'http://stella.test')
        else: entry_registry.browser_url(after, 'http://stella.test')
    # Exercise the actual launch router too. Only its presented-session identity
    # is synthetic; the registry selection/denial and persisted tickets are real.
    from types import SimpleNamespace
    from uuid import UUID
    from app.routers import auth as auth_router
    monkeypatch.setattr(auth_router, '_presented_session', lambda *_: SimpleNamespace(user_id=UUID('00000000-0000-4000-8000-000000000001'), id=UUID('00000000-0000-4000-8000-000000000002')))
    with factory() as db: tickets_before = copy.deepcopy(store.state(db)['tickets'])
    launch = c.post('/external-modules/'+mid+'/launch')
    assert launch.status_code == (403 if transport=='proxy' else 422), launch.text
    with factory() as db: assert store.state(db)['tickets'] == tickets_before
    assert c.patch('/website-settings/'+mid, json=payload).json() == updated.json()
    stable = copy.deepcopy(after)
    for change in [dict(private_address=alternate), dict(entry_policy='public'), dict(address=root+'/different'),
                   dict(connection=dict(transport=transport, auth_mode='original', header_name='Authorization', injection_delivery='proxy' if transport=='proxy' else 'loader'))]:
        rejected = c.patch('/website-settings/'+mid, json=payload | change | {'idempotency_key':'reject-hidden-'+next(iter(change))})
        assert rejected.status_code == 422, rejected.text
        assert c.get('/external-modules/'+mid).json() == stable
    monkeypatch.setenv('STELLA_APP_ORIGIN_TEMPLATE', 'https://changed-{id}.example.test')
    template_drift = c.patch('/website-settings/'+mid, json=payload | {'idempotency_key':'reject-origin-template-drift'})
    assert template_drift.status_code == 422, template_drift.text
    assert c.get('/external-modules/'+mid).json() == stable
