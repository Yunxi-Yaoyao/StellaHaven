"""Keep all backend gates within per-job budgets without sharing Python state.

GitLab `needs: backend-test` requires all parallel instances (currently seven). Each instance
has its own existing PostgreSQL service and identical database bootstrap. Runner
concurrency remains unchanged; this splits budgets, not host resource limits.
"""
import argparse
import math
import runpy
import json
import os
from pathlib import Path
import subprocess
import sys


# Frozen estimates, never learned or rewritten by CI. CI168 (a7907973) full
# command timestamp intervals include Python startup and teardown: ceil(1.05*t).
# Unobserved commands retain CI158/host-local estimates or the 10s default;
# those mixed runtimes / guarded PG skips are NOT a wall-clock guarantee.
# CI170 (ae489f8) complete next-command intervals use ceil(1.05*t), retaining
# larger prior estimates except documentation: job968 finally completed that
# command in 22.710521s (1 passed), replacing its old censored 450s reserve.
# job966 tests_website_settings was censored after >110s: reserve 240s, NOT a
# completed measurement. Failed/unfinished commands never become observations.
# The remaining unknown commands retain 10s, not a guaranteed bound. Selection
# evidence and 4/5/6 comparison: ci170-shard-capacity-fix/timings.json + REPORT.md.
# Per-file sources, line ranges and limitations: ci168-budget-fix evidence.
# Setup observations: inert shards 69.176/73.616s, browser shards
# 212.630/213.537s. Charge 75s common + 140s once when a shard needs browsers.
COMMON_SETUP_SECONDS = 75.0
BROWSER_SETUP_SECONDS = 140.0
DEFAULT_ESTIMATED_SECONDS = 10.0
ESTIMATED_SECONDS = {
    'tests': 238,
    'tests_experience': 5,
    'tests_generic_templates': 36,
    'tests_ha': 7.974,
    'tests_isolated/test_access_defaults.py': 5.603,
    'tests_isolated/test_access_entries.py': 6.15,
    'tests_isolated/test_access_entries_pg.py': 4.504,
    'tests_isolated/test_access_pages_pg.py': 2,
    'tests_isolated/test_access_runtime.py': 9,
    'tests_isolated/test_agent_channel_tls.py': 23,
    'tests_isolated/test_agent_channels.py': 1,
    'tests_isolated/test_agent_http_health_compat.py': 7,
    'tests_isolated/test_agent_identity_v11.py': 1.852,
    'tests_isolated/test_agent_installer.py': 12,
    'tests_isolated/test_agent_installer_umask_v12.py': 19,
    'tests_isolated/test_agent_ipv6_wire_v6.py': 4,
    'tests_isolated/test_agent_ping.py': 1,
    'tests_isolated/test_agent_privileges.py': 15,
    'tests_isolated/test_agent_release_continuity.py': 1.247,
    'tests_isolated/test_agent_release_v8.py': 2,
    'tests_isolated/test_agent_runtime_instances_v11.py': 2,
    'tests_isolated/test_agent_scheduler.py': 7,
    'tests_isolated/test_agent_udp_ipv6_v6.py': 0.743,
    'tests_isolated/test_agent_update.py': 4.128,
    'tests_isolated/test_agent_windows_instances_v11.py': 1.06,
    'tests_isolated/test_api_auth_gate.py': 41,
    'tests_isolated/test_api_contract_save_event_reconciliation.py': 95,
    'tests_isolated/test_api_draft_contract.py': 32,
    'tests_isolated/test_api_migration_graph.py': 1,
    'tests_isolated/test_api_openapi_contract.py': 54,
    'tests_isolated/test_api_response_ci167_evidence.py': 148,
    'tests_isolated/test_api_response_completion.py': 535,
    'tests_isolated/test_api_response_contract.py': 496,
    'tests_isolated/test_api_response_current_overlay_v13.py': 33,
    'tests_isolated/test_api_response_final_gate.py': 238,
    'tests_isolated/test_api_response_reconcile.py': 179,
    'tests_isolated/test_api_response_source_metadata_v13.py': 50,
    'tests_isolated/test_api_response_v11_integration.py': 187,
    'tests_isolated/test_api_response_v11_runtime.py': 6,
    'tests_isolated/test_api_response_v11_scope.py': 2,
    'tests_isolated/test_api_response_v6_integration.py': 138,
    # Separate successful host preflight (25.03s pytest + process allowance),
    # NOT the failed 26.556s command in CI168 job 948.
    'tests_isolated/test_api_response_v6_runtime.py': 31,
    'tests_isolated/test_api_response_v7_integration.py': 56,
    'tests_isolated/test_api_response_v8_integration.py': 135,
    'tests_isolated/test_api_tag_contract.py': 5,
    'tests_isolated/test_api_zip_reconciliation_sources.py': 33,
    'tests_isolated/test_app_origin_namespace.py': 2,
    'tests_isolated/test_auth_provider_wiring.py': 1.046,
    'tests_isolated/test_backup_group_identity.py': 15,
    'tests_isolated/test_backup_response_contract.py': 108,
    'tests_isolated/test_browser_sessions.py': 48,
    'tests_isolated/test_browser_sessions_pg.py': 3,
    'tests_isolated/test_build_mirror.py': 2,
    'tests_isolated/test_builtin_stream_snapshot.py': 7,
    'tests_isolated/test_capability_log_redaction.py': 1,
    'tests_isolated/test_channel_recovery_fence.py': 1.306,
    'tests_isolated/test_client_callback_contract.py': 2,
    'tests_isolated/test_detached_source_pg.py': 4.123,
    'tests_isolated/test_detached_source_unit.py': 1.119,
    'tests_isolated/test_direct_entry_mapping.py': 2,
    'tests_isolated/test_document_save_projection.py': 3,
    'tests_isolated/test_documentation_export.py': 24,
    'tests_isolated/test_drive_daily_access.py': 5,
    'tests_isolated/test_email_attempts.py': 16,
    'tests_isolated/test_email_attempts_pg.py': 2,
    'tests_isolated/test_entry_lifecycle_v11.py': 4,
    'tests_isolated/test_entry_monitor_groups.py': 4,
    'tests_isolated/test_entry_monitor_migration.py': 3,
    'tests_isolated/test_entry_monitoring.py': 5,
    'tests_isolated/test_entry_monitoring_pg.py': 1,
    'tests_isolated/test_entry_scope.py': 6,
    'tests_isolated/test_feedback_integration_contract.py': 23,
    'tests_isolated/test_followup_contract.py': 18,
    'tests_isolated/test_gallery_ingress_candidate.py': 4,
    'tests_isolated/test_hardware_agent.py': 1,
    'tests_isolated/test_hardware_refresh_failures.py': 2,
    'tests_isolated/test_host_install_attempt_v12.py': 3,
    'tests_isolated/test_host_instances_v11.py': 1.104,
    'tests_isolated/test_host_monitor_display.py': 2.626,
    'tests_isolated/test_host_registration_atomic_v12.py': 4,
    'tests_isolated/test_html_note_conversion.py': 2,
    'tests_isolated/test_html_note_conversion_pg.py': 2,
    'tests_isolated/test_html_note_semantics_v12.py': 2,
    'tests_isolated/test_install_binding_v12.py': 3,
    'tests_isolated/test_integration_security_hotfix.py': 37,
    'tests_isolated/test_machine_agent.py': 1,
    'tests_isolated/test_metrics_source.py': 9,
    'tests_isolated/test_monitor_basics_v7.py': 2.445,
    'tests_isolated/test_monitor_binary_v7.py': 3.194,
    'tests_isolated/test_monitor_experience_v5.py': 4,
    'tests_isolated/test_monitor_group_delete.py': 5,
    'tests_isolated/test_monitor_group_identity_migration.py': 2,
    'tests_isolated/test_monitor_health_compat.py': 4,
    'tests_isolated/test_monitor_index.py': 2,
    'tests_isolated/test_monitor_index_migration.py': 1.154,
    'tests_isolated/test_monitor_lifecycle_v7.py': 3,
    'tests_isolated/test_monitor_management_migration_v8.py': 2,
    'tests_isolated/test_monitor_management_v8.py': 4,
    'tests_isolated/test_monitor_missing_node_v13.py': 3.518,
    'tests_isolated/test_monitor_performance.py': 3,
    'tests_isolated/test_monitor_review_fixes_v6.py': 4,
    'tests_isolated/test_monitor_validity_v6.py': 3,
    'tests_isolated/test_native_entry_scope_v11.py': 3,
    'tests_isolated/test_node_monitor_policy.py': 2.533,
    'tests_isolated/test_notes_feedback_pg.py': 3,
    'tests_isolated/test_notes_lifecycle.py': 3,
    'tests_isolated/test_notes_overhaul.py': 4,
    'tests_isolated/test_notes_overhaul_pg.py': 3,
    'tests_isolated/test_notes_review_boundaries_pg.py': 12,
    'tests_isolated/test_notes_timeline_contract_pg.py': 2,
    'tests_isolated/test_oidc_auth_connection_release.py': 4,
    'tests_isolated/test_oidc_authorize_errors.py': 44,
    'tests_isolated/test_oidc_configured_issuer.py': 2,
    'tests_isolated/test_oidc_existing_native_callback.py': 2,
    'tests_isolated/test_oidc_pool_security.py': 2,
    'tests_isolated/test_oidc_provider.py': 14,
    'tests_isolated/test_oidc_secret_reveal_pg.py': 1,
    'tests_isolated/test_oidc_session_claim.py': 3,
    'tests_isolated/test_openlist_admin_gate.py': 9,
    'tests_isolated/test_operations_audit_pg.py': 2,
    'tests_isolated/test_operations_status.py': 3,
    'tests_isolated/test_production_health_contract.py': 1,
    'tests_isolated/test_profile_username.py': 4,
    'tests_isolated/test_project_files_pg.py': 3,
    'tests_isolated/test_project_files_unit.py': 1,
    'tests_isolated/test_public_node_tasks.py': 4,
    'tests_isolated/test_report_channels.py': 3.116,
    'tests_isolated/test_request_security.py': 13,
    'tests_isolated/test_server_freshness.py': 1.54,
    'tests_isolated/test_session_list_identity.py': 11,
    'tests_isolated/test_session_location_db_boundary.py': 5,
    'tests_isolated/test_session_location_deadline.py': 13,
    'tests_isolated/test_single_password_flows_v6.py': 16,
    'tests_isolated/test_single_password_v6.py': 5.726,
    'tests_isolated/test_small_public_outputs.py': 7,
    'tests_isolated/test_small_public_scopes.py': 3,
    'tests_isolated/test_speedtest_duration_v13.py': 15,
    'tests_isolated/test_system_memory.py': 1,
    'tests_isolated/test_system_memory_roundtrip.py': 2,
    'tests_isolated/test_task_security.py': 3,
    'tests_isolated/test_throughput_backend_v12.py': 5,
    'tests_isolated/test_throughput_fix2_http_v12.py': 2,
    'tests_isolated/test_throughput_fix2_v12.py': 3.377,
    'tests_isolated/test_traffic_query_fastpath.py': 2,
    'tests_isolated/test_upgrade_handoff.py': 15,
    'tests_isolated/test_v5_alert_contract_integration.py': 18,
    'tests_isolated/test_v5_contract_integration.py': 23,
    'tests_isolated/test_validation_redaction.py': 1.839,
    'tests_isolated/test_validation_route_boundaries.py': 3,
    'tests_isolated/test_web_project_7790dcf_response_contract.py': 227,
    'tests_isolated/test_web_project_html_bootstrap.py': 3,
    'tests_isolated/test_web_project_manifest_membership_pg.py': 11,
    'tests_isolated/test_web_project_response_contract.py': 93,
    'tests_isolated/test_web_project_review_pg.py': 5,
    'tests_isolated/test_web_projects_pg.py': 3,
    'tests_isolated/test_website_software_hint.py': 1,
    'tests_isolated/test_windows_installer.py': 2,
    'tests_notes_upgrade': 3,
    'tests_isolated/test_api_response_agent_rollout_evidence.py': 38,
    'tests_isolated/test_api_response_monitor_ux_evidence.py': 136,
    'tests_isolated/test_web_project_renewal_pg.py': 11,
    'tests_isolated/test_final_review_fixes.py': 23,
    'tests_isolated/test_notes_review_boundaries.py': 16,
    'tests_isolated/test_owner_admin_security.py': 11,
    'tests_website_settings': 240,
}
# Stdlib-only inventory is loaded from this exact runner directory, including
# when the script is loaded offline by importlib or Python -S.
_OWNED = runpy.run_path(str(Path(__file__).with_name('owned_inventory.py')))
_OWNED_TIMINGS = json.loads(Path(__file__).with_name('owned-timings.json').read_text())
# Retire provisional reserves only where successful complete observations exist.
# Keep larger CI170 intervals; no timeout/skip becomes a completed measurement.
# Owned commands retain 20% plus 5s on the largest local/remote observation,
# rather than stacking a provisional 50% reserve over completed remote costs.
# Seven shards, scheduler, setup charges and all capacity limits are unchanged.
_CI178_TIMINGS = json.loads(Path(__file__).with_name('ci178-backend-timings.json').read_text())
_COMPLETED = dict(_CI178_TIMINGS['successful_command_seconds'])
for _source in (_OWNED_TIMINGS['prior_remote_completed_seconds'], _OWNED_TIMINGS['completed_seconds']):
    for _path, _seconds in _source.items():
        if isinstance(_seconds, bool) or not isinstance(_seconds, (int, float)) or not math.isfinite(_seconds) or _seconds <= 0:
            raise ValueError('completed timings must be finite positive numbers')
        _COMPLETED[_path] = max(_COMPLETED.get(_path, 0), _seconds)
