"""Exact pending v19 successor edges and literal predecessor source controls."""
import gzip
import hashlib
import json
from functools import lru_cache
from test_api_openapi_contract import ROOT
REVIEW='api_response_v19_unified_files_review.json'
DIGEST='8beb2030ad77a5773bc43d2195337cdec9f7dc3ce0861a630383821bee2317a9'
MANIFEST_DIGEST='c7e32f04cf1c477b699b683a453296760c62651e2c80dfd2034192edba8d9b7d'

def review():
    body=(ROOT/'app'/REVIEW).read_bytes()
    assert hashlib.sha256(body).hexdigest()==DIGEST
    return _decode(body)

@lru_cache(maxsize=1)
def _decode(body):return json.loads(body)

def frozen(file,digest):
    folder=ROOT/'tests_isolated/fixtures/api_response_unified_files_history'
    manifest=(folder/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest()==MANIFEST_DIGEST
    row,=[r for r in json.loads(manifest) if (r['file'],r['sha256'])==(file,digest)]
    body=gzip.decompress((folder/row['fixture']).read_bytes())
    assert len(body)==row['size']
    assert hashlib.sha256(body).hexdigest()==digest
    assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()==row['git_blob']
    return body

def historical_body(source):
    if source in review()['source_preconditions'].values():
        return frozen(source['file'],source['sha256'])
    from fnos_policy_evidence_fixture import historical_body as current_body
    return current_body(source)

def successor(key):
    from fnos_policy_evidence_fixture import successor as current_successor
    return current_successor(review()['source_replacements'].get(key,key))

def advance_row(row):
    from fnos_policy_evidence_fixture import advance_row as current_row
    updates=[u for u in review()['operation_source_updates'] if (u['method'],u['path'])==(row['method'],row['path'])]
    if not updates:return current_row(row)
    update,=updates
    assert row['endpoint']==update['endpoint']
    assert row['sources']==update['before_sources']
    return current_row({**row,'sources':list(update['sources'])})

def source_maps(row,maps):
    from fnos_policy_evidence_fixture import source_maps as current_maps
    if any((u['method'],u['path'],u['endpoint'])==(row['method'],row['path'],row['endpoint']) for u in review()['operation_source_updates']):
        maps = [*(maps if isinstance(maps,list) else [maps]),'app/'+REVIEW]
    return current_maps(row, maps)
