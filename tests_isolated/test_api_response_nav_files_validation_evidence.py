"""v18 metadata-only validation closure: exact scope and immutable predecessors."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from test_api_openapi_contract import ROOT
from test_api_response_contract import response_module

REVIEW = 'api_response_v18_nav_files_validation_review.json'
VALIDATION = 'app/validation_errors.py:response-projection'
MAIN = 'main.py@v11-review@v17-nav-files'


@pytest.fixture(scope='module')
def reviewed():
    return response_module()


def test_exact_23_validation_edges_reuse_existing_sources_without_contract_changes(reviewed):
    m = reviewed
    r = m._V18_NAV_FILES_VALIDATION_REVIEW
    v17 = m._V17_REVIEW
    expected = [row for row in v17['operations'] if row['request_validation']]
    assert len(expected) == 23
    assert sum(row['endpoint'].startswith('app.routers.native_nav.') for row in expected) == 9
    assert sum(row['endpoint'].startswith(('app.routers.node_files.', 'app.routers.node_files_release.')) for row in expected) == 14
    assert r['source_approval'] is True and r['release_approval'] is False
    assert r['source_additions'] == [VALIDATION, MAIN]
    assert r['sources'] == {} and r['operations'] == []
    assert r['source_preconditions'] == {key: m.SOURCE_EVIDENCE[key] for key in [VALIDATION, MAIN]}
    assert len(r['operation_source_updates']) == 23
    from unified_files_evidence_fixture import advance_row, source_maps
    actual = {(row['method'], row['path']): row for row in m.INVENTORY}
    for before, update in zip(expected, r['operation_source_updates'], strict=True):
        assert update['before_operation'] == before
        assert update['before_sources'] == before['sources']
        assert (update['method'], update['path'], update['endpoint']) == (before['method'], before['path'], before['endpoint'])
        assert update['sources'] == sorted(set(before['sources']) | {VALIDATION, MAIN})
        assert actual[before['method'], before['path']] == advance_row({**before, 'sources': update['sources']})
        op = {}
        m.decorate_response(op, before['method'], before['path'], before['endpoint'], document={})
        assert op['x-stella-contract-evidence']['source-map'] == source_maps(before, ['app/api_response_v17_nav_files_review.json', 'app/' + REVIEW])
        assert op['x-stella-contract-evidence']['supporting-symbols'] == advance_row({**before, 'sources': update['sources']})['sources']
    for before in v17['operations']:
        if not before['request_validation']:
            assert actual[before['method'], before['path']] == advance_row(before)
    for key in [VALIDATION, MAIN]:
        source = m.SOURCE_EVIDENCE[key]
        assert hashlib.sha256((ROOT/source['file']).read_bytes()).hexdigest() == source['sha256']


@pytest.mark.parametrize('damage', ['endpoint', 'before_union', 'before_order', 'missing_validation', 'missing_main', 'extra_source', 'scope_extra', 'scope_missing', 'duplicate', 'precondition', 'release', 'request_validation', 'immutable_note'])
def test_v18_loader_refuses_review_damage(monkeypatch, damage, reviewed):
    r = deepcopy(reviewed._V18_NAV_FILES_VALIDATION_REVIEW)
    u = r['operation_source_updates'][0]
    if damage == 'endpoint': u['endpoint'] = 'wrong.endpoint'
    elif damage == 'before_union': u['before_sources'] = []
    elif damage == 'before_order': u['before_sources'].reverse()
    elif damage == 'missing_validation': u['sources'].remove(VALIDATION)
    elif damage == 'missing_main': u['sources'].remove(MAIN)
    elif damage == 'extra_source': u['sources'].append('unapproved')
    elif damage == 'scope_extra': r['operation_source_updates'].append({**u, 'path': '/unapproved'})
    elif damage == 'scope_missing': r['operation_source_updates'].pop()
    elif damage == 'duplicate': r['operation_source_updates'][-1] = deepcopy(u)
    elif damage == 'precondition': r['source_preconditions'][VALIDATION]['sha256'] = '0'*64
    elif damage == 'release': r['release_approval'] = True
    elif damage == 'immutable_note': r['scope'] = 'unapproved note'
    else: u['before_operation']['request_validation'] = False
    read = Path.read_text
    monkeypatch.setattr(Path, 'read_text', lambda p, *a, **kw: json.dumps(r) if p == ROOT/'app'/REVIEW else read(p, *a, **kw))
    reason = ('immutable review drift' if damage == 'immutable_note' else
              'scope/source precondition drift' if damage in {
                  'endpoint', 'scope_extra', 'scope_missing', 'duplicate', 'precondition', 'release'} else
              'exact before operation/source union drift')
    with pytest.raises(ValueError, match='v18 nav files validation ' + reason):
        response_module()
