"""Bounded approved auth source/input gates; no router or live state imports."""

import hashlib
import json

import pytest

from test_api_openapi_contract import ROOT, install, source_shaped_app, static_inventory
from test_api_response_contract import response_module
from test_api_response_v11_integration import approved_reviews, check_metadata


AUTH_FILE = 'app/routers/auth.py'
AUTH_SHA256 = '8f9a216c13e17ebb9c13cec539c546ad05d69bb4443089da57adba8e0e3766b8'
V6_AUTH_SHA256 = 'b31ea8d1c47e1fe0ecd85c234841a34ee11b14aad12591a3d72d5c1ea60f0ffb'
ACTIVE_AUTH_SHA256 = '895baf8953665c853711653db4a19910f199409eaed38f487556da34246bda17'
PROFILE = 'app.routers.auth.ProfileIn'
ACTIVE_PROFILE = PROFILE + '@v12-final'
CURRENT_PROFILE = ACTIVE_PROFILE + '@v17-nav-files'
CURRENT_AUTH_SHA256 = '9c65382161fe6bbfbc9821a5d774041e37ab99e801220f0c5db2a59eef90b2d6'
ENDPOINT = 'app.routers.auth.update_profile'
HISTORICAL_HASHES = {
    'app/api_response_inventory.json': 'ffbacf41ec5b07935a10194e6e6bc3a02ec1233185dd831b97ae1656e0a65a3e',
    'app/api_response_integrated.json': '8d0bcc77e6f158b448866635be505c56b51ad7c6d1158b8a5750c4774710c772',
    'app/api_response_auth_review.json': '6154c892d9f4fdda10cc73b90a809721296fa3de95cf5fbfef8d6407817a13e6',
    'app/api_response_v6_integration.json': '0aade4e711b35fcf57d8a74c2f77b266de63814f773904dace3276b0a0a8132a',
}


def assert_current_auth_evidence(operation, module):
    layers = approved_reviews()
    _, review, *_ = layers
    row = next(row for row in review['operation_source_updates']
               if (row['method'], row['path']) == ('PATCH', '/auth/me'))
    handler = review['sources'][review['handler_source_replacements'][ENDPOINT]]
    metadata = layers[6]  # Explicit V13 metadata predecessor, not the latest overlay.
    successor = next(row for row in metadata['operation_source_updates']
                     if (row['method'], row['path']) == ('PATCH', '/auth/me'))
    assert successor['endpoint'] == ENDPOINT
    assert successor['before_sources'] == row['sources']
    from nav_files_evidence_fixture import review as navfiles_review,advance_row
    navfiles=navfiles_review()
    old_key=review['handler_source_replacements'][ENDPOINT]
    assert navfiles['source_preconditions'][old_key]==handler
    assert navfiles['handler_source_preconditions'][ENDPOINT]==old_key
    handler=navfiles['sources'][navfiles['handler_source_replacements'][ENDPOINT]]
    successor=advance_row(successor)
    assert operation['x-stella-contract-evidence'] == {
        'source-map': ['app/api_response_v12_final_review.json', 'app/api_response_v13_source_metadata_review.json','app/api_response_v17_nav_files_review.json'],
        'handler': handler,
        'supporting-symbols': successor['sources'],
    }
    assert ACTIVE_PROFILE in row['sources']
    assert PROFILE not in row['sources']
    assert module.SOURCE_EVIDENCE[ACTIVE_PROFILE] == review['sources'][ACTIVE_PROFILE]
    check_metadata(handler)


