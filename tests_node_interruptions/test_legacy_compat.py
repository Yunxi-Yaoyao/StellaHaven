"""Exercise original alert service cases under the new owned-PG guard.

The root tests/conftest.py intentionally accepts different CI/HA DB targets;
never loosen that guard just to run these cases on this ephemeral database.
"""
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from app.models.user import User
from app.services import alerts
from test_pg import engine

spec = importlib.util.spec_from_file_location('original_alert_cases', Path(__file__).resolve().parents[1] / 'tests/test_alerts.py')
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)
CASES = [
    'test_create_rule_validates_and_rejects_duplicate',
    'test_update_and_delete_rule_archives_state',
    'test_node_offline_deadline_then_own_heartbeat_resolves',
    'test_firing_repeat_reminder_respects_interval',
    'test_disabled_rule_is_not_evaluated',
    'test_pending_or_removed_node_does_not_fire',
    'test_rule_on_deleted_target_preserves_incident_and_stays_quiet',
    'test_monitor_down_fires_and_recovers',
    'test_wg_link_fires_on_failed_only_and_unknown_is_not_bad',
    'test_wg_link_missing_from_topology_is_neutral',
]

@pytest.mark.parametrize('name', CASES)
def test_original_service_cases(engine, monkeypatch, name):
    with Session(engine) as db:
        calls = {'email': [], 'ws': []}
        db.add(User(username='owned-'+uuid4().hex, display_name='owned', is_admin=True, email='owned@example.invalid'))
        db.commit()
        monkeypatch.setattr(alerts, '_send_alert_email', lambda snapshot: calls['email'].append((snapshot['rule_id'], snapshot['event'])))
        monkeypatch.setattr(alerts, '_push_ws', calls['ws'].append)
        fn = getattr(original, name)
        args = {'db_session': db, 'monkeypatch': monkeypatch, 'no_side_effects': calls}
        import inspect
        fn(**{key: args[key] for key in inspect.signature(fn).parameters})
