"""Exact historical copy-cohort bytes and separately measured v23 successor.

No Git access: the retired sources remain literal hash-pinned fixtures in shallow CI.
The successor is capacity evidence, not a release/source approval.
"""
import gzip
import hashlib
import json
import math
from pathlib import Path

MANIFEST_SHA256 = '914c58958f3fa7b1eed2709803f8cb1202857d1a6af257a652ad46a3d5134ab3'
V23_SHA256 = '179a95e5cc73def47e2b7c7b79c97366c700bd1f8f2b5b227e5ce61020b30ed1'


def load():
    raw = Path(__file__).with_name('v23-capacity-timings.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256, 'successor timing manifest drift'
    data = json.loads(raw)
    assert data['approved_overlay_sha256'] == V23_SHA256
    for command, row in data['observations'].items():
        seconds = row['completed_seconds']
        assert type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0
        assert type(row['case_count']) is int and row['case_count'] > 0
        assert command in data['current_source_sha256']
    return data


DERIVATION_SHA256 = '1f29c6aa22d3c24609d511e60a6a9ec0dde535b51105fd99d6602688dbdb7266'


def load_derivation():
    raw = Path(__file__).with_name('derivation-capacity-timings.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == DERIVATION_SHA256, 'derivation manifest drift'
    data = json.loads(raw)
    assert data['predecessor_manifest_sha256'] == MANIFEST_SHA256
    for command, row in data['observations'].items():
        assert command in data['current_source_sha256']
        assert math.isfinite(row['completed_seconds']) and 0 < row['completed_seconds'] < row['before_seconds']
        assert type(row['case_count']) is int and row['case_count'] > 0
    return data


AUDIT_SOURCES_SHA256 = 'b1923999499c5d21bdfe366f63406ee5985b160244ae35b170159336521a8726'


def load_audit():
    raw = Path(__file__).with_name('servers-audit-capacity-sources.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == AUDIT_SOURCES_SHA256, 'audit capacity source manifest drift'
    data = json.loads(raw)
    assert data['predecessor_manifest_sha256'] == DERIVATION_SHA256
    assert data['approved_overlay_sha256'] == 'fea8cfe9e08568d9ea62706da4172444b0c3ee601d19e89ab244fc1b5b14bc57'
    assert data['release_approval'] is False
    for command, row in data['observations'].items():
        assert command in data['current_source_sha256']
        assert data['current_source_sha256'][command] == row['source_sha256'], command
        assert row['retained_completed_seconds']
        assert all(type(s) in (int, float) and math.isfinite(s) and s > 0
                   for s in row['retained_completed_seconds'])
        assert row['completed_seconds'] == max(row['retained_completed_seconds'])
        assert type(row['cases']) is int and row['cases'] > 0
        cases = row['cases_json']
        assert len(cases) == row['cases'] and len(cases) == len({tuple(case) for case in cases})
        assert hashlib.sha256(json.dumps(cases).encode()).hexdigest() == row['cases_sha256']
        for kind in ('log', 'xml'):
            assert data['current_source_sha256'][row[kind]] == row[kind + '_sha256']
    return data


def derivation_source(root, path):
    """Literal predecessor bytes; never count current sources as old timings."""
    row = load_audit()['retired_sources'].get(path)
    if row is None:
        body = (root/path).read_bytes()
    else:
        body = gzip.decompress((root/row['fixture']).read_bytes())
        assert len(body) == row['size'] and hashlib.sha256(body).hexdigest() == row['sha256'], path
        assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == row['git_blob'], path
    assert hashlib.sha256(body).hexdigest() == load_derivation()['current_source_sha256'][path], path
    return body


def apply_audit(estimates):
    data = load_audit()
    for command, row in data['observations'].items():
        completed = row['completed_seconds']
        estimates[command] = max(estimates.get(command, 0), math.ceil(1.20 * completed + 5))
    return data


def v23_source(root, path):
    row = load_derivation()['retired_v23_sources'].get(path)
    if row is None:
        body = derivation_source(root, path)
    else:
        body = gzip.decompress((root/row['fixture']).read_bytes())
        assert len(body) == row['size'], path
        assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == row['git_blob'], path
        assert hashlib.sha256(body).hexdigest() == row['sha256'], path
    assert hashlib.sha256(body).hexdigest() == load()['current_source_sha256'][path], path
    return body


def validate_sources(root):
    data = load()
    optimized = load_derivation()
    audit = load_audit()
    for path, digest in audit['current_source_sha256'].items():
        assert hashlib.sha256((root/path).read_bytes()).hexdigest() == digest, path
    import xml.etree.ElementTree as ET
    for command, row in audit['observations'].items():
        cases = list(ET.parse(root/row['xml']).iter('testcase'))
        assert [[case.get('classname'), case.get('name')] for case in cases] == row['cases_json'], command
        assert all(not any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
                   for case in cases), command
    origin = Path(__file__).resolve().parents[2]
    for path in optimized['current_source_sha256']:
        derivation_source(origin, path)
    # Frozen source provenance is independently bound, not relabelled current.
    for path in data['current_source_sha256']:
        v23_source(origin, path)
    assert data['current_source_sha256']['app/api_response_v23_final_offload_review.json'] == V23_SHA256
    return data


def apply_derivation(estimates):
    data = load_derivation()
    # Only the fully replayed changed cohort retires its predecessor floors.
    for command in data['modeled_replacements']:
        row = data['observations'][command]
        estimates[command] = math.ceil(1.20*row['completed_seconds']+5)
    return data


def historical_source(root, path):
    data = load()
    row = data['historical_sources'].get(path)
    if row is None:
        body = v23_source(root, path)
        frozen = json.loads((root/'deploy/ci/copy-capacity-timings.json').read_text())
        digest = frozen['changed_source_sha256'][path]
    else:
        body = gzip.decompress((root/row['fixture']).read_bytes())
        digest = row['historical_sha256']
        assert len(body) == row['size'], path
        assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == row['git_blob'], path
    assert hashlib.sha256(body).hexdigest() == digest, path
    return body


def apply(estimates):
    """Retain the larger prior completed weight; never restore pre-clone costs."""
    data = load()
    for command, row in data['observations'].items():
        estimates[command] = max(estimates.get(command, 10), math.ceil(1.20*row['completed_seconds']+5))
    return data
