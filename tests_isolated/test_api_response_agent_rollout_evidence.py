"""Bounded .15 pin approval: immutable parent bytes and exact source unions."""
import ast
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest
from test_api_openapi_contract import ROOT, static_inventory
from test_api_response_contract import response_module
from test_api_response_ci167_evidence import ast_node
from test_api_response_v11_integration import check_metadata
from monitor_ux_evidence_fixture import review as ux_review, parent_bytes as ux_parent

REVIEW='api_response_v15_agent_rollout_review.json'
DIGEST='23b2e8350b02b83760f732f27b76c19e12b86c976b7b8e4c8d4c5aa81d2f55be'


def review():
    body=(ROOT/'app'/REVIEW).read_bytes()
    assert hashlib.sha256(body).hexdigest()==DIGEST
    return json.loads(body)


def parent_bytes():
    folder=ROOT/'tests_isolated/fixtures/api_response_agent_rollout_history'
    manifest=(folder/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest()=='37c5726569cf30ce5458c48f5887434479ca2f10817824e932107c060edc4485'
    row=json.loads(manifest)
    body=gzip.decompress((folder/row['fixture']).read_bytes())
    assert len(body)==row['size']
    assert hashlib.sha256(body).hexdigest()==row['sha256']
    assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()==row['git_blob']
    return body


def test_exact_65_successors_88_unions_and_61_handlers_restore_original_source_gate():
    r=review(); m=response_module()
    assert m.validate_response_sources(ROOT,static_inventory()[0])==[]
    assert r['base']=='96766477caffcbf85f66eae82af07d99e638214a'
    assert r['source_approval'] is True and r['release_approval'] is False
    assert len(r['source_preconditions'])==len(r['sources'])==len(r['source_replacements'])==65
    assert len(r['operation_source_updates'])==88
    assert len(r['handler_source_preconditions'])==61
    active={s for row in m.INVENTORY for s in row['sources']}
    assert not active.intersection(r['source_preconditions'])
    ux=ux_review()
    from unified_files_evidence_fixture import successor
    assert {successor(ux['source_replacements'][s]) for s in r['sources']}<=active
    for key,before in r['source_preconditions'].items():
        assert m.SOURCE_EVIDENCE[key]==before
        after=r['sources'][r['source_replacements'][key]]
        assert m.SOURCE_EVIDENCE[r['source_replacements'][key]]==after
        check_metadata(before,parent_bytes())
        check_metadata(after,ux_parent(after['file']))
        check_metadata(ux['sources'][ux['source_replacements'][r['source_replacements'][key]]])
    actual={(row['method'],row['path']):row for row in m.INVENTORY}
    for row in r['operation_source_updates']:
        assert row['sources']==sorted(r['source_replacements'].get(s,s) for s in row['before_sources'])
        assert actual[row['method'],row['path']]['endpoint']==row['endpoint']
        update=next(x for x in ux['operation_source_updates'] if (x['method'],x['path'])==(row['method'],row['path']))
        assert update['before_sources']==row['sources']
        from nav_files_evidence_fixture import advance_row
        assert actual[row['method'],row['path']]['sources']==advance_row(update)['sources']
    for endpoint,key in r['handler_source_preconditions'].items():
        assert r['source_replacements'][key]==r['handler_source_replacements'][endpoint]
        assert ux['handler_source_preconditions'][endpoint]==r['source_replacements'][key]
        assert m._V5_HANDLERS[endpoint]==successor(ux['handler_source_replacements'][endpoint])


def test_individual_ast_review_is_only_finite_pin_literal_and_whole_file():
    r=review(); old=parent_bytes(); new=ux_parent('app/routers/monitor.py')
    assert old.replace(b"{'0.6.9', '0.6.10', '0.6.11', '0.6.16', '0.6.17', available}",b"{'0.6.9', '0.6.10', '0.6.11', '0.6.15', '0.6.16', '0.6.17', available}")==new
    changed=[]
    for row in r['symbol_comparison']['rows']:
        before=r['source_preconditions'][row['key']]
        after=r['sources'][row['successor']]
        same=ast.dump(ast_node(before,old))==ast.dump(ast_node(after,new))
        assert same==row['ast_equal']==row['segment_equal']
        assert (before['line'],before['end_line'],before['symbol'])==(after['line'],after['end_line'],after['symbol'])
        if not same: changed.append(before['symbol'])
    assert sorted(changed)==['app.routers.monitor.agent_version','app/routers/monitor.py']
    from nav_files_evidence_fixture import current_agent
    current,artifact=current_agent()
    assert len(artifact)==232703
    assert hashlib.sha256(artifact).hexdigest()=='25bc5e8c4f8e6ec262b89118098ea6d7b796f0bf3e75d8b10bd9a0aab070208b'


@pytest.mark.parametrize('field', ['line','end_line','symbol','sha256','symbol_sha256'])
def test_all_65_old_and_new_records_keep_hash_range_segment_negatives(field):
    r=review()
    for collection,body in [(r['source_preconditions'],parent_bytes()),(r['sources'],ux_parent('app/routers/monitor.py'))]:
        for source in collection.values():
            check_metadata(source,body)
            changed=deepcopy(source)
            changed[field]=(source[field]+1 if field in {'line','end_line'} else
                            'missing.symbol' if field=='symbol' else '0'*64)
            with pytest.raises((AssertionError,StopIteration)):
                check_metadata(changed,body)


@pytest.mark.parametrize('damage', ['byte','missing','original-pre-fix-bytes'])
def test_original_source_guard_still_rejects_router_drift(monkeypatch,damage):
    m=response_module(); records=static_inventory()[0]
    assert m.validate_response_sources(ROOT,records)==[]
    read,exists=Path.read_bytes,Path.is_file
    target=ROOT/'app/routers/monitor.py'
    if damage=='missing':
        monkeypatch.setattr(Path,'is_file',lambda p:False if p==target else exists(p))
    else:
        body=parent_bytes() if damage=='original-pre-fix-bytes' else read(target)+b' '
        monkeypatch.setattr(Path,'read_bytes',lambda p:body if p==target else read(p))
    assert m.validate_response_sources(ROOT,records)==['source drift or missing source: app/routers/monitor.py']


@pytest.mark.parametrize('damage', ['old_line','old_sha256','old_symbol_hash','new_range','new_symbol',
    'missing_source','missing_precondition','replacement_collision','handler','handler_successor',
    'endpoint','before_sources','after_sources','missing_operation','duplicate_operation','new_operation','new_model'])
def test_overlay_loader_rejects_exact_precondition_scope_and_union_damage(monkeypatch,damage):
    r=review(); changed=deepcopy(r)
    key=next(iter(r['source_preconditions'])); new=r['source_replacements'][key]
    if damage.startswith('old_'):
        field={'old_line':'line','old_sha256':'sha256','old_symbol_hash':'symbol_sha256'}[damage]
        changed['source_preconditions'][key][field]=0 if field=='line' else '0'*64
    elif damage in {'new_range','new_symbol'}:
        changed['sources'][new]['line' if damage=='new_range' else 'symbol']=0 if damage=='new_range' else 'missing.symbol'
    elif damage=='missing_source': del changed['sources'][new]
    elif damage=='missing_precondition': del changed['source_preconditions'][key]
    elif damage=='replacement_collision':
        changed['source_replacements'][key]=key
        changed['sources'][key]=changed['sources'].pop(new)
    elif damage in {'handler','handler_successor'}:
        field='handler_source_preconditions' if damage=='handler' else 'handler_source_replacements'
        changed[field][next(iter(changed[field]))]='missing'
    elif damage in {'endpoint','before_sources','after_sources'}:
        field='sources' if damage=='after_sources' else damage
        changed['operation_source_updates'][0][field]='missing' if damage=='endpoint' else []
    elif damage=='missing_operation': changed['operation_source_updates'].pop()
    elif damage=='duplicate_operation': changed['operation_source_updates'][-1]=changed['operation_source_updates'][0]
    elif damage=='new_operation': changed['operations']=[{'method':'POST','path':'/unexpected'}]
    else: changed['models']={'Unexpected':{}}
    read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**kw:json.dumps(changed) if p==ROOT/'app'/REVIEW else read(p,*a,**kw))
    with pytest.raises(ValueError,match='v15 agent rollout'):
        response_module()


def test_ci_planner_discovers_each_new_suite_exactly_once():
    import importlib.util
    from collections import Counter
    spec=importlib.util.spec_from_file_location('rollout_ci_planner',ROOT/'deploy/ci/run-backend-shard.py')
    assert spec is not None and spec.loader is not None
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    commands=[tuple(cmd) for i in range(1,5) for cmd in module.plan(ROOT,i,4)]
    counts=Counter(commands)
    expected={('tests_isolated/'+name,'--noconftest') for name in [
        'test_agent_canary_tool.py','test_agent_legacy_upgrade.py','test_agent_rollout_compat.py',
        'test_api_response_agent_rollout_evidence.py']}
    assert expected<=counts.keys()
    assert all(counts[cmd]==1 for cmd in expected)
    assert len(commands)==len(set(commands))
