"""Stdlib discovery shared by setup, costing, execution and offline gates."""
from pathlib import Path

FILES_DIRECTORIES = ('tests_node_files', 'tests_node_files_delivery', 'tests_agent_unified', 'tests_agent_refresh_timeout')
# Exact real collector IDs: neither a selected parameter nor zero-exit skip is
# sufficient for the mandatory main/lifespan regression.
FULL_MAIN_NODEIDS = (
    'tests_agent_refresh_timeout/test_full_main.py::test_active_upload_survives_periodic_network_timeout[/agent/files/config]',
    'tests_agent_refresh_timeout/test_full_main.py::test_active_upload_survives_periodic_network_timeout[/agent/identity]',
)
FILES_BROWSER = frozenset({'tests_node_files/test_acl_browser.py', 'tests_node_files/test_build.py', 'tests_node_files/test_pipeline.py'})
NAV_BROWSER = 'tests_isolated/test_native_nav_completion_browser_pg.py'
# Deliberately outside CI: requires an operator-supplied private legacy export.
# Never substitute a synthetic export for that distinct historical oracle.
MANUAL_NODEIDS = {
    'tests_isolated/test_native_nav_completion_pg.py::test_actual_readonly_source_rehearsal_roundtrip':
        'manual private-input rehearsal; NAV_LEGACY_TRANSFER must be supplied by its owner',
}


def files_commands(root):
    return [[str(path.relative_to(root))] for directory in FILES_DIRECTORIES
            for path in sorted((root / directory).glob('test_*.py'))]


def owned_command(command):
    path = Path(command[0])
    return (path.parent.as_posix() in FILES_DIRECTORIES or
            (path.parent == Path('tests_isolated') and path.name.endswith('_pg.py')
             and (path.name.startswith('test_native_nav_') or path.name == 'test_homebg_references_pg.py')))


def browser_command(command):
    return command[0] in FILES_BROWSER or command[0] == NAV_BROWSER
