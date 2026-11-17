"""Record exact pytest node IDs and outcomes; no assertion/skip rewriting."""
import json
import os
from pathlib import Path

results = {}
collected = []
deselected = []


def pytest_collection_modifyitems(config, items):
    from deploy.ci.owned_inventory import MANUAL_NODEIDS
    from deploy.ci.owned_pg import owned_target
    target = owned_target()
    if os.environ.get('STELLA_CI_UNIFIED') == '1':
        import sys
        from deploy.ci.unified_ci import audit_boundary, expected_ids
        actual = [item.nodeid for item in items]
        if sorted(actual) != sorted(expected_ids(target['test'])):
            raise ValueError('partial unified collection refused before running tests')
        roots = (Path(os.environ['TMPDIR']), Path(os.environ['NODE_FILES_EVIDENCE']))
        sys.addaudithook(lambda event, args: audit_boundary(event, args, roots))
    if any(item.nodeid.startswith('tests_agent_refresh_timeout/') for item in items):
        # Adapt the historical two-field receipt only after live-parent/relay
        # admission; the original test independently queries the actual PG role.
        from deploy.ci.owned_inventory import FULL_MAIN_NODEIDS
        if sorted(item.nodeid for item in items) != sorted(FULL_MAIN_NODEIDS):
            raise ValueError('partial full-main collection refused before running tests')
        port, database, user, _ = target
        nonce = os.environ['STELLA_CI_OWNED_NONCE']
        receipt = Path(os.environ['TMPDIR']) / 'auto-receipt.json'
        receipt.write_text(json.dumps({'nonce': nonce, 'database': database}))
        receipt.chmod(0o600)
        os.environ['NODE_FILES_AUTO_NONCE'] = nonce
        os.environ['NODE_FILES_AUTO_RECEIPT'] = str(receipt)
    manual = [item for item in items if item.nodeid in MANUAL_NODEIDS]
    items[:] = [item for item in items if item.nodeid not in MANUAL_NODEIDS]
    deselected.extend(item.nodeid for item in manual)
    if manual:
        config.hook.pytest_deselected(items=manual)


def pytest_collection_finish(session):
    collected.extend(item.nodeid for item in session.items)


def pytest_runtest_logreport(report):
    value = results.setdefault(report.nodeid, {})
    value[report.when] = report.outcome


def pytest_sessionfinish(session, exitstatus):
    data = {'collected': collected, 'manual_deselected': deselected, 'results': results, 'exit_code': int(exitstatus)}
    Path(os.environ['NODE_FILES_EVIDENCE'], 'nodeids.json').write_text(json.dumps(data, indent=2))
