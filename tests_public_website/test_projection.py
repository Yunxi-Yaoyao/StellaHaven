"""Public read boundaries: synthetic records only, no config/database imports.

Run from scratch, PYTHONPATH=checkout, pytest --noconftest. AST loads the
actual service functions; only their persistence dependencies are substituted.
"""
import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def functions(path, names, **namespace):
    tree = ast.parse((ROOT / path).read_text())
    body: list[ast.stmt] = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert len(body) == len(names)
    for node in body:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        node.decorator_list = []
    exec(compile(ast.Module(body=body, type_ignores=[]), str(ROOT / path), 'exec'), namespace)
    return SimpleNamespace(**namespace)


def service():
    return functions('app/services/integrations.py', ['present', 'display_module'], copy=copy, ICONS={'globe', 'home'})


def module() -> dict[str, Any]:
    return dict(id='legacy-id', name='Owner website', icon='old-custom-icon',
                mode='isolated_proxy', adapter='generic', browser_url='https://site.test/a',
                target_id='target', initial_path='/a', enabled=True,
                origin='https://app-legacy-id.test', injection=dict(draft=None, active=None, previous=None))


def version() -> dict[str, Any]:
    return dict(enabled=True, css='body{color:red}', js='window.ownerCode = "secret is legitimate code";',
                timing='dom_ready', csp_policy='controlled', version='old-v1', source_origin='https://site.test')


def test_module_actual_output_projects_extensions_without_losing_owner_code():
    raw = module()
    raw.update(unknown={'secret': 'synthetic-extension-secret'}, migration={'private': 'synthetic-migration'})
    raw['connection'] = dict(transport='proxy', auth_mode='header', header_name='Authorization',
                             injection_delivery='proxy', has_token=True, token='synthetic-token',
                             clear_token=False, headers={'authorization': 'synthetic-header'}, other='synthetic-connection')
    raw['request_policy'] = dict(management_prefixes=['/admin'], read_post_paths=['/api/list'],
                                 protect_other_writes=True, password='synthetic-policy')
    raw['injection'] = {slot: version() | {'private': 'synthetic-version'} for slot in ('draft', 'active', 'previous')}
    before = copy.deepcopy(raw)
    actual = service().present(raw)
    assert 'synthetic-' not in json.dumps(actual)
    assert actual['icon'] == 'old-custom-icon'  # renderer owns unknown-icon fallback
    assert actual['connection']['has_token'] is True
    assert actual['request_policy']['protect_other_writes'] is True
    for slot in ('draft', 'active', 'previous'):
        assert actual['injection'][slot] == version()
    assert raw == before


def test_target_actual_output_drops_header_secrets_and_validates_known_fields():
    target = dict(id='target', name='Target', upstream_url='https://site.test', allowed_ips=['127.0.0.1'],
                  controlled=True, headers={'authorization': 'synthetic-secret', 'synthetic-private-header': 'private'},
                  password='synthetic-top-secret')
    masked = functions('app/services/integrations_proxy.py', ['masked_target']).masked_target
    before = copy.deepcopy(target)
    actual = masked(target)
    assert 'synthetic-' not in json.dumps(actual)
    assert actual['credential_headers'] == ['authorization']
    assert actual['controlled'] is True
    assert target == before
    actual = masked(target | {'controlled': 'false', 'allowed_ips': {'secret': 'synthetic-bad'}})
    assert actual['controlled'] is False
    assert actual['allowed_ips'] == []
    assert actual['projection']['state'] == 'incomplete'


def test_navigation_actual_output_allows_display_only_and_isolates_bad_entries():
    builtins = [dict(id='home', title='Home', icon='home', route='/'),
                dict(id='settings', title='Settings', icon='settings', route='/settings')]
    config = dict(modules={'legacy-id': module()}, navigation=[
        {'id': 'home', 'title': 'My Home', 'icon': 'globe', 'visible': False,
         'builtin': False, 'route': 'https://evil.test', 'password': 'synthetic-secret'},
        {'id': 'legacy-id', 'title': ['synthetic-bad'], 'visible': 'false', 'icon': 'unknown-old'},
        {'id': [], 'route': 'synthetic-bad'}, None],
        legacy_routes={'drive': 'legacy-id', 'gallery': [], 'password': 'legacy-id'})
    before = copy.deepcopy(config)
    navigation = functions('app/services/integrations.py', ['navigation'], state=lambda db: config, BUILTINS=builtins).navigation
    actual = navigation(None)
    assert 'synthetic-' not in json.dumps(actual)
    home, website, settings = actual['entries']
    assert (home['title'], home['visible'], home['builtin'], home['route']) == ('My Home', False, True, '/')
    assert home['icon'] == 'globe'
    assert website['title'] == 'Owner website' and type(website['visible']) is bool
    assert website['icon'] == 'unknown-old'  # historical value is not a new write; renderer falls back
    assert website['projection']['state'] == 'incomplete'
    assert settings['route'] == '/settings'
    assert actual['legacy_routes'] == {'drive': 'legacy-id'}
    assert config == before


def test_unknown_navigation_icon_is_retained_but_does_not_replace_editor_value():
    raw = module()
    config = dict(modules={'legacy-id': raw}, navigation=[{'id': 'legacy-id', 'icon': 'retired-custom-icon'}])
    actual = service().present(raw, config)
    assert actual['icon'] == raw['icon']
    assert actual['projection']['invalid_fields'] == ['navigation.icon']
    assert config['navigation'][0]['icon'] == 'retired-custom-icon'


