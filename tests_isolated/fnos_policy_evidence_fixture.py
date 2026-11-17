"""Literal v19 service bytes and exact v20 successor edges, offline/depth-one."""
import gzip
import hashlib
import json
from functools import lru_cache
from test_api_openapi_contract import ROOT
REVIEW = 'api_response_v20_fnos_policy_review.json'
DIGEST = '96c47ca8ec9f5dab1310346f8d057c59e12b2d5037e38513b62b4daf1663cbbd'

@lru_cache(maxsize=1)
def review():
    body = (ROOT/'app'/REVIEW).read_bytes()
    assert hashlib.sha256(body).hexdigest() == DIGEST
    return json.loads(body)

def parent_loader():
    folder = ROOT/'tests_isolated/fixtures/api_response_fnos_policy_history'
    manifest = (folder/'loader-manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == '1638380f7076e2c0b16cda0bb39566c366efe52d67ebb46137d2fa4e034d5f69'
    row = json.loads(manifest)
    body = gzip.decompress((folder/row['fixture']).read_bytes())
    assert len(body) == row['size']
    assert hashlib.sha256(body).hexdigest() == row['sha256']
    assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == row['git_blob']
    return body


def historical_body(source):
    if source not in review()['source_preconditions'].values():
        from refresh_timeout_evidence_fixture import historical_body as current_body
        return current_body(source)
    folder = ROOT/'tests_isolated/fixtures/api_response_fnos_policy_history'
    manifest = (folder/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == '7648cced186b0e7a201a79e775598ccd4b390b772dc2e981c070d44c3b0fd996'
    row = json.loads(manifest)
    assert (row['file'], row['sha256']) == (source['file'], source['sha256'])
    body = gzip.decompress((folder/row['fixture']).read_bytes())
    assert len(body) == row['size']
    assert hashlib.sha256(body).hexdigest() == row['sha256']
    assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == row['git_blob']
    return body

def successor(key):
    from refresh_timeout_evidence_fixture import successor as current_successor
    return current_successor(review()['source_replacements'].get(key,key))

def advance_row(row):
    from refresh_timeout_evidence_fixture import advance_row as current_row
    updates = [u for u in review()['operation_source_updates'] if (u['method'],u['path']) == (row['method'],row['path'])]
    if not updates: return current_row(row)
    update, = updates
    assert row == update['before_operation']
    assert row['sources'] == update['before_sources']
    return current_row(update['operation'])

def source_maps(row,maps):
    from refresh_timeout_evidence_fixture import source_maps as current_maps
    if any((u['method'],u['path'],u['endpoint']) == (row['method'],row['path'],row['endpoint']) for u in review()['operation_source_updates']):
        maps = [*(maps if isinstance(maps,list) else [maps]),'app/'+REVIEW]
    return current_maps(row,maps)
