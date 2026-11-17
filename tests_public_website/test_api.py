"""Loopback HTTP + synthetic SQLite; no application PG and no live credentials."""
import copy
import pytest

from tests_public_website.test_projection import module

from tests_website_settings.test_website_settings import api_env, upstream


def test_fresh_and_replay_share_projection_without_rewriting_private_receipt(api_env, upstream, monkeypatch):
    from app.services import website_settings, integrations
    client, factory, _, _ = api_env
    root, _, seen = upstream
    real_check = website_settings.check_draft

    async def legacy_check(*args, **kwargs):
        result = await real_check(*args, **kwargs)
        result['private'] = {'secret': 'synthetic-fresh-receipt'}
        result['access']['token'] = 'synthetic-fresh-access'
        return result

    monkeypatch.setattr(website_settings, 'check_draft', legacy_check)
    draft = dict(address=root + '/site', idempotency_key='public-projection-save',
                 template_id='user_' + 'a' * 32, custom={'enabled': True, 'css': 'body{color:red}'})
    fresh = client.post('/website-settings', json=draft)
    assert fresh.status_code == 201, fresh.text
    assert 'synthetic-fresh' not in fresh.text
    module = fresh.json()
    assert module['template_id'] == draft['template_id']
    assert module['injection']['active']['css'] == draft['custom']['css']
    with factory() as db:
        before = copy.deepcopy(integrations.state(db))
    receipt = next(iter(before['website_save_keys'].values()))
    assert receipt['check']['private']['secret'] == 'synthetic-fresh-receipt'
    requests = len(seen)
    replay = client.post('/website-settings', json=draft)
    assert replay.status_code == 201 and replay.json() == module
    assert len(seen) == requests
    with factory() as db:
        assert integrations.state(db) == before


@pytest.mark.parametrize('raw', [None, [], 'synthetic-invalid', {}, {'id': ['synthetic-invalid']}])
def test_module_list_keeps_healthy_siblings_and_never_rewrites_malformed_rows(api_env, raw):
    from app.public_website import PublicModule, PublicNavigation, PublicTarget
    from app.services import integrations
    client, factory, _, _ = api_env
    with factory() as db:
        with integrations.edit(db) as state:
            state['modules'] = {'legacy-id': module(), 'malformed': raw}
            state['targets'] = {'bad': raw}
        before = copy.deepcopy(integrations.state(db))
    response = client.get('/external-modules')
    assert response.status_code == 200 and len(response.json()) == 2
    for item in response.json():
        PublicModule.model_validate(item)
    assert response.json()[0]['name'] == 'Owner website'
    assert response.json()[1]['projection']['state'] == 'incomplete'
    nav = client.get('/navigation')
    assert nav.status_code == 200
    PublicNavigation.model_validate(nav.json())
    targets = client.get('/integration-targets')
    assert targets.status_code == 200
    PublicTarget.model_validate(targets.json()[0])
    assert 'synthetic-invalid' not in response.text + nav.text + targets.text
    with factory() as db:
        assert integrations.state(db) == before


@pytest.mark.parametrize('action,slot', [('apply', 'draft'), ('rollback', 'previous')])
@pytest.mark.parametrize('bad', [[], {'enabled': True}, {'version': ['synthetic-invalid']}])
def test_invalid_legacy_publish_is_controlled_without_rewriting_history(api_env, action, slot, bad):
    from app.services import integrations
    client, factory, _, _ = api_env
    raw = module()
    raw['injection'][slot] = bad
    with factory() as db:
        with integrations.edit(db) as state:
            state['modules']['legacy-id'] = raw
        before = copy.deepcopy(integrations.state(db))
    response = client.post(f'/external-modules/legacy-id/injection/{action}')
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'incomplete_injection'
    assert 'synthetic-invalid' not in response.text
    with factory() as db:
        assert integrations.state(db) == before