def test_approved_auth_overlay_is_loaded_without_rewriting_historical_evidence():
    module = response_module()
    historical = json.loads((ROOT / 'app/api_response_integrated.json').read_text())
    auth_keys = {key for key, source in historical['sources'].items() if source['file'] == AUTH_FILE}
    assert len(auth_keys) == 50
    # Historical auth/v6 evidence remains append-only; V12 alone retires its use.
    approved = json.loads((ROOT / 'app/api_response_auth_review.json').read_text())
    assert {approved['sources'][key]['sha256'] for key in auth_keys} == {AUTH_SHA256}
    overlay = json.loads((ROOT / 'app/api_response_v6_integration.json').read_text())
    assert overlay['provenance']['auth']['commit'] == 'e07f5989cdc569283c60747e6836965df6edbaf2'
    assert {module.SOURCE_EVIDENCE[key]['sha256'] for key in auth_keys} == {V6_AUTH_SHA256}
    assert module.SOURCE_EVIDENCE[PROFILE] == {
        'file': AUTH_FILE, 'sha256': V6_AUTH_SHA256, 'line': 394, 'end_line': 398, 'symbol': PROFILE,
    }
    assert module.SOURCE_EVIDENCE[ACTIVE_PROFILE] == {
        'file': AUTH_FILE, 'sha256': ACTIVE_AUTH_SHA256, 'line': 401, 'end_line': 405,
        'symbol': PROFILE, 'symbol_sha256': '1d3f4ad2514b1cd0a5d8ed29408d7fdbdb85883d9d6fc7c807d9816aa942bdad',
    }
    row = next(row for row in module.INVENTORY if row['endpoint'] == ENDPOINT)
    assert (row['method'], row['path']) == ('PATCH', '/auth/me')
    assert CURRENT_PROFILE in row['sources'] and ACTIVE_PROFILE not in row['sources'] and PROFILE not in row['sources']
    assert module.DECLARATIONS['PATCH', '/auth/me']['sources'] == row['sources']
    operation = {}
    module.decorate_response(operation, 'PATCH', '/auth/me', ENDPOINT)
    assert_current_auth_evidence(operation, module)
    assert operation['x-stella-contract-evidence']['handler']['sha256'] == CURRENT_AUTH_SHA256
    for filename, digest in HISTORICAL_HASHES.items():
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == digest
    assert module.validate_response_sources(ROOT, static_inventory()[0]) == []


def test_all_approved_auth_symbol_ranges_match_exact_source():
    module = response_module()
    sources = {key: source for key, source in module.SOURCE_EVIDENCE.items() if source['file'] == AUTH_FILE}
    historical = json.loads((ROOT / 'app/api_response_v6_integration.json').read_text())
    historical = {key: source for key, source in historical['sources'].items() if source['file'] == AUTH_FILE}
    _, review, *_ = approved_reviews()
    current = {key: source for key, source in review['sources'].items() if source['file'] == AUTH_FILE}
    assert len(historical) == 67 and len(current) == 51
    assert not historical.keys() & current.keys()
    from nav_files_evidence_fixture import review as navfiles_review
    navfiles=navfiles_review()
    live={key:source for key,source in navfiles['sources'].items() if source['file']==AUTH_FILE}
    assert len(live)==51 and not live.keys() & (historical|current).keys()
    assert sources == historical | current | live
    active = {key for row in module.INVENTORY for key in row['sources']}
    assert not active.intersection(historical)
    assert not current.keys() & active
    assert live.keys() <= active
    for key, source in historical.items():
        assert source['sha256'] == V6_AUTH_SHA256
        if key in review['source_replacements']:
            successor = review['source_replacements'][key]
            assert successor in current
            symbol = AUTH_FILE if key in {AUTH_FILE + ':integrated-review', AUTH_FILE + ':response-shapes'} else source['symbol']
            assert (current[successor]['file'], current[successor]['symbol']) == (source['file'], symbol)
        else:
            # These historical DTO/helper records were already unreferenced at
            # the approved V12 edge, not silently replaced or checked as live.
            assert all(key not in row['before_sources'] for row in review['operation_source_updates'])
    for source in current.values():
        assert source['sha256'] == ACTIVE_AUTH_SHA256
        check_metadata(source)
    for source in live.values():
        assert source['sha256']==CURRENT_AUTH_SHA256
        check_metadata(source)


