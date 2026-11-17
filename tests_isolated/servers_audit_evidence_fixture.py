"""Exact v24 successors and literal pre-audit source evidence, offline only."""
import gzip
import hashlib
import json
from functools import lru_cache
from test_api_openapi_contract import ROOT
REVIEW='api_response_v24_servers_audit_review.json'
DIGEST='fea8cfe9e08568d9ea62706da4172444b0c3ee601d19e89ab244fc1b5b14bc57'
@lru_cache(maxsize=1)
def review():
    raw=(ROOT/'app'/REVIEW).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==DIGEST
    return json.loads(raw)
def historical_body(source):
    if source not in review()['source_preconditions'].values():return (ROOT/source['file']).read_bytes()
    return frozen(source['file'],source['sha256'])
def frozen(file,digest=None):
    folder=ROOT/'tests_isolated/fixtures/api_response_servers_audit_history'
    raw=(folder/'manifest.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='bb5a0bb28782942066179503a26c3681cd37247ef54de0aa9b20c05d8d8f6e87'
    row,=[r for r in json.loads(raw) if r['file']==file and (digest is None or r['sha256']==digest)]
    body=gzip.decompress((folder/row['fixture']).read_bytes())
    assert len(body)==row['size'] and hashlib.sha256(body).hexdigest()==row['sha256']
    return body
def successor(key):return review()['source_replacements'].get(key,key)
def advance_row(row):
    matches=[u for u in review()['operation_source_updates'] if (u['method'],u['path'])==(row['method'],row['path'])]
    if not matches:return row
    u,=matches
    assert row['endpoint']==u['endpoint'] and row['sources']==u['before_sources']
    return {**row,'sources':list(u['sources'])}
def source_maps(row,maps):
    if any((u['method'],u['path'])==(row['method'],row['path']) for u in review()['operation_source_updates']):
        return [*(maps if isinstance(maps,list) else [maps]),'app/'+REVIEW]
    return maps
