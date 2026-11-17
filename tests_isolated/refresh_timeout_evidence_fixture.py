"""Literal v20 Agent/monitor bytes and exact pending v21 successor edges."""
import gzip
import hashlib
import json
from functools import lru_cache
from test_api_openapi_contract import ROOT
REVIEW = 'api_response_v21_refresh_timeout_review.json'
DIGEST = 'c1f31ea58a78205bcda43f1ff2c78e7df4278a4312c2b64b8297635b031fd73b'
MANIFEST_DIGEST = 'a2b39feca9627fd5798026f64c78f2795cac83b3aad8cd09fa73604102d731aa'

@lru_cache(maxsize=1)
def review():
    body = (ROOT/'app'/REVIEW).read_bytes()
    assert hashlib.sha256(body).hexdigest() == DIGEST
    return json.loads(body)

def frozen(file, digest):
    folder = ROOT/'tests_isolated/fixtures/api_response_refresh_timeout_history'
    manifest = (folder/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == MANIFEST_DIGEST
    row, = [r for r in json.loads(manifest)['files'] if (r['file'],r['sha256']) == (file,digest)]
    body = gzip.decompress((folder/row['fixture']).read_bytes())
    assert len(body) == row['size']
    assert hashlib.sha256(body).hexdigest() == digest
    assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == row['git_blob']
    return body

def parent_loader():
    folder = ROOT/'tests_isolated/fixtures/api_response_refresh_timeout_history'
    manifest = (folder/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == MANIFEST_DIGEST
    row, = [r for r in json.loads(manifest)['files'] if r['file']=='app/api_response_contracts.py']
    return frozen(row['file'],row['sha256'])

def historical_body(source):
    if source in review()['source_preconditions'].values():
        return frozen(source['file'],source['sha256'])
    from private_remediation_evidence_fixture import historical_body as current_body
    return current_body(source)

def successor(key):
    from private_remediation_evidence_fixture import successor as current_successor
    return current_successor(review()['source_replacements'].get(key,key))

def advance_row(row):
    from private_remediation_evidence_fixture import advance_row as current_row
    updates = [u for u in review()['operation_source_updates'] if (u['method'],u['path']) == (row['method'],row['path'])]
    if not updates: return current_row(row)
    update, = updates
    # Older callers may pass update records; all operation fields and the exact
    # source precondition are still checked, never merged with today's row.
    before = update['before_operation']
    assert all(row[k] == v for k,v in before.items() if k in row)
    assert (row['method'],row['path'],row['endpoint']) == (before['method'],before['path'],before['endpoint'])
    assert row['sources'] == update['before_sources']
    return current_row({**row,'sources':list(update['sources'])})

def source_maps(row,maps):
    from private_remediation_evidence_fixture import source_maps as current_maps
    if any((u['method'],u['path'],u['endpoint']) == (row['method'],row['path'],row['endpoint']) for u in review()['operation_source_updates']):
        maps = [*(maps if isinstance(maps,list) else [maps]),'app/'+REVIEW]
    return current_maps(row,maps)
