"""Bounded in-process deadline checks, independent of agents and backup jobs.

No leader election/outbox: PostgreSQL writable-primary and per-node transaction
claims fence writes; Node → Rule → State locks/watermarks serialize reports.
"""
import logging
import math
import os
import threading
from time import monotonic
from collections import deque
from contextlib import contextmanager

from sqlalchemy import String, cast, create_engine, event, text
from sqlalchemy.orm import Session

from app.models.alert import AlertRule
from app.models.node import Node
from app.services import alerts

logger = logging.getLogger(__name__)
CLAIM_NAMESPACE = 1937006964


def _writable_primary(db):
    # One round trip; settings are LOCAL to this transaction. Retain a fresh
    # server-side fence before EACH node's claim, not a cached discovery result.
    row = db.execute(text("SELECT set_config('statement_timeout', '2000ms', true), "
                          "set_config('lock_timeout', '250ms', true), "
                          "NOT pg_is_in_recovery(), current_setting('transaction_read_only') = 'off'")).one()
    return bool(row[2] and row[3])


def _ha_admitted():
    if os.getenv('STELLA_HA_MODE') != 'primary-only':
        return True
    # Background work does not pass through PrimaryOnlyMiddleware. Patroni is
    # admission, not a replacement for the database write fence below.
    import httpx
    base = os.getenv('STELLA_PATRONI_URL', 'http://127.0.0.1:8008').rstrip('/')
    with httpx.Client(trust_env=False, timeout=1.0) as client:
        response = client.get(base + '/primary')
    if response.status_code != 200:
        return False
    status = response.json()
    return status.get('state') == 'running' and status.get('role') in ('primary', 'master')


