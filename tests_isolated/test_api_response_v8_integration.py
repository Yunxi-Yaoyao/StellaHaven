"""Scoped v8 approval; original checker, no main/config/DB/network execution."""
import ast
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from api_response_evidence_fixture import frozen, successor, current_handler, reviews, check_metadata as exact_metadata
from test_api_response_v7_integration import history, historical_loader
import pytest
from pydantic import TypeAdapter, ValidationError
from jsonschema import Draft202012Validator
from test_api_openapi_contract import ROOT, static_inventory, source_shaped_app, install
from test_api_response_contract import response_module

LEDGER=json.loads((ROOT/'app/api_response_v8_review.json').read_text())
FILES=LEDGER['source_files']

@pytest.fixture(scope='module')
def records():return static_inventory()[0]

def test_historical_ledgers_and_preexisting_source_rows_remain_immutable():
    m=response_module()
    for name,digest in LEDGER['historical_ledgers'].items():
        assert hashlib.sha256((ROOT/'app'/name).read_bytes()).hexdigest()==digest
    # Import the exact pre-v8 loader under a distinct namespace, without app bootstrap.
    ns=historical_loader('a9afff1f9ceaeef98a45da9a689fa4b79063bda1238c4238da233acf0d3b1363')
    historical=historical_loader(LEDGER['loader_sha256'])
    assert all(m.SOURCE_EVIDENCE[k]==v for k,v in ns['SOURCE_EVIDENCE'].items())
    oldrows={(r['method'],r['path']):r for r in ns['INVENTORY']}
    active={(r['method'],r['path']):r for r in historical['INVENTORY']}
    updates={(r['method'],r['path']):r for r in LEDGER['operation_source_updates']}
    assert active.keys()-oldrows.keys()=={('GET','/agent/release')}
    for key,before in oldrows.items():
        after=deepcopy(before)
        if key in updates:
            assert updates[key]['before_sources']==before['sources']
            after['sources']=updates[key]['sources']
        assert active[key]==after
    for key in [('GET','/notifications'),('GET','/notifications/{notification_id}'),('GET','/alerts/incidents/{incident_id}')]:
        assert historical['DECLARATIONS'][key]==ns['DECLARATIONS'][key] | {'sources':historical['DECLARATIONS'][key]['sources']}
        assert m.DECLARATIONS[key]['status']==historical['DECLARATIONS'][key]['status']=='incomplete'
    assert hashlib.sha256(frozen('app/api_response_contracts.py', LEDGER['loader_sha256'])).hexdigest()==LEDGER['loader_sha256']
    assert hashlib.sha256(history('app/openapi_contract.py', LEDGER['auth_loader_sha256'])).hexdigest()==LEDGER['auth_loader_sha256']
    # Replay every independently pinned successor edge; never union live rows.
    expected=deepcopy(active)
    layers=reviews(); start=next(i for i,r in enumerate(layers) if r.get('loader_sha256')==LEDGER['loader_sha256'])
    for layer in layers[start+1:]:
        for update in layer.get('operation_source_updates', []):
            key=update['method'],update['path']
            assert expected[key]['endpoint']==update['endpoint']
            assert expected[key]['sources']==update['before_sources']
            expected[key]['sources']=list(update['sources'])
        for row in layer.get('operations', []):
            key=row['method'],row['path']; assert key not in expected
            expected[key]=deepcopy(row)
    assert expected=={(r['method'],r['path']):r for r in m.INVENTORY}
    assert LEDGER['release_approval'] is False

def check_metadata(source, body=None):
    body=history(source['file'], source['sha256']) if body is None else body
    assert hashlib.sha256(body).hexdigest()==source['sha256']
    if source['symbol']==source['file']:
        segment=body;lines=(1,len(body.splitlines()))
    else:
        node=next(n for n in ast.parse(body).body if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==source['symbol'].rsplit('.',1)[-1])
        segment=ast.get_source_segment(body.decode(),node).encode();lines=node.lineno,node.end_lineno
    assert (source['line'],source['end_line'])==lines
    assert source['symbol_sha256']==hashlib.sha256(segment).hexdigest()

