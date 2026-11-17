"""Source-only audit successor preserves every predecessor API contract."""
from copy import deepcopy
from typing import Any
import pytest
from test_api_response_contract import response_module
from test_api_openapi_contract import ROOT, static_inventory
from servers_audit_evidence_fixture import frozen, review


@pytest.fixture(scope='module')
def current_contract():
    return response_module(), static_inventory()[0]


def test_exact_current_inventory_declarations_and_decorators(current_contract):
    old: dict[str, Any]={'__file__':str(ROOT/'app/api_response_contracts.py')}
    from evidence_graph_copy import contract_copy_dependency
    with contract_copy_dependency():
        exec(compile(frozen('app/api_response_contracts.py'),'literal-v23','exec'),old)
    current,records=current_contract;r=review()
    assert len(current.INVENTORY)==len(old['INVENTORY'])
    updates={(u['method'],u['path']):u for u in r['operation_source_updates']}
    for before,after in zip(old['INVENTORY'],current.INVENTORY,strict=True):
        key=before['method'],before['path'];expected={**before}
        if key in updates:
            assert before==updates[key]['before_operation']
            expected['sources']=updates[key]['sources']
        assert after==expected
        prior=old['DECLARATIONS'][key];active=current.DECLARATIONS[key]
        assert active=={**prior,'sources':expected['sources']}
        a={};b={}
        old['decorate_response'](a,*key,before['endpoint'],document={})
        current.decorate_response(b,*key,after['endpoint'],document={})
        if key in updates:
            a['x-stella-contract-evidence']['supporting-symbols']=list(expected['sources'])
            handler=current._V5_HANDLERS.get(after['endpoint'],after['endpoint'])
            a['x-stella-contract-evidence']['handler']=dict(current.SOURCE_EVIDENCE[handler])
            maps=a['x-stella-contract-evidence']['source-map']
            a['x-stella-contract-evidence']['source-map']=[*(maps if isinstance(maps,list) else [maps]),'app/api_response_v24_servers_audit_review.json']
        assert a==b,key
    assert all(current.SOURCE_EVIDENCE[k]==v for k,v in old['SOURCE_EVIDENCE'].items())
    assert current.validate_response_sources(ROOT,records)==[]


@pytest.mark.parametrize('file',['agent/stella_agent.py','app/routers/monitor.py','app/services/task.py'])
def test_current_audit_inputs_still_reject_damage(monkeypatch,file,current_contract):
    from pathlib import Path
    m,records=current_contract
    read=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda p:read(p)+b'\n' if p==ROOT/file else read(p))
    assert m.validate_response_sources(ROOT,records)==['source drift or missing source: '+file]
