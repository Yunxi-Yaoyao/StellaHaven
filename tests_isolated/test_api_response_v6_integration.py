"""Append-only v6 source/DTO union: offline original gate, no application state."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_api_openapi_contract import ROOT, static_inventory
from test_api_response_contract import response_module
from api_response_evidence_fixture import (reviews, frozen, successor, current_handler,
                                           replay_v6_rows, check_metadata)

OVERLAY = json.loads((ROOT / 'app/api_response_v6_integration.json').read_text())
AGENT = json.loads((ROOT / 'app/api_response_ipv6_udp_source_review.json').read_text())
V8 = json.loads((ROOT / 'app/api_response_v8_review.json').read_text())
CHANGED_FILES = sorted({s['file'] for s in OVERLAY['sources'].values()
                        if s['file'] not in {'app/api_response_contracts.py', 'app/openapi_contract.py'}} |
                       {s['file'] for s in AGENT['sources'].values()})


@pytest.fixture(scope='module')
def mounted_records():
    return static_inventory()[0]


def test_history_provenance_and_current_loader_are_distinct():
    for file, digest in OVERLAY['historical_ledgers'].items():
        assert hashlib.sha256((ROOT / file).read_bytes()).hexdigest() == digest
    assert OVERLAY['provenance']['auth']['commit'] == 'e07f5989cdc569283c60747e6836965df6edbaf2'
    assert OVERLAY['provenance']['websites']['commit'] == '1d7d992616696026e5c639a49a5164cfffefb512'
    assert OVERLAY['provenance']['monitors']['commit'] == '819e0a375048e78c686027153979e86036177652'
    assert AGENT['provenance']['commit'] == '1c703528fc33b0877aac11c03991aa37cd02efa9'
    assert OVERLAY['auth_update_count'] == 90
    assert OVERLAY['loader_independent_review_pending'] is True
    assert OVERLAY['release_approval'] is AGENT['release_approval'] is False
    # V6/V8 loaders are historical receipts, not today's append-only loader.
    reviews()  # Independently pinned approved layers; no hash refresh.
    frozen('app/api_response_contracts.py', OVERLAY['loader_sha256'])
    frozen('app/api_response_contracts.py', V8['loader_sha256'])
    from test_api_response_ci167_evidence import history as ci167_history
    prior_loader = '80ba3f4dec6e164e129946d93b373e41ff036e62a83ecab3ecdc3dafe99a259e'
    assert hashlib.sha256(ci167_history()['app/api_response_contracts.py', prior_loader]).hexdigest() == prior_loader
    from api_response_evidence_fixture import rollout_parent_loader
    assert hashlib.sha256(rollout_parent_loader()).hexdigest() == 'b60ddbb1b307a3b64982538bd1902466d92179708303e9dc4c6611f9ec84dfc1'
    from monitor_ux_evidence_fixture import parent_bytes as ux_parent
    assert hashlib.sha256(ux_parent('app/api_response_contracts.py')).hexdigest() == 'ccaa3966eb695d694ab7cbc1dce253329b65a169c3f079ac9a4dcdae0c099cd1'
    from nav_files_evidence_fixture import frozen as navfiles_frozen
    assert hashlib.sha256(navfiles_frozen('app/api_response_contracts.py','77f42446db3fccabe18f6bd96abdc03f3614725b1a8b8c87ba7f6c16dd87aa6c')).hexdigest() == '77f42446db3fccabe18f6bd96abdc03f3614725b1a8b8c87ba7f6c16dd87aa6c'
    # Keep V17's literal loader approval; V18 is a separate exact current pin.
    import gzip
    history = ROOT/'tests_isolated/fixtures/api_response_nav_files_validation_history'
    prior = gzip.decompress((history/'fda8d002c00b0521bb79cfea9013cce81dc34e55aaa310ed7acffc5c61af6957.py.gz').read_bytes())
    assert len(prior) == 90515
    assert hashlib.sha256(prior).hexdigest() == 'fda8d002c00b0521bb79cfea9013cce81dc34e55aaa310ed7acffc5c61af6957'
    assert hashlib.sha1(b'blob '+str(len(prior)).encode()+b'\0'+prior).hexdigest() == '41cb95708e040d701693484ec8d343a4d6c89a3d'
    from unified_files_evidence_fixture import frozen as unified_frozen
    assert hashlib.sha256(unified_frozen('app/api_response_contracts.py','271d5076328641598037c02d196392c5f23e17ce3b85ab7557999ac10b1f95df')).hexdigest() == '271d5076328641598037c02d196392c5f23e17ce3b85ab7557999ac10b1f95df'
    from fnos_policy_evidence_fixture import parent_loader
    assert hashlib.sha256(parent_loader()).hexdigest() == '7ccbcfc50d5462d3bdb193dd97152f47638465c8748ff527ea02f77e80ba2b48'
    from refresh_timeout_evidence_fixture import parent_loader as refresh_parent_loader
    assert hashlib.sha256(refresh_parent_loader()).hexdigest() == '2e9351eb63ae264409692151a6969c9b2a2a4a015b4a8051972954f839ca3e8f'
    from private_remediation_evidence_fixture import parent_loader as private_parent_loader
    assert hashlib.sha256(private_parent_loader()).hexdigest() == '73164f9ab7ae2a76cce0d500b6a4ff7b626996a923307befe1bbb7980307bfc2'
    from private_remediation_evidence_fixture import v22_loader, final_review
    literal_v22 = v22_loader()
    assert hashlib.sha256(literal_v22).hexdigest() == 'b45e85594572f6753acb8a95ceaa195ec6d5e4f10f405e759e434ce48bf2134b'
    assert (ROOT / 'app/api_response_contracts.py').read_bytes() != literal_v22
    current = response_module()
    assert current._V23_REVIEW == final_review()
    assert current.validate_response_sources(ROOT, static_inventory()[0]) == []
    assert not (ROOT / 'app/api_response_ping_source_review.json').exists()
    assert OVERLAY['shared_file_reconciliation']['app/routers/monitor.py']['conflict_free']
    assert OVERLAY['shared_file_reconciliation']['app/schemas/monitor.py']['conflict_free']


@pytest.mark.parametrize('file', CHANGED_FILES)
def test_original_source_gate_rejects_per_file_byte_drift(monkeypatch, file, mounted_records):
    """Intercept the actual file reader: no product or scratch source mutation."""
    module = response_module()
    records = mounted_records
    assert module.validate_response_sources(ROOT, records) == []
    read = Path.read_bytes
    def altered(path):
        body = read(path)
        return body + b' ' if path == ROOT / file else body
    monkeypatch.setattr(Path, 'read_bytes', altered)
    assert module.validate_response_sources(ROOT, records) == ['source drift or missing source: ' + file]


def test_deleted_password_helpers_fail_if_reintroduced_and_logout_keeps_audit():
    module = response_module()
    removed = set(OVERLAY['removed_active_symbols'])
    assert len(removed) == 4
    assert not any(removed.intersection(row['sources']) for row in module.INVENTORY)
    logout = next(row for row in module.INVENTORY if row['endpoint'] == 'app.routers.auth.logout')
    assert {'app.services.backup_health.record_change', 'app.services.backup_health._audit_entries'} <= set(logout['sources'])
    assert 'app.services.admin_security.lock' not in logout['sources']
    for name in ('update_security', 'change_management_password', 'admin_setup', 'admin_unlock', 'admin_lock'):
        record = next(row for row in module.INVENTORY if row['endpoint'] == 'app.routers.auth.' + name)
        expected = replay_v6_rows()[record['method'], record['path']]
        assert record['endpoint'] == expected['endpoint']
        assert record['sources'] == expected['sources']
        assert {successor(s) for s in ('app.routers.auth.current_user',
                'app.services.admin_security.require_owner',
                'app.services.admin_security.management_password_retired')} <= set(record['sources'])
        declaration = module.DECLARATIONS[record['method'], record['path']]
        assert '200' not in declaration['responses']
        assert {'401', '403', '410'} <= set(declaration['responses'])
    # An old valid-looking helper record cannot make the deleted code approved.
    logout['sources'].append(sorted(removed)[0])
    assert module.validate_response_sources(ROOT, static_inventory()[0]) == [
        'source drift or missing source: app/services/admin_security.py']


def test_changed_handler_evidence_and_unchanged_closure_remain_exact():
    module = response_module()
    for endpoint, key in OVERLAY['handler_source_replacements'].items():
        key = current_handler(endpoint, key)
        source = module.SOURCE_EVIDENCE[key]
        text = (ROOT / source['file']).read_bytes()
        assert hashlib.sha256(text).hexdigest() == source['sha256']
        node = next(n for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == endpoint.rsplit('.', 1)[-1])
        assert (source['line'], source['end_line']) == (node.lineno, node.end_lineno)
    # Compare against frozen pre-union hashes, not an expectation derived from
    # the same current bytes. Newly added reviewed files are checked above.
    changed = set(CHANGED_FILES) | {f for layer in reviews()[1:]
                for f in [*layer.get('source_files', []), *layer.get('source_file_hashes', {})]}
    changed |= {source['file'] for layer in reviews()[1:] for source in layer['sources'].values()}
    for file, digest in OVERLAY['closure_before'].items():
        if file not in changed:
            assert hashlib.sha256((ROOT / file).read_bytes()).hexdigest() == digest


def test_union_symbol_metadata_matches_current_reviewed_files():
    """Resolve only approved successors; dormant records use literal old blobs."""
    module = response_module()
    for key, historical in OVERLAY['sources'].items():
        assert module.SOURCE_EVIDENCE[key] == historical, key
        current = successor(key)
        source = module.SOURCE_EVIDENCE[current]
        active = any(current in row['sources'] for row in module.INVENTORY)
        current_bytes = (ROOT/source['file']).read_bytes()
        body = (None if active or hashlib.sha256(current_bytes).hexdigest() == source['sha256']
                else frozen(source['file'], source['sha256']))
        check_metadata(current, source, body)


def test_object_list_success_and_nested_website_check_copies_agree():
    from pydantic import TypeAdapter
    from app.schemas.monitor import MonitorRead
    from app.public_website import PublicModule, PublicWebsiteCheck, PublicWebsiteResult
    module = response_module()
    expected = {'MonitorRead': TypeAdapter(MonitorRead).json_schema(mode='serialization'),
                'PublicModule': TypeAdapter(PublicModule).json_schema(mode='serialization'),
                'PublicWebsiteCheck': TypeAdapter(PublicWebsiteCheck).json_schema(mode='serialization'),
                'PublicWebsiteResult': TypeAdapter(PublicWebsiteResult).json_schema(mode='serialization')}
    assert module.MODELS['MonitorRead'] == expected['MonitorRead']
    assert module.MODELS['list[MonitorRead]'] == TypeAdapter(list[MonitorRead]).json_schema(mode='serialization')
    assert module.MODELS['PublicModule'] == expected['PublicModule']
    assert module.MODELS['list[PublicModule]'] == TypeAdapter(list[PublicModule]).json_schema(mode='serialization')
    assert module.WEBSITE_CHECK == expected['PublicWebsiteCheck']
    # Inline definitions omit $defs; verify at their own shape level too.
    def visit(value):
        if isinstance(value, dict):
            title = value.get('title')
            if isinstance(title, str) and title in expected:
                assert {k: v for k, v in value.items() if k != '$defs'} == {
                    k: v for k, v in expected[title].items() if k != '$defs'}, title
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    for declaration in module.DECLARATIONS.values(): visit(declaration['responses'])
    for model in module.MODELS.values(): visit(model)
    assert {'invalid_target', 'unsupported', 'scope_pending'} <= set(expected['MonitorRead']['properties']['status_reason']['enum'])
    for name in ('NodeRead excluding token', 'NodeDetail', 'AgentConfig', 'MonitorGroupRead'):
        assert 'status_reason' not in module.MODELS[name].get('properties', {})


def test_unknown_public_dto_fields_are_rejected_not_schema_widened():
    from app.public_website import public_module
    module = response_module()
    value = public_module({'id':'fixture', 'unknown_internal':'not public'})
    schema = module.MODELS['PublicModule']
    validator = Draft202012Validator(schema)
    validator.validate(value)
    assert 'unknown_internal' not in value
    assert not validator.is_valid({**value, 'unknown_internal':'no'})
    assert not validator.is_valid({**value, 'name':'x' * 101})
    assert not validator.is_valid({**value, 'address_mode':'wildcard'})
    assert not validator.is_valid({**value, 'alternate_address':123})


@pytest.mark.parametrize('damage', ['digest', 'missing', 'bytes'])
def test_frozen_history_is_required_and_tamper_fails_closed(monkeypatch, damage):
    from api_response_evidence_fixture import HISTORY
    digest = OVERLAY['loader_sha256']
    target = HISTORY/(digest+'.gz')
    original = Path.read_bytes
    def altered(path):
        if path == target:
            if damage == 'missing':
                raise FileNotFoundError(path)
            if damage == 'bytes':
                import gzip
                return gzip.compress(b'not the approved blob', mtime=0)
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', altered)
    with pytest.raises((AssertionError, FileNotFoundError, ValueError)):
        frozen('app/api_response_contracts.py', '0'*64 if damage == 'digest' else digest)


@pytest.mark.parametrize('damage', ['endpoint', 'before_sources', 'order'])
def test_approved_successor_replay_rejects_edge_damage(damage):
    layers = deepcopy(reviews())
    if damage == 'order':
        # V18 only touches new Nav/Files rows, so it commutes within V6's
        # historical subset. Reverse two explicitly dependent V6 successors.
        from api_response_evidence_fixture import REVIEW_DIGESTS
        names = list(REVIEW_DIGESTS)
        left = names.index('api_response_v15_agent_rollout_review.json')
        right = names.index('api_response_v16_monitor_ux_review.json')
        assert left < right
        layers[left], layers[right] = layers[right], layers[left]
    else:
        row = next(r for r in layers[2]['operation_source_updates']
                   if (r['method'],r['path']) in replay_v6_rows())
        row[damage] = 'wrong.endpoint' if damage == 'endpoint' else ['not-approved']
    with pytest.raises(AssertionError):
        replay_v6_rows(layers)


def test_exact_rows_and_new_operation_gate_still_fail_closed():
    module = response_module()
    records = static_inventory()[0]
    assert module.validate_response_sources(ROOT, records) == []
    future = [*records, ('GET', '/future-v6', 'app.routers.auth.me', None)]
    assert any('unclassified/new' in error for error in module.validate_response_sources(ROOT, future))
    assert module.response_contract_errors({}, 'GET', '/future-v6', 'app.routers.auth.me') == [
        'unclassified response contract (missing or stale exact operation review)']
    # Original three notification gaps remain exactly incomplete, not normalized.
    incomplete = {key: value for key, value in module.DECLARATIONS.items() if value['status'] == 'incomplete'}
    assert len(incomplete) == 3
    assert all('notification' in (value['endpoint'] + value['reason']).lower() for value in incomplete.values())
