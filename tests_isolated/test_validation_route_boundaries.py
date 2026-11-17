"""In-process HTTP/AST acceptance only; no production bootstrap or services.

Use the scratch allowlisted runner with --noconftest and plugin autoload disabled.
Every secret here is synthetic. AST extraction preserves real route/model code.
"""
import ast
import importlib.util
from pathlib import Path
from typing import Annotated, Literal
import types

import pytest
from fastapi import APIRouter, Body, Depends, FastAPI, Form, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[1]
MARKER = 'SYNTHETIC-SECRET-BOUNDARY-7c1a'
SPEC = importlib.util.spec_from_file_location('boundary_validation', ROOT/'app/validation_errors.py')
assert SPEC is not None and SPEC.loader is not None
HANDLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HANDLER)


def extract(path, names, namespace):
    tree = ast.parse((ROOT/path).read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in names]
    assert len(nodes) == len(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT/path), 'exec'), namespace)
    return namespace


def app_for(model, *, route_class=APIRoute, path='/probe', dependencies=(), body_info=None):
    app = FastAPI(debug=False)
    app.add_exception_handler(RequestValidationError, HANDLER.validation_exception_handler)
    router = APIRouter(route_class=route_class, dependencies=list(dependencies))
    calls = []

    def endpoint(body):
        calls.append(body)
        return {'ok': True}

    endpoint.__annotations__ = {'body': Annotated[model, body_info] if body_info is not None else model}
    router.post(path)(endpoint)
    app.include_router(router)
    return app, calls


def errors(response):
    assert response.status_code == 422, response.text
    assert MARKER not in response.text
    detail = response.json()['detail']
    assert all(set(item) == {'loc', 'type', 'msg'} for item in detail)
    return [(item['loc'], item['type']) for item in detail]


class Leaf(BaseModel):
    token: int = Field(alias='apiToken')


class Tree(BaseModel):
    entries: dict[str, list[Leaf]] = Field(default_factory=dict)
    child: 'Tree | None' = None
    apiToken: int = 0


Tree.model_rebuild()


@pytest.mark.parametrize('key', ['apiToken', 'body', 'entries', 'child', MARKER])
def test_recursive_mapping_slot_redacted_but_value_alias_and_index_survive(key):
    app, calls = app_for(Tree)
    with TestClient(app) as client:
        response = client.post('/probe', json={'child': {'entries': {key: [{'apiToken': MARKER}]}}})
    assert errors(response) == [(['body', 'child', 'entries', '[redacted]', 0, 'apiToken'], 'int_parsing')]
    assert calls == []


class AliasMap(BaseModel):
    entries: dict[str, Leaf] = Field(validation_alias=AliasChoices('entryAlias', AliasPath('envelope', 'credentials', 1)))
    apiToken: int = 0


@pytest.mark.parametrize('payload, prefix', [
    ({'entryAlias': {'apiToken': {'apiToken': MARKER}}}, ['entryAlias']),
    ({'envelope': {'credentials': [None, {'credentials': {'apiToken': MARKER}}]}}, ['envelope', 'credentials', 1]),
])
def test_alias_choices_and_path_do_not_authorize_a_dictionary_slot(payload, prefix):
    app, _ = app_for(AliasMap)
    with TestClient(app) as client:
        response = client.post('/probe', json=payload)
    assert errors(response) == [(['body', *prefix, '[redacted]', 'apiToken'], 'int_parsing')]


class Cat(BaseModel):
    kind: Literal['cat']
    entries: dict[str, Leaf]


class Dog(BaseModel):
    kind: Literal['dog']
    token: int


class Unions(BaseModel):
    ordinary: Cat | Dog
    tagged: list[Annotated[Cat | Dog, Field(discriminator='kind')]]


def test_union_branch_does_not_turn_dynamic_keys_into_declared_fields():
    app, _ = app_for(Unions)
    with TestClient(app) as client:
        response = client.post('/probe', json={
            'ordinary': {'kind': 'cat', 'entries': {'token': {'apiToken': MARKER}}},
            'tagged': [{'kind': 'cat', 'entries': {'kind': {'apiToken': MARKER}}}],
        })
    detail = errors(response)
    assert (['body', 'ordinary', '[redacted]', 'entries', '[redacted]', 'apiToken'], 'int_parsing') in detail
    assert (['body', 'tagged', 0, '[redacted]', 'entries', '[redacted]', 'apiToken'], 'int_parsing') in detail
    assert (['body', 'ordinary', '[redacted]', 'kind'], 'literal_error') in detail
    assert (['body', 'ordinary', '[redacted]', 'token'], 'missing') in detail