for _path, _seconds in _COMPLETED.items():
    if isinstance(_seconds, bool) or not isinstance(_seconds, (int, float)) or not math.isfinite(_seconds) or _seconds <= 0:
        raise ValueError('completed timings must be finite positive numbers')
    ESTIMATED_SECONDS[_path] = (math.ceil(1.20 * _seconds + 5)
                                if _path in _OWNED_TIMINGS['completed_seconds']
                                else math.ceil(1.05 * _seconds))

# Include every complete CI182 interval; failed/censored commands are absent.
_CI182_TIMINGS = json.loads(Path(__file__).with_name('ci182-backend-timings.json').read_text())
for _local, _source in ((False, _CI182_TIMINGS['successful_command_seconds']),
                         (True, _CI182_TIMINGS['new_local_successful_command_seconds'])):
    for _path, _seconds in _source.items():
        if isinstance(_seconds, bool) or not isinstance(_seconds, (int, float)) or not math.isfinite(_seconds) or _seconds <= 0:
            raise ValueError('completed timings must be finite positive numbers')
        _owned_margin = _local or _path in _OWNED_TIMINGS['completed_seconds']
        ESTIMATED_SECONDS[_path] = max(ESTIMATED_SECONDS.get(_path, DEFAULT_ESTIMATED_SECONDS),
            math.ceil((1.20 if _owned_margin else 1.05) * _seconds + (5 if _owned_margin else 0)))
