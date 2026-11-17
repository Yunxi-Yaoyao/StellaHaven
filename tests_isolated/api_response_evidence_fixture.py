"""Owning-test evidence boundaries, not a product loader or approval generator."""
import ast
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

from test_api_openapi_contract import ROOT

HISTORY = Path(__file__).parent/'fixtures/api_response_history'
REVIEW_DIGESTS = {
    'api_response_v6_integration.json': '0aade4e711b35fcf57d8a74c2f77b266de63814f773904dace3276b0a0a8132a',
    'api_response_ipv6_udp_source_review.json': 'd1c24506af35150b2b1363ae3dfb11356c31e373aeb0d0814a905eb4bba32ab7',
    'api_response_v8_review.json': '2f495dc620892fab91f21f7b777f71416d371d7284a41b9140e5d210a1b3ab9c',
    'api_response_v11_review.json': 'bac85446d66572cd654e821d60f68544006104bd926bbb8e14b9197ac2c422a3',
    'api_response_v12_final_review.json': '45b542418bb39357a842fb4947bf8afc315c57f2eb743362f31d9633d366ea14',
    'api_response_v12_notes_review.json': 'c30ca41baf23f811f78658e00e7175dfa06b081bafb3b1826cd64951751d88c3',
    'api_response_v12_installer_umask_review.json': '52b50bde470285a5f70dba07a93778bc5e45879b5482cb4b22bcf70c7d231cab',
    'api_response_v13_speedtest_duration_review.json': 'dd17f38ecfe03cb9aeec68da352bafeada3d1ec7a286af75884dd08c08d6ecd8',
    'api_response_v13_monitor404_review.json': '73ff3a13e0c3f106ac442ce9ceea27cfb47e2a50f7e1bf62dcdd2ad10d2b645f',
    'api_response_v13_source_metadata_review.json': '0f9d5694370840dcccf02807726070bacde0b3eb0a5162f275d28f6c508b0e39',
    'api_response_v14_ci167_review.json': 'b80cb43ac67552a54708f22741ceaeb2889de97a39bf6153e9fb119ad6b53c6b',
    'api_response_v15_agent_rollout_review.json': '23b2e8350b02b83760f732f27b76c19e12b86c976b7b8e4c8d4c5aa81d2f55be',
    'api_response_v16_monitor_ux_review.json': 'a4034ef41bf26506485b59eebc845d1b4f5b0e1141ece576d7da4bf3606bea18',
    'api_response_v17_nav_files_review.json': 'dd1bd79485b43553522c66ef9123efa091fb660878b2a9e1eb1a8d3fb856ff75',
    'api_response_v18_nav_files_validation_review.json': '6fd0076187200906416dcfb155e06cdc73e162b2afde7cf0f587e194d2e8a232',
    'api_response_v19_unified_files_review.json': '8beb2030ad77a5773bc43d2195337cdec9f7dc3ce0861a630383821bee2317a9',
    'api_response_v20_fnos_policy_review.json': '96c47ca8ec9f5dab1310346f8d057c59e12b2d5037e38513b62b4daf1663cbbd',
    'api_response_v21_refresh_timeout_review.json': 'c1f31ea58a78205bcda43f1ff2c78e7df4278a4312c2b64b8297635b031fd73b',
    'api_response_v22_private_remediation_review.json': 'd93542ae89b386a5325ec7ec8616f5e7f33d92aa66d2a40ac8f0a5df087d0b82',
    'api_response_v23_final_offload_review.json': '179a95e5cc73def47e2b7c7b79c97366c700bd1f8f2b5b227e5ce61020b30ed1',
    'api_response_v24_servers_audit_review.json': 'fea8cfe9e08568d9ea62706da4172444b0c3ee601d19e89ab244fc1b5b14bc57',
}


def named_reviews():
    """Bind immutable approvals to filenames, never mutable list positions."""
    result = {}
    for name, digest in REVIEW_DIGESTS.items():
        body = (ROOT/'app'/name).read_bytes()
        assert hashlib.sha256(body).hexdigest() == digest, name
        from evidence_exact_cache import json_body
        review = json_body(body)
        assert review['release_approval'] is False
        result[name] = review
    return result


def reviews():
    return list(named_reviews().values())