def test_invalid_display_override_uses_original_and_marks_incomplete():
    raw = module()
    config = dict(navigation=[{'id': 'legacy-id', 'title': {'secret': 'synthetic-title'}, 'icon': []}])
    actual = service().present(raw, config)
    assert actual['name'] == raw['name'] and actual['icon'] == raw['icon']
    assert actual['projection']['invalid_fields'] == ['navigation.icon', 'navigation.title']
    assert 'synthetic-title' not in json.dumps(actual)


def checked() -> dict[str, Any]:
    return dict(normalized_url='https://site.test/a', name_suggestion='Owner website',
                access=dict(status='reachable', http_status=200),
                embedding=dict(status='allowed', reason_code='no_observed_restriction', reason='Browser unverified'),
                injection=dict(status='supported', reason='Owner code supported'), help=None,
                can_save=True, recommended_behavior='embedded', issues=[])


def test_injection_actual_apply_rollback_project_history_without_mutating_extensions():
    from contextlib import contextmanager
    from uuid import uuid4
    from fastapi import HTTPException
    raw = module()
    raw['injection'] = {slot: version() | {'private': 'synthetic-history'} for slot in ('draft', 'active', 'previous')}
    state = dict(modules={'legacy-id': raw}, targets={})

    @contextmanager
    def edit(db):
        yield state

    methods = functions('app/services/integrations_injection.py', ['apply', 'rollback'],
                        store=SimpleNamespace(edit=edit), uuid4=uuid4, HTTPException=HTTPException,
                        record_change=lambda *a, **k: None, errors=lambda *a: [])
    for action in (methods.apply, methods.rollback):
        output = action(None, 'legacy-id', 'owner')
        assert 'synthetic-history' not in json.dumps(output)
        for slot in ('draft', 'active', 'previous'):
            assert output[slot]['css'] == version()['css']
            assert output[slot]['source_origin'] == version()['source_origin']
            assert raw['injection'][slot]['private'] == 'synthetic-history'


def test_replay_actual_receipt_projects_nested_check_and_preserves_digest_payload():
    import hashlib
    import time
    from fastapi import HTTPException
    raw = module() | {'template_id': 'user_' + 'a' * 32}
    receipt = checked() | {'secret': 'synthetic-receipt'}
    receipt['access']['token'] = 'synthetic-access'
    receipt['help'] = dict(title='Help', location=None, instructions=['Install loader'], external_url=None,
                           password='synthetic-help')
    config = dict(modules={'legacy-id': raw}, website_save_keys={'slot': dict(id='legacy-id', expires=time.time() + 100,
                  digest='digest', module_digest=hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(), check=receipt)})
    before = copy.deepcopy(config)
    retry = functions('app/services/website_settings.py', ['retry_result'], time=time, hashlib=hashlib, json=json,
                      copy=copy, store=service(), HTTPException=HTTPException).retry_result
    actual = retry(config, 'slot', 'digest')
    assert 'synthetic-' not in json.dumps(actual)
    assert actual['template_id'] == raw['template_id']
    assert actual['check']['help']['instructions'] == ['Install loader']
    assert actual['check']['access']['http_status'] == 200
    assert config == before
    config['website_save_keys']['slot']['check']['access']['http_status'] = {'secret': 'synthetic-status'}
    actual = retry(config, 'slot', 'digest')
    assert actual['check']['projection']['state'] == 'incomplete'
    assert actual['check']['access']['http_status'] is None
    assert actual['check']['can_save'] is False
    assert 'synthetic-' not in json.dumps(actual)


@pytest.mark.parametrize('active', [{'version': ['synthetic-bad']}, {'enabled': True}, 'synthetic-bad'])
def test_check_route_handles_malformed_legacy_version_before_any_probe(active):
    import asyncio
    raw = module() | {'mode': 'iframe'}
    raw['injection']['active'] = active
    check = functions('app/routers/integrations.py', ['check'], service=SimpleNamespace(get_module=lambda *a: raw),
                      Depends=lambda x: None, get_db=lambda: None).check
    actual = asyncio.run(check('legacy-id', None))
    assert actual['configuration_valid'] is False
    assert actual['injection_version'] is None
    assert actual['ready'] is False
    assert 'synthetic-' not in json.dumps(actual)


def test_missing_version_code_and_nested_receipt_fields_are_explicitly_incomplete():
    from app.public_website import public_versions, public_check
    versions = public_versions({'active': {'enabled': True, 'version': 'v1'}})
    assert versions['projection']['state'] == 'incomplete'
    assert versions['active']['enabled'] is False
    receipt = public_check(checked() | {'access': {}})
    assert receipt['projection']['state'] == 'incomplete'
    assert receipt['can_save'] is False


@pytest.mark.parametrize('field,value', [('name', {'secret': 'synthetic-bad-name'}), ('enabled', 'false'),
    ('keep_alive', []), ('connection', []), ('request_policy', {'protect_other_writes': 'false'}),
    ('injection', {'active': {'version': ['synthetic-bad-version']}})])
def test_malformed_module_is_typed_incomplete_not_a_new_normal_config(field, value):
    raw = module() | {field: value}
    before = copy.deepcopy(raw)
    actual = service().present(raw)
    assert actual['projection']['state'] == 'incomplete'
    assert actual['projection']['invalid_fields']
    assert 'synthetic-bad-' not in json.dumps(actual)
    assert isinstance(actual['name'], str)
    assert type(actual['enabled']) is bool
    assert type(actual['keep_alive']) is bool
    assert raw == before