# Exact-cache + fresh plain-graph cloning changes this measured cohort only.
# No global speed factor, no extrapolation to unmeasured commands, no scheduler,
# inventory, setup, shard-count or timeout changes. Preserve all frozen inputs.
_COPY_TIMINGS = json.loads(Path(__file__).with_name('copy-capacity-timings.json').read_text())
for _path, _observation in _COPY_TIMINGS['observations'].items():
    _seconds = _observation['completed_seconds']
    if (isinstance(_seconds, bool) or not isinstance(_seconds, (int, float)) or
            not math.isfinite(_seconds) or _seconds <= 0 or
            type(_observation['original_case_count']) is not int or _observation['original_case_count'] <= 0):
        raise ValueError('copy calibration requires completed original cases and positive finite seconds')
    if _path not in ESTIMATED_SECONDS or _observation['new_weight'] != math.ceil(1.20 * _seconds + 5):
        raise ValueError('copy calibration is not an observed command with unchanged margin')
    ESTIMATED_SECONDS[_path] = _observation['new_weight']

# Separate source-bound successor observations never rewrite retired evidence.
_SUCCESSOR = runpy.run_path(str(Path(__file__).with_name('capacity_successor.py')))
_V23_TIMINGS = _SUCCESSOR['apply'](ESTIMATED_SECONDS)
_DERIVATION_TIMINGS = _SUCCESSOR['apply_derivation'](ESTIMATED_SECONDS)

