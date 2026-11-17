"""Schema/fixture parity and arbitrary legacy JSON shape regression tests."""
import copy
import json
from pathlib import Path

import pytest

from app import public_website as public
from tests_public_website.fixtures import contract_fixture
from tests_public_website.test_projection import module, version, checked

ROOT = Path(__file__).resolve().parents[1]
MODELS = [public.PublicModule, public.PublicTarget, public.PublicNavigation,
          public.PublicInjectionVersions, public.PublicWebsiteResult]


def test_exported_schema_and_frontend_fixture_match_real_projection():
    schemas = json.loads((ROOT / 'docs/projection-websites-models.json').read_text())
    assert schemas == {model.__name__: model.model_json_schema() for model in MODELS}
    fixture = json.loads((ROOT / 'frontend/tests/fixtures/publicWebsiteProjection.json').read_text())
    assert fixture == contract_fixture()
    public.PublicWebsiteResult.model_validate(fixture['saved'])
    public.PublicModule.model_validate(fixture['malformed'])
    public.PublicNavigation.model_validate(fixture['navigation'])
    for slot in ('draft', 'active', 'previous'):
        assert fixture['saved']['injection'][slot]['source_origin'] == 'https://site.test'


def test_source_mapping_delta_matches_real_routes():
    import ast
    delta = json.loads((ROOT / 'docs/projection-websites-source-mapping-delta.json').read_text())
    # A handoff artifact, not a requirement that the parent keep blockers open.
    actual = {(row['method'], row['path']) for row in delta['operations']}
    assert len(actual) == len(delta['operations']) == delta['resolved_blocker_candidates']
    for row in delta['operations']:
        assert all((ROOT / path).is_file() for path in row['source_paths'])
        router_name, function = row['router_symbol'].split('.')
        tree = ast.parse((ROOT / 'app/routers' / (router_name + '.py')).read_text())
        node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function)
        prefix = '/website-settings' if router_name == 'website_settings' else ''
        assert any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and
                   d.func.attr.upper() == row['method'] and prefix + ast.literal_eval(d.args[0]) == row['path']
                   for d in node.decorator_list)


@pytest.mark.parametrize('value', [None, [], {'private': 'synthetic-extra'}, True, 1, 'false'])
def test_every_declared_module_field_is_typed_even_when_legacy_value_is_wrong(value):
    for field in public.PublicModule.model_fields:
        raw = module() | {field: value}
        before = copy.deepcopy(raw)
        output = public.public_module(raw)
        public.PublicModule.model_validate(output)
        assert raw == before
        assert 'synthetic-extra' not in json.dumps(output)


@pytest.mark.parametrize('value', [None, [], {'private': 'synthetic-extra'}, True, 1, 'false'])
def test_nested_known_fields_do_not_smuggle_untyped_json(value):
    for name, original, model in [('connection', {}, public.PublicConnection),
                                  ('request_policy', {}, public.PublicRequestPolicy)]:
        for field in model.model_fields:
            raw = module() | {name: original | {field: value}}
            result = public.public_module(raw)
            public.PublicModule.model_validate(result)
            assert 'synthetic-extra' not in json.dumps(result)
    for slot in ('draft', 'active', 'previous'):
        for field in public.PublicInjectionVersion.model_fields:
            raw = {slot: version() | {field: value}}
            output = public.public_versions(raw)
            public.PublicInjectionVersions.model_validate(output)
            assert 'synthetic-extra' not in json.dumps(output)
    for field in public.PublicWebsiteCheck.model_fields:
        result = public.public_check(checked() | {field: value})
        public.PublicWebsiteCheck.model_validate(result)
        assert 'synthetic-extra' not in json.dumps(result)
