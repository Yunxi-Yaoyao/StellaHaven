"""Coverage of the common text boundary, URI spelling and replay receipts."""
import copy
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from tests_public_website.test_projection import checked, module, version
from tests_website_settings.test_website_settings import api_env, upstream


def change(raw, path, value):
    target = raw
    parts = path.split('.')
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


@pytest.mark.parametrize('field,value', [
    ('name', '\ud800'), ('upstream_url', 'https://example.test/\udfff'),
    ('allowed_ips', ['127.0.0.1', '\ud800']), ('id', '\udfff'),
    ('credential_headers', ['authorization', '\ud800']),
])
def test_unicode_target_http_keeps_neighbor_and_raw_headers(api_env, field, value):
    from app.models.config import AppConfig
    from app.public_website import PublicTarget, public_target
    from app.services import integrations

    _, factory, app, _ = api_env
    good = dict(id='healthy', name='目标🌟', upstream_url='https://例子.测试/路径?q=%2f#🌟',
                allowed_ips=['127.0.0.1'], controlled=True,
                headers={'authorization': 'SYNTHETIC_UNICODE_SECRET', '\ud800': '\udfff'})
    bad = copy.deepcopy(good) | dict(id='legacy')
    bad[field] = value
    with factory() as db:
        state = integrations.state(db)
        state['targets'] = {'healthy': good, 'legacy': bad}
        text = json.dumps(state, ensure_ascii=True)
        db.add(AppConfig(key=integrations.KEY, value=text))
        db.commit()
    with TestClient(app, base_url='http://stella.test', raise_server_exceptions=False) as client:
        response = client.get('/integration-targets')
    with factory() as db:
        assert db.get(AppConfig, integrations.KEY).value == text
    assert response.status_code == 200
    healthy, projected = response.json()
    assert healthy == public_target(good) and 'projection' not in healthy
    assert projected['projection'] == dict(state='incomplete', invalid_fields=[field])
    assert public_target(projected) == projected
    PublicTarget.model_validate(projected)
    assert 'SYNTHETIC_UNICODE_SECRET' not in response.text


CHECK_CASES = [
    ('normalized_url', 'https://example.test/\ud800'), ('name_suggestion', '\udfff'),
    ('embedding.reason_code', '\ud800'), ('embedding.reason', '\udfff'),
    ('injection.reason', '\ud800'), ('help.title', '\udfff'),
    ('help.location', '\ud800'), ('help.instructions', ['中文🌟', '\udfff']),
    ('help.external_url', 'https://example.test/\ud800'), ('issues', ['\udfff']),
]


@pytest.mark.parametrize('field,value', CHECK_CASES)
def test_unicode_historical_receipt_http_replay_uses_same_projection_without_write(api_env, upstream, field, value):
    from app.models.config import AppConfig
    from app.public_website import PublicWebsiteResult, public_website_result
    from app.services import integrations

    client, factory, app, _ = api_env
    root, _, seen = upstream
    owner_js = 'window.secret = "<script>中文🌟𠀀</script>";'
    draft = dict(address=root + '/site?q=%2f#anchor', name='中文🌟𠀀', icon='heart',
                 idempotency_key='unicode-replay', custom=dict(enabled=True, css='body{color:red}', js=owner_js))
    first = client.post('/website-settings', json=draft)
    assert first.status_code == 201, first.text
    fresh = first.json()
    assert fresh['name'] == draft['name'] and fresh['injection']['active']['js'] == owner_js
    assert fresh['browser_url'] == draft['address']
    assert client.post('/website-settings', json=draft).json() == fresh
    with factory() as db:
        state = integrations.state(db)
        raw_module = state['modules'][fresh['id']]
        raw_module['icon'] = '\ud800'
        raw_module['private'] = {'secret': 'SYNTHETIC_UNICODE_SECRET'}
        receipt = next(iter(state['website_save_keys'].values()))
        receipt['module_digest'] = hashlib.sha256(json.dumps(raw_module, sort_keys=True).encode()).hexdigest()
        receipt['check']['help'] = dict(title='帮助🌟', location='设置', instructions=['中文🌟'], external_url=None)
        change(receipt['check'], field, value)
        receipt['check']['private'] = {'secret': 'SYNTHETIC_UNICODE_SECRET', '\udfff': '\ud800'}
        expected = public_website_result(raw_module, receipt['check'])
        text = json.dumps(state, ensure_ascii=True)
        db.get(AppConfig, integrations.KEY).value = text
        db.commit()
    requests = len(seen)
    with TestClient(app, base_url='http://stella.test', raise_server_exceptions=False) as probe:
        replay = probe.post('/website-settings', json=draft)
        again = probe.post('/website-settings', json=draft)
    with factory() as db:
        assert db.get(AppConfig, integrations.KEY).value == text
    assert replay.status_code == again.status_code == 201
    assert replay.json() == again.json() == expected
    assert len(seen) == requests
    PublicWebsiteResult.model_validate(expected)
    assert expected['check']['can_save'] is False
    assert field in expected['check']['projection']['invalid_fields']
    assert public_website_result(expected, expected['check']) == expected
    assert 'SYNTHETIC_UNICODE_SECRET' not in replay.text


