"""Literal pre-v22 evidence and exact pending successor, no Git/runtime import."""
import gzip
import hashlib
import json
from functools import lru_cache
from test_api_openapi_contract import ROOT
REVIEW='api_response_v22_private_remediation_review.json'
DIGEST='d93542ae89b386a5325ec7ec8616f5e7f33d92aa66d2a40ac8f0a5df087d0b82'
MANIFEST_DIGEST='f48e978eb5bba5ddef3da1a19a82075387d26a1a7cbcf074032f9c4fd6052464'
@lru_cache(maxsize=1)
def review():
    body=(ROOT/'app'/REVIEW).read_bytes()
    assert hashlib.sha256(body).hexdigest()==DIGEST
    return json.loads(body)
def manifest():
    folder=ROOT/'tests_isolated/fixtures/api_response_private_remediation_history'
    body=(folder/'manifest.json').read_bytes()
    assert hashlib.sha256(body).hexdigest()==MANIFEST_DIGEST
    return folder,json.loads(body)
def frozen(file,digest):
    folder,m=manifest()
    row,=[r for r in m['files'] if (r['file'],r['sha256'])==(file,digest)]
    body=gzip.decompress((folder/row['fixture']).read_bytes())
    assert len(body)==row['size']
    assert hashlib.sha256(body).hexdigest()==digest
    assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()==row['git_blob']
    return body
def parent_loader():
    _,m=manifest();row,=[r for r in m['files'] if r['file']=='app/api_response_contracts.py']
    return frozen(row['file'],row['sha256'])
FINAL_REVIEW='api_response_v23_final_offload_review.json'
FINAL_DIGEST='179a95e5cc73def47e2b7c7b79c97366c700bd1f8f2b5b227e5ce61020b30ed1'
FINAL_MANIFEST_DIGEST='6c180ad4e0146416ff5800919e7ac4543864646c33034cf31db9ace1f6e419f0'
@lru_cache(maxsize=1)
def final_review():
    body=(ROOT/'app'/FINAL_REVIEW).read_bytes()
    assert hashlib.sha256(body).hexdigest()==FINAL_DIGEST
    return json.loads(body)
def final_manifest():
    folder=ROOT/'tests_isolated/fixtures/api_response_private_remediation_history/v23'
    body=(folder/'manifest.json').read_bytes()
    assert hashlib.sha256(body).hexdigest()==FINAL_MANIFEST_DIGEST
    data=json.loads(body)
    assert data['commit']=='22a55697cb83c41b4d7dd39e601fe1105d8b47f6'
    return folder,data
def final_frozen(file,digest):
    folder,m=final_manifest()
    row,=[r for r in m['files'] if (r['file'],r['sha256'])==(file,digest)]
    body=gzip.decompress((folder/row['fixture']).read_bytes())
    assert len(body)==row['size']
    assert hashlib.sha256(body).hexdigest()==digest
    assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()==row['git_blob']
    return body
def v22_loader():
    return final_frozen('app/api_response_contracts.py','b45e85594572f6753acb8a95ceaa195ec6d5e4f10f405e759e434ce48bf2134b')
def historical_body(source):
    if source in final_review()['source_preconditions'].values():
        return final_frozen(source['file'],source['sha256'])
    if source in review()['source_preconditions'].values():return frozen(source['file'],source['sha256'])
    from servers_audit_evidence_fixture import historical_body as audit_body
    return audit_body(source)
def final_successor(key):
    from servers_audit_evidence_fixture import successor as audit_successor
    return audit_successor(final_review()['source_replacements'].get(key,key))
def successor(key):return final_successor(review()['source_replacements'].get(key,key))
def final_advance_row(row):
    from servers_audit_evidence_fixture import advance_row as audit_row
    updates=[u for u in final_review()['operation_source_updates'] if (u['method'],u['path'])==(row['method'],row['path'])]
    if not updates:return audit_row(row)
    u,=updates;b=u['before_operation']
    assert all(row[k]==v for k,v in b.items() if k in row)
    assert (row['method'],row['path'],row['endpoint'])==(b['method'],b['path'],b['endpoint'])
    assert row['sources']==u['before_sources']
    return audit_row({**row,'sources':list(u['sources'])})
def advance_row(row,*,current=True):
    updates=[u for u in review()['operation_source_updates'] if (u['method'],u['path'])==(row['method'],row['path'])]
    if not updates:return final_advance_row(row) if current else row
    u,=updates;b=u['before_operation']
    assert all(row[k]==v for k,v in b.items() if k in row)
    assert (row['method'],row['path'],row['endpoint'])==(b['method'],b['path'],b['endpoint'])
    assert row['sources']==u['before_sources']
    result={**row,'sources':list(u['sources'])}
    return final_advance_row(result) if current else result
def final_source_maps(row,maps):
    from servers_audit_evidence_fixture import source_maps as audit_maps
    if any((u['method'],u['path'],u['endpoint'])==(row['method'],row['path'],row['endpoint']) for u in final_review()['operation_source_updates']):
        maps = [*(maps if isinstance(maps,list) else [maps]),'app/'+FINAL_REVIEW]
    return audit_maps(row,maps)
def source_maps(row,maps):
    if any((u['method'],u['path'],u['endpoint'])==(row['method'],row['path'],row['endpoint']) for u in review()['operation_source_updates']):
        maps=[*(maps if isinstance(maps,list) else [maps]),'app/'+REVIEW]
    return final_source_maps(row,maps)
