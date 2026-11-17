"""Regression of reviewed metadata against current DTOs and captured real HTTP.

Captured payloads are owned full-main TCP/PG evidence, not new live execution.
DTO import uses only the standalone schema module; no main/config/database.
"""
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from test_api_response_contract import response_module, validate_payload
from test_api_openapi_contract import ROOT


def document_schema_module():
    spec = importlib.util.spec_from_file_location('standalone_document_schema', ROOT / 'app/schemas/document.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_document_dtos_include_current_display_field():
    models = response_module().MODELS
    actual = document_schema_module()
    for name, schema in [('DocumentRead', actual.DocumentRead.model_json_schema()),
                         ('list[DocumentListItem]', {'type': 'array', 'items': actual.DocumentListItem.model_json_schema()})]:
        assert models[name] == schema
    assert 'saved_event_at' not in json.dumps(models['DocumentRead'])
    # Nullable display is optional in the current DTO, not an input/CAS token.
    for name in ['DocumentCreate', 'DocumentUpdate', 'ConsumedDraft', 'DraftRead']:
        props = getattr(actual, name).model_json_schema()['properties']
        assert 'updated_at_display' not in props and 'saved_event_at' not in props


def test_timeline_requires_unknown_history_slots_without_raw_clock_fallback():
    module = response_module()
    for unknown, path in [(False, None), (True, '/notes')]:
        validate_payload('GET', '/timeline', dict(items=[], has_more=False,
                         unknown_notes_present=unknown, history_path=path))
    validator = Draft202012Validator(module.TIMELINE)
    for missing in ['unknown_notes_present', 'history_path']:
        payload = dict(items=[], has_more=False, unknown_notes_present=True, history_path='/notes')
        del payload[missing]
        assert not validator.is_valid(payload)


def test_template_delete_keeps_runtime_validation_declaration():
    module = response_module()
    declaration = module.DECLARATIONS[('DELETE', '/website-templates/{tid}')]
    assert '422' in declaration['responses']
    assert 'content' not in declaration['responses']['204']
    # Historical upstream review stays revision-pinned, not retroactively edited.
    assert '422' not in module.TEMPLATE_INTEGRATION_EVIDENCE[('DELETE', '/website-templates/{tid}')]['responses']


def test_captured_owned_http_payloads_match_declarations():
    fixture = json.loads((Path(__file__).parent / 'fixtures/contract_reconcile_1907a99.json').read_text())
    assert fixture['provenance']['evidence_level'] == 'full-main TCP HTTP; real auth; owned PostgreSQL; no dependency overrides'
    assert len(fixture['responses']) == 27
    # Historical HTTP bytes must keep their literal predecessor contract. New
    # v22 save envelopes are exercised by the separate real-route owning file.
    from private_remediation_evidence_fixture import parent_loader, review as v22_review
    predecessor={'__file__':str(ROOT/'app/api_response_contracts.py')}
    exec(compile(parent_loader(),'literal-v21-captured-contract','exec'),predecessor)
    changed={(r['method'],r['path']) for r in v22_review()['response_overrides']}
    for response in fixture['responses']:
        key=response['method'],response['path']
        if key in changed:
            schema=predecessor['DECLARATIONS'][key]['responses'][str(response['status'])]['content']['application/json']['schema']
            Draft202012Validator(schema).validate(response['body'])
        else:
            validate_payload(response['method'], response['path'], response['body'], str(response['status']))
    puts = [r['body'] for r in fixture['responses'] if r['method'] == 'PUT' and r['status'] == 200]
    assert len(puts) == 1
    payload = puts[0]
    assert payload['draft_content'] == 'retained-slot'
    assert 'saved_event_at' not in payload and 'has_draft' not in payload
    assert payload['updated_at_display'] != payload['updated_at']
    from datetime import datetime
    observed = datetime.fromisoformat(payload['updated_at_display'])
    assert observed.utcoffset() is not None
    assert datetime.fromisoformat(payload['updated_at']).utcoffset() is None
    timelines = [r['body'] for r in fixture['responses'] if r['path'] == '/timeline' and r['status'] == 200]
    known = next(t for t in timelines if any(i['id'] == payload['id'] for i in t['items']))
    note = next(i for i in known['items'] if i['id'] == payload['id'])
    assert datetime.fromisoformat(note['ts']) == observed
    unknown = next(t for t in timelines if t['unknown_notes_present'])
    assert unknown['history_path'] == '/notes' and all(i['id'] != payload['id'] for i in unknown['items'])
    # A future internal column must not be silently admitted as public output.
    schema = response_module().DOCUMENT_ORM
    assert not Draft202012Validator(schema).is_valid(dict(payload, saved_event_at=payload['updated_at_display']))