def test_all_new_source_ranges_segments_and_supporting_edges_are_exact(records):
    m=response_module();active={s for r in m.INVENTORY for s in r['sources']}
    assert not active.intersection(LEDGER['source_replacements'])
    for key,source in LEDGER['sources'].items():
        check_metadata(source)  # literal v8 evidence, not today's source
        current=successor(key)
        if current in active:
            exact_metadata(current, m.SOURCE_EVIDENCE[current])
    for endpoint,key in LEDGER['handler_source_replacements'].items():
        rows=[r for r in m.INVENTORY if r['endpoint']==endpoint]
        current=current_handler(endpoint,key)
        assert rows and all(current in r['sources'] for r in rows)
    assert Counter((r['method'],r['path'],r['endpoint']) for r in m.INVENTORY)==Counter((a,b,c) for a,b,c,_ in records)
    assert m.validate_response_sources(ROOT,records)==[]

@pytest.mark.parametrize('file',FILES)
@pytest.mark.parametrize('damage',['single-byte','deleted'])
def test_original_checker_rejects_each_source_in_memory(monkeypatch,records,file,damage):
    m=response_module();assert m.validate_response_sources(ROOT,records)==[]
    read=Path.read_bytes;isfile=Path.is_file
    # Same byte length; mutate exactly one byte, never the running tree.
    monkeypatch.setattr(Path,'read_bytes',lambda p:bytes([read(p)[0]^1])+read(p)[1:] if p==ROOT/file else read(p)) if damage=='single-byte' else monkeypatch.setattr(Path,'is_file',lambda p:False if p==ROOT/file else isfile(p))
    assert m.validate_response_sources(ROOT,records)==['source drift or missing source: '+file]

@pytest.mark.parametrize('field,value',[('line',0),('symbol','missing.symbol'),('symbol_sha256','0'*64)])
def test_source_metadata_mutations_are_rejected(field,value):
    source=deepcopy(LEDGER['sources']['app.services.monitor_management.effective_enabled@v8-review-9c543a9']);source[field]=value
    with pytest.raises((AssertionError,StopIteration)):check_metadata(source)

def test_new_undeclared_endpoint_and_wrong_auth_signature_rejected(records):
    from app.openapi_contract import classify_auth
    m=response_module()
    assert m.validate_response_sources(ROOT,[*records,('GET','/agent/release/future','app.routers.monitor.agent_release',None)])==["('GET', '/agent/release/future'): unclassified/new, stale or changed response operation"]
    assert m.response_contract_errors({},'GET','/agent/release/future','app.routers.monitor.agent_release')==['unclassified response contract (missing or stale exact operation review)']
    assert classify_auth('GET','/agent/release','app.routers.monitor.agent_release',frozenset()).auth_type=='anonymous'
    for method,path,endpoint,deps in [('POST','/agent/release','app.routers.monitor.agent_release',frozenset()),('GET','/agent/release','app.routers.monitor.other',frozenset()),('GET','/agent/release','app.routers.monitor.agent_release',frozenset({'app.database.get_db'}))]:
        assert classify_auth(method,path,endpoint,deps).auth_type=='unclassified'

