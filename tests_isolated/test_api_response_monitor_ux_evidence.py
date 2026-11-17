"""Merged UX source approval; exact old edges/new closure, no product bootstrap."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from test_api_openapi_contract import ROOT, static_inventory, source_shaped_app, install
from test_api_response_contract import response_module, validate_payload
from test_api_response_ci167_evidence import ast_node
from test_api_response_v11_integration import check_metadata
from monitor_ux_evidence_fixture import REVIEW, review, parent_bytes, assert_only_approved_additions


def test_81_retirements_92_sources_88_edges_and_61_handlers_are_exact():
    r=review();m=response_module()
    assert r['base']=='aecf4d6233a4c5cc2d23ea91d8220192d5baeaa9'
    assert r['source_approval'] is True and r['release_approval'] is False
    assert len(r['source_preconditions'])==len(r['source_replacements'])==81
    assert len(r['sources'])==92 and len(r['new_source_keys'])==11
    assert len(r['operation_source_updates'])==88
    assert len(r['handler_source_preconditions'])==61
    assert m.validate_response_sources(ROOT,static_inventory()[0])==[]
    active={s for row in m.INVENTORY for s in row['sources']}
    assert not active.intersection(r['source_preconditions'])
    from unified_files_evidence_fixture import successor
    assert {successor(s) for s in r['sources']}<=active
    rows={(x['method'],x['path']):x for x in m.INVENTORY}
    for key,before in r['source_preconditions'].items():
        assert m.SOURCE_EVIDENCE[key]==before
        check_metadata(before,parent_bytes(before['file']))
    for key,after in r['sources'].items():
        assert m.SOURCE_EVIDENCE[key]==after
        check_metadata(after)
    for row in r['operation_source_updates']:
        assert row['sources']==sorted(r['source_replacements'].get(s,s) for s in row['before_sources'])
        assert rows[row['method'],row['path']]['endpoint']==row['endpoint']
        from nav_files_evidence_fixture import advance_row
        assert rows[row['method'],row['path']]['sources']==advance_row(row)['sources']
    for endpoint,key in r['handler_source_preconditions'].items():
        assert m._V5_HANDLERS[endpoint]==successor(r['source_replacements'][key])==successor(r['handler_source_replacements'][endpoint])
    for row in r['operations']:
        from nav_files_evidence_fixture import advance_row
        assert rows[row['method'],row['path']]==advance_row(row)
        assert m._V5_HANDLERS[row['endpoint']]==successor(r['new_handler_sources'][row['endpoint']])


def test_actual_symbols_and_complete_files_only_add_approved_ux_without_changing_agent():
    assert_only_approved_additions();r=review();changed=[]
    for row in r['symbol_comparison']['rows']:
        before=r['source_preconditions'][row['key']];after=r['sources'][row['successor']]
        old=parent_bytes(before['file'])
        from unified_files_evidence_fixture import historical_body
        new=historical_body(after)
        same=ast.dump(ast_node(before,old))==ast.dump(ast_node(after,new))
        assert same==row['ast_equal']==row['segment_equal']
        if not same:changed.append(before['symbol'])
    assert changed==['app/routers/monitor.py','app/schemas/monitor.py']
    from nav_files_evidence_fixture import current_agent
    current,agent=current_agent()
    assert len(agent)==232703
    assert hashlib.sha256(agent).hexdigest()=='25bc5e8c4f8e6ec262b89118098ea6d7b796f0bf3e75d8b10bd9a0aab070208b'
    before=parent_bytes('app/routers/monitor.py')
    from unified_files_evidence_fixture import frozen
    after=frozen('app/routers/monitor.py','30bd86ea0e39046ed450511c903601e981d05b2d7b2be0848c4ddb761d36a56d')
    def version(b):return ast.get_source_segment(b.decode(),next(n for n in ast.parse(b).body if isinstance(n,ast.FunctionDef) and n.name=='agent_version'))
    assert version(before)==version(after)
    assert "'0.6.15'" in version(after)


@pytest.mark.parametrize('field',['line','end_line','symbol','sha256','symbol_sha256'])
def test_all_old_and_new_metadata_keep_original_range_hash_segment_negatives(field):
    r=review()
    for collection,old in [(r['source_preconditions'],True),(r['sources'],False)]:
        for source in collection.values():
            body=parent_bytes(source['file']) if old else None
            check_metadata(source,body)
            bad=deepcopy(source);bad[field]=source[field]+1 if field in {'line','end_line'} else 'missing.symbol' if field=='symbol' else '0'*64
            with pytest.raises((AssertionError,StopIteration)):
                check_metadata(bad,body)


@pytest.mark.parametrize('file',['app/routers/monitor.py','app/schemas/monitor.py','app/services/monitor_batches.py','app/repositories/config.py'])
@pytest.mark.parametrize('damage',['byte','missing'])
def test_original_checker_fails_closed_for_each_changed_file_and_new_dependency(monkeypatch,file,damage):
    m=response_module();records=static_inventory()[0]
    assert m.validate_response_sources(ROOT,records)==[]
    read=Path.read_bytes;exists=Path.is_file
    if damage=='byte':monkeypatch.setattr(Path,'read_bytes',lambda p:read(p)+b' ' if p==ROOT/file else read(p))
    else:monkeypatch.setattr(Path,'is_file',lambda p:False if p==ROOT/file else exists(p))
    assert m.validate_response_sources(ROOT,records)==['source drift or missing source: '+file]


@pytest.mark.parametrize('damage',[
    'old_line','old_sha','missing_precondition','missing_source','extra_source','replacement_collision',
    'symbol','new_symbol','new_file','new_keys_duplicate','handler','handler_successor',
    'endpoint','before_sources','after_sources','missing_operation','duplicate_operation',
    'new_missing','new_duplicate','new_path','new_endpoint','new_status','new_errors','new_validation',
    'new_model','new_sources_missing','new_sources_extra','new_handler','model','extra_model'])
def test_loader_rejects_precondition_collision_union_and_new_operation_closure_damage(monkeypatch,damage):
    r=deepcopy(review());key=next(iter(r['source_preconditions']));new=r['source_replacements'][key]
    if damage=='old_line':r['source_preconditions'][key]['line']+=1
    elif damage=='old_sha':r['source_preconditions'][key]['sha256']='0'*64
    elif damage=='missing_precondition':del r['source_preconditions'][key]
    elif damage=='missing_source':del r['sources'][new]
    elif damage=='extra_source':r['sources']['unexpected']=r['sources'][new]
    elif damage=='replacement_collision':r['source_replacements'][key]=key
    elif damage=='symbol':r['sources'][new]['symbol']='missing.symbol'
    elif damage in {'new_symbol','new_file'}:r['sources'][r['new_source_keys'][0]]['symbol' if damage=='new_symbol' else 'file']='missing'
    elif damage=='new_keys_duplicate':r['new_source_keys'][-1]=r['new_source_keys'][0]
    elif damage in {'handler','handler_successor'}:r['handler_source_preconditions' if damage=='handler' else 'handler_source_replacements'][next(iter(r['handler_source_preconditions']))]='missing'
    elif damage in {'endpoint','before_sources','after_sources'}:r['operation_source_updates'][0]['sources' if damage=='after_sources' else damage]='missing' if damage=='endpoint' else []
    elif damage=='missing_operation':r['operation_source_updates'].pop()
    elif damage=='duplicate_operation':r['operation_source_updates'][-1]=r['operation_source_updates'][0]
    elif damage=='new_missing':r['operations'].pop()
    elif damage=='new_duplicate':r['operations'][-1]=r['operations'][0]
    elif damage in {'new_path','new_endpoint','new_status','new_errors','new_validation','new_model'}:
        field={'new_path':'path','new_endpoint':'endpoint','new_status':'status_code','new_errors':'error_statuses','new_validation':'request_validation','new_model':'model'}[damage]
        r['operations'][0][field]=[] if damage=='new_errors' else False if damage=='new_validation' else 'missing'
    elif damage=='new_sources_missing':r['operations'][0]['sources'].pop()
    elif damage=='new_sources_extra':r['operations'][0]['sources'].append('unknown')
    elif damage=='new_handler':r['new_handler_sources'][next(iter(r['new_handler_sources']))]='missing'
    elif damage=='model':r['models']['MonitorBatchReceipt']['properties']['monitor_ids']={}
    else:r['models']['Unexpected']={}
    read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**kw:json.dumps(r) if p==ROOT/'app'/REVIEW else read(p,*a,**kw))
    with pytest.raises(ValueError,match='v16 monitor UX'):
        response_module()


@pytest.mark.parametrize('collision',['source','operation','model'])
def test_new_operation_and_model_collision_rejected_against_prior_registry(monkeypatch,collision):
    read=Path.read_text
    target=ROOT/'app'/('api_response_v14_ci167_review.json' if collision in {'source','operation'} else 'api_response_models.json')
    prior=json.loads(read(target))
    if collision=='source':
        key=review()['new_source_keys'][0]
        prior['sources'][key]=review()['sources'][key]
    elif collision=='operation':
        row=deepcopy(review()['operations'][0]);row['sources']=['app.database.get_db']
        prior['operations'].append(row)
    else:prior['MonitorBatchReceipt']={'type':'string'}
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**kw:json.dumps(prior) if p==target else read(p,*a,**kw))
    with pytest.raises(ValueError,match='v16 monitor UX '+('source key' if collision=='source' else collision)+' collision'):
        response_module()


def test_native_source_shaped_openapi_response_request_auth_and_error_closure():
    from app.schemas.monitor import MonitorBatchCreate, MonitorBatchReceipt
    from pydantic import ValidationError
    m=response_module();app,_=source_shaped_app();install(app);doc=app.openapi()
    for method,path,code in [('POST','/monitors/batches','201'),('GET','/monitors/batches/receipts/{request_key}','200')]:
        row=m.DECLARATIONS[method,path];op=doc['paths'][path][method.lower()]
        assert row['status']=='reviewed'
        assert row['responses'][code]['content']['application/json']['schema']==MonitorBatchReceipt.model_json_schema(mode='serialization')
        validate_payload(method,path,dict(group_id=None,monitor_ids=[1,2]),code)
        assert set(op['responses'])==({'201','400','409','401','403','503','422'} if method=='POST' else {'200','404','401','403','503','422'})
        from refresh_timeout_evidence_fixture import source_maps
        assert op['x-stella-contract-evidence']['source-map']==source_maps(dict(method=method,path=path,endpoint=row['endpoint']),['app/api_response_inventory.json','app/'+REVIEW,'app/api_response_v17_nav_files_review.json','app/api_response_v19_unified_files_review.json'])
        assert op['x-stella-contract-evidence']['handler']==m.SOURCE_EVIDENCE[m._V5_HANDLERS[row['endpoint']]]
        assert op['x-stella-contract-evidence']['supporting-symbols']==row['sources']
        assert op['security']==[{'StellaAccessCookie':[]}]
        assert op['x-stella-auth-type']=='cookie-access'
        endpoint=row['endpoint']
        record, = [r for r in static_inventory()[0] if r[:3]==(method,path,endpoint)]
        assert record[3]==frozenset({'app.database.get_db','app.routers.auth.current_user'} |
            ({'app.routers.auth.admin_user'} if method=='POST' else set()))
    # New request is closed; real constraints, not undocumented invented checks.
    good=dict(items=[dict(name='probe',type='ping',target='example.com',node_id=1)],request_key='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
    assert MonitorBatchCreate.model_validate(good).group_id is None
    for bad in [good|{'items':[]},good|{'items':good['items']*13},good|{'request_key':'bad'},good|{'group_id':True},good|{'extra':1}]:
        with pytest.raises(ValidationError):MonitorBatchCreate.model_validate(bad)
    from tools.check_api_response_contracts import document_errors
    assert document_errors(doc)==[]


def test_ci_auto_discovers_new_suite_once_without_yaml_or_budget_changes():
    import importlib.util
    from collections import Counter
    spec=importlib.util.spec_from_file_location('monitor_ux_ci_planner',ROOT/'deploy/ci/run-backend-shard.py')
    assert spec is not None and spec.loader is not None
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    commands=[tuple(cmd) for i in range(1,5) for cmd in module.plan(ROOT,i,4)]
    counts=Counter(commands)
    for name in ['test_api_response_monitor_ux_evidence.py','test_monitor_ux_batch.py','test_agent_canary_tool.py','test_api_response_agent_rollout_evidence.py']:
        assert counts['tests_isolated/'+name,'--noconftest']==1
    assert len(commands)==len(set(commands))