def test_auth_source_gate_rejects_one_byte_drift(tmp_path):
    module = response_module()
    records = static_inventory()[0]
    assert module.validate_response_sources(ROOT, records) == []
    # Project only referenced files; unchanged bytes stay read-only symlink targets.
    files = {module.SOURCE_EVIDENCE[key]['file'] for row in module.INVENTORY for key in row['sources']}
    for filename in files:
        destination = tmp_path / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        if filename == AUTH_FILE:
            destination.write_bytes((ROOT / filename).read_bytes() + b' ')
        else:
            destination.symlink_to(ROOT / filename)
    assert module.validate_response_sources(tmp_path, records) == ['source drift or missing source: ' + AUTH_FILE]


def test_profile_input_is_present_in_native_and_decorated_offline_openapi():
    import inspect
    import sys
    from fastapi.routing import APIRoute
    from jsonschema import Draft202012Validator

    app, _ = source_shaped_app()
    native = app.openapi()
    request = native['paths']['/auth/me']['patch']['requestBody']
    assert request == {
        'content': {'application/json': {'schema': {'$ref': '#/components/schemas/ProfileIn'}}},
        'required': True,
    }
    expected = {
        'type': 'object', 'title': 'ProfileIn',
        'properties': {
            'username': {'anyOf': [{'type': 'string', 'maxLength': 254}, {'type': 'null'}], 'title': 'Username'},
            'display_name': {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'title': 'Display Name'},
            'email': {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'title': 'Email'},
            'home_bg': {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'title': 'Home Bg'},
        },
    }
    assert native['components']['schemas']['ProfileIn'] == expected
    endpoint = next(route.endpoint for route in app.routes if isinstance(route, APIRoute) and route.path == '/auth/me' and 'PATCH' in route.methods)
    parameters = inspect.signature(endpoint).parameters
    assert parameters['user'].default.dependency.__name__ == 'current_user'
    assert parameters['db'].default.dependency.__name__ == 'get_db'
    model = parameters['data'].annotation
    assert model.__name__ == 'ProfileIn'
    # Pydantic includes null defaults, while native FastAPI omits them: keep both oracles.
    model_schema = model.model_json_schema()
    assert all(value['default'] is None for value in model_schema['properties'].values())
    assert not model_schema.get('required')
    payload = {'username': 'new-owner', 'display_name': 'Fixture Name', 'email': 'fixture@example.invalid', 'home_bg': '/fixture.png'}
    assert model(**payload).model_dump() == payload
    for value in ({}, {'username': None}, {'username': 'x' * 254}, payload):
        Draft202012Validator(expected).validate(value)
    for value in ({'username': 123}, {'username': 'x' * 255}):
        assert not Draft202012Validator(expected).is_valid(value)

    install(app)
    app.openapi_schema = None
    decorated = app.openapi()
    patch = decorated['paths']['/auth/me']['patch']
    assert patch['requestBody'] == request
    assert decorated['components']['schemas']['ProfileIn'] == expected
    response = patch['responses']['200']['content']['application/json']['schema']
    if '$ref' in response:
        response = decorated['components']['schemas'][response['$ref'].rsplit('/', 1)[-1]]
    assert response['properties']['username'] == {'type': 'string'}
    assert 'username' in response['required']
    Draft202012Validator(response).validate({
        'id': 'fixture-owner', 'username': payload['username'], 'display_name': payload['display_name'],
        'email': payload['email'], 'home_bg': payload['home_bg'], 'is_admin': True,
        'avatar_url': '', 'email_verified': False,
    })
    assert_current_auth_evidence(patch, response_module())
    assert not {'main', 'app.database', 'app.config', 'app.routers.auth'}.intersection(sys.modules)


@pytest.mark.parametrize('field,value', [
    ('source-map', 'app/api_response_v6_integration.json'),
    ('source-map', []),
    ('source-map', 'arbitrary.json'),
    ('handler', {}),
    ('supporting-symbols', [PROFILE]),
])
def test_current_auth_mapping_rejects_stale_or_missing_evidence(field, value):
    module = response_module()
    operation = {}
    module.decorate_response(operation, 'PATCH', '/auth/me', ENDPOINT)
    assert_current_auth_evidence(operation, module)
    operation['x-stella-contract-evidence'][field] = value
    with pytest.raises(AssertionError):
        assert_current_auth_evidence(operation, module)
