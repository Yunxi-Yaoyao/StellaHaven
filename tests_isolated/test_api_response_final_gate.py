"""Final frozen-contract checks; real projections/HTTP, never main or a live DB."""
import copy
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError

from test_api_openapi_contract import ROOT, source_shaped_app, static_inventory, install
from test_api_response_contract import response_module, validate_payload


def test_public_validation_schema_tracks_real_builder_and_private_wrappers(record_property):
    from app import validation_errors as v
    from test_validation_route_boundaries import app_for, Tree, extract
    from fastapi.routing import APIRoute
    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError
    from fastapi.testclient import TestClient
    m = response_module()
    item = m.VALIDATION_ITEM
    assert set(item['properties']['type']['enum']) == v._SAFE_TYPES
    assert set(item['properties']['msg']['enum']) == set(v._SAFE_MESSAGES.values()) | {'Invalid value'}
    classes = [APIRoute]
    for path, name in [('app/routers/auth_provider.py', 'PrivateValidationRoute'),
                       ('app/routers/website_settings.py', 'PrivateInputRoute')]:
        classes.append(extract(path, {name}, dict(APIRoute=APIRoute,
            HTTPException=HTTPException, RequestValidationError=RequestValidationError,
            validation_error_response=v.validation_error_response))[name])
    for cls in classes:
        app, calls = app_for(Tree, route_class=cls)
        with TestClient(app) as client:
            response = client.post('/probe', json={'entries': {'SYNTHETIC-PRIVATE-KEY': [{'apiToken': 'SYNTHETIC-PRIVATE-VALUE'}]}})
        assert response.status_code == 422 and calls == []
        assert response.json() == {'detail': [{'loc': ['body', 'entries', '[redacted]', 0, 'apiToken'],
            'type': 'int_parsing', 'msg': v._SAFE_MESSAGES['int_parsing']}]}
        Draft202012Validator(m.VALIDATION_ERROR).validate(response.json())
        record_property('selected_body_sample', json.dumps({'validation_'+cls.__name__: response.json()}))
        for field, value in [('input', 'private'), ('ctx', {}), ('url', 'private'),
                             ('type', 'SYNTHETIC-PRIVATE-TYPE'), ('msg', 'SYNTHETIC-PRIVATE-MESSAGE')]:
            damaged = copy.deepcopy(response.json()); damaged['detail'][0][field] = value
            with pytest.raises(ValidationError):
                Draft202012Validator(m.VALIDATION_ERROR).validate(damaged)
    # Business HTTPException details are separate; no full error/log redaction claim.
    Draft202012Validator(m.VALIDATION_ERROR).validate({'detail': 'explicit business error'})


def test_document_gate_checks_openapi_root_not_only_component_shapes():
    from tools.check_api_response_contracts import document_errors
    app, _ = source_shaped_app(); install(app)
    document = app.openapi()
    assert document_errors(document) == []
    del document['info']
    assert any('OpenAPI root' in e for e in document_errors(document))


def test_final_sources_bind_projection_helpers_and_validation_routes():
    m = response_module()
    assert m.validate_response_sources(ROOT, static_inventory()[0]) == []
    for row in m.INVENTORY:
        files = {m.SOURCE_EVIDENCE[s]['file'] for s in row['sources']}
        if (row['method'], row['path']) == ('GET', '/alerts/v2/rules'):
            assert {'app/public_alert_metrics.py', 'app/alert_metrics.py', 'app/services/alert_metrics.py'} <= files
        if row.get('request_validation') or row['endpoint'].startswith(('app.routers.auth_provider.', 'app.routers.website_settings.')):
            assert 'app/validation_errors.py' in files
    assert {key for key, declaration in m.DECLARATIONS.items() if declaration['status']=='incomplete'} == {
        ('GET','/notifications'), ('GET','/notifications/{notification_id}'), ('GET','/alerts/incidents/{incident_id}')
    }


def test_website_unicode_projection_and_owner_code_validate_real_output(record_property):
    from app import public_website as w
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    raw = dict(id='demo', name='正常站点', icon='heart', mode='iframe', browser_url='https://example.invalid/',
               enabled=True, origin='https://example.invalid', injection=dict(draft=dict(css='body { color: red; }',
               js='console.log("正常代码")', enabled=True, timing='dom_ready', csp_policy='reject'), active=None, previous=None))
    before = copy.deepcopy(raw)
    app = FastAPI()
    @app.get('/sample')
    def sample(): return w.public_module(raw)
    with TestClient(app) as client:
        good = client.get('/sample'); assert good.status_code == 200
        payload = good.json()
        assert payload['injection']['draft']['css'] == raw['injection']['draft']['css']
        assert payload['injection']['draft']['js'] == raw['injection']['draft']['js']
        validate_payload('GET', '/external-modules/{mid}', payload)
        assert raw == before
        raw['name'] = '\ud800'
        bad = client.get('/sample'); assert bad.status_code == 200
        output = bad.json(); validate_payload('GET', '/external-modules/{mid}', output)
        assert output['name'] == w.PublicModule.model_fields['name'].default and 'name' in output['projection']['invalid_fields']
        assert w.public_module(output) == output
        assert raw['name'] == '\ud800'
        record_property('selected_body_sample', json.dumps({'website_healthy': payload, 'website_unicode': output}, ensure_ascii=True))
    # Public model parity, including normal style/source enums, is checked in
    # the owning website tests and the merged serialization-schema parity test.


def test_strict_gate_still_rejects_incomplete_and_does_not_fake_passthrough(monkeypatch, capsys):
    from tools import check_api_response_contracts as gate
    m = gate.responses
    key = ('GET', '/alerts/v2/rules')
    prior_incomplete={key: value for key,value in m.DECLARATIONS.items() if value['status']=='incomplete'}
    assert set(prior_incomplete)=={('GET','/notifications'), ('GET','/notifications/{notification_id}'), ('GET','/alerts/incidents/{incident_id}')}
    declaration = copy.deepcopy(m.DECLARATIONS[key])
    declaration.update(status='incomplete', reason='synthetic missing read review')
    monkeypatch.setitem(m.DECLARATIONS, key, declaration)
    assert gate.run(require_complete=True) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['source_and_classification_gate_passed'] is True
    assert report['normalization_complete'] is False
    assert report['classification']['incomplete'] == 4
    expected_errors=['GET /alerts/v2/rules: incomplete response contract: synthetic missing read review']
    expected_errors += [f'{method} {path}: incomplete response contract: {value["reason"]}' for (method,path),value in prior_incomplete.items()]
    assert sorted(report['errors']) == sorted(expected_errors)
    expected = {('GET','/drive/openlist/{path}'), ('POST','/drive/openlist/{path}'),
                ('PUT','/drive/openlist/{path}'), ('PATCH','/drive/openlist/{path}'),
                ('DELETE','/drive/openlist/{path}'), ('HEAD','/drive/openlist/{path}')}
    actual = {key for key, value in m.DECLARATIONS.items() if value['status']=='passthrough'}
    assert actual == expected
    assert report['classification']['passthrough'] == len(actual)
