"""Independent admission/transaction budgets and strict rollback on owned PG.

The external original B1/B2 listeners remain unchanged (only owned port adapts).
Discovery-only controls are separate; they never substitute for all-SQL B2.
"""
import threading
import time

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from test_pg import engine, seed
from app.models.alert import AlertEvent, Notification
from app.services.node_deadlines import NodeDeadlineWatcher
from app.services.alerts import _push_ws as real_push_ws, _send_alert_email as real_send_alert_email


@pytest.mark.parametrize('kwargs', [
    {'interval': value} for value in (True, 0, -1, float('nan'), float('inf'), '10')
] + [
    {'batch_size': value} for value in (True, 0, 101, 1.5, '2')
] + [
    {key: value} for key, maximum in (('cycle_budget', 5), ('transaction_budget', 10))
    for value in (True, 0, -1, maximum + .1, float('nan'), float('inf'), '2')
])
def test_invalid_budget_configuration_fails_closed(kwargs):
    with pytest.raises(ValueError, match='invalid deadline worker budget'):
        NodeDeadlineWatcher(object(), **kwargs)


def test_budget_configuration_defaults_and_boundaries():
    worker = NodeDeadlineWatcher(object())
    assert worker.cycle_budget == 2 and worker.transaction_budget == 10
    NodeDeadlineWatcher(object(), interval=.01, batch_size=1, cycle_budget=.01,
                        transaction_budget=.01)
    NodeDeadlineWatcher(object(), batch_size=100, cycle_budget=5, transaction_budget=10)


def test_stop_cancels_subtimeout_node_roundtrips_without_late_commit(engine):
    seed(engine)
    worker = NodeDeadlineWatcher(engine)
    reached = threading.Event()
    active = []

    def delay(conn, cursor, sql, params, context, many):
        if 'pg_try_advisory_xact_lock' in sql:
            active.append(True)
        if active:
            cursor.execute('SELECT pg_sleep(1.0)')
        if 'FROM nodes' in sql and 'FOR UPDATE' in sql:
            reached.set()

    event.listen(engine, 'before_cursor_execute', delay)
    started = time.monotonic()
    try:
        worker.start()
        assert reached.wait(15)
        worker.stop()
        assert worker.timer is not None and not worker.timer.is_alive()
        assert time.monotonic() - started <= 3.0
    finally:
        event.remove(engine, 'before_cursor_execute', delay)
        worker.stop()
        if worker.timer is not None:
            worker.timer.join(40)
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 0


def test_transaction_budget_rolls_back_without_stop(engine):
    # Approved v2 contract: expiry is per admitted transaction, not admission.
    seed(engine)
    worker = NodeDeadlineWatcher(engine, cycle_budget=2, transaction_budget=.25)
    active = []

    def delay(conn, cursor, sql, params, context, many):
        if 'pg_try_advisory_xact_lock' in sql:
            active.append(True)
        if active:
            cursor.execute('SELECT pg_sleep(0.1)')

    event.listen(engine, 'before_cursor_execute', delay)
    started = time.monotonic()
    try:
        worker.tick()
    finally:
        event.remove(engine, 'before_cursor_execute', delay)
    assert time.monotonic() - started < .75
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 0


def test_admitted_transaction_completes_after_admission_budget(engine):
    seed(engine, 2)
    worker = NodeDeadlineWatcher(engine, cycle_budget=.25)
    active = []

    def delay(conn, cursor, sql, params, context, many):
        if 'pg_try_advisory_xact_lock' in sql:
            active.append(True)
        if active:
            cursor.execute('SELECT pg_sleep(0.1)')

    event.listen(engine, 'before_cursor_execute', delay)
    started = time.monotonic()
    try:
        assert worker.tick() == 1
    finally:
        event.remove(engine, 'before_cursor_execute', delay)
    assert .25 < time.monotonic() - started < 3
    assert len(worker.pending) == 1  # no second admission after budget
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 1


