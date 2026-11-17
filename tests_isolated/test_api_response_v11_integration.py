"""V11 ledger-only acceptance: no main/config/database or sockets."""
import ast
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from test_api_openapi_contract import ROOT, static_inventory, source_shaped_app, install
from test_api_response_contract import response_module
from servers_audit_capacity_checks import (
    current_contract, test_current_audit_inputs_still_reject_damage,
    test_exact_current_inventory_declarations_and_decorators,
)

FILES = ['main.py', 'agent/stella_agent.py', 'agent/install.sh', 'agent/install.ps1', 'agent/run-agent.ps1',
         'app/routers/monitor.py', 'app/schemas/monitor.py', 'app/services/entry_monitor_groups.py',
         'app/services/entry_monitoring.py', 'app/services/monitor.py', 'app/services/monitor_groups.py',
         'app/services/node.py', 'app/services/host.py', 'app/services/agent_install.py', 'app/services/access_entries.py']
INCOMPLETE = {('GET','/notifications'), ('GET','/notifications/{notification_id}'), ('GET','/alerts/incidents/{incident_id}')}
# Independent immutable approvals, not hashes derived from today's source bytes.
REVIEW_DIGESTS = {
    'api_response_v11_review.json': 'bac85446d66572cd654e821d60f68544006104bd926bbb8e14b9197ac2c422a3',
    'api_response_v12_final_review.json': '45b542418bb39357a842fb4947bf8afc315c57f2eb743362f31d9633d366ea14',
    'api_response_v12_notes_review.json': 'c30ca41baf23f811f78658e00e7175dfa06b081bafb3b1826cd64951751d88c3',
    'api_response_v12_installer_umask_review.json': '52b50bde470285a5f70dba07a93778bc5e45879b5482cb4b22bcf70c7d231cab',
    'api_response_v13_speedtest_duration_review.json': 'dd17f38ecfe03cb9aeec68da352bafeada3d1ec7a286af75884dd08c08d6ecd8',
    'api_response_v13_monitor404_review.json': '73ff3a13e0c3f106ac442ce9ceea27cfb47e2a50f7e1bf62dcdd2ad10d2b645f',
    'api_response_v13_source_metadata_review.json': '0f9d5694370840dcccf02807726070bacde0b3eb0a5162f275d28f6c508b0e39',
    'api_response_v14_ci167_review.json': 'b80cb43ac67552a54708f22741ceaeb2889de97a39bf6153e9fb119ad6b53c6b',
    'api_response_v15_agent_rollout_review.json': '23b2e8350b02b83760f732f27b76c19e12b86c976b7b8e4c8d4c5aa81d2f55be',
    'api_response_v16_monitor_ux_review.json': 'a4034ef41bf26506485b59eebc845d1b4f5b0e1141ece576d7da4bf3606bea18',
    'api_response_v17_nav_files_review.json': 'dd1bd79485b43553522c66ef9123efa091fb660878b2a9e1eb1a8d3fb856ff75',
    'api_response_v18_nav_files_validation_review.json': '6fd0076187200906416dcfb155e06cdc73e162b2afde7cf0f587e194d2e8a232',
    'api_response_v19_unified_files_review.json': '8beb2030ad77a5773bc43d2195337cdec9f7dc3ce0861a630383821bee2317a9',
    'api_response_v20_fnos_policy_review.json': '96c47ca8ec9f5dab1310346f8d057c59e12b2d5037e38513b62b4daf1663cbbd',
    'api_response_v21_refresh_timeout_review.json': 'c1f31ea58a78205bcda43f1ff2c78e7df4278a4312c2b64b8297635b031fd73b',
    'api_response_v22_private_remediation_review.json': 'd93542ae89b386a5325ec7ec8616f5e7f33d92aa66d2a40ac8f0a5df087d0b82',
    'api_response_v23_final_offload_review.json': '179a95e5cc73def47e2b7c7b79c97366c700bd1f8f2b5b227e5ce61020b30ed1',
    'api_response_v24_servers_audit_review.json': 'fea8cfe9e08568d9ea62706da4172444b0c3ee601d19e89ab244fc1b5b14bc57',
}


def approved_reviews():
    reviews = []
    for name, digest in REVIEW_DIGESTS.items():
        body = (ROOT/'app'/name).read_bytes()
        assert hashlib.sha256(body).hexdigest() == digest, name
        from evidence_exact_cache import json_body
        review = json_body(body)
        assert review['release_approval'] is False
        if reviews:
            assert review['source_approval'] is True
        reviews.append(review)
    return reviews


