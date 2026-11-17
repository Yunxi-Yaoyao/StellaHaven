"""Bounded v7 review: original checker, retained history, exact DTOs and negatives."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import gzip
from functools import lru_cache
from api_response_evidence_fixture import frozen, successor, reviews, check_metadata as exact_metadata
import pytest
from pydantic import TypeAdapter
from jsonschema import Draft202012Validator
from test_api_openapi_contract import ROOT, static_inventory
from test_api_response_contract import response_module

LEDGER = json.loads((ROOT/'app/api_response_v6_integration.json').read_text())
REVIEW = LEDGER['v7_binary_review']
V8 = json.loads((ROOT/'app/api_response_v8_review.json').read_text())
FILES = sorted(REVIEW['source_files'])


def history(file, digest):
    """Independent literal history, pinned even when Git is unavailable."""
    directory = Path(__file__).parent/'fixtures/ci158_response_history'
    manifest = (directory/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == 'ee217dcbaaf78d308a1e87d619c1e9e5a4b09f8a8d0708ea9bac69a54f7c8b29'
    row, = [r for r in json.loads(manifest) if (r['file'], r['sha256']) == (file, digest)]
    body = gzip.decompress((directory/row['fixture']).read_bytes())
    assert len(body) == row['size'] and hashlib.sha256(body).hexdigest() == digest
    assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == row['git_blob']
    return body


@pytest.mark.parametrize('damage', ['tampered', 'missing'])
def test_literal_history_rejects_damaged_fixtures(monkeypatch, damage):
    file='app/api_response_v6_integration.json'
    digest='e163b0ba7108f9e7eda580773985b8fa095c1518399c7fb92e1b6521faccac5d'
    target=Path(__file__).parent/'fixtures/ci158_response_history'/(digest+'.gz')
    read=Path.read_bytes
    def damaged(path):
        if path == target:
            if damage == 'missing':
                raise FileNotFoundError(path)
            return gzip.compress(gzip.decompress(read(path))+b' ', mtime=0)
        return read(path)
    monkeypatch.setattr(Path, 'read_bytes', damaged)
    with pytest.raises((AssertionError, FileNotFoundError)):
        history(file, digest)


@lru_cache
def historical_loader(digest):
    ns = {'__file__': str(ROOT/'app/api_response_contracts.py')}
    exec(compile(frozen('app/api_response_contracts.py', digest), 'literal-historical-loader', 'exec'), ns)
    return ns


@pytest.fixture(scope='module')
def records(): return static_inventory()[0]


def test_retained_original_rows_and_only_reviewed_scope_changed():
    before=json.loads(history('app/api_response_v6_integration.json', 'e163b0ba7108f9e7eda580773985b8fa095c1518399c7fb92e1b6521faccac5d'))
    assert all(LEDGER['sources'][k]==v for k,v in before['sources'].items())
    assert len(REVIEW['source_replacements'])==21
    assert set(LEDGER['sources'])-set(before['sources'])==set(REVIEW['source_replacements'].values())
    assert {LEDGER['sources'][k]['file'] for k in REVIEW['source_replacements'].values()}==set(FILES)
    assert REVIEW['added_existing_operation_rows']==[]
    old_rows={(r['method'],r['path']):r for r in before['operation_source_updates']}
    new_rows={(r['method'],r['path']):r for r in LEDGER['operation_source_updates']}
    retained={(r['method'],r['path']):r for r in REVIEW['previous_operation_source_updates']}
    assert len(retained)==83 and old_rows.keys()==new_rows.keys()
    for key,old in old_rows.items():
        expected=deepcopy(old)
        expected['sources']=sorted(REVIEW['source_replacements'].get(s,s) for s in old['sources'])
        assert expected==new_rows[key]
        if expected!=old: assert retained[key]==old
    for key,old in before.items():
        if key not in {'sources','operation_source_updates','models','success_schema_replacements'}:
            assert LEDGER[key]==old,key
    assert hashlib.sha256(frozen('app/api_response_contracts.py', LEDGER['loader_sha256'])).hexdigest()==LEDGER['loader_sha256']
    assert hashlib.sha256(frozen('app/api_response_contracts.py', V8['loader_sha256'])).hexdigest()==V8['loader_sha256']
    assert LEDGER['release_approval'] is False
    assert REVIEW['previous_success_schema_replacements']==before['success_schema_replacements']
    def only_binary(value):
        if isinstance(value,dict):
            if value.get('title') in ('MonitorRead','MonitorGroupRead'):
                value['properties']['status']['enum']=['up','down']
            for child in value.values():only_binary(child)
        elif isinstance(value,list):
            for child in value:only_binary(child)
    success=deepcopy(before['success_schema_replacements']);only_binary(success)
    assert LEDGER['success_schema_replacements']==success
    for name,old in before['models'].items():
        expected=deepcopy(old)
        if name in ('MonitorRead','list[MonitorRead]'):only_binary(expected)
        assert LEDGER['models'][name]==expected
    assert set(LEDGER['models'])-set(before['models'])=={'MonitorGroupRead','list[MonitorGroupRead]'}


def check_metadata(source):
    body=(ROOT/source['file']).read_bytes()
    assert hashlib.sha256(body).hexdigest()==source['sha256']
    symbol=source['symbol']
    if symbol==source['file']:
        assert (source['line'],source['end_line'])==(1,len(body.splitlines()))
        segment=body
    else:
        node=next(n for n in ast.parse(body).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==symbol.rsplit('.',1)[-1])
        assert (source['line'],source['end_line'])==(node.lineno,node.end_lineno)
        segment=ast.get_source_segment(body.decode(),node).encode()
    assert source['symbol_sha256']==hashlib.sha256(segment).hexdigest()


def test_actual_symbols_ranges_segment_hashes_and_active_references_are_exact():
    m=response_module();active={s for r in m.INVENTORY for s in r['sources']}
    assert not active.intersection(REVIEW['source_replacements'])
    assert {successor(k) for k in REVIEW['source_replacements'].values()}<=active
    for key in REVIEW['source_replacements'].values():
        current=successor(key)
        exact_metadata(current, m.SOURCE_EVIDENCE[current])


@pytest.mark.parametrize('field,value',[('line',0),('symbol','missing.actual_symbol'),('symbol_sha256','0'*64)])
def test_metadata_mutation_is_rejected(field,value):
    m=response_module()
    key=next(k for k in REVIEW['source_replacements'].values() if LEDGER['sources'][k]['symbol'].startswith('app.services.monitor.'))
    source=deepcopy(m.SOURCE_EVIDENCE[successor(key)])
    source[field]=value
    with pytest.raises((AssertionError,StopIteration)):check_metadata(source)


@pytest.mark.parametrize('file',FILES)
@pytest.mark.parametrize('damage',['byte-drift','deleted'])
def test_original_checker_rejects_each_reviewed_file(monkeypatch,records,file,damage):
    m=response_module();assert m.validate_response_sources(ROOT,records)==[]
    read=Path.read_bytes;isfile=Path.is_file
    if damage=='byte-drift':monkeypatch.setattr(Path,'read_bytes',lambda p:read(p)+b' ' if p==ROOT/file else read(p))
    else:monkeypatch.setattr(Path,'is_file',lambda p:False if p==ROOT/file else isfile(p))
    assert m.validate_response_sources(ROOT,records)==['source drift or missing source: '+file]


def test_original_unapproved_candidate_is_rejected_by_current_unchanged_checker(monkeypatch,records):
    original=history('app/api_response_v6_integration.json', 'e163b0ba7108f9e7eda580773985b8fa095c1518399c7fb92e1b6521faccac5d').decode()
    read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**kw:original if p==ROOT/'app/api_response_v6_integration.json' else read(p,*a,**kw))
    # The append-only v8 union requires the exact approved v7 input. The
    # original pre-v7 candidate now fails even earlier, never auto-rebased.
    with pytest.raises(ValueError,match='v8 source-union precondition drift'):
        response_module()


def test_frozen_object_list_schemas_and_all_operation_copies_remain_binary():
    from app.schemas.monitor import MonitorRead,MonitorGroupRead
    m=response_module();expected={name:TypeAdapter(dto).json_schema(mode='serialization') for name,dto in [
        ('MonitorRead',MonitorRead),('list[MonitorRead]',list[MonitorRead]),('MonitorGroupRead',MonitorGroupRead),('list[MonitorGroupRead]',list[MonitorGroupRead])]}
    assert {k:m.MODELS[k] for k in expected}==expected
    titles={'MonitorRead','MonitorGroupRead'};visited=[]
    def visit(value):
        if isinstance(value,dict):
            if isinstance(value.get('title'),str) and value['title'] in titles:
                assert value==expected[value['title']];visited.append(value['title'])
            for child in value.values():visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    # Historical v7 remains binary; later reviewed group status may be nullable.
    for name in titles:
        assert LEDGER['models'][name]['properties']['status']['enum']==['up','down']
    for d in m.DECLARATIONS.values():visit(d['responses'])
    assert titles<=set(visited)
    sample=dict(id=1,name='probe',node_id=7,type='ping',target='192.0.2.1',interval=60,timeout=2,status='down')
    validator=Draft202012Validator(expected['MonitorRead'])
    assert validator.is_valid(sample)
    assert not validator.is_valid(sample|{'status':'unknown'})
    assert not validator.is_valid(sample|{'status':'stale'})


def test_new_operation_still_rejected_and_inherited_incomplete_not_closed(records):
    m=response_module();assert m.validate_response_sources(ROOT,records)==[]
    assert m.validate_response_sources(ROOT,[*records,('GET','/future-v7','app.routers.monitor.list_monitors',None)])
    incomplete={k for k,v in m.DECLARATIONS.items() if v['status']=='incomplete'}
    assert incomplete=={('GET','/notifications'),('GET','/alerts/incidents/{incident_id}'),('GET','/notifications/{notification_id}')}
