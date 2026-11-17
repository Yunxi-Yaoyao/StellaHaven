"""Literal v17 successor evidence. Works with Git absent in depth-one CI."""
import gzip
import hashlib
import json
from functools import lru_cache
from test_api_openapi_contract import ROOT

REVIEW='api_response_v17_nav_files_review.json'
DIGEST='dd1bd79485b43553522c66ef9123efa091fb660878b2a9e1eb1a8d3fb856ff75'
MANIFEST_DIGEST='f4f98599da6d2ad4f7380173573a1c1667d0aebf0346ef9c8d4619fe66ca31f4'


def review():
    body=(ROOT/'app'/REVIEW).read_bytes()
    assert hashlib.sha256(body).hexdigest()==DIGEST
    return _decode_review(body)


@lru_cache(maxsize=1)
def _decode_review(body):
    # Digest is rechecked before this immutable parse cache on every call.
    return json.loads(body)


def history_rows():
    folder=ROOT/'tests_isolated/fixtures/api_response_nav_files_history'
    manifest=(folder/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest()==MANIFEST_DIGEST
    rows=json.loads(manifest)
    assert len(rows)==len({(r['commit'],r['file']) for r in rows})
    return folder,rows


def frozen(file,digest):
    folder,rows=history_rows()
    row,=[r for r in rows if r['file']==file and r['sha256']==digest]
    body=gzip.decompress((folder/row['fixture']).read_bytes())
    assert len(body)==row['size']
    assert hashlib.sha256(body).hexdigest()==digest
    assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()==row['git_blob']
    return body


def historical_body(source):
    """Only an explicitly retired v17 edge may select historical bytes."""
    r=review()
    if source in r['source_preconditions'].values():
        return frozen(source['file'],source['sha256'])
    from unified_files_evidence_fixture import historical_body as unified_history
    return unified_history(source)


def advance_row(row):
    """Exact old endpoint/before_sources comparison, never a subset union."""
    r=review();key=row['method'],row['path']
    updates=[v for v in r['operation_source_updates'] if (v['method'],v['path'])==key]
    from unified_files_evidence_fixture import advance_row as advance_unified
    if not updates:return advance_unified(row)
    update,=updates
    assert row['endpoint']==update['endpoint']
    assert row['sources']==update['before_sources']
    return advance_unified({**row,'sources':list(update['sources'])})


def current_agent():
    r=review();artifact=r['agent_artifacts']
    from unified_files_evidence_fixture import frozen as unified_frozen
    body=unified_frozen('agent/stella_agent.py',artifact['current']['sha256'])
    assert len(body)==artifact['current']['size']==233494
    assert hashlib.sha256(body).hexdigest()==artifact['current']['sha256']=='728b859c92039c67a23243b87f91ffda5789cf2236120d1ead9b52c9a9031126'
    previous=frozen('agent/stella_agent.py',artifact['previous']['sha256'])
    assert len(previous)==232703
    assert hashlib.sha256(previous).hexdigest()=='25bc5e8c4f8e6ec262b89118098ea6d7b796f0bf3e75d8b10bd9a0aab070208b'
    return body,previous
