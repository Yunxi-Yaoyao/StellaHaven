"""Documentation snapshot must come from isolated runtime and exact inventory."""
import copy
import difflib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
def test_export_has_runtime_request_models_and_inventory_parity(tmp_path):
    output=tmp_path/'api.json'
    result=subprocess.run([sys.executable,str(ROOT/'tools/export_documentation_api.py'),'--output',str(output)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    doc=json.loads(output.read_text())
    assert doc['provenance']['kind']=='isolated-runtime-openapi'
    assert doc['provenance']['lifespan_started'] is False
    assert doc['provenance']['network_calls']==0
    assert doc['coverage']['missing']==[] and doc['coverage']['extra']==[]
    assert doc['schema']['paths']['/auth/login']['post']['requestBody']
    assert doc['schema']['paths']['/operations/backups/config']['patch']['requestBody']
    assert doc['websockets']
    assert doc['coverage']['http_operations']==len(doc['operations'])
    frozen=json.loads((ROOT/'frontend/src/modules/documentation/api.generated.json').read_text())
    # Keep complete structural equality, but do not ask pytest to render an
    # ndiff of this multi-MB document (CI enables that even with -q).
    schema_matches = doc['schema']==frozen['schema']
    assert schema_matches, 'Regenerate documentation snapshot: runtime schema changed'
    operations_match = doc['operations']==frozen['operations']
    assert operations_match, 'Regenerate documentation snapshot: runtime operations changed'
    websockets_match = doc['websockets']==frozen['websockets']
    assert websockets_match, 'Regenerate documentation snapshot: runtime websockets changed'


@pytest.mark.parametrize('field', ['schema', 'operations', 'websockets'])
def test_snapshot_drift_fails_without_ci_rich_diff(tmp_path, monkeypatch, field):
    """Full nested comparisons must fail without pytest's CI-only ndiff cost."""
    # Only the diagnostic unit fixture is small; the original test above still
    # exports and compares every field of the actual runtime document.
    frozen = {
        'provenance': {'kind': 'isolated-runtime-openapi', 'lifespan_started': False, 'network_calls': 0},
        'coverage': {'missing': [], 'extra': [], 'http_operations': 1},
        'schema': {'paths': {
            '/auth/login': {'post': {'requestBody': {'required': True}}},
            '/operations/backups/config': {'patch': {'requestBody': {'required': True}}},
        }},
        'operations': [{'method': 'POST', 'path': '/auth/login', 'endpoint': 'fixture.login'}],
        'websockets': [{'path': '/ws', 'source': 'fixture.py', 'handler': 'fixture_ws'}],
    }
    runtime = copy.deepcopy(frozen)
    if field == 'schema':
        runtime[field]['paths']['/auth/login']['post']['requestBody']['x-drift'] = True
    elif field == 'operations':
        runtime[field][0]['endpoint'] += '.drift'
    else:
        runtime[field][0]['handler'] += '_drift'
    snapshot = tmp_path/'frontend/src/modules/documentation/api.generated.json'
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(json.dumps(frozen))

    def export_fixture(argv, **kwargs):
        Path(argv[-1]).write_text(json.dumps(runtime))
        return subprocess.CompletedProcess(argv, 0, stdout='', stderr='')

    rich_diffs = []
    def forbidden_diff(*args, **kwargs):
        rich_diffs.append(True)
        raise RuntimeError('Giant snapshot diffs must not run')

    monkeypatch.setenv('CI', 'true')
    monkeypatch.setattr(subprocess, 'run', export_fixture)
    monkeypatch.setattr(difflib, 'ndiff', forbidden_diff)
    monkeypatch.setitem(globals(), 'ROOT', tmp_path)
    with pytest.raises(AssertionError) as caught:
        test_export_has_runtime_request_models_and_inventory_parity(tmp_path)
    assert not rich_diffs
    assert 'Regenerate documentation snapshot: runtime ' + field + ' changed' in str(caught.value)
    assert len(str(caught.value)) < 256
