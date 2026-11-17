"""B05: real alert editor/evaluator behavior across settings restores."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session
from tests_backups.test_settings_integrity_resources import settings_zip


def seed_rule(engine, revision):
    from app.models.node import Node
    from app.services.alert_metrics import save
    with Session(engine) as db:
        node = Node(name='metric-target', platform='linux', host='fixture.invalid', status='online')
        db.add(node)
        db.flush()
        intent = dict(node_id=node.id, label='Archived CPU rule', condition=dict(metric='cpu', threshold='80'),
                      debounce=2, repeat_minutes=0, email=False, enabled=True)
        rule = save(db, intent, now=datetime.now(timezone.utc) - timedelta(minutes=5))
        rule.revision = revision
        db.commit()
        return node.id, rule.id, intent


@pytest.mark.parametrize('archive_revision,current_revision', [(1, 7), (11, 3)])
def test_restore_advances_alert_cas_and_rejects_both_stale_editors(engine, tmp_path, archive_revision, current_revision):
    from app.models.alert import AlertRule
    from app.services.alert_metrics import save
    from app.services.backup_projection import restore_settings
    nid, rid, intent = seed_rule(engine, archive_revision)
    path = settings_zip(engine, tmp_path)
    with Session(engine) as db:
        rule = db.get(AlertRule, rid)
        rule.revision = current_revision
        rule.label = 'Current CPU rule'
        db.commit()
    restore_settings(engine, path)
    for stale in (archive_revision, current_revision):
        with Session(engine) as db:
            with pytest.raises(ValueError, match='revision'):
                save(db, intent | {'label': 'Stale editor'}, rule_id=rid, revision=stale)
            db.rollback()
    with Session(engine) as db:
        rule = db.get(AlertRule, rid)
        restored_revision = rule.revision
        assert restored_revision > max(archive_revision, current_revision)
        assert rule.label == intent['label']
        edited = save(db, intent | {'label': 'Fresh editor'}, rule_id=rid, revision=restored_revision)
        assert edited.revision == restored_revision + 1
        db.commit()
    with Session(engine) as db:
        assert db.get(AlertRule, rid).label == 'Fresh editor'


def test_restore_restarts_evaluation_without_replaying_history_or_resolving_incident(engine, tmp_path):
    from sqlalchemy import select
    from app.models.alert import AlertRule, AlertState, AlertEvent, Notification
    from app.models.node import NodeSysMetric
    from app.services.alert_metrics import save, evaluate_node
    from app.services.backup_projection import restore_settings
    nid, rid, intent = seed_rule(engine, 1)
    path = settings_zip(engine, tmp_path)
    old = datetime.now(timezone.utc) - timedelta(minutes=2)
    with Session(engine) as db:
        save(db, intent | {'condition': {'metric': 'cpu', 'threshold': '50'}}, rule_id=rid, revision=1, now=old)
        state = db.get(AlertState, rid)
        state.state, state.consecutive = 'firing', 9
        state.last_change_at, state.last_notified_at = old, old
        state.message, state.watermark, state.evaluated_at, state.preview = 'keep-live-incident', old, old, {'old-condition': 'cache'}
        db.add(AlertEvent(rule_id=rid, event='fired', ts=old, message='keep-history'))
        db.add(Notification(rule_id=rid, title='keep-notification', body='not a config value', ts=old))
        db.add(NodeSysMetric(node_id=nid, ts=old + timedelta(seconds=30), cpu_pct=60))
        db.commit()
    with engine.connect() as conn:
        events_before = conn.execute(select(AlertEvent.__table__)).all()
        notes_before = conn.execute(select(Notification.__table__)).all()
    before_restore = datetime.now(timezone.utc)
    restore_settings(engine, path)
    after_restore = datetime.now(timezone.utc)
    with Session(engine) as db:
        rule, state = db.get(AlertRule, rid), db.get(AlertState, rid)
        assert rule.condition['threshold'] == '80'
        assert (state.state, state.message, state.last_change_at, state.last_notified_at) == (
            'firing', 'keep-live-incident', old, old)
        assert state.consecutive == 0, 'old debounce must not carry into restored definition'
        assert before_restore <= state.watermark <= after_restore
        assert state.evaluated_at is None and state.preview is None
        restored_watermark = state.watermark
        evaluate_node(db, nid, now=after_restore)
        db.commit()
    with engine.connect() as conn:
        assert conn.execute(select(AlertEvent.__table__)).all() == events_before
        assert conn.execute(select(Notification.__table__)).all() == notes_before
    with Session(engine) as db:
        assert db.get(AlertState, rid).state == 'firing', 'cached pre-restore healthy sample must not resolve incident'
        assert db.get(AlertState, rid).watermark == restored_watermark
        fresh_time = after_restore + timedelta(seconds=1)
        db.add(NodeSysMetric(node_id=nid, ts=fresh_time, cpu_pct=60))
        db.flush()
        evaluate_node(db, nid, now=fresh_time)
        db.commit()
    with Session(engine) as db:
        assert db.get(AlertState, rid).state == 'ok'
        assert [r.event for r in db.query(AlertEvent).order_by(AlertEvent.id)] == ['fired', 'resolved']
        assert db.query(Notification).count() == len(notes_before) + 1


def test_restore_does_not_rewind_a_newer_live_evaluation_watermark(engine, tmp_path):
    from app.models.alert import AlertState
    from app.services.backup_projection import restore_settings
    _, rid, _ = seed_rule(engine, 1)
    path = settings_zip(engine, tmp_path)
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    with Session(engine) as db:
        db.get(AlertState, rid).watermark = future
        db.commit()
    restore_settings(engine, path)
    with Session(engine) as db:
        assert db.get(AlertState, rid).watermark == future


def test_restoring_expired_fixed_condition_is_not_new_save_admission_or_history_replay(engine, tmp_path):
    from app.models.node import Node, NodeMetric
    from app.models.alert import AlertRule, AlertState, AlertEvent, Notification
    from app.services.alert_metrics import save, evaluate_node
    from app.services.backup_projection import restore_settings
    now = datetime.now(timezone.utc)
    start, end = now - timedelta(hours=2), now - timedelta(hours=1)
    with Session(engine) as db:
        node = Node(name='fixed-target', platform='linux', host='fixture.invalid', status='online', interfaces={'eth0': {}})
        db.add(node)
        db.flush()
        condition = dict(metric='network.volume', interface='eth0', direction='in', threshold='10',
                         window=dict(kind='fixed', start=start.isoformat(), end=end.isoformat(), timezone='UTC'))
        intent = dict(node_id=node.id, label='Ended fixed rule', condition=condition, debounce=1, repeat_minutes=0, email=False)
        rule = save(db, intent, now=start - timedelta(minutes=1))
        db.add(NodeMetric(node_id=node.id, iface='eth0', ts=end, interval_start=end-timedelta(seconds=60),
                          elapsed_seconds=60, quality='valid', rx_delta=100, tx_delta=0))
        db.commit()
        nid, rid, fingerprint, normalized = node.id, rule.id, rule.fingerprint, rule.condition
    path = settings_zip(engine, tmp_path)
    with Session(engine) as db:
        save(db, intent | {'condition': dict(metric='cpu', threshold='70')}, rule_id=rid, revision=1, now=now)
        db.commit()
    restore_settings(engine, path)
    with Session(engine) as db:
        rule = db.get(AlertRule, rid)
        assert (rule.condition, rule.fingerprint, rule.enabled) == (normalized, fingerprint, True)
        evaluate_node(db, nid, now=now + timedelta(seconds=1))
        db.commit()
    with Session(engine) as db:
        assert db.get(AlertState, rid).state == 'ok'
        assert db.query(AlertEvent).count() == 0
        assert db.query(Notification).count() == 0
