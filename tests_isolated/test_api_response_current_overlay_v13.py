"""Current approved overlays: portable, offline fail-closed regression controls."""
from copy import deepcopy
from pathlib import Path

import pytest

from test_api_openapi_contract import ROOT, static_inventory
from test_api_response_contract import response_module
from test_api_response_v11_integration import (
    REVIEW_DIGESTS, approved_reviews, apply_review, assert_identity_evidence, check_metadata,
)

# Explicit acceptance closure; do not derive the negative-control inventory from
# whatever files the candidate happens to declare after an accidental omission.
OVERLAY_FILES = (
    'agent/install.sh', 'agent/stella_agent.py',
    'app/routers/auth.py', 'app/routers/monitor.py', 'app/routers/task.py',
    'app/schemas/monitor.py', 'app/schemas/public_task.py',
    'app/services/admin_security.py', 'app/services/host.py',
    'app/services/html_note_conversion.py', 'app/services/node.py', 'app/services/task.py',
    'app/repositories/node.py', 'app/routers/auth_provider.py', 'app/routers/config.py',
    'app/services/integrations_sessions.py', 'app/services/oidc.py', 'app/services/web_project_runtime.py',
    'app/services/entry_registry.py', 'app/monitor_targets.py',
    'app/repositories/workspace.py', 'app/services/notes_templates.py',
    'app/services/entry_monitoring.py', 'app/services/monitor.py', 'app/services/monitor_groups.py',
    'app/repositories/config.py', 'app/services/monitor_batches.py', 'app/services/entry_monitor_groups.py',
    'agent/node_files.py', 'agent/node_files_delivery.py', 'agent/node_files_lifecycle.py',
    'alembic/versions/cf20261023nav_native_navigation.py', 'alembic/versions/nf20261023_node_files.py',
    'app/models/native_nav.py', 'app/models/node_file.py', 'app/routers/homebg.py',
    'app/routers/native_nav.py', 'app/routers/node_files.py', 'app/routers/node_files_release.py',
    'app/schemas/native_nav.py', 'app/schemas/node_file.py', 'app/services/backup_preferences.py',
    'app/services/backup_projection.py', 'app/services/homebg_references.py', 'app/services/integrations.py',
    'app/services/native_nav_backup.py', 'app/services/native_nav_budget.py', 'app/services/native_nav_import.py',
    'app/services/native_nav_limits.py', 'app/services/native_nav_package.py', 'app/services/node_files.py',
    'frontend/src/stores/navigation.ts', 'main.py',
    'app/routers/integrations.py', 'app/routers/website_settings.py', 'app/routers/integrations_host.py',
    'app/services/access_entries.py', 'app/services/ha_readiness.py',
    'app/services/openlist_compat.py', 'app/services/website_settings.py',
    'frontend/src/api/websiteSettings.ts', 'frontend/src/modules/settings/WebsiteSettings.vue',
    'frontend/src/shell/ExternalModuleCache.vue',
)


@pytest.fixture(scope='module')
def current():
    module = response_module()
    records = static_inventory()[0]
    assert module.validate_response_sources(ROOT, records) == []
    return module, records


def test_overlay_negative_inventory_covers_every_actual_current_approved_file(current):
    module, _ = current
    active = {key for row in module.INVENTORY for key in row['sources']}
    sources = {key: source for review in approved_reviews()[1:]
               for key, source in review['sources'].items() if key in active}
    assert {source['file'] for source in sources.values()} == set(OVERLAY_FILES)
    for source in sources.values():
        check_metadata(source)
        # Independently reject wrong segments and line ranges for every active
        # overlay record, including whole files and the installer's Python body.
        for field, value in [('symbol_sha256', '0'*64), ('line', source['line']+1)]:
            with pytest.raises(AssertionError):
                check_metadata(source | {field: value})


@pytest.mark.parametrize('file', OVERLAY_FILES)
@pytest.mark.parametrize('damage', ['byte', 'missing'])
def test_original_checker_rejects_every_current_overlay_file(current, monkeypatch, file, damage):
    module, records = current
    read, is_file = Path.read_bytes, Path.is_file
    assert module.validate_response_sources(ROOT, records) == []
    if damage == 'byte':
        monkeypatch.setattr(Path, 'read_bytes', lambda path: read(path)+b' ' if path == ROOT/file else read(path))
    else:
        monkeypatch.setattr(Path, 'is_file', lambda path: False if path == ROOT/file else is_file(path))
    assert module.validate_response_sources(ROOT, records) == ['source drift or missing source: '+file]


@pytest.mark.parametrize('name', tuple(REVIEW_DIGESTS))
def test_frozen_historical_and_approved_overlay_ledgers_reject_one_byte_tamper(monkeypatch, name):
    approved_reviews()
    read = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda path: read(path)+b' ' if path == ROOT/'app'/name else read(path))
    with pytest.raises(AssertionError, match=name):
        approved_reviews()


