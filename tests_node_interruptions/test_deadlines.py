"""Owned in-memory domain/real-router tests; no configured DB or delivery."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.node import Node, NodeStatusEvent, NodeMetric, NodeSysMetric
from app.models.alert import AlertRule, AlertState, AlertEvent, Notification
from app.models.user import User
from app.models.config import AppConfig
from app.models.monitor import Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember
from app.services import alerts

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)
PRODUCTION_SEND_EMAIL = alerts._send_alert_email

@compiles(JSONB, 'sqlite')
def json_sqlite(*args, **kwargs):
    return 'JSON'

@compiles(BigInteger, 'sqlite')
def bigint_sqlite(*args, **kwargs):
    return 'INTEGER'

TABLES = (Node, NodeStatusEvent, NodeMetric, NodeSysMetric, AlertRule, AlertState,
          AlertEvent, Notification, User, AppConfig, Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember)

@pytest.fixture
def db(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    for cls in TABLES:
        cls.__table__.create(engine)
    monkeypatch.setattr(alerts, '_push_ws', lambda payload: None)
    monkeypatch.setattr(alerts, '_send_alert_email', lambda payload: pytest.fail('unexpected mail'))
    with Session(engine) as session:
        yield session
    engine.dispose()


def new(db, **kw):
    node = Node(name='owned', host='invalid.test', platform='linux', **kw)
    db.add(node); db.flush()
    return node


def events(db):
    return db.query(AlertEvent).order_by(AlertEvent.id).all()


def test_new_node_has_one_enabled_quiet_rule_in_same_transaction(db):
    from app.services.node import create_node
    node = create_node(db, 'owned', 'linux', 'invalid.test')
    assert node.status == 'pending' and node.last_seen_at is None
    rules = db.query(AlertRule).all()
    assert len(rules) == 1
    rule = rules[0]
    assert (rule.kind, rule.target, rule.label, rule.link, rule.enabled, rule.email,
            rule.repeat_minutes, rule.debounce, rule.severity) == (
        'node_offline', str(node.id), 'owned · 上报中断', f'/status/{node.id}', True, False, 0, 1, 'warning')
    assert db.get(AlertState, rule.id).state == 'ok'
    assert events(db) == [] and db.query(Notification).count() == 0


def test_new_host_uses_same_hook_without_recreating_on_reinstall(db):
    from app.services.node_monitor_policy import ensure_local_host
    node = ensure_local_host(db, 'linux')
    rule = db.query(AlertRule).one()
    assert rule.target == str(node.id) and not rule.email
    rule.enabled = False; rule.email = True; db.commit()
    assert ensure_local_host(db, 'linux').id == node.id
    assert db.query(AlertRule).count() == 1
    assert not rule.enabled and rule.email


@pytest.mark.parametrize('first_late', [120.000001, 150])
def test_deadline_is_not_report_count_and_only_own_heartbeat_recovers(db, first_late):
    node = new(db, status='online', installed=True, last_seen_at=NOW)
    rule = alerts.create_node_interruption_rule(db, node)
    db.commit()
    for seconds in (0, 119.999, 120):
        alerts.evaluate_node_rules(db, now=NOW + timedelta(seconds=seconds))
        assert events(db) == []
    alerts.evaluate_node_rules(db, now=NOW + timedelta(seconds=first_late))
    assert [e.event for e in events(db)] == ['fired']
    assert events(db)[0].ts.replace(tzinfo=timezone.utc) == NOW + timedelta(seconds=120)
    assert db.get(AlertState, rule.id).state == 'firing'
    db.commit()
    alerts.evaluate_node_rules(db, now=NOW + timedelta(days=2))
    assert db.query(Notification).count() == 1  # repeat=0
    # Current fresh receipt alone cannot make timer/restart invent recovery.
    node.last_seen_at = NOW + timedelta(days=2, seconds=1); db.commit()
    alerts.evaluate_node_rules(db, now=NOW + timedelta(days=2, seconds=2))
    assert [e.event for e in events(db)] == ['fired']
    alerts.evaluate_node_rules(db, now=NOW + timedelta(days=2, seconds=3), heartbeat_node_id=node.id)
    alerts.evaluate_node_rules(db, now=NOW + timedelta(days=2, seconds=4), heartbeat_node_id=node.id)
    assert [e.event for e in events(db)] == ['fired', 'resolved']
    assert events(db)[1].ts.replace(tzinfo=timezone.utc) == node.last_seen_at.replace(tzinfo=timezone.utc)


def test_authenticated_report_catches_missed_tick_then_recovers(db):
    from app.schemas.monitor import AgentReport
    from app.services.node import handle_report
    node = new(db, token='owned-token', status='online', installed=True,
               last_seen_at=datetime.now(timezone.utc) - timedelta(seconds=300))
    alerts.create_node_interruption_rule(db, node); db.commit()
    handle_report(db, 'owned-token', AgentReport())
    assert [e.event for e in events(db)] == ['fired', 'resolved']
    assert all('owned' in e.message for e in events(db))
    assert db.query(Notification).count() == 2


def test_new_api_email_default_and_repeat_validation(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers.auth import current_user, admin_user
    from app.routers.alerts import router
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: object()
    app.dependency_overrides[admin_user] = lambda: object()
    create_schema = app.openapi()['components']['schemas']['RuleCreate']['properties']
    assert create_schema['email']['default'] is False
    assert create_schema['repeat_minutes']['default'] == create_schema['repeat_minutes']['minimum'] == 0
    assert create_schema['repeat_minutes']['maximum'] == 1440
    with TestClient(app) as client:
        response = client.post('/alerts/rules', json={'kind': 'node_offline', 'target': '999'})
        assert response.status_code == 201, response.text
        rule = client.get('/alerts/rules').json()[0]
        assert rule['email'] is False and rule['repeat_minutes'] == 0
        for value in (-1, 1441, 0.5, True, '0'):
            assert client.patch(f"/alerts/rules/{rule['id']}", json={'repeat_minutes': value}).status_code == 422
        assert client.patch(f"/alerts/rules/{rule['id']}", json={'repeat_minutes': 0, 'email': True}).status_code == 200
        assert client.get('/alerts/rules').json()[0]['email'] is True


@pytest.mark.parametrize('case', ['pending', 'future', 'removed', 'disabled', 'uninstall', 'unmanaged'])
def test_neutral_or_suppressed_observations_never_fire_or_resolve(db, case):
    node = new(db, status='online', installed=True, last_seen_at=NOW)
    rule = alerts.create_node_interruption_rule(db, node); db.commit()
    alerts.evaluate_node_rules(db, now=NOW + timedelta(seconds=121)); db.commit()
    assert [e.event for e in events(db)] == ['fired']
    if case == 'pending': node.status = 'pending'; node.last_seen_at = None
    elif case == 'future': node.last_seen_at = NOW + timedelta(days=3)
    elif case == 'removed': node.status = 'removed'
    elif case == 'disabled': node.status = 'disabled'
    elif case == 'uninstall': node.uninstall_status = 'pending'
    else: node.installed = False
    db.commit()
    alerts.evaluate_node_rules(db, now=NOW + timedelta(seconds=130), heartbeat_node_id=node.id)
    assert [e.event for e in events(db)] == ['fired']
    assert db.get(AlertState, rule.id).state == 'firing'
    assert db.query(Notification).count() == 1


def test_never_reported_node_is_pending_not_a_zero_sample_failure(db):
    node = new(db)
    rule = alerts.create_node_interruption_rule(db, node); db.commit(); db.refresh(node)
    assert node.last_seen_at is None  # actual persisted default, not assumed
    alerts.evaluate_node_rules(db, now=NOW + timedelta(days=30), node_id=node.id)
    assert db.get(AlertState, rule.id).preview['reason'] == 'pending'
    assert events(db) == []


@pytest.mark.parametrize('action', ['disable', 'archive'])
def test_disabled_archived_rule_is_never_recreated_by_report(db, action):
    from app.services.node import handle_report
    from app.schemas.monitor import AgentReport
    node = new(db, token='owned', status='online', installed=True,
               last_seen_at=datetime.now(timezone.utc) - timedelta(seconds=300))
    rule = alerts.create_node_interruption_rule(db, node); db.commit()
    alerts.evaluate_node_rules(db, node_id=node.id); db.commit()
    if action == 'disable': alerts.update_rule(db, rule.id, {'enabled': False})
    else: alerts.delete_rule(db, rule.id)
    db.commit()
    handle_report(db, 'owned', AgentReport())
    assert db.query(AlertRule).count() == 1
    assert db.get(AlertState, rule.id).state == 'firing'
    assert [e.event for e in events(db)] == ['fired']


def test_existing_node_report_does_not_backfill_a_rule(db):
    from app.services.node import handle_report
    from app.schemas.monitor import AgentReport
    node = new(db, token='old-owned')
    db.commit()
    handle_report(db, 'old-owned', AgentReport())
    assert db.query(AlertRule).count() == 0
    assert node.last_seen_at is not None


def test_existing_user_rule_and_same_id_retry_are_respected(db):
    node = new(db)
    rule = alerts.create_rule(db, 'node_offline', str(node.id), email=True, label='user', debounce=7)
    rule.enabled = False; db.commit()
    for _ in range(2):
        assert alerts.create_node_interruption_rule(db, node).id == rule.id
    assert db.query(AlertRule).count() == 1
    assert (rule.email, rule.enabled, rule.label, rule.debounce) == (True, False, 'user', 7)


def test_creation_and_auto_rule_failure_roll_back_inventory(db, monkeypatch):
    from app.services import node_monitor_policy, node as service
    def fail(*args): raise RuntimeError('owned failure after hook')
    monkeypatch.setattr(node_monitor_policy, 'reconcile', fail)
    with pytest.raises(RuntimeError): service.create_node(db, 'owned', 'linux', 'invalid.test')
    assert db.query(Node).count() == db.query(AlertRule).count() == db.query(AlertState).count() == 0


@pytest.mark.parametrize('commit', [True, False])
def test_outer_and_savepoint_dispatch_boundaries(db, monkeypatch, commit):
    pushed = []; monkeypatch.setattr(alerts, '_push_ws', pushed.append)
    nodes = [new(db, status='online', installed=True, last_seen_at=NOW) for _ in range(3)]
    for node in nodes: alerts.create_node_interruption_rule(db, node)
    db.commit()
    alerts.evaluate_node_rules(db, node_id=nodes[0].id, now=NOW + timedelta(seconds=130))
    with db.begin_nested():
        alerts.evaluate_node_rules(db, node_id=nodes[1].id, now=NOW + timedelta(seconds=130))
    savepoint = db.begin_nested()
    alerts.evaluate_node_rules(db, node_id=nodes[2].id, now=NOW + timedelta(seconds=130))
    savepoint.rollback()
    assert pushed == []
    if commit:
        db.commit()
        assert len(pushed) == len(events(db)) == db.query(Notification).count() == 2
    else:
        db.rollback()
        assert pushed == [] and events(db) == [] and db.query(Notification).count() == 0


def test_email_enable_only_affects_future_transition_no_backfill(db, monkeypatch):
    pushed = []; mailed = []
    monkeypatch.setattr(alerts, '_push_ws', pushed.append)
    monkeypatch.setattr(alerts, '_send_alert_email', mailed.append)
    db.add(User(username='owned', display_name='owned', is_admin=True, email='owned@example.invalid'))
    node = new(db, status='online', installed=True, last_seen_at=NOW)
    rule = alerts.create_node_interruption_rule(db, node); db.commit()
    alerts.evaluate_node_rules(db, now=NOW + timedelta(seconds=130)); db.commit()
    assert len(pushed) == 1 and mailed == []
    alerts.update_rule(db, rule.id, {'email': True}); db.commit()
    alerts.evaluate_node_rules(db, now=NOW + timedelta(seconds=140)); db.commit()
    assert mailed == []  # no retroactive fired email
    node.last_seen_at = NOW + timedelta(seconds=145); db.commit()
    alerts.evaluate_node_rules(db, now=NOW + timedelta(seconds=146), heartbeat_node_id=node.id); db.commit()
    assert len(pushed) == 2 and [m['event'] for m in mailed] == ['resolved']
    assert isinstance(mailed[0]['rule_id'], int) and mailed[0]['address'] == 'owned@example.invalid'


def test_smtp_disabled_keeps_durable_in_app_event_without_sending(db, monkeypatch):
    from app.routers import admin_email
    threads = []; sends = []; loaded = []
    real_thread = alerts.threading.Thread
    def thread(*args, **kwargs):
        instance = real_thread(*args, **kwargs); threads.append(instance); return instance
    def load(): loaded.append(True); return {'enabled': False, 'host': ''}
    monkeypatch.setattr(alerts.threading, 'Thread', thread)
    monkeypatch.setattr(alerts, '_send_alert_email', PRODUCTION_SEND_EMAIL)
    monkeypatch.setattr(admin_email, '_load', load)
    monkeypatch.setattr(admin_email, '_send', lambda *args: sends.append(args))
    db.add(User(username='smtp-owned', display_name='owned', is_admin=True, email='owned@example.invalid'))
    node = new(db, status='online', installed=True, last_seen_at=NOW)
    rule = alerts.create_node_interruption_rule(db, node); rule.email = True; db.commit()
    alerts.evaluate_node_rules(db, now=NOW + timedelta(seconds=130)); db.commit()
    for instance in threads:
        instance.join(2); assert not instance.is_alive()
    assert loaded == [True] and sends == []
    assert len(events(db)) == db.query(Notification).count() == 1


def test_old_clock_and_short_entry_switch_do_not_invent_transitions(db):
    node = new(db, status='online', installed=True, last_seen_at=NOW)
    alerts.create_node_interruption_rule(db, node); db.commit()
    alerts.evaluate_node_rules(db, now=NOW + timedelta(seconds=119))
    node.last_seen_at = NOW + timedelta(seconds=119); db.flush()
    alerts.evaluate_node_rules(db, now=NOW + timedelta(seconds=120), heartbeat_node_id=node.id)
    alerts.evaluate_node_rules(db, now=NOW + timedelta(seconds=30))  # delayed old tick
    assert events(db) == [] and db.query(Notification).count() == 0


def test_reenable_does_not_catch_up_reminders_or_fake_recovery(db, monkeypatch):
    node = new(db, status='online', installed=True, last_seen_at=NOW)
    rule = alerts.create_rule(db, 'node_offline', str(node.id), repeat_minutes=30)
    db.commit()
    alerts.evaluate_node_rules(db, now=NOW + timedelta(seconds=130)); db.commit()
    alerts.update_rule(db, rule.id, {'enabled': False}); db.commit()
    class Clock:
        @staticmethod
        def now(tz): return NOW + timedelta(days=1)
    monkeypatch.setattr(alerts, 'datetime', Clock)
    alerts.update_rule(db, rule.id, {'enabled': True}); db.commit()
    alerts.evaluate_node_rules(db, now=NOW + timedelta(days=1, seconds=1)); db.commit()
    assert db.query(Notification).count() == 1
    assert db.get(AlertState, rule.id).state == 'firing'
