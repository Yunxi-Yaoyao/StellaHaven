"""Real schemas/routes with synthetic SQLite + loopback HTTP only.
Run with -p tests_website_settings.review_isolation --noconftest from scratch.
This does NOT claim PostgreSQL/concurrency or production integration coverage.
"""
import pytest
from tests_website_settings.test_website_settings import api_env, upstream  # noqa: F401
from app.navigation_icons import NAVIGATION_ICONS


def test_every_legal_key_is_accepted_by_all_three_real_schemas():
    from app.services.integrations import ModuleInput, NavigationEntry
    from app.services.website_settings import WebsiteInput
    for key in NAVIGATION_ICONS:
        assert ModuleInput(name='Fixture', icon=key).icon == key
        assert NavigationEntry(id='home', icon=key).icon == key
        assert WebsiteInput(address='http://fixture.test', icon=key).icon == key
    for model, fields in [(ModuleInput, {'name': 'Fixture'}), (NavigationEntry, {'id': 'home'}), (WebsiteInput, {'address': 'http://fixture.test'})]:
        for key in ['future-icon-v2', '<script>', '', 'HOME']:
            with pytest.raises(ValueError): model(icon=key, **fields)


def test_all_124_keys_save_read_back_and_survive_an_unrelated_edit(upstream, api_env):
    root, _, _ = upstream
    client, _, _, _ = api_env
    for key in sorted(NAVIGATION_ICONS):
        created = client.post('/website-settings', json=dict(address=root + '/icons', name='图标测试', icon=key, idempotency_key='catalog-' + key))
        assert created.status_code == 201, (key, created.text)
        mid = created.json()['id']
        assert client.get('/external-modules/' + mid).json()['icon'] == key
        changed = client.patch('/website-settings/' + mid, json=dict(address=root + '/icons', name='只改名称'))
        assert changed.status_code == 200, (key, changed.text)
        assert changed.json()['icon'] == key
        assert client.get('/external-modules/' + mid).json()['icon'] == key
        entry = next(e for e in client.get('/navigation').json()['entries'] if e['id'] == mid)
        assert entry['icon'] == key


def test_unknown_stored_value_is_not_silently_replaced_on_rejected_save(upstream, api_env):
    from app.services import integrations as store
    root, _, _ = upstream
    client, factory, _, _ = api_env
    created = client.post('/website-settings', json=dict(address=root + '/icons', name='旧网站', idempotency_key='unknown-legacy-icon')).json()
    mid = created['id']
    with factory() as db:
        with store.edit(db) as config:
            config['modules'][mid]['icon'] = 'future-icon-v2'
            next(e for e in config['navigation'] if e['id'] == mid)['icon'] = 'future-icon-v2'
    result = client.patch('/website-settings/' + mid, json=dict(address=root + '/icons', name='只改名称'))
    assert result.status_code == 422  # Existing backend policy, not a silent migration.
    assert client.get('/external-modules/' + mid).json()['icon'] == 'future-icon-v2'