class NodeDeadlineWatcher:
    def __init__(self, engine, *, interval=10.0, clock=None, batch_size=100, cycle_budget=2.0,
                 transaction_budget=10.0, owns_engine=False):
        if (any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0
                for value in (interval, cycle_budget, transaction_budget))
                or type(batch_size) is not int or not 1 <= batch_size <= 100
                or cycle_budget > 5 or transaction_budget > 10):
            raise ValueError('invalid deadline worker budget')
        self.engine, self.interval, self.clock = engine, interval, clock
        self.batch_size, self.cycle_budget = batch_size, cycle_budget
        self.transaction_budget = transaction_budget
        self.owns_engine = owns_engine
        self.stop_event = threading.Event()
        self.timer = None
        self.cursor = 0
        self.pending = deque()
        self.page_short = False
        self.tick_lock = threading.Lock()

    @contextmanager
    def _bounded_connection(self, deadline, *, finish_read=False):
        """Own cancellation until rollback/commit and pool return have finished.

        Transaction deadlines are checked at EVERY SQL boundary (including
        flush and COMMIT); discovery instead admits reads before the soft cycle
        boundary and retains a final read that completes after it. One already
        admitted statement can use its bounded statement timeout. Stop also
        interrupts in-flight libpq; no connection may return to the pool while
        cancellation could still target it. COMMIT rejection explicitly rolls
        back the physical driver transaction, even if SQLAlchemy marked it ended.
        """
        def check(*args):
            if self.stop_event.is_set() or monotonic() >= deadline:
                raise TimeoutError('node deadline transaction cancelled')

        def after_execute(*args):
            # Discovery is read-only and may retain the result of its final
            # admitted statement after the SOFT cycle boundary. Never start a
            # further SQL/COMMIT past it; stop still discards the read at once.
            if finish_read:
                if self.stop_event.is_set():
                    raise TimeoutError('node deadline discovery cancelled')
            else:
                check()

        check()
        with self.engine.connect() as conn:
            driver = conn.connection.driver_connection
            finished = threading.Event()

            def cancel_on_stop():
                while not finished.wait(.01):
                    if self.stop_event.is_set():
                        try:
                            driver.cancel()
                        except Exception as exc:
                            logger.warning('node_deadline_cancel_failed error=%s', type(exc).__name__)
                        return

            # Cancellation lifetime is INSIDE the connection lifetime; join
            # before close/pool return, including exceptions and rollbacks.
            canceller = threading.Thread(target=cancel_on_stop, daemon=True,
                                         name='stella-node-deadline-cancel')
            guards = (('before_cursor_execute', check), ('after_cursor_execute', after_execute),
                      ('commit', check))
            for name, guard in guards:
                event.listen(conn, name, guard)
            canceller.start()
            try:
                check()
                yield conn
            except BaseException:
                # A COMMIT listener can reject before DBAPI commit while
                # SQLAlchemy has ALREADY deactivated its RootTransaction.
                # Session.close()/pool reset may then skip physical rollback.
                # Drain the canceller first, explicitly discard the libpq txn,
                # and never pool a connection whose rollback failed.
                finished.set()
                canceller.join()
                try:
                    driver.rollback()
                except BaseException:
                    conn.invalidate()
                    raise
                raise
            finally:
                finished.set()
                canceller.join()
                for name, guard in guards:
                    event.remove(conn, name, guard)

    @classmethod
    def from_url(cls, url):
        # Private one-connection pool: no competition with request/backup pools.
        # Connect and statement budgets bound shutdown even during DB failure.
        engine = create_engine(url, pool_size=1, max_overflow=0, pool_timeout=2,
                               connect_args={'connect_timeout': 2,
                                   'options': '-c statement_timeout=2000 -c lock_timeout=250'})
        return cls(engine, owns_engine=True)

    def _prepare(self, db):
        return _writable_primary(db)

    def tick(self):
        if self.engine.dialect.name != 'postgresql':
            raise RuntimeError('deadline worker requires a PostgreSQL primary write fence')
        if self.stop_event.is_set() or not self.tick_lock.acquire(blocking=False):
            return 0
        try:
            return self._tick()
        except TimeoutError:
            return 0
        finally:
            self.tick_lock.release()

    def _tick(self):
        deadline = monotonic() + self.cycle_budget
        if not _ha_admitted():
            return 0
        evaluated = 0
        if not self.pending:
            with self._bounded_connection(deadline, finish_read=True) as conn:
                with Session(bind=conn) as db:
                    if not self._prepare(db):
                        return 0
                    ids = [row[0] for row in db.query(Node.id).filter(
                        Node.id > self.cursor, Node.status.in_(['online', 'offline']),
                        db.query(AlertRule.id).filter(
                            AlertRule.kind == 'node_offline', AlertRule.schema_version == 1,
                            AlertRule.enabled.is_(True), AlertRule.archived.is_(False),
                            AlertRule.target == cast(Node.id, String)).exists()
                    ).order_by(Node.id).limit(self.batch_size).all()]
            if not ids:
                self.cursor = 0
                return 0
            self.pending.extend(ids)
            self.page_short = len(ids) < self.batch_size
        while self.pending:
            # Soft admission only: an admitted node has its OWN atomic budget.
            if self.stop_event.is_set() or monotonic() >= deadline:
                break
            node_id = self.pending.popleft()
            try:
                with self._bounded_connection(monotonic() + self.transaction_budget) as conn:
                    with Session(bind=conn) as db:
                        if not self._prepare(db):
                            self.pending.appendleft(node_id)
                            break
                        if not db.scalar(text('SELECT pg_try_advisory_xact_lock(:namespace, :node)'),
                                         {'namespace': CLAIM_NAMESPACE, 'node': node_id}):
                            continue
                        # Same Node → Rule → State evaluator and locked clock.
                        alerts.evaluate_node_rules(db, node_id=node_id,
                                                   now=self.clock() if self.clock else None)
                        db.commit()  # guarded after flush, before physical COMMIT
                        evaluated += 1
            except Exception as exc:
                logger.warning('node_deadline_failed error=%s', type(exc).__name__)
            finally:
                # Busy/failing nodes must not starve the rest of the page.
                self.cursor = node_id
        if not self.pending and self.page_short:
            self.cursor = 0
        return evaluated

    def start(self):
        if self.timer is not None and self.timer.is_alive():
            return
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    logger.warning('node_deadline_cycle_failed error=%s', type(exc).__name__)
                self.stop_event.wait(self.interval)
        self.timer = threading.Thread(target=loop, daemon=True, name='stella-node-deadlines')
        self.timer.start()

    def stop(self):
        self.stop_event.set()
        # Wait for synchronous tick callers too, not only the lifecycle thread.
        # The flag closes SQL/COMMIT admission immediately; the connection owner
        # cancels in-flight libpq and completes rollback before releasing this.
        deadline = monotonic() + 8
        if not self.tick_lock.acquire(timeout=max(0, deadline - monotonic())):
            raise RuntimeError('node deadline worker did not stop within budget')
        self.tick_lock.release()
        if self.timer is not None:
            self.timer.join(max(0, deadline - monotonic()))
            if self.timer.is_alive():
                raise RuntimeError('node deadline worker did not stop within budget')
        if self.owns_engine:
            self.engine.dispose()
