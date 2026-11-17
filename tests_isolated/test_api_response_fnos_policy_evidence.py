"""v20: one predicate's exact source successor; no API/Agent version change."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from test_api_openapi_contract import ROOT, static_inventory
from test_api_response_contract import response_module

REVIEW = 'api_response_v20_fnos_policy_review.json'
DIGEST = '96c47ca8ec9f5dab1310346f8d057c59e12b2d5037e38513b62b4daf1663cbbd'


def test_service_only_successor_has_exact_whole_union_and_unchanged_contracts():
    m = response_module()
    r = m._V20_REVIEW
    assert hashlib.sha256((ROOT/'app'/REVIEW).read_bytes()).hexdigest() == DIGEST
    assert r['status'] == 'PENDING_INDEPENDENT_REVIEW_NOT_APPROVED'
    assert r['source_approval'] is True and r['release_approval'] is False
    assert r['scope_files'] == ['app/services/node_files.py']
    assert r['operations'] == [] and r['models'] == {}
    assert len(r['source_preconditions']) == len(r['sources']) == 13
    assert len(r['operation_source_updates']) == 17
    from private_remediation_evidence_fixture import review as v22_review
    assert len(m.INVENTORY) == 325 + len(v22_review()['operations'])
    active = {s for row in [*m.INVENTORY,*m.WEBSOCKET_DECLARATIONS] for s in row['sources']}
    assert set(r['source_preconditions']).isdisjoint(active)
    assert set(r['sources']) <= active
    assert {s for s in active if m.SOURCE_EVIDENCE[s]['file'] == r['scope_files'][0]} == set(r['sources'])
    rows = {(row['method'],row['path']):row for row in m.INVENTORY}
    from fnos_policy_evidence_fixture import historical_body
    from test_api_response_v11_integration import check_metadata
    changed = []
    for key, old in r['source_preconditions'].items():
        new = r['sources'][r['source_replacements'][key]]
        assert m.SOURCE_EVIDENCE[key] == old
        check_metadata(old, historical_body(old))
        check_metadata(new)
        assert old['line'] == new['line'] and old['end_line'] == new['end_line']
        if old['symbol_sha256'] != new['symbol_sha256']: changed.append(old['symbol'])
    assert sorted(changed) == ['app.services.node_files.automatic_policy','app/services/node_files.py']
    for update in r['operation_source_updates']:
        before = update['before_operation']
        after = sorted(r['source_replacements'].get(s,s) for s in before['sources'])
        assert before['sources'] == update['before_sources']
        assert update['sources'] == after
        from refresh_timeout_evidence_fixture import advance_row
        assert rows[update['method'],update['path']] == advance_row(update['operation']) == advance_row({**before,'sources':after})
        op = {}
        m.decorate_response(op,update['method'],update['path'],update['endpoint'],document={})
        from refresh_timeout_evidence_fixture import review as refresh_review
        maps = op['x-stella-contract-evidence']['source-map']
        from private_remediation_evidence_fixture import final_review
        if (update['method'],update['path']) in {(u['method'],u['path']) for u in final_review()['operation_source_updates']}:
            assert maps[-1] == 'app/api_response_v23_final_offload_review.json'
            maps = maps[:-1]
        if (update['method'],update['path']) in {(u['method'],u['path']) for u in v22_review()['operation_source_updates']}:
            assert maps[-1] == 'app/api_response_v22_private_remediation_review.json'
            maps = maps[:-1]
        if (update['method'],update['path']) in {(u['method'],u['path']) for u in refresh_review()['operation_source_updates']}:
            assert maps[-1] == 'app/api_response_v21_refresh_timeout_review.json'
            maps = maps[:-1]
        assert maps[-1] == 'app/'+REVIEW
    assert m.validate_response_sources(ROOT,static_inventory()[0]) == []
    before = historical_body(next(iter(r['source_preconditions'].values())))
    assert before.replace(b".startswith('fnos')",b".startswith(('fnos', 'debian gnu/linux'))") == (ROOT/r['scope_files'][0]).read_bytes()


@pytest.mark.parametrize('field', ['line','end_line','sha256','symbol_sha256','symbol'])
def test_fnos_live_successors_keep_all_metadata_negative_controls(field):
    from test_api_response_v11_integration import check_metadata
    for original in response_module()._V20_REVIEW['sources'].values():
        check_metadata(original)
        damaged = deepcopy(original)
        damaged[field] = damaged[field]+1 if field in {'line','end_line'} else 'missing.symbol' if field == 'symbol' else '0'*64
        with pytest.raises((AssertionError,ValueError,StopIteration,SyntaxError)):
            check_metadata(damaged)


@pytest.mark.parametrize('damage', ['before','after','endpoint','scope','missing-edge','duplicate-edge','precondition','source','release','schema'])
def test_fnos_successor_refuses_review_damage(monkeypatch, damage):
    r = deepcopy(response_module()._V20_REVIEW)
    if damage == 'before': r['operation_source_updates'][0]['before_sources'] = []
    elif damage == 'after': r['operation_source_updates'][0]['sources'] = []
    elif damage == 'endpoint': r['operation_source_updates'][0]['endpoint'] = 'wrong'
    elif damage == 'scope': r['scope_files'].append('agent/stella_agent.py')
    elif damage == 'missing-edge': r['operation_source_updates'].pop()
    elif damage == 'duplicate-edge': r['operation_source_updates'][-1] = r['operation_source_updates'][0]
    elif damage == 'precondition': r['source_preconditions'][next(iter(r['source_preconditions']))]['sha256'] = '0'*64
    elif damage == 'source': r['sources'].pop(next(iter(r['sources'])))
    elif damage == 'release': r['release_approval'] = True
    else: r['models'] = {'Unreviewed':{}}
    read = Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**kw:json.dumps(r) if p == ROOT/'app'/REVIEW else read(p,*a,**kw))
    with pytest.raises(ValueError,match='v20 fnos policy'):
        response_module()