def test_integer_dictionary_key_is_not_an_array_index():
    class Numeric(BaseModel):
        entries: dict[int, Leaf]
        items: list[Leaf]

    app = FastAPI()
    app.add_exception_handler(RequestValidationError, HANDLER.validation_exception_handler)
    # JSON keys are strings. Produce genuine Pydantic errors on Python int keys
    # through an HTTP endpoint with the same declared schema. This explicit
    # adaptation supplies only the source prefix, never rewrites a key/index.
    @app.post('/python-input')
    def python_input(body: Numeric):
        try:
            Numeric.model_validate({'entries': {731904: {'apiToken': MARKER}}, 'items': [{'apiToken': MARKER}]})
        except ValidationError as exc:
            raise RequestValidationError([{**e, 'loc': ('body', *e['loc'])} for e in exc.errors()]) from None

    with TestClient(app) as client:
        response = client.post('/python-input', json={'entries': {}, 'items': []})
    assert errors(response) == [
        (['body', 'entries', '[redacted]', 'apiToken'], 'int_parsing'),
        (['body', 'items', 0, 'apiToken'], 'int_parsing'),
    ]


@pytest.fixture(params=['provider', 'website'])
def private_route(request):
    provider = request.param == 'provider'
    path = 'app/routers/auth_provider.py' if provider else 'app/routers/website_settings.py'
    name = 'PrivateValidationRoute' if provider else 'PrivateInputRoute'
    ns = extract(path, {name}, dict(
        APIRoute=APIRoute, RequestValidationError=RequestValidationError,
        HTTPException=HTTPException, JSONResponse=JSONResponse,
        validation_error_response=HANDLER.validation_error_response,
    ))
    return ns[name], provider


def real_model(name):
    ns = dict(BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field, StrictBool=StrictBool,
              Literal=Literal, field_validator=field_validator, model_validator=model_validator)
    if name in {'ClientCreate', 'ClientPatch'}:
        ns['oidc'] = types.SimpleNamespace(SUPPORTED_SCOPES=['openid'])
        return extract('app/routers/auth_provider.py', {name}, ns)[name]
    if name == 'TemplateInput':
        return extract('app/services/saved_website_templates.py', {name}, ns)[name]
    extract('app/services/website_connection.py', {'ConnectionInput', 'RequestPolicy'}, ns)
    # WebsiteInput now inherits the real mapping schema; retain its validators.
    extract('app/services/website_mapping.py', {'WebsiteMappingInput'}, ns)
    if name == 'CheckInput':
        return extract('app/services/website_check.py', {name}, ns)[name]
    # icon validation is not invoked by these default-icon requests; all actual
    # ConnectionInput, RequestPolicy and CustomInput validators execute unchanged.
    return extract('app/services/website_settings.py', {'CustomInput', 'WebsiteInput'}, ns)[name]


@pytest.mark.parametrize('name,path,valid,invalid,expected', [
    ('ClientCreate', '/auth/provider/clients',
     {'client_id': 'fixture', 'name': 'fixture', 'redirect_uris': ['https://example.test/cb']},
     {'name': 7}, (['body', 'name'], 'string_type')),
    ('ClientPatch', '/auth/provider/clients/fixture', {}, {'enabled': MARKER},
     (['body', 'enabled'], 'bool_type')),
    ('TemplateInput', '/website-templates', {'name': 'fixture', 'draft': {}}, {'name': 7},
     (['body', 'name'], 'string_type')),
    ('WebsiteInput', '/website-settings', {'address': 'https://example.test'},
     {'connection': {'token': MARKER + '\n'}}, (['body', 'connection', 'token'], 'value_error')),
    ('CheckInput', '/website-settings/check', {'address': 'https://example.test'},
     {'connection': {'token': MARKER + '\n'}}, (['body', 'connection', 'token'], 'value_error')),
])
def test_mounted_actual_models_succeed_and_redact_extra_and_typed_errors(private_route, name, path, valid, invalid, expected):
    cls, provider = private_route
    app, calls = app_for(real_model(name), route_class=cls, path=path)
    with TestClient(app) as client:
        good = client.post(path, json=valid)
        bad = client.post(path, json={**valid, **invalid, MARKER: MARKER})
    assert good.status_code == 200
    assert len(calls) == 1
    assert errors(bad) == [expected, (['body', '[redacted]'], 'extra_forbidden')]
    if provider:
        for response in (good, bad):
            assert response.headers['cache-control'] == 'no-store'
            assert response.headers['pragma'] == 'no-cache'


