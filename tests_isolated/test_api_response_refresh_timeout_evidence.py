"""v21 exact source successor; compatibility approval is NOT release approval."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest
from test_api_openapi_contract import ROOT, static_inventory
from test_api_response_contract import response_module
from refresh_timeout_evidence_fixture import REVIEW, DIGEST, review, historical_body, parent_loader


def test_exact_successor_preserves_every_old_record_contract_and_handler(monkeypatch):
    m=response_module();r=m._V21_REVIEW
    assert hashlib.sha256((ROOT/'app'/REVIEW).read_bytes()).hexdigest()==DIGEST
    assert r['status']=='PENDING_INDEPENDENT_REVIEW_NOT_APPROVED'
    assert r['source_approval'] is True and r['release_approval'] is False
    assert r['scope_files']==['agent/stella_agent.py','app/routers/monitor.py']
    assert r['operations']==[] and r['models']=={}
    assert len(r['source_preconditions'])==102 and len(r['sources'])==103
    assert len(r['operation_source_updates'])==107
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Git forbidden')))
    before={'__file__':str(ROOT/'app/api_response_contracts.py')}
    exec(compile(parent_loader(),'literal-v20-loader','exec'),before)
    from private_remediation_evidence_fixture import review as v22_review, advance_row as v22_row, source_maps as v22_maps
    v22=v22_review()
    from private_remediation_evidence_fixture import final_review
    v23=final_review()
    assert len(before['INVENTORY'])==325 and len(m.INVENTORY)==326
    assert m.WEBSOCKET_DECLARATIONS==before['WEBSOCKET_DECLARATIONS']
    assert len([r for r in static_inventory()[2] if r[2]=='websocket'])==4
    assert m.MODELS==before['MODELS']|v22['models']
    assert all(m.SOURCE_EVIDENCE[k]==v for k,v in before['SOURCE_EVIDENCE'].items())
    assert set(m.SOURCE_EVIDENCE)-set(before['SOURCE_EVIDENCE'])==set(r['sources'])|set(v22['sources'])|set(v23['sources'])
    active={s for row in [*m.INVENTORY,*m.WEBSOCKET_DECLARATIONS] for s in row['sources']}
    assert set(r['source_preconditions']).isdisjoint(active)
    assert {s for s in active if m.SOURCE_EVIDENCE[s]['file'] in r['scope_files']}==set(r['sources'])
    rows={(x['method'],x['path']):x for x in m.INVENTORY}
    from test_api_response_v11_integration import check_metadata
    changed=[]
    for key,old in r['source_preconditions'].items():
        new=r['sources'][r['source_replacements'][key]]
        check_metadata(old,historical_body(old));check_metadata(new)
        if old['symbol_sha256']!=new['symbol_sha256']:changed.append(old['symbol'])
    assert sorted(changed)==sorted(['agent.stella_agent._file_fetcher','agent.stella_agent._file_internal_main','agent/stella_agent.py','app.routers.monitor.agent_version','app/routers/monitor.py'])
    check_metadata(r['sources'][r['new_source_keys'][0]])
    for u in r['operation_source_updates']:
        b=u['before_operation']
        key=u['method'],u['path']
        expected=deepcopy(before['DECLARATIONS'][key]);expected['sources']=v22_row(u['operation'])['sources']
        overrides=[o for o in v22['response_overrides'] if (o['method'],o['path'])==key]
        if overrides:
            override,=overrides
            assert expected['responses']==override['before_responses']
            expected['responses']=override['responses']
        assert m.DECLARATIONS[key]==expected
        assert b['sources']==u['before_sources']
        after=sorted({r['source_replacements'].get(s,s) for s in b['sources']}|set(u['source_additions']))
        assert u['operation']=={**b,'sources':after}
        assert rows[u['method'],u['path']]==v22_row(u['operation'])
        expected=r['new_source_keys'] if any(before['SOURCE_EVIDENCE'][s]['file']=='agent/stella_agent.py' for s in b['sources']) else []
        assert u['source_additions']==expected
        op={};m.decorate_response(op,u['method'],u['path'],u['endpoint'],document={})
        expected_maps=v22_maps(u['operation'],['app/'+REVIEW])
        assert op['x-stella-contract-evidence']['source-map'][-len(expected_maps):]==expected_maps
        assert op['x-stella-contract-evidence']['handler']==m.SOURCE_EVIDENCE[m._V5_HANDLERS.get(u['endpoint'],u['endpoint'])]
    assert len(r['handler_source_preconditions'])==63
    for endpoint,key in r['handler_source_preconditions'].items():
        assert before['_V5_HANDLERS'][endpoint]==key
        assert m._V5_HANDLERS[endpoint]==r['source_replacements'][key]
    assert m.validate_response_sources(ROOT,static_inventory()[0])==[]


@pytest.mark.parametrize('field',['line','end_line','sha256','symbol_sha256','symbol'])
def test_live_and_literal_historical_metadata_negative_controls(field):
    from test_api_response_v11_integration import check_metadata
    r=review()
    for original in [*r['source_preconditions'].values(),*r['sources'].values()]:
        body=historical_body(original);check_metadata(original,body)
        bad=deepcopy(original)
        bad[field]=bad[field]+1 if field in {'line','end_line'} else 'missing.symbol' if field=='symbol' else '0'*64
        with pytest.raises((AssertionError,ValueError,StopIteration,SyntaxError)):check_metadata(bad,body)


@pytest.mark.parametrize('file',['agent/stella_agent.py','app/routers/monitor.py'])
@pytest.mark.parametrize('damage',['byte','missing'])
def test_live_byte_and_missing_source_stay_fail_closed(monkeypatch,file,damage):
    m=response_module();records=static_inventory()[0]
    assert m.validate_response_sources(ROOT,records)==[]
    read=Path.read_bytes;exists=Path.is_file
    if damage=='byte':monkeypatch.setattr(Path,'read_bytes',lambda p:read(p)+b' ' if p==ROOT/file else read(p))
    else:monkeypatch.setattr(Path,'is_file',lambda p:False if p==ROOT/file else exists(p))
    assert m.validate_response_sources(ROOT,records)==['source drift or missing source: '+file]


@pytest.mark.parametrize('damage',['before','before-operation','after','endpoint','scope','missing-edge','duplicate-edge','precondition','source','new-key','addition','handler-before','handler-after','release','schema'])
def test_successor_refuses_exact_scope_edge_authority_damage(monkeypatch,damage):
    r=deepcopy(review())
    if damage=='before':r['operation_source_updates'][0]['before_sources']=[]
    elif damage=='before-operation':r['operation_source_updates'][0]['before_operation']['endpoint']='wrong'
    elif damage=='after':r['operation_source_updates'][0]['sources']=[]
    elif damage=='endpoint':r['operation_source_updates'][0]['endpoint']='wrong'
    elif damage=='scope':r['scope_files'].append('app/security.py')
    elif damage=='missing-edge':r['operation_source_updates'].pop()
    elif damage=='duplicate-edge':r['operation_source_updates'][-1]=r['operation_source_updates'][0]
    elif damage=='precondition':r['source_preconditions'][next(iter(r['source_preconditions']))]['sha256']='0'*64
    elif damage=='source':r['sources'].pop(next(iter(r['sources'])))
    elif damage=='new-key':r['new_source_keys']=[]
    elif damage=='addition':r['operation_source_updates'][0]['source_additions']=[]
    elif damage=='handler-before':r['handler_source_preconditions'][next(iter(r['handler_source_preconditions']))]='wrong'
    elif damage=='handler-after':r['handler_source_replacements'][next(iter(r['handler_source_replacements']))]='wrong'
    elif damage=='release':r['release_approval']=True
    else:r['models']={'Unreviewed':{}}
    read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**kw:json.dumps(r) if p==ROOT/'app'/REVIEW else read(p,*a,**kw))
    with pytest.raises(ValueError,match='v21 refresh timeout'):response_module()