@pytest.mark.parametrize('mapping', [
    'app/api_response_v11_review.json',
    'app/api_response_v12_final_review.json',
    'app/api_response_v13_speedtest_duration_review.json',
    [], ['app/api_response_v11_review.json'], ['arbitrary.json'],
    ['app/api_response_v13_speedtest_duration_review.json', 'app/api_response_v12_final_review.json'],
    ['app/api_response_v12_final_review.json', 'app/api_response_v13_speedtest_duration_review.json', 'extra.json'],
])
def test_identity_source_map_rejects_stale_missing_arbitrary_or_reordered_approvals(current, mapping):
    module, _ = current
    operation = {}
    module.decorate_response(operation, 'GET', '/agent/identity', 'app.routers.monitor.agent_identity')
    assert_identity_evidence(operation, module)
    operation['x-stella-contract-evidence']['source-map'] = mapping
    with pytest.raises(AssertionError):
        assert_identity_evidence(operation, module)


@pytest.mark.parametrize('field', ['handler', 'supporting-symbols'])
def test_identity_latest_mapping_does_not_accept_stale_evidence(current, field):
    module, _ = current
    operation = {}
    module.decorate_response(operation, 'GET', '/agent/identity', 'app.routers.monitor.agent_identity')
    assert_identity_evidence(operation, module)
    v11 = approved_reviews()[0]
    evidence = operation['x-stella-contract-evidence']
    evidence[field] = (v11['sources'][v11['handler_source_replacements']['app.routers.monitor.agent_identity']]
                       if field == 'handler' else v11['operations'][0]['sources'])
    with pytest.raises(AssertionError):
        assert_identity_evidence(operation, module)


@pytest.mark.parametrize('index', range(1, len(REVIEW_DIGESTS)))
@pytest.mark.parametrize('field,value', [('before_sources', []), ('endpoint', 'unapproved.endpoint')])
def test_approved_overlay_replay_keeps_exact_edge_preconditions(index, field, value):
    update = deepcopy(approved_reviews()[index]['operation_source_updates'][0])
    key = update['method'], update['path']
    before = {key: dict(method=key[0], path=key[1], endpoint=update['endpoint'], sources=update['before_sources'])}
    review = {'operation_source_updates': [update]}
    assert apply_review(before, review)[key]['sources'] == update['sources']
    update[field] = value
    with pytest.raises(AssertionError):
        apply_review(before, review)


@pytest.mark.parametrize('mapping', [
    'app/api_response_v13_monitor404_review.json',
    ['app/api_response_v12_final_review.json', 'app/api_response_v13_speedtest_duration_review.json'],
    ['app/api_response_v12_final_review.json', 'app/api_response_v13_monitor404_review.json'],
    ['app/api_response_v12_final_review.json', 'app/api_response_v13_monitor404_review.json',
     'app/api_response_v13_speedtest_duration_review.json'],
    ['app/api_response_v12_final_review.json', 'app/api_response_v13_speedtest_duration_review.json',
     'app/api_response_v13_monitor404_review.json', 'app/api_response_v13_monitor404_review.json'],
    ['app/api_response_v12_final_review.json', 'app/api_response_v13_speedtest_duration_review.json',
     'app/api_response_v13_monitor404_review.json', 'extra.json'],
])
def test_identity_monitor404_map_rejects_incomplete_reordered_or_extra_layers(current, mapping):
    module, _ = current
    operation = {}
    module.decorate_response(operation, 'GET', '/agent/identity', 'app.routers.monitor.agent_identity')
    assert_identity_evidence(operation, module)
    operation['x-stella-contract-evidence']['source-map'] = mapping
    with pytest.raises(AssertionError):
        assert_identity_evidence(operation, module)


@pytest.mark.parametrize('index', [1, 4])
@pytest.mark.parametrize('field', ['handler', 'supporting-symbols'])
def test_identity_monitor404_rejects_superseded_v12_and_duration_evidence(current, index, field):
    module, _ = current
    operation = {}
    module.decorate_response(operation, 'GET', '/agent/identity', 'app.routers.monitor.agent_identity')
    assert_identity_evidence(operation, module)
    reviews = approved_reviews()
    row = next(row for row in reviews[index]['operation_source_updates']
               if (row['method'], row['path']) == ('GET', '/agent/identity'))
    # Duration retained the V12 handler; only its supporting source union changed.
    v12 = reviews[1]
    operation['x-stella-contract-evidence'][field] = (
        v12['sources'][v12['handler_source_replacements'][row['endpoint']]]
        if field == 'handler' else row['sources'])
    with pytest.raises(AssertionError):
        assert_identity_evidence(operation, module)


@pytest.mark.parametrize('damage', ['missing', 'reordered'])
def test_identity_monitor404_supporting_symbols_are_the_complete_ordered_union(current, damage):
    module, _ = current
    operation = {}
    module.decorate_response(operation, 'GET', '/agent/identity', 'app.routers.monitor.agent_identity')
    assert_identity_evidence(operation, module)
    sources = operation['x-stella-contract-evidence']['supporting-symbols']
    operation['x-stella-contract-evidence']['supporting-symbols'] = (
        sources[:-1] if damage == 'missing' else list(reversed(sources)))
    with pytest.raises(AssertionError):
        assert_identity_evidence(operation, module)