@pytest.mark.parametrize('boundary', ['flush', 'commit'])
def test_transaction_expiry_discards_staged_event_state_and_dispatch(engine, monkeypatch, boundary):
    from app.models.alert import AlertState
    from app.services import alerts
    seed(engine)
    worker = NodeDeadlineWatcher(engine, transaction_budget=.25)
    pushed = []
    monkeypatch.setattr(alerts, '_push_ws', pushed.append)
    observed = []

    def expire(conn, *args):
        if observed:
            return
        if boundary == 'flush' and not args[1].startswith('INSERT INTO notifications'):
            return
        cursor = conn.connection.driver_connection.cursor()
        try:
            cursor.execute('SELECT (SELECT count(*) FROM alert_events), (SELECT count(*) FROM notifications)')
            observed.append(cursor.fetchone())
            cursor.execute('SELECT pg_sleep(0.3)')
        finally:
            cursor.close()

    def before_worker_guards(conn):
        # Install before the worker's final COMMIT-admission listener, not an
        # engine-level callback which SQLAlchemy runs AFTER connection listeners.
        event.listen(conn, 'commit', expire)

    hook = 'after_cursor_execute' if boundary == 'flush' else 'engine_connect'
    listener = expire if boundary == 'flush' else before_worker_guards
    event.listen(engine, hook, listener)
    started = time.monotonic()
    try:
        assert worker.tick() == 0
    finally:
        event.remove(engine, hook, listener)
    assert observed == [(1, 1)]  # the work existed INSIDE the uncommitted txn
    assert time.monotonic() - started < .8
    assert pushed == []
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 0
        assert db.query(AlertState).one().state == 'ok'
        assert db.scalar(text('SELECT 1')) == 1


def test_stop_at_last_precommit_boundary_rolls_back_and_drains(engine, monkeypatch):
    from app.services import alerts
    seed(engine)
    worker = NodeDeadlineWatcher(engine)
    reached, release = threading.Event(), threading.Event()
    pushed, failures, stopped = [], [], []
    monkeypatch.setattr(alerts, '_push_ws', pushed.append)

    def hold(conn):
        reached.set()
        assert release.wait(3)

    def run():
        try:
            worker.tick()
        except Exception as exc:
            failures.append(exc)

    def stop():
        try:
            worker.stop()
            stopped.append(True)
        except Exception as exc:
            failures.append(exc)

    def before_worker_guards(conn):
        event.listen(conn, 'commit', hold)

    event.listen(engine, 'engine_connect', before_worker_guards)
    caller = threading.Thread(target=run)
    stopper = threading.Thread(target=stop)
    try:
        caller.start()
        assert reached.wait(3)
        started = time.monotonic()
        stopper.start()
        assert worker.stop_event.wait(1)  # gate is closed before releasing COMMIT
        release.set()
        stopper.join(2)
        caller.join(1)
        assert time.monotonic() - started < 3
        assert not stopper.is_alive() and not caller.is_alive()
        assert stopped == [True] and failures == [] and pushed == []
        assert not any(t.name == 'stella-node-deadline-cancel' for t in threading.enumerate())
    finally:
        release.set()
        caller.join(4)
        if stopper.ident is not None:
            stopper.join(4)
        event.remove(engine, 'engine_connect', before_worker_guards)
        worker.stop()
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 0
        assert db.scalar(text('SELECT 1')) == 1


def test_real_postcommit_delivery_adapters_do_not_hold_worker_stop(engine, monkeypatch):
    import asyncio
    from app.models.alert import AlertRule
    from app.models.user import User
    from app.routers import admin_email, notify_ws
    from app.services import alerts
    seed(engine)
    with Session(engine) as db:
        db.query(AlertRule).one().email = True
        db.add(User(username='owned-admin', display_name='owned', email='owned@invalid.test', is_admin=True))
        db.commit()
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait({'owned': 'full'})
    monkeypatch.setattr(notify_ws, '_queue', queue)
    monkeypatch.setattr(alerts, '_push_ws', real_push_ws)
    monkeypatch.setattr(alerts, '_send_alert_email', real_send_alert_email)
    monkeypatch.setattr(admin_email, '_load', lambda: {'enabled': True, 'host': 'invalid.test'})
    entered, release = threading.Event(), threading.Event()
    mail_threads = []

    def hold_mail(*args):
        mail_threads.append(threading.current_thread())
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(admin_email, '_send', hold_mail)  # never open SMTP
    worker = NodeDeadlineWatcher(engine)
    try:
        worker.start()
        assert entered.wait(3)
        started = time.monotonic()
        worker.stop()
        assert time.monotonic() - started < .75
        assert not worker.timer.is_alive()
        assert mail_threads[0].is_alive()  # separate existing best-effort daemon
        assert not any(t.name == 'stella-node-deadline-cancel' for t in threading.enumerate())
        with Session(engine) as db:
            assert db.query(AlertEvent).count() == db.query(Notification).count() == 1
        assert queue.get_nowait() == {'owned': 'full'}  # WS QueueFull drops, no wait
    finally:
        release.set()
        worker.stop()
        for thread in mail_threads:
            thread.join(3)
            assert not thread.is_alive()