def test_mounted_wrapper_keeps_dependency_schema_and_recursive_body_locations(private_route):
    cls, provider = private_route

    def auth_dependency(api_token: Annotated[int, Header(alias='X-Api-Token')],
                        revision: Annotated[int, Query(alias='rev')]):
        return api_token

    app, calls = app_for(Tree, route_class=cls, dependencies=[Depends(auth_dependency)])
    with TestClient(app) as client:
        response = client.post('/probe', json={'entries': {'rev': [{'apiToken': MARKER}]}},
                               headers={'X-Api-Token': MARKER}, params={'rev': MARKER})
    assert { (tuple(loc), kind) for loc, kind in errors(response)} == {
        (('header', 'X-Api-Token'), 'int_parsing'), (('query', 'rev'), 'int_parsing'),
        (('body', 'entries', '[redacted]', 0, 'apiToken'), 'int_parsing'),
    }
    assert calls == []


@pytest.mark.parametrize('status', [401, 403, 409, 422])
def test_mounted_wrapper_does_not_swallow_auth_or_business_http_exception(private_route, status):
    cls, _ = private_route
    detail = {'code': 'synthetic-business', 'message': MARKER}

    def gate():
        raise HTTPException(status, detail, headers={'X-Sentinel': 'unchanged'})

    app, calls = app_for(Tree, route_class=cls, dependencies=[Depends(gate)])
    with TestClient(app) as client:
        response = client.post('/probe', json={})
    assert response.status_code == status
    assert response.json() == {'detail': detail}
    assert response.headers['x-sentinel'] == 'unchanged'
    assert calls == []


def test_mounted_wrapper_does_not_reclassify_runtime_failure(private_route):
    cls, _ = private_route

    def gate():
        raise RuntimeError(MARKER)

    app, _ = app_for(Tree, route_class=cls, dependencies=[Depends(gate)])
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post('/probe', json={})
    assert response.status_code == 500
    assert response.text == 'Internal Server Error'


def test_mounted_wrapper_handles_json_parse_errors(private_route):
    cls, provider = private_route
    app, _ = app_for(Tree, route_class=cls)
    with TestClient(app) as client:
        response = client.post('/probe', content='{"child":' + MARKER,
                               headers={'content-type': 'application/json'})
    detail = errors(response)
    assert detail[0][1] == 'json_invalid'
    assert detail[0][0][0] == 'body' and type(detail[0][0][1]) is int
    if provider:
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['pragma'] == 'no-cache'


@pytest.mark.parametrize('size,status', [(1048575, 200), (1048576, 200), (1048577, 413)])
def test_website_template_stream_body_limit_is_unchanged(size, status):
    import json
    ns = extract('app/routers/website_settings.py', {'PrivateInputRoute'}, dict(
        APIRoute=APIRoute, RequestValidationError=RequestValidationError,
        HTTPException=HTTPException, validation_error_response=HANDLER.validation_error_response))
    app, calls = app_for(real_model('TemplateInput'), route_class=ns['PrivateInputRoute'], path='/website-templates')
    skeleton = json.dumps({'name': 'fixture', 'draft': {'padding': ''}})
    body = skeleton.replace('"padding": ""', '"padding": "' + 'x' * (size - len(skeleton)) + '"').encode()
    assert len(body) == size
    # Streaming chunks exercise the wrapper's actual request.stream limit.
    with TestClient(app) as client:
        response = client.post('/website-templates', content=iter([body[:524288], body[524288:]]),
                               headers={'content-type': 'application/json'})
    assert response.status_code == status
    assert len(calls) == (1 if status == 200 else 0)
    if status == 413:
        assert response.json() == {'detail': '模板内容过大'}


