"""Offline query contract plus opt-in, identity-guarded disposable PG proofs.
Run with --noconftest. Never imports app.database/config or production settings.
"""
import importlib.util
import os
from pathlib import Path
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, func, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, Query


@pytest.fixture(scope='module')
def repo():
    # Load the actual model/repository into a private namespace, without DB settings.
    root = Path(__file__).resolve().parents[1]
    namespace = '_traffic_test_' + uuid.uuid4().hex
    package = types.ModuleType(namespace); package.__path__ = [str(root / 'app')]
    models = types.ModuleType(namespace + '.models'); models.__path__ = [str(root / 'app/models')]
    class Base(DeclarativeBase):
        pass
    models.Base = Base; models.Mapped = Mapped; models.mapped_column = mapped_column
    modules = {namespace: package, namespace + '.models': models}
    with patch.dict(sys.modules, modules):
        model_spec = importlib.util.spec_from_file_location(namespace + '.models.node', root / 'app/models/node.py')
        model = importlib.util.module_from_spec(model_spec)
        # Only the import prefix is adapted; all model/query functions are real.
        code = (root / 'app/models/node.py').read_text().replace('from app.models import', f'from {namespace}.models import')
        exec(compile(code, str(root / 'app/models/node.py'), 'exec'), model.__dict__)
        sys.modules[namespace + '.models.node'] = model
        repository = types.ModuleType(namespace + '.repository')
        source = (root / 'app/repositories/node.py').read_text().replace('from app.models.node import', f'from {namespace}.models.node import')
        exec(compile(source, str(root / 'app/repositories/node.py'), 'exec'), repository.__dict__)
        yield repository
        sys.modules.pop(namespace + '.models.node', None)


def capture_query(repo, iface='wlan0', step=300, limit=720, node_id=19, start=None):
    queries = []
    def capture(q):
        queries.append(q.statement)
        return []
    start = start or datetime(2026, 10, 3, 16, 54, 35, 340296, tzinfo=timezone.utc)
    def execute(db, statement):
        queries.append(statement)
        return types.SimpleNamespace(all=lambda: [])
    with Session() as db, patch.object(Query, 'all', capture), patch.object(Session, 'execute', execute):
        repo.get_metrics(db, node_id, iface, start, start + timedelta(days=7), limit, step)
    assert len(queries) == 1  # One SQL statement, not a per-bucket timeout reset.
    return queries[0]