def apply_review(rows, review):
    """Replay exact approved edges, retaining before_sources and endpoint guards."""
    rows = deepcopy(rows)
    for update in review['operation_source_updates']:
        key = update['method'], update['path']
        assert rows[key]['endpoint'] == update['endpoint']
        assert rows[key]['sources'] == update['before_sources']
        rows[key]['sources'] = list(update['sources'])
    for operation in review.get('operations', []):
        key = operation['method'], operation['path']
        assert key not in rows
        rows[key] = deepcopy(operation)
    return rows


def assert_identity_evidence(operation, module):
    # Exact approved sequence: V12 replacement, duration, then monitor404.
    named = dict(zip(REVIEW_DIGESTS, approved_reviews(), strict=True))
    monitor404 = named['api_response_v13_monitor404_review.json']
    metadata = named['api_response_v13_source_metadata_review.json']
    feedback = named['api_response_v14_ci167_review.json']
    rollout = named['api_response_v15_agent_rollout_review.json']
    ux = named['api_response_v16_monitor_ux_review.json']
    key = 'GET', '/agent/identity'
    row = next(r for r in monitor404['operation_source_updates'] if (r['method'], r['path']) == key)
    handler = monitor404['handler_source_replacements'][row['endpoint']]
    assert handler == 'app.routers.monitor.agent_identity@v13-monitor404'
    source = monitor404['sources'][handler]
    row = next(r for r in metadata['operation_source_updates'] if (r['method'], r['path']) == key)
    update = next(r for r in feedback['operation_source_updates'] if (r['method'], r['path']) == key)
    assert update['before_sources'] == row['sources']
    assert feedback['handler_source_preconditions'][row['endpoint']] == handler
    handler = feedback['handler_source_replacements'][row['endpoint']]
    source = feedback['sources'][handler]
    row = update
    update = next(r for r in rollout['operation_source_updates'] if (r['method'], r['path']) == key)
    assert update['before_sources'] == row['sources']
    assert rollout['handler_source_preconditions'][row['endpoint']] == handler
    handler = rollout['handler_source_replacements'][row['endpoint']]
    source = rollout['sources'][handler]
    row = update
    update = next(r for r in ux['operation_source_updates'] if (r['method'], r['path']) == key)
    assert update['before_sources'] == row['sources']
    assert ux['handler_source_preconditions'][row['endpoint']] == handler
    handler = ux['handler_source_replacements'][row['endpoint']]
    source = ux['sources'][handler]
    from nav_files_evidence_fixture import advance_row
    row = advance_row(update)
    from unified_files_evidence_fixture import successor, source_maps
    handler = successor(handler)
    source = module.SOURCE_EVIDENCE[handler]
    assert operation['x-stella-contract-evidence'] == {
        'source-map': ['app/api_response_v12_final_review.json',
                       'app/api_response_v13_speedtest_duration_review.json',
                       'app/api_response_v13_monitor404_review.json',
                       'app/api_response_v13_source_metadata_review.json',
                       'app/api_response_v14_ci167_review.json',
                       'app/api_response_v15_agent_rollout_review.json',
                       'app/api_response_v16_monitor_ux_review.json',
                       'app/api_response_v17_nav_files_review.json',
                       'app/api_response_v19_unified_files_review.json',
                       'app/api_response_v21_refresh_timeout_review.json',
                       'app/api_response_v24_servers_audit_review.json'],
        'handler': source,
        'supporting-symbols': row['sources'],
    }
    assert module.SOURCE_EVIDENCE[handler] == source
    check_metadata(source)

def ledger():
    return json.loads((ROOT/'app/api_response_v11_review.json').read_text())

@pytest.fixture(scope='module')
def records():
    return static_inventory()[0]

def test_exact_source_gate_and_new_identity_inventory(records):
    m = response_module()
    assert m.validate_response_sources(ROOT, records) == []
    actual = Counter((a,b,c) for a,b,c,_ in records)
    assert Counter((r['method'],r['path'],r['endpoint']) for r in m.INVENTORY) == actual
    assert all(n == 1 for n in actual.values())
    assert ('GET','/agent/identity') in m.DECLARATIONS