@pytest.mark.parametrize('source', ['query', 'header', 'form'])
def test_flattened_parameter_models_keep_alias_fields(source):
    class Parameters(BaseModel):
        api_token: int = Field(alias='X-Token')

    app = FastAPI()
    app.add_exception_handler(RequestValidationError, HANDLER.validation_exception_handler)

    def endpoint(params):
        return {'ok': True}

    info = {'query': Query(), 'header': Header(), 'form': Form()}[source]
    endpoint.__annotations__ = {'params': Annotated[Parameters, info]}
    app.post('/parameters')(endpoint)
    kwargs = {'query': {'params': {'X-Token': MARKER}}, 'header': {'headers': {'X-Token': MARKER}},
              'form': {'data': {'X-Token': MARKER}}}[source]
    with TestClient(app) as client:
        response = client.post('/parameters', **kwargs)
    assert errors(response) == [([('body' if source == 'form' else source), 'X-Token'], 'int_parsing')]


def test_embedded_and_multiple_bodies_keep_position_specific_paths():
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, HANDLER.validation_exception_handler)

    @app.post('/embedded')
    def embedded(payload: Annotated[Tree, Body(embed=True, alias='envelope')]):
        return {'ok': True}

    @app.post('/multiple')
    def multiple(payload: Tree, other: Leaf):
        return {'ok': True}

    with TestClient(app) as client:
        single = client.post('/embedded', json={'envelope': {'entries': {'apiToken': [{'apiToken': MARKER}]}}})
        multi = client.post('/multiple', json={'payload': {'entries': {'other': [{'apiToken': MARKER}]}}, 'other': {'apiToken': MARKER}})
    assert errors(single) == [(['body', 'envelope', 'entries', '[redacted]', 0, 'apiToken'], 'int_parsing')]
    assert errors(multi) == [
        (['body', 'payload', 'entries', '[redacted]', 0, 'apiToken'], 'int_parsing'),
        (['body', 'other', 'apiToken'], 'int_parsing'),
    ]


def test_deep_recursive_field_locations_do_not_overflow_redaction():
    payload = {'entries': {'child': [{'apiToken': MARKER}]}}
    for _ in range(180):
        payload = {'child': payload}
    app, _ = app_for(Tree)
    with TestClient(app) as client:
        response = client.post('/probe', json=payload)
    assert errors(response) == [(['body', *(['child'] * 180), 'entries', '[redacted]', 0, 'apiToken'], 'int_parsing')]


def test_mixed_dict_and_model_union_uses_branch_not_field_name_allowlist():
    class Mixed(BaseModel):
        item: dict[str, Leaf] | Leaf

    app, _ = app_for(Mixed)
    with TestClient(app) as client:
        response = client.post('/probe', json={'item': {'apiToken': {'apiToken': MARKER}}})
    assert errors(response) == [
        (['body', 'item', '[redacted]', '[redacted]', 'apiToken'], 'int_parsing'),
        (['body', 'item', '[redacted]', 'apiToken'], 'int_type'),
    ]


def test_custom_json_invalid_type_cannot_turn_integer_mapping_key_into_parser_offset():
    from pydantic import AfterValidator, RootModel
    from pydantic_core import PydanticCustomError

    def reject(value):
        raise PydanticCustomError('json_invalid', MARKER)

    Model = RootModel[dict[int, Annotated[str, AfterValidator(reject)]]]
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, HANDLER.validation_exception_handler)

    @app.post('/python-map')
    def endpoint(body: Model):
        try:
            Model.model_validate({731904: MARKER})
        except ValidationError as exc:
            raise RequestValidationError([{**e, 'loc': ('body', *e['loc'])} for e in exc.errors()]) from None

    with TestClient(app) as client:
        response = client.post('/python-map', json={})
    assert errors(response) == [(['body', '[redacted]'], 'json_invalid')]


def test_dictionary_value_alias_named_key_keeps_legitimate_location():
    class Value(BaseModel):
        token: int = Field(alias='[key]')

    class Model(BaseModel):
        entries: dict[str, Value]

    app, _ = app_for(Model)
    with TestClient(app) as client:
        response = client.post('/probe', json={'entries': {'[key]': {'[key]': MARKER}}})
    assert errors(response) == [(['body', 'entries', '[redacted]', '[key]'], 'int_parsing')]


@pytest.mark.parametrize('path', ['app/routers/auth_provider.py', 'app/routers/website_settings.py'])
def test_production_wrapper_imports_the_shared_builder(path):
    tree = ast.parse((ROOT/path).read_text())
    assert any(isinstance(n, ast.ImportFrom) and n.module == 'app.validation_errors'
               and any(a.name == 'validation_error_response' for a in n.names) for n in tree.body)
