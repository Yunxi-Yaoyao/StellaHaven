"""CI167 append-only feedback ledger: literal history, exact AST and negatives."""
import ast
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest
from api_response_evidence_fixture import reviews, successor, check_metadata, reviewed_body
from test_api_openapi_contract import ROOT, static_inventory
from test_api_response_contract import response_module, validate_payload
from test_api_response_v11_integration import approved_reviews, apply_review, check_metadata as check_segment

REVIEW = 'api_response_v14_ci167_review.json'
MANIFEST_SHA = '552dfc757a2f1cd61186b37500b4f26ba747332570d739a7760528c59c830fd4'
FILES = ('agent/stella_agent.py', 'app/monitor_targets.py', 'app/repositories/workspace.py',
         'app/routers/monitor.py', 'app/schemas/monitor.py', 'app/services/entry_monitoring.py',
         'app/services/monitor.py', 'app/services/monitor_groups.py')


def history():
    folder = ROOT/'tests_isolated/fixtures/api_response_ci167_history'
    manifest = (folder/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == MANIFEST_SHA
    result = {}
    for row in json.loads(manifest):
        body = gzip.decompress((folder/row['fixture']).read_bytes())
        assert len(body) == row['size']
        assert hashlib.sha256(body).hexdigest() == row['sha256']
        assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == row['git_blob']
        result[row['file'], row['sha256']] = body
    assert {file for file, _ in result} == set(FILES) | {'app/api_response_contracts.py'}
    return result


@pytest.fixture(scope='module')
def current():
    review = next(r for r in reviews() if r.get('base')=='a1f847a8b58b51e64345020aa705b48a61f2d37f')
    assert next(r for r in approved_reviews() if r.get('base')==review['base']) == review
    assert review['base'] == 'a1f847a8b58b51e64345020aa705b48a61f2d37f'
    assert review['release_approval'] is False and review['source_approval'] is True
    return review, response_module(), static_inventory()[0]


def ast_node(source, body):
    text = body.decode()
    symbol = source['symbol']; file = source['file']
    if ':' in symbol or symbol == file:
        return ast.parse(text)
    nodes = ast.parse(text).body
    for part in symbol.removeprefix(file.removesuffix('.py').replace('/', '.')+'.').split('.'):
        def matches(n):
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                return n.name == part
            if isinstance(n, ast.Assign):
                return any(isinstance(t, ast.Name) and t.id == part for t in n.targets)
            return isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == part
        node, = [n for n in nodes if matches(n)]
        nodes = getattr(node, 'body', [])
    return node


def test_all_135_retired_pins_keep_literal_history_and_exact_semantic_classification(current):
    review, module, records = current
    assert len(review['source_replacements']) == 135
    assert len(review['sources']) == 151
    assert len(review['operation_source_updates']) == 113
    assert len(review['operations']) == 2
    assert module.validate_response_sources(ROOT, records) == []
    old_bytes = history()
    active = {s for r in module.INVENTORY for s in r['sources']}
    comparison = {r['key']: r for r in review['symbol_comparison']['rows']}
    assert comparison.keys() == review['source_replacements'].keys()
    semantic = 0
    for old, new in review['source_replacements'].items():
        before = review['source_preconditions'][old]; after = review['sources'][new]
        assert module.SOURCE_EVIDENCE[old] == before  # no rewrite
        assert old not in active and successor(new) in active
        layers=reviews();at=next(i for i,r in enumerate(layers) if r==review)
        assert successor(old, layers[:at+1]) == new
        assert successor(old) == successor(new)
        body = old_bytes[before['file'], before['sha256']]
        check_metadata(old, before, body)
        check_metadata(new, after, reviewed_body(after))
        check_segment(after, reviewed_body(after))
        same = ast.dump(ast_node(before, body)) == ast.dump(ast_node(after, reviewed_body(after)))
        assert same == comparison[old]['ast_equal']
        semantic += not same
    assert semantic == 13
    assert sum(r['segment_equal'] for r in comparison.values()) == 122


@pytest.mark.parametrize('damage', ['line', 'end_line', 'sha256', 'symbol_sha256', 'symbol'])
def test_every_successor_and_new_dependency_keeps_metadata_negatives(current, damage):
    review, _, _ = current
    for key, original in review['sources'].items():
        source = deepcopy(original)
        check_segment(source, reviewed_body(original))
        if damage in {'line', 'end_line'}:
            source[damage] += 1
        elif damage == 'symbol':
            source[damage] = 'missing.symbol'
        else:
            source[damage] = '0'*64
        with pytest.raises((AssertionError, ValueError, StopIteration)):
            check_segment(source, reviewed_body(original))


@pytest.mark.parametrize('file', FILES)
@pytest.mark.parametrize('damage', ['byte', 'missing'])
def test_original_source_guard_rejects_each_affected_file(current, monkeypatch, file, damage):
    _, module, records = current
    read, exists = Path.read_bytes, Path.is_file
    if damage == 'byte':
        monkeypatch.setattr(Path, 'read_bytes', lambda p: read(p)+b' ' if p == ROOT/file else read(p))
    else:
        monkeypatch.setattr(Path, 'is_file', lambda p: False if p == ROOT/file else exists(p))
    assert module.validate_response_sources(ROOT, records) == ['source drift or missing source: '+file]


@pytest.mark.parametrize('damage', ['source_precondition', 'handler_precondition', 'endpoint', 'before_sources', 'collision'])
def test_overlay_preconditions_reject_damage_without_relaxing_loader(current, monkeypatch, damage):
    review, _, _ = current
    changed = deepcopy(review)
    if damage == 'source_precondition':
        next(iter(changed['source_preconditions'].values()))['line'] = 0
    elif damage == 'handler_precondition':
        changed['handler_source_preconditions']['app.routers.monitor.agent_identity'] = 'wrong'
    elif damage in {'endpoint', 'before_sources'}:
        changed['operation_source_updates'][0][damage] = 'wrong' if damage == 'endpoint' else []
    else:
        key = next(iter(changed['source_preconditions']))
        changed['sources'][key] = changed['source_preconditions'][key]
    read = Path.read_text
    monkeypatch.setattr(Path, 'read_text', lambda p, *a, **kw: json.dumps(changed) if p == ROOT/'app'/REVIEW else read(p, *a, **kw))
    with pytest.raises(ValueError, match='v14 ci167'):
        response_module()


def test_full_prior_rows_replay_exactly_and_only_two_reviewed_operations_are_added(current):
    review, module, _ = current
    rows = {(r['method'], r['path']): dict(r, sources=r['before_sources']) for r in review['operation_source_updates']}
    replayed = apply_review(rows, review)
    layers=reviews();at=next(i for i,r in enumerate(layers) if r==review)
    for layer in layers[at+1:]:
        later = deepcopy(layer)
        later['operation_source_updates'] = [r for r in later['operation_source_updates']
                                             if (r['method'], r['path']) in replayed]
        replayed = apply_review(replayed, later)
    actual = {(r['method'], r['path']): r for r in module.INVENTORY}
    for key, row in replayed.items():
        assert row['sources'] == actual[key]['sources']
        assert row['endpoint'] == actual[key]['endpoint']
    assert {(r['method'], r['path']) for r in review['operations']} == {
        ('GET', '/monitors/groups/{group_id}/deletion-state'),
        ('POST', '/monitors/groups/{group_id}/delete')}


def test_new_group_read_schema_and_bodyless_deletion_preserve_errors_and_strict_input(current):
    from app.schemas.monitor import MonitorGroupDeletionState, MonitorGroupDelete
    from pydantic import ValidationError
    _, module, _ = current
    key = 'GET', '/monitors/groups/{group_id}/deletion-state'
    assert module.MODELS['MonitorGroupDeletionState'] == MonitorGroupDeletionState.model_json_schema(mode='serialization')
    validate_payload(*key, dict(stable_uuid=None, identity_matches=False, group_exists=False, name=None,
                               children=[], protected=False, remaining_child_ids=[]))
    delete = module.DECLARATIONS['POST', '/monitors/groups/{group_id}/delete']
    assert 'content' not in delete['responses']['204']
    assert {'400', '409', '401', '403', '422', '503'} <= set(delete['responses'])
    valid = dict(expected_stable_uuid='00000000-0000-0000-0000-000000000001', expected_child_ids=[1])
    assert MonitorGroupDelete.model_validate(valid).expected_child_ids == [1]
    for bad in [valid | {'expected_stable_uuid': 1}, valid | {'expected_child_ids': [True]},
                valid | {'expected_child_ids': [1, 1]}, valid | {'expected_child_ids': list(range(1, 14))}]:
        with pytest.raises(ValidationError):
            MonitorGroupDelete.model_validate(bad)