def frozen(file, digest):
    """Literal Git blobs, checked offline even in depth-one CI; no fallback."""
    manifest = (HISTORY/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == '8b65c6104d5040766e467fa78096b8f7c9c372c86b44b7b0f737f77e30001fb4'
    row, = [r for r in json.loads(manifest) if (r['file'], r['sha256']) == (file, digest)]
    body = gzip.decompress((HISTORY/row['fixture']).read_bytes())
    assert len(body) == row['size']
    assert hashlib.sha256(body).hexdigest() == digest, file
    header = b'blob '+str(len(body)).encode()+b'\0'
    assert hashlib.sha1(header+body).hexdigest() == row['git_blob'], file
    return body


def successor(symbol, layers=None):
    layers = reviews() if layers is None else layers
    first, *later = layers
    symbol = first.get('v7_binary_review', {}).get('source_replacements', {}).get(symbol, symbol)
    seen = {symbol}
    for layer in later:
        new = layer.get('source_replacements', {}).get(symbol, symbol)
        if new != symbol:
            assert new not in seen, 'cyclic source successor'
            seen.add(new)
            symbol = new
    return symbol


def replay_v6_rows(layers=None):
    """Replay literal endpoint/before_sources edges, never union today's sources."""
    first, *later = reviews() if layers is None else layers
    rows = {(r['method'], r['path']): deepcopy(r) for r in first['operation_source_updates']}
    for layer in later:
        # IPv6/UDP precedes V8 and uses an exact additions/replacements union.
        if 'source_additions' in layer and 'operation_source_updates' not in layer:
            for row in rows.values():
                row['sources'] = sorted({layer.get('source_replacements', {}).get(s, s)
                    for s in [*row['sources'], *layer['source_additions'].get(row['endpoint'], [])]})
        for update in layer.get('operation_source_updates', []):
            key = update['method'], update['path']
            if key not in rows:
                continue  # Outside the original v6 row set.
            assert rows[key]['endpoint'] == update['endpoint'], key
            assert rows[key]['sources'] == update['before_sources'], key
            rows[key]['sources'] = list(update['sources'])
    return rows


def current_handler(endpoint, original, layers=None):
    layers = reviews() if layers is None else layers
    key = original
    for layer in layers[1:]:
        key = layer.get('source_replacements', {}).get(key, key)
        key = layer.get('handler_source_replacements', {}).get(endpoint, key)
    return key


def rollout_parent_loader():
    """Literal pre-v15 loader, preserving its prior exact digest assertion."""
    folder = ROOT/'tests_isolated/fixtures/api_response_agent_rollout_history'
    manifest = (folder/'loader-manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == 'e4af3cecf77a5ca6f927c57a80d08a83e5cb4f67c6b37805d9412c373e8424a4'
    row = json.loads(manifest)
    body = gzip.decompress((folder/row['fixture']).read_bytes())
    assert len(body) == row['size']
    assert hashlib.sha256(body).hexdigest() == row['sha256']
    assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == row['git_blob']
    return body


def reviewed_body(source):
    """Retired evidence is read from exact literal source, never current bytes."""
    from private_remediation_evidence_fixture import final_review, historical_body as v23_body
    if source in final_review()['source_preconditions'].values():
        return v23_body(source)
    from private_remediation_evidence_fixture import review as v22_review, historical_body as v22_body
    if source in v22_review()['source_preconditions'].values():
        return v22_body(source)
    from nav_files_evidence_fixture import historical_body
    candidate = historical_body(source)
    if hashlib.sha256(candidate).hexdigest() == source['sha256']:
        return candidate
    from monitor_ux_evidence_fixture import parent_bytes as ux_parent
    if source['file'] in {'app/routers/monitor.py', 'app/schemas/monitor.py'}:
        body = ux_parent(source['file'])
        if hashlib.sha256(body).hexdigest() == source['sha256']:
            return body
    if (source['file'], source['sha256']) != ('app/routers/monitor.py',
            '3a9041dd6c30cd785f4bec464a27def52f0a0b5972bccacddc2dfdd8e50a25fe'):
        return (ROOT/source['file']).read_bytes()
    folder = ROOT/'tests_isolated/fixtures/api_response_agent_rollout_history'
    manifest = (folder/'manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == '37c5726569cf30ce5458c48f5887434479ca2f10817824e932107c060edc4485'
    row = json.loads(manifest)
    body = gzip.decompress((folder/row['fixture']).read_bytes())
    assert len(body) == row['size']
    assert hashlib.sha256(body).hexdigest() == row['sha256'] == source['sha256']
    assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == row['git_blob']
    return body


def check_metadata(symbol, source, body=None):
    """Hash plus exact AST ranges for live or explicitly frozen evidence."""
    body = (ROOT/source['file']).read_bytes() if body is None else body
    assert hashlib.sha256(body).hexdigest() == source['sha256'], symbol
    text = body.decode()
    name = source.get('symbol', symbol).split('@', 1)[0]
    if name == 'agent/install.sh:embedded.install':
        prefix, embedded = text.split("<<'STELLA_INSTANCE_INSTALLER'\n", 1)
        embedded = embedded.rsplit('\nSTELLA_INSTANCE_INSTALLER', 1)[0]
        tree_text = '\n' * (prefix.count('\n') + 1) + embedded
        from evidence_exact_cache import symbol_range
        coordinates = symbol_range(tree_text, ['install'], function_only=True)
        assert (source['line'], source['end_line']) == coordinates[:2], symbol
    elif ':' in name or name == source['file'] or name.endswith('.py'):
        assert 1 <= source['line'] <= source['end_line'] <= len(body.splitlines()), symbol
    else:
        prefix = source['file'].removesuffix('.py').replace('/', '.')+'.'
        parts = name.removeprefix(prefix).split('.')
        from evidence_exact_cache import symbol_range
        coordinates = symbol_range(text, parts)
        assert (source['line'], source['end_line']) == coordinates[:2], symbol

    # Legacy ledgers use several symbol-hash encodings (AST dump, decorated
    # source, and raw segment). Their owning gates retain those checks. This
    # original gate binds full-file SHA-256 plus exact symbol ranges only.