GROUP_COMMANDS = (
    ('tests',),
    ('tests_ha', '--noconftest'),
    ('tests_notes_upgrade', '--confcutdir=tests_notes_upgrade'),
    ('tests_website_settings', '--confcutdir=tests_website_settings'),
    ('tests_generic_templates', '--noconftest'),
    ('tests_experience', '--noconftest'),
)


def estimated_seconds(command):
    value = ESTIMATED_SECONDS.get(command[0], DEFAULT_ESTIMATED_SECONDS)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError('backend timing estimates must be finite positive numbers')
    return value


def plan(root, index, total):
    if (type(total) is not int or not 1 <= total <= 200 or
            type(index) is not int or not 1 <= index <= total):
        raise ValueError('backend requires 1..200 shards, numbered 1..total')
    files = sorted((root / 'tests_isolated').glob('test_*.py'))
    if not files:
        raise ValueError('isolated test inventory is empty')
    commands = [list(cmd) for cmd in GROUP_COMMANDS] + [
        [str(path.relative_to(root)), '--noconftest'] for path in files] + _OWNED['files_commands'](root)
    # Longest processing time first; path/argv and shard index break every tie.
    # All six grouped commands participate, with original subprocess arguments.
    commands.sort(key=lambda cmd: (-estimated_seconds(cmd), tuple(cmd)))
    shards = [[] for _ in range(total)]
    loads = [COMMON_SETUP_SECONDS] * total
    browsers = [False] * total
    for command in commands:
        weight = estimated_seconds(command)
        needs_browser = command_requires_browser(command)
        # Setup is paid once per shard, not per browser command. Minimize
        # projected completion, including activating an otherwise inert shard.
        costs = [loads[i] + weight + (
            BROWSER_SETUP_SECONDS if needs_browser and not browsers[i] else 0)
            for i in range(total)]
        target = min(range(total), key=lambda i: (costs[i], i))
        shards[target].append(command)
        loads[target] = costs[target]
        browsers[target] |= needs_browser
    return shards[index - 1]