@pytest.mark.parametrize('url', [
    'https://例子.测试/中文/🌟?q=%2f&text=𠀀#片段',
    'HTTPS://Example.Test:443/a%2Fb?q=%2F#A', 'http://[::1]:8080/a?q=x#z',
    'https://example.test/a/../b', 'https://example.test//a',
    'https://example.test/%ED%A0%80',  # valid ASCII URI spelling, not a Python surrogate
])
def test_unicode_valid_uri_is_not_reencoded_or_normalized(url):
    from app.public_website import public_module

    raw = module() | dict(browser_url=url, origin=url, initial_path='/中文🌟?q=%2f#𠀀')
    raw['injection'] = {'active': version() | dict(source_origin=url)}
    projected = public_module(raw)
    assert 'projection' not in projected
    assert projected['browser_url'] == projected['origin'] == url
    assert projected['initial_path'] == raw['initial_path']
    assert projected['injection']['active']['source_origin'] == url
    assert public_module(json.loads(bytes(JSONResponse(projected).body))) == projected


@pytest.mark.parametrize('url', [
    'javascript:alert(1)', 'data:text/html,hello', '//evil.test/path', 'https:///no-host',
    'https://user:password@example.test', 'https://example.test:bad/path', 'https://[broken',
    ' https://example.test', 'https://example.test\\@evil.test', 'https://example.test/\nnext',
    'https://example.test/\ud800', 'https://example.test\uff0fevil.test/',
])
def test_unicode_bad_uri_has_empty_fallback_not_an_invented_origin(url):
    from app.public_website import public_module

    raw = module() | dict(browser_url=url, origin=url)
    projected = public_module(raw)
    assert projected['browser_url'] == projected['origin'] == ''
    assert projected['projection']['invalid_fields'] == ['browser_url', 'origin']
    assert public_module(projected) == projected
    assert raw['browser_url'] == url


@pytest.mark.parametrize('path', ['//evil.test', '/\\evil.test', 'relative', '/\x00bad', '/\udfff'])
def test_unicode_invalid_local_path_has_local_fallback(path):
    from app.public_website import public_module

    result = public_module(module() | dict(initial_path=path))
    assert result['initial_path'] == '/'
    assert result['projection']['invalid_fields'] == ['initial_path']
    assert public_module(result) == result


def test_unicode_all_declared_optional_text_is_checked_but_unknown_extensions_are_not():
    from app.public_website import public_module, public_check, public_navigation

    raw = module() | dict(route='/\udfff', capabilities=dict(managed_settings='\ud800'))
    raw['request_policy'] = dict(management_prefixes=['/admin', '/\udfff'])
    raw['private'] = {'\ud800': '\udfff'}
    result = public_module(raw)
    assert result['projection']['invalid_fields'] == ['capabilities.managed_settings', 'request_policy.management_prefixes', 'route']
    assert public_module(result) == result
    good = module() | dict(icon='自定义🌟𠀀', private={'\ud800': '\udfff'})
    before = copy.deepcopy(good)
    assert 'projection' not in public_module(good)
    nav = public_navigation(dict(modules={'legacy-id': good}, navigation=[dict(id='legacy-id', title='中文🌟𠀀', icon='旧图标🌟')]), [])
    assert nav['entries'][0]['title'] == '中文🌟𠀀'
    assert nav['entries'][0]['icon'] == '旧图标🌟'
    assert 'projection' not in nav['entries'][0]
    assert good == before
    JSONResponse(nav)
    receipt = public_check(checked() | dict(issues=['正常中文🌟𠀀']))
    assert receipt['issues'] == ['正常中文🌟𠀀'] and 'projection' not in receipt
