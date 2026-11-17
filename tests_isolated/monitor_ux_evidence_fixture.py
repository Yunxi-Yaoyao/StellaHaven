"""Literal pre-merge source, not a hash-refresh fallback."""
import ast
import gzip
import hashlib
import json
from test_api_openapi_contract import ROOT

REVIEW = 'api_response_v16_monitor_ux_review.json'
DIGEST = 'a4034ef41bf26506485b59eebc845d1b4f5b0e1141ece576d7da4bf3606bea18'

def review():
    body = (ROOT/'app'/REVIEW).read_bytes()
    assert hashlib.sha256(body).hexdigest() == DIGEST
    return json.loads(body)

def parent_bytes(file):
    folder = ROOT/'tests_isolated/fixtures/api_response_monitor_ux_history'
    manifest = (folder/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == '4f9669ef7424f51dc594d1ccdd470a2d5434731028e9d847f7bea7a20f3393a3'
    row, = [r for r in json.loads(manifest) if r['file'] == file]
    body = gzip.decompress((folder/row['fixture']).read_bytes())
    assert len(body) == row['size']
    assert hashlib.sha256(body).hexdigest() == row['sha256']
    assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == row['git_blob']
    return body

def assert_only_approved_additions():
    r = review()
    for file, new_names in [('app/routers/monitor.py', {'create_monitor_batch','monitor_batch_receipt'}),
                            ('app/schemas/monitor.py', {'MonitorBatchCreate','MonitorBatchReceipt'})]:
        before = parent_bytes(file)
        whole, = [s for s in r['sources'].values() if s['symbol'] == file]
        from unified_files_evidence_fixture import historical_body
        after = historical_body(whole)
        assert hashlib.sha256(after).hexdigest() == whole['sha256']
        old = ast.parse(before); new = ast.parse(after)
        removed = []
        for node in new.body:
            if isinstance(node, (ast.FunctionDef,ast.ClassDef)) and node.name in new_names:
                removed.append(node)
            elif (file == 'app/routers/monitor.py' and isinstance(node,ast.ImportFrom)
                  and node.module == 'app.schemas.monitor'
                  and [a.name for a in node.names] == ['MonitorBatchCreate','MonitorBatchReceipt']):
                removed.append(node)
        assert len(removed) == (3 if file == 'app/routers/monitor.py' else 2)
        new.body = [n for n in new.body if n not in removed]
        assert ast.dump(new) == ast.dump(old)
        # Exact bytes outside those additions must match, not just an AST subset.
        lines = after.splitlines(keepends=True)
        for node in sorted(removed,key=lambda n:n.lineno,reverse=True):
            start = min([node.lineno]+[d.lineno for d in getattr(node,'decorator_list',[])])-1
            stop = node.end_lineno
            while stop < len(lines) and not lines[stop].strip():
                stop += 1
            del lines[start:stop]
        assert b''.join(lines) == before
