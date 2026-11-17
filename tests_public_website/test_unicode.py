"""Escaped historical JSON crosses the real DB and FastAPI UTF-8 boundary."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from tests_public_website.test_projection import checked, module, version
from tests_website_settings.test_website_settings import api_env


@pytest.mark.parametrize('field', ['name', 'icon', 'browser_url', 'origin', 'initial_path',
                                  'injection.active.css', 'injection.active.js',
                                  'injection.active.version', 'injection.active.source_origin'])
@pytest.mark.parametrize('surrogate', ['\ud800', '\udfff'])
def test_unicode_history_http_keeps_healthy_neighbor_and_private_storage(api_env, field, surrogate):
    from app.models.config import AppConfig
    from app.public_website import PublicModule, PublicNavigation
    from app.services import integrations

    _, factory, app, _ = api_env
    healthy = module() | dict(id='healthy', name='中文🌟𠀀', browser_url='https://例子.测试/中文/🌟?q=%2f#片段')
    healthy['injection'] = {slot: version() | dict(js='window.secret = "<script>中文🌟</script>";')
                            for slot in ('draft', 'active', 'previous')}
    bad = copy.deepcopy(healthy) | dict(id='legacy')
    parts = field.split('.')
    target = bad
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] += surrogate
    bad['private'] = {'secret': 'SYNTHETIC_UNICODE_PRIVATE', surrogate: surrogate}
    with factory() as db:
        state = integrations.state(db)
        state['modules'] = {'healthy': healthy, 'legacy': bad}
        text = json.dumps(state, ensure_ascii=True)
        db.add(AppConfig(key=integrations.KEY, value=text))
        db.commit()
    # A fresh session must really decode the escaped historical value.
    with factory() as db:
        assert integrations.state(db)['modules']['legacy'] == bad
    with TestClient(app, base_url='http://stella.test', raise_server_exceptions=False) as client:
        response = client.get('/external-modules')
        detail = client.get('/external-modules/legacy')
        navigation = client.get('/navigation')
    with factory() as db:
        assert db.get(AppConfig, integrations.KEY).value == text
    assert response.status_code == detail.status_code == navigation.status_code == 200
    good, projected = response.json()
    assert projected == detail.json()
    PublicModule.model_validate(good)
    PublicModule.model_validate(projected)
    PublicNavigation.model_validate(navigation.json())
    assert good['name'] == healthy['name'] and good['browser_url'] == healthy['browser_url']
    assert good['injection'] == healthy['injection']
    assert 'projection' not in good
    assert projected['projection']['state'] == 'incomplete'
    assert field in projected['projection']['invalid_fields']
    assert projected['enabled'] is True
    assert projected['injection']['previous'] == healthy['injection']['previous']
    assert 'SYNTHETIC_UNICODE_PRIVATE' not in response.text + detail.text + navigation.text
    nav_good = next(e for e in navigation.json()['entries'] if e['id'] == 'healthy')
    nav_bad = next(e for e in navigation.json()['entries'] if e['id'] == 'legacy')
    assert nav_good['title'] == healthy['name'] and nav_good['icon'] == healthy['icon']
    assert nav_bad['projection']['state'] == 'incomplete'


@pytest.mark.parametrize('field', ['title', 'icon'])
@pytest.mark.parametrize('mid', ['home', 'legacy-id'])
def test_unicode_navigation_override_uses_safe_original(api_env, field, mid):
    from app.models.config import AppConfig
    from app.services import integrations

    _, factory, app, _ = api_env
    raw = module()
    with factory() as db:
        state = integrations.state(db)
        state['modules'] = {raw['id']: raw}
        state['navigation'] = [dict(id=mid, **{field: '\ud800'})]
        text = json.dumps(state, ensure_ascii=True)
        db.add(AppConfig(key=integrations.KEY, value=text))
        db.commit()
    with TestClient(app, base_url='http://stella.test', raise_server_exceptions=False) as client:
        nav = client.get('/navigation')
        detail = client.get('/external-modules/legacy-id')
    with factory() as db:
        assert db.get(AppConfig, integrations.KEY).value == text
    assert nav.status_code == detail.status_code == 200
    item = next(e for e in nav.json()['entries'] if e['id'] == mid)
    assert field in item['projection']['invalid_fields']
    if mid == 'legacy-id':
        assert detail.json()['name'] == raw['name']
        assert detail.json()['icon'] == raw['icon']
        assert 'navigation.' + field in detail.json()['projection']['invalid_fields']


@pytest.mark.parametrize('kind,raw', [
    ('module', module() | {'icon': '\ud800'}),
    ('module', module() | {'injection': {'active': version() | {'js': '\ud800'}}}),
    ('module', module() | {'connection': {'auth_mode': []}}),
    ('module', None),
    ('versions', {'active': version() | {'source_origin': 'javascript:invalid'}}),
    ('versions', {'draft': None, 'active': None, 'previous': None}),
    ('check', checked() | {'embedding': {'reason': '\ud800'}}),
    ('target', dict(id='target', name='目标', upstream_url='https://site.test',
                    allowed_ips=['127.0.0.1'], controlled=True,
                    headers={'authorization': 'SYNTHETIC_PRIVATE_HEADER'})),
    ('target', {'name': '\ud800', 'headers': []}),
])
def test_unicode_public_projection_is_idempotent_after_json_roundtrip(kind, raw):
    from app.public_website import public_module, public_versions, public_check, public_target
    from starlette.responses import JSONResponse

    project = dict(module=public_module, versions=public_versions, check=public_check, target=public_target)[kind]
    before = copy.deepcopy(raw)
    first = project(raw)
    second = project(json.loads(bytes(JSONResponse(first).body)))
    assert second == first
    assert project(second) == first
    assert raw == before
    assert 'SYNTHETIC_PRIVATE_HEADER' not in bytes(JSONResponse(second).body).decode()


@pytest.mark.parametrize('marker', [
    {'state': 'complete', 'invalid_fields': []},
    {'state': 'incomplete', 'invalid_fields': ['SYNTHETIC_PRIVATE_PATH', '\ud800', 'connection.token']},
    {'state': 'incomplete', 'invalid_fields': {'secret': 'SYNTHETIC_PRIVATE_PATH'}},
])
def test_unicode_untrusted_status_never_echoes_values_or_claims_normal(marker):
    from app.public_website import public_module
    from starlette.responses import JSONResponse

    raw = module() | dict(projection=marker)
    first = public_module(raw)
    assert first['projection'] == dict(state='incomplete', invalid_fields=['projection'])
    assert public_module(first) == first
    assert 'SYNTHETIC_PRIVATE' not in bytes(JSONResponse(first).body).decode()


@pytest.mark.parametrize('value', [None, [], {}, True, 1, 'false', '\ud800', '\udfff'])
def test_unicode_each_module_field_remains_incomplete_on_reprojection(value):
    from app.public_website import PublicModule, public_module
    from starlette.responses import JSONResponse

    for field in PublicModule.model_fields:
        first = public_module(module() | {field: value})
        assert public_module(json.loads(bytes(JSONResponse(first).body))) == first, field