def test_slow_discovery_only_makes_durable_progress(engine):
    seed(engine, 2)
    worker = NodeDeadlineWatcher(engine)
    evaluating = []

    def delay(conn, cursor, sql, params, context, many):
        if 'pg_try_advisory_xact_lock' in sql:
            evaluating.append(True)
        if not evaluating:
            cursor.execute('SELECT pg_sleep(0.55)')

    event.listen(engine, 'before_cursor_execute', delay)
    try:
        counts = [worker.tick(), worker.tick()]
    finally:
        event.remove(engine, 'before_cursor_execute', delay)
    assert sum(counts) > 0
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 2


def test_original_all_roundtrip_slow_discovery_oracle(engine):
    """Keep the original blocker visible; do not xfail or relax its assertion."""
    seed(engine, 2)
    worker = NodeDeadlineWatcher(engine)

    def slow(conn, cursor, sql, params, context, many):
        cursor.execute('SELECT pg_sleep(0.55)')

    event.listen(engine, 'before_cursor_execute', slow)
    try:
        counts = [worker.tick(), worker.tick()]
    finally:
        event.remove(engine, 'before_cursor_execute', slow)
    with Session(engine) as db:
        fired = db.query(AlertEvent).count()
    print({'evaluated_per_tick': counts, 'cursor': worker.cursor, 'fired': fired})
    assert fired > 0, 'every tick spends its budget rediscovering the same page and evaluates nothing'


def test_discovery_exhaustion_caches_each_page_for_next_tick(engine):
    ids = seed(engine, 5)
    worker = NodeDeadlineWatcher(engine, batch_size=2)
    discovering = True
    pages = []

    def delay(conn, cursor, sql, params, context, many):
        nonlocal discovering
        if 'pg_try_advisory_xact_lock' in sql:
            discovering = False
        if discovering:
            cursor.execute('SELECT pg_sleep(1.05)')  # each SQL below 2s

    event.listen(engine, 'before_cursor_execute', delay)
    try:
        for expected in (ids[:2], ids[2:4], ids[4:]):
            discovering = True
            assert worker.tick() == 0  # discovery alone spends > 2s
            assert list(worker.pending) == expected
            pages.append(list(worker.pending))
            discovering = False
            assert worker.tick() == len(expected)  # cached page, fresh tx budgets
            assert not worker.pending
    finally:
        event.remove(engine, 'before_cursor_execute', delay)
    assert [node for page in pages for node in page] == ids
    assert worker.cursor == 0
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 5
    assert worker.tick() == 2  # wrap is live; already-firing nodes don't duplicate
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 5


def test_stop_drains_direct_tick_and_inflight_libpq_before_pool_return(engine):
    seed(engine)
    worker = NodeDeadlineWatcher(engine)
    reached = threading.Event()
    failures = []

    def delay(conn, cursor, sql, params, context, many):
        if 'pg_try_advisory_xact_lock' in sql:
            reached.set()
            cursor.execute('SELECT pg_sleep(1.5)')

    def run():
        try:
            worker.tick()
        except Exception as exc:
            failures.append(exc)

    event.listen(engine, 'before_cursor_execute', delay)
    caller = threading.Thread(target=run)
    try:
        caller.start()
        assert reached.wait(3)
        started = time.monotonic()
        worker.stop()
        assert time.monotonic() - started < .75
        caller.join(1)
        assert not caller.is_alive() and failures == []
        assert not any(t.name == 'stella-node-deadline-cancel' for t in threading.enumerate())
    finally:
        event.remove(engine, 'before_cursor_execute', delay)
        worker.stop()
        caller.join(3)
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 0
        # Same pool is healthy, no cancellation targets a future borrower.
        assert db.scalar(text('SELECT 1')) == 1