# File-level dependency metadata, NOT shard assignments. Files and native-Nav
# PG/browser fixtures now run through owned admission; unrelated opt-ins stay off.
UNCONDITIONAL_BROWSER_TESTS = frozenset({
    'tests_isolated/test_dual_entry.py',
    'tests_isolated/test_web_project_html_bootstrap.py',
    *_OWNED['FILES_BROWSER'], _OWNED['NAV_BROWSER'],
})


def command_requires_browser(command):
    """One file/directory dependency predicate for costing and setup alike."""
    return any(Path(path).is_relative_to(Path(command[0]))
               for path in UNCONDITIONAL_BROWSER_TESTS)


def browser_required(root, index, total):
    """Stdlib-only setup predicate using the very same plan as execution."""
    commands = plan(root, index, total)
    if not commands or any(not (root / cmd[0]).exists() for cmd in commands):
        raise ValueError('backend shard plan is empty or references missing tests')
    if not UNCONDITIONAL_BROWSER_TESTS or any(
            not (root / path).is_file() for path in UNCONDITIONAL_BROWSER_TESTS):
        raise ValueError('unconditional browser test metadata is empty or missing')
    return any(command_requires_browser(cmd) for cmd in commands)


def execute(root, index, total):
    commands = plan(root, index, total)
    print(f'BACKEND_SHARD {index}/{total}: {len(commands)} commands', flush=True)
    for args in commands:
        print('BACKEND_COMMAND ' + ' '.join(args), flush=True)
        argv = ([sys.executable, str(root / 'deploy/ci/run-owned-suite.py'), *args]
                if _OWNED['owned_command'](args) else [sys.executable, '-m', 'pytest', '-q', *args])
        result = subprocess.run(argv, cwd=root)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requires-browser', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    index, total = int(os.environ['CI_NODE_INDEX']), int(os.environ['CI_NODE_TOTAL'])
    if args.requires_browser:
        print('required' if browser_required(root, index, total) else 'not-required')
    else:
        raise SystemExit(execute(root, index, total))