def identity_client():
    tree = ast.parse((ROOT/'app/routers/monitor.py').read_text())
    nodes = [n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in {'AgentIdentityRead','agent_identity','agent_release','AgentReleaseRead','agent_version'}]
    auth = next(n for n in ast.parse((ROOT/'app/security.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='agent_token')
    authns = dict(Request=Request,HTTPException=HTTPException)
    exec(compile(ast.Module(body=[auth],type_ignores=[]),'real-agent-auth','exec'),authns)
    repo = SimpleNamespace(get_by_token=lambda db,token: SimpleNamespace(id=17,status='online') if token=='owned' else None)
    calls = []
    def center():
        calls.append(True)
        return 'a'*64
    ns = dict(__file__=str(ROOT/'app/routers/monitor.py'), agent_router=APIRouter(prefix='/agent'),
              BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,Literal=__import__('typing').Literal,
              Depends=Depends,Annotated=Annotated,Session=object,get_db=lambda:None,
              agent_token=authns['agent_token'],HTTPException=HTTPException,identity_node_repo=repo,
              identity_install_svc=SimpleNamespace(installation_center_id=center))
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'real-agent-route-slice','exec'),ns)
    app=FastAPI();app.include_router(ns['agent_router'])
    return TestClient(app),ns,repo,calls


def test_identity_closed_actual_http_auth_no_store_source_fingerprint(monkeypatch):
    monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION','0.6.16')
    c,ns,repo,calls=identity_client()
    for headers in ({}, {'Authorization':'Basic owned'}, {'Authorization':'Bearer'}, {'Authorization':'Bearer bad'}):
        assert c.get('/agent/identity',headers=headers).status_code==401
    assert calls==[]
    for url,headers in [('/agent/identity',{'Authorization':'Bearer owned'}),('/agent/identity?token=owned',{}),('/agent/identity?token=bad',{'Authorization':'Bearer owned'})]:
        response=c.get(url,headers=headers)
        assert response.status_code==200
        body=response.json(); source=(ROOT/'agent/stella_agent.py').read_bytes()
        assert set(body)=={'center_id','node_id','source_version','source_sha256','source_size'}
        assert body==dict(center_id='a'*64,node_id=17,source_version='0.6.21',source_sha256=hashlib.sha256(source).hexdigest(),source_size=len(source))
        assert response.headers['cache-control']=='no-store'
        schema=response_module().MODELS['AgentIdentityRead']; v=Draft202012Validator(schema);v.validate(body)
        assert not v.is_valid(body|{'token':'secret'})
        for key,bad in [('node_id',0),('source_size',0),('center_id','x'*64),('source_sha256','a'*63)]:
            assert not v.is_valid(body|{key:bad})
    assert c.get('/agent/identity?token=owned',headers={'Authorization':'Basic bad'}).status_code==401
    before=len(calls);repo.get_by_token=lambda db,token: SimpleNamespace(id=17,status='removed')
    assert c.get('/agent/identity',headers={'Authorization':'Bearer owned'}).status_code==401
    assert len(calls)==before
    with pytest.raises(ValidationError):
        ns['AgentIdentityRead'].model_validate(body|{'token':'secret'})
    release=c.get('/agent/release')
    assert release.status_code==200 and release.headers['cache-control']=='no-store'
    assert release.json()['source_sha256']==hashlib.sha256(source).hexdigest()
    assert release.json()['source_size']==len(source)
    assert release.json()['source_version']==body['source_version']
    assert c.get('/agent/version').json()=={'version':'0.6.16'}


def test_identity_source_shaped_openapi_and_metadata_mutation_negative(records):
    app,_=source_shaped_app();contract=install(app)
    schema=contract.validate_contract(app,require_all_overrides=True)
    op=schema['paths']['/agent/identity']['get']
    assert op['security']==[{'StellaAgentBearer':[]},{'StellaAgentQueryLegacy':[]}]
    assert op['x-stella-auth-type']=='agent-bearer'
    assert set(op['responses'])=={'200','401','503'}
    assert op['responses']['200']['headers']['Cache-Control']['schema']=={'type':'string','const':'no-store'}
    assert_identity_evidence(op, response_module())
    original_openapi=app.openapi
    app.openapi=lambda:schema  # Hold damaged metadata; don't let decorator repair it first.
    for field in ['security','x-stella-auth-type','responses']:
        before=deepcopy(op[field]);op[field]={} if field=='responses' else []
        with pytest.raises(contract.ContractError):contract.validate_contract(app)
        op[field]=before
    app.openapi=original_openapi
    with pytest.raises(contract.ContractError,match='incomplete response contract'):
        contract.validate_contract(app,require_complete_responses=True)
    assert {k for k,v in response_module().DECLARATIONS.items() if v['status']=='incomplete'}==INCOMPLETE


def check_metadata(source, body=None):
    if body is None:
        from api_response_evidence_fixture import reviewed_body
        body=reviewed_body(source)
    assert hashlib.sha256(body).hexdigest()==source['sha256']
    if (source['symbol']==source['file'] or (source['symbol'].startswith(source['file']+':') and source['symbol']!='agent/install.sh:embedded.install') or
            source['symbol'] in {source['file']+':'+suffix for suffix in
                ('renewal-detached-review','backup-response-review','integrated-review','web-project-review')}):
        segment_digest=hashlib.sha256(body).hexdigest();lines=(1,len(body.splitlines()))
    else:
        text = body.decode()
        if source['symbol'] == 'agent/install.sh:embedded.install':
            prefix, embedded = text.split("<<'STELLA_INSTANCE_INSTALLER'\n", 1)
            embedded = embedded.rsplit('\nSTELLA_INSTANCE_INSTALLER', 1)[0]
            tree_text = '\n' * (prefix.count('\n') + 1) + embedded
            parts = ['install']
        else:
            tree_text = text
            parts=source['symbol'].removeprefix(source['file'].removesuffix('.py').replace('/','.')+'.').split('.')
        from evidence_exact_cache import symbol_range, symbol_digest
        coordinates = symbol_range(tree_text, parts)
        lines = coordinates[:2]
        segment_digest = symbol_digest(text, coordinates)
    assert (source['line'],source['end_line'])==lines
    assert source['symbol_sha256']==segment_digest


def test_append_only_exact_review_ranges_edges_and_history(records):
    l, *overlays = approved_reviews();m=response_module()
    assert l['release_approval'] is False
    assert sorted(l['source_files'])==sorted(FILES)
    # V11 was reviewed on dirty source: use exact base bytes only where their
    # digest matches. Unreconstructable historical records remain digest-frozen;
    # they are not asserted to be current or synthesized from a private archive.
    # Literal verified base blobs work in shallow CI without a network fetch.
    import gzip
    history = ROOT/'tests_isolated/fixtures/v11_base_history'
    manifest_bytes = (history/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == '40043f9001ea9ae6d04348e2d71deb70cf72d01c33f76dcdb90fec327406bcbc'
    manifest = json.loads(manifest_bytes)
    assert manifest['commit'] == l['base']
    assert set(manifest['files']) == set(l['source_files']) | {'app/api_response_contracts.py'}
    frozen = {}
    for file, record in manifest['files'].items():
        body = gzip.decompress((history/record['fixture']).read_bytes())
        assert len(body) == record['size']
        assert hashlib.sha256(body).hexdigest() == record['sha256']
        assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == record['git_blob']
        frozen[file] = body
    replacements = {k:v for review in overlays for k,v in review['source_replacements'].items()}
    active={s for r in m.INVENTORY for s in r['sources']}
    for key, source in l['sources'].items():
        assert m.SOURCE_EVIDENCE[key] == source
        body = frozen[source['file']]
        if hashlib.sha256(body).hexdigest() == source['sha256']:
            check_metadata(source, body)
        else:
            # Only an explicit approved replacement can retire an old record.
            assert key in replacements or key in active
        successor = key
        seen = set()
        while successor in replacements:
            assert successor not in seen
            seen.add(successor)
            successor = replacements[successor]
        assert successor in active
        current = m.SOURCE_EVIDENCE[successor]
        assert (current['file'], current['symbol']) == (source['file'], source['symbol'])
        check_metadata(current)
    for name,digest in l['historical_ledgers'].items():
        assert hashlib.sha256((ROOT/'app'/name).read_bytes()).hexdigest()==digest
    old=frozen['app/api_response_contracts.py'].decode()
    ns={'__file__':str(ROOT/'app/api_response_contracts.py')};exec(compile(old,'pre-v11-loader','exec'),ns)
    assert all(m.SOURCE_EVIDENCE[k]==v for k,v in ns['SOURCE_EVIDENCE'].items())
    before={(r['method'],r['path']):r for r in ns['INVENTORY']}
    v11 = apply_review(before, l)
    assert v11.keys()-before.keys()=={('GET','/agent/identity')}
    v11_active={s for r in v11.values() for s in r['sources']}
    assert not v11_active.intersection(l['source_replacements'])
    for endpoint,sources in l['source_additions'].items():
        assert all(set(sources)<=set(r['sources']) for r in v11.values() if r['endpoint']==endpoint)
    assert set(l['sources'])<=v11_active
    expected = v11
    for review in overlays:
        expected = apply_review(expected, review)
        assert all(m.SOURCE_EVIDENCE[k] == v for k,v in review['sources'].items())
        assert not active.intersection(review['source_replacements'])
        for key, source in review['sources'].items():
            if key in active:
                check_metadata(source)
    assert {(r['method'],r['path']):r for r in m.INVENTORY} == expected
    assert m.validate_response_sources(ROOT, records) == []
    for key in INCOMPLETE:
        assert m.DECLARATIONS[key]==ns['DECLARATIONS'][key]|{'sources':m.DECLARATIONS[key]['sources']}


@pytest.mark.parametrize('file',FILES)
@pytest.mark.parametrize('damage',['byte','missing'])
def test_original_checker_rejects_each_approved_file(monkeypatch,records,file,damage):
    m=response_module();assert m.validate_response_sources(ROOT,records)==[]
    read=Path.read_bytes;isfile=Path.is_file
    if damage=='byte':monkeypatch.setattr(Path,'read_bytes',lambda p:read(p)+b' ' if p==ROOT/file else read(p))
    else:monkeypatch.setattr(Path,'is_file',lambda p:False if p==ROOT/file else isfile(p))
    assert m.validate_response_sources(ROOT,records)==['source drift or missing source: '+file]


@pytest.mark.parametrize('field,value',[('line',0),('end_line',0),('symbol','missing.symbol'),('symbol_sha256','0'*64),('sha256','0'*64)])
def test_review_metadata_negative(field,value):
    from api_response_evidence_fixture import successor
    current = response_module(); key = successor('app.routers.monitor.agent_identity@v13-monitor404')
    source=deepcopy(current.SOURCE_EVIDENCE[key]);check_metadata(source);source[field]=value
    with pytest.raises((AssertionError,StopIteration)):check_metadata(source)


def test_new_operation_wrong_callable_and_union_precondition_fail_closed(monkeypatch,records):
    m=response_module()
    assert m.validate_response_sources(ROOT,[*records,('POST','/agent/identity','app.routers.monitor.agent_identity',None)])
    assert m.response_contract_errors({},'GET','/agent/identity','app.routers.monitor.other')
    l=ledger();l['operation_source_updates'][0]['before_sources']=[]
    original=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**kw:json.dumps(l) if p==ROOT/'app/api_response_v11_review.json' else original(p,*a,**kw))
    with pytest.raises(ValueError,match='v11 source-union precondition drift'):response_module()


def test_frozen_dto_object_list_nested_copies_empty_availability_not_health():
    from app.schemas.monitor import MonitorRead,MonitorGroupRead,MonitorGroupReceipt
    m=response_module()
    expected={name:TypeAdapter(dto).json_schema(mode='serialization') for name,dto in [
        ('MonitorRead',MonitorRead),('list[MonitorRead]',list[MonitorRead]),('MonitorGroupRead',MonitorGroupRead),
        ('list[MonitorGroupRead]',list[MonitorGroupRead]),('MonitorGroupReceipt',MonitorGroupReceipt)]}
    assert {k:m.MODELS[k] for k in expected}==expected
    visited=Counter()
    def visit(v):
        if isinstance(v,dict):
            title=v.get('title')
            if isinstance(title,str) and title in {'MonitorRead','MonitorGroupRead'}:
                assert v==expected[title];visited[title]+=1
            for child in v.values():visit(child)
        elif isinstance(v,list):
            for child in v:visit(child)
    for row in m.DECLARATIONS.values():visit(row['responses'])
    assert visited['MonitorRead']>=4 and visited['MonitorGroupRead']>=3
    body=dict(id=1,name='public',child_ids=[],status=None,down_count=0,unknown_count=0,entry_id='public',target_origin='https://example.test',availability_reason='no_connected_nodes')
    validator=Draft202012Validator(expected['MonitorGroupRead']);validator.validate(body)
    for status in ('unknown','pending','unavailable','stale'):
        assert not validator.is_valid(body|{'status':status})
    assert not validator.is_valid(body|{'availability_reason':'healthy'})
    for key in [('DELETE','/monitors/{monitor_id}'),('DELETE','/monitors/groups/{group_id}')]:
        assert '400' in m.DECLARATIONS[key]['responses']
        assert 'content' not in m.DECLARATIONS[key]['responses']['204']