def test_frozen_dto_single_list_nested_success_copies_flags_and_binary_status():
    from app.schemas.monitor import MonitorRead,MonitorGroupRead,MonitorUpdate,MonitorGroupWrite
    m=response_module();expected={name:TypeAdapter(dto).json_schema(mode='serialization') for name,dto in [('MonitorRead',MonitorRead),('list[MonitorRead]',list[MonitorRead]),('MonitorGroupRead',MonitorGroupRead),('list[MonitorGroupRead]',list[MonitorGroupRead])]}
    assert {k:m.MODELS[k] for k in expected}==expected
    found=Counter()
    def visit(v):
        if isinstance(v,dict):
            if v.get('title') in ('MonitorRead','MonitorGroupRead'):
                assert v==expected[v['title']];found[v['title']]+=1
                assert LEDGER['models'][v['title']]['properties']['status']['enum']==['up','down']
                for f in ('visible','enabled'):assert v['properties'][f]['default'] is True
                if v['title']=='MonitorRead':assert v['properties']['effective_enabled']['default'] is True
                else:assert v['properties']['eligible_child_ids']['default']==[]
            for child in v.values():visit(child)
        elif isinstance(v,list):
            for child in v:visit(child)
    for d in m.DECLARATIONS.values():visit(d['responses'])
    assert found['MonitorRead']>=4 and found['MonitorGroupRead']>=3
    for model,base in [(MonitorUpdate,{}),(MonitorGroupWrite,{'name':'group'})]:
        for flag in ('visible','enabled'):
            assert model.model_validate(base|{flag:False}).model_dump()[flag] is False
            for bad in ('false',0,1,[],{}):
                with pytest.raises(ValidationError):model.model_validate(base|{flag:bad})
    sample=dict(id=1,name='probe',node_id=7,type='ping',target='192.0.2.1',interval=60,timeout=2,status='down',visible=False,enabled=False,effective_enabled=False)
    validator=Draft202012Validator(expected['MonitorRead']);validator.validate(sample)
    assert not validator.is_valid(sample|{'status':'unknown'})

def test_public_release_real_http_schema_no_store_and_legacy_unchanged(monkeypatch):
    from test_agent_release_v8 import routes
    monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION','0.6.16')
    client,ns=routes();reply=client.get('/agent/release');assert reply.status_code==200
    m=response_module();schema=m.MODELS['AgentReleaseRead'];Draft202012Validator(schema).validate(reply.json())
    assert set(reply.json())=={'source_version','source_sha256','source_size','announcement_version','rollout_policy'}
    assert schema['additionalProperties'] is False
    assert not Draft202012Validator(schema).is_valid(reply.json()|{'token':'private'})
    assert reply.headers['cache-control']=='no-store'
    assert client.get('/agent/version').json()=={'version':'0.6.16'}
    old=history('app/routers/monitor.py','7d3b8abbfec0bb7db25cf4a737be4423475307f5fd415247d20768d4b5612635').decode()
    current=(ROOT/'app/routers/monitor.py').read_text()
    def segment(text):return ast.get_source_segment(text,next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='agent_version'))
    from api_response_evidence_fixture import reviewed_body, reviews
    rollout = next(r for r in reviews() if r.get('base')=='96766477caffcbf85f66eae82af07d99e638214a')
    before = rollout['source_preconditions']['app.routers.monitor.agent_version@v13-monitor404@v14-ci167-feedback']
    legacy = reviewed_body(before).decode()
    assert segment(old)==segment(legacy)  # retain the exact historical equality
    # The separately approved current delta is exactly one finite parked pin;
    # every other byte, including the entire version response body, is equal.
    from monitor_ux_evidence_fixture import parent_bytes as ux_parent, assert_only_approved_additions
    assert_only_approved_additions()
    assert ux_parent('app/routers/monitor.py').decode() == legacy.replace(
        "{'0.6.9', '0.6.10', '0.6.11', '0.6.16', '0.6.17', available}",
        "{'0.6.9', '0.6.10', '0.6.11', '0.6.15', '0.6.16', '0.6.17', available}")
    app,_=source_shaped_app();install(app);op=app.openapi()['paths']['/agent/release']['get']
    assert op['security']==[] and op['x-stella-auth-type']=='anonymous'
    assert op['responses']['200']['headers']['Cache-Control']['schema']=={'type':'string','const':'no-store'}
    assert set(op['responses'])=={'200','503'}
    assert {k for k,v in m.DECLARATIONS.items() if v['status']=='incomplete'}=={('GET','/notifications'),('GET','/notifications/{notification_id}'),('GET','/alerts/incidents/{incident_id}')}