def test_bounded_single_interface_seeks_nonempty_buckets_before_summing(repo):
    sql = str(capture_query(repo).compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    assert 'WITH RECURSIVE' in sql
    assert 'LATERAL' in sql
    assert 'node_metrics.ts < traffic_buckets.ts' in sql
    assert 'traffic_buckets.n < 720' in sql
    assert 'GROUP BY' not in sql


def test_bucket_query_avoids_per_row_numeric_epoch_conversion(repo):
    sql = str(capture_query(repo).compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    assert 'date_bin(' in sql
    assert 'EXTRACT(epoch' not in sql
    assert 'node_metrics.ts >=' in sql and 'node_metrics.ts <=' in sql
    assert 'sum(node_metrics.rx_delta)' in sql and 'sum(node_metrics.tx_delta)' in sql
    assert 'LIMIT 720' in sql and 'DESC' in sql


@pytest.fixture(scope='module')
def pg(repo):
    dsn = os.environ.get('STELLA_TRAFFIC_TEST_DSN')
    if not dsn:
        pytest.skip('requires owned disposable localhost PG')
    url = make_url(dsn)
    assert url.drivername == 'postgresql+psycopg2'
    assert url.host == '127.0.0.1' and url.database == 'stella_test_trafficprobe'
    assert url.username == 'trafficprobe' and url.port and url.port > 1024 and not url.query
    engine = create_engine(url)
    schema = 'traffic_' + uuid.uuid4().hex
    with engine.begin() as c:
        assert c.execute(text("SELECT current_database(), current_user, current_setting('stella.test_isolation', true)")).one() == ('stella_test_trafficprobe', 'trafficprobe', 'traffic-test-only')
        c.execute(text(f'CREATE SCHEMA {schema}'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        repo.Node.metadata.create_all(scoped, tables=[repo.Node.__table__, repo.NodeMetric.__table__])
        yield scoped
    finally:
        with engine.begin() as c:
            c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            assert not c.execute(text('SELECT 1 FROM pg_namespace WHERE nspname=:s'), {'s': schema}).first()
        engine.dispose()


def old_query(db, repo, node_id, iface, start, end, limit, step):
    m = repo.NodeMetric
    bucket = func.to_timestamp(func.floor(func.extract('epoch', m.ts) / step) * step)
    q = db.query(bucket.label('ts'), func.sum(m.rx_delta).label('rx_delta'), func.sum(m.tx_delta).label('tx_delta')).filter(m.node_id == node_id)
    if iface:
        q = q.filter(m.iface == iface)
    if start is not None:
        q = q.filter(m.ts >= start)
    if end is not None:
        q = q.filter(m.ts <= end)
    return q.group_by(bucket).order_by(bucket.desc()).limit(limit)


def normalized(rows):
    return [(r.ts, int(r.rx_delta), int(r.tx_delta)) for r in rows]


@pytest.mark.parametrize('zone', ['UTC', 'Asia/Shanghai', 'America/New_York'])
@pytest.mark.parametrize('step', [6, 7, 30, 300, 86400])
def test_bucket_semantics_negative_epoch_boundaries_and_timezones(repo, pg, zone, step):
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    offsets = [-86401, -601, -600, -300, -1, 0, 1, 6, 7, 299, 300, 301, 86400]
    instants = sorted(set(epoch + timedelta(seconds=i, microseconds=j) for i in offsets for j in (-1, 0, 1)))
    with Session(pg) as db:
        n = repo.Node(name='boundary', host='127.0.0.1', platform='linux'); db.add(n); db.flush()
        for i, ts in enumerate(instants):
            for iface, rx in [('a', i + 1), ('b', 2 * i + 3)]:
                db.add(repo.NodeMetric(node_id=n.id, iface=iface, ts=ts, rx_delta=rx, tx_delta=rx * 2))
        db.commit()
        db.execute(text('SET TRANSACTION READ ONLY'))
        db.execute(text("SELECT set_config('TimeZone', :zone, true)"), {'zone': zone})
        for iface in ('a', None, '', 'missing'):
            for start, end in [(instants[1], instants[-2]), (None, None), (epoch, epoch)]:
                for limit in (1, 3, 5000):
                    expected = normalized(old_query(db, repo, n.id, iface, start, end, limit, step).all())
                    actual = normalized(repo.get_metrics(db, n.id, iface, start, end, limit, step))
                    assert actual == expected
        db.rollback()


def test_long_window_all_buckets_and_exact_interface_statistics(repo, pg):
    start = datetime(2025, 2, 7, 3, 4, 5, 123456, tzinfo=timezone.utc)
    count = 120961  # Full seven days including both endpoints, 5s samples.
    with Session(pg) as db:
        n = repo.Node(name='long', host='127.0.0.1', platform='linux'); db.add(n); db.flush()
        node_id = n.id
        # Interleaved multiple interfaces, not a cached production timestamp.
        for begin in range(0, count, 10000):
            db.bulk_insert_mappings(repo.NodeMetric, [dict(node_id=node_id, iface=iface, ts=start + timedelta(seconds=i * 5), rx_delta=rx, tx_delta=rx * 2) for i in range(begin, min(begin + 10000, count)) for iface, rx in [('wlan0', i % 100), ('background', 100 - i % 100)]])
        db.commit()
        db.execute(text('SET TRANSACTION READ ONLY'))
        db.execute(text("SET LOCAL statement_timeout='5000ms'"))
        schema = pg.get_execution_options()['schema_translate_map'][None]
        statement = capture_query(repo, node_id=node_id, start=start)
        compiled = str(statement.compile(dialect=postgresql.dialect(),
            schema_translate_map={None: schema}, render_schema_translate=True,
            compile_kwargs={'literal_binds': True}))
        plan = db.execute(text('EXPLAIN (FORMAT JSON) ' + compiled)).scalar()[0]['Plan']
        def walk(node):
            yield node
            for child in node.get('Plans', []):
                yield from walk(child)
        nodes = list(walk(plan))
        assert any(p['Node Type'] == 'Recursive Union' for p in nodes)
        assert any(p['Node Type'] == 'Index Only Scan' and p.get('Scan Direction') == 'Backward' for p in nodes)
        assert any(p['Node Type'] == 'Index Scan' and 'traffic_buckets.ts' in p.get('Index Cond', '') for p in nodes)
        assert not any(p['Node Type'] == 'Bitmap Heap Scan' for p in nodes)
        end = start + timedelta(days=7)
        for iface in ('wlan0', None):
            for limit in (1, 720, 2016, 5000):
                old = normalized(old_query(db, repo, node_id, iface, start, end, limit, 300).all())
                new = normalized(repo.get_metrics(db, node_id, iface, start, end, limit, 300))
                assert new == old
            full = repo.get_metrics(db, node_id, iface, start, end, 5000, 300)
            stats = repo.get_traffic_stats(db, node_id, [iface] if iface else None, start, end)
            assert sum(r.rx_delta for r in full) == stats['rx_total']
            assert sum(r.tx_delta for r in full) == stats['tx_total']
            assert stats['sample_count'] == count
            if iface is None:
                assert stats['rx_95'] == stats['rx_max'] == stats['rx_min'] == 100.0
                assert stats['tx_95'] == 200.0
                assert stats['rx_total'] == count * 100
        db.rollback()


def test_raw_path_unchanged(repo):
    for step in (None, 1, 5):
        sql = str(capture_query(repo, step=step).compile(dialect=postgresql.dialect()))
        assert 'date_bin' not in sql and 'GROUP BY' not in sql
        assert 'ORDER BY node_metrics.ts DESC' in sql
