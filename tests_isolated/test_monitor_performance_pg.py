"""Explicitly opt-in PG proofs on an audit-owned disposable localhost database.
No real agent is running; tasks are ORM rows only. Never use app settings DSN.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.models import Base
from app.models.node import Node, NodeMetric, NodeSysMetric
from app.models.monitor import Monitor, MonitorCheck
from app.models.task import IperfTask
from app.repositories import node as node_repo, monitor as monitor_repo, task as task_repo

@pytest.fixture
def engine():
    dsn = os.environ.get('STELLA_PERFORMANCE_TEST_DSN')
    if not dsn: pytest.skip('requires audit-owned disposable PG')
    url = make_url(dsn)
    assert url.host == '127.0.0.1' and url.database == 'stella_perf_test'
    assert url.username == 'performance' and url.port and url.port > 1024 and not url.query
    engine = create_engine(url)
    schema = 'perf_' + uuid.uuid4().hex
    with engine.begin() as conn:
        assert conn.execute(text("SELECT current_database(), current_user, current_setting('stella.test_isolation',true)")).one() == ('stella_perf_test','performance','performance-test-only')
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    scoped = engine.execution_options(schema_translate_map={None:schema})
    Base.metadata.create_all(scoped, tables=[Node.__table__,NodeMetric.__table__,NodeSysMetric.__table__,Monitor.__table__,MonitorCheck.__table__,IperfTask.__table__])
    try: yield scoped
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            assert not conn.execute(text('SELECT 1 FROM pg_namespace WHERE nspname=:s'),{'s':schema}).first()
        engine.dispose()


def test_parallel_create_exactly_one_then_cancel_releases(engine):
    with Session(engine) as db:
        n=Node(name='synthetic',host='127.0.0.1',platform='linux'); db.add(n); db.commit(); node_id=n.id
    barrier=Barrier(8)
    def create():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            try:
                t=task_repo.create_iperf(db,None,node_id,'speedtest','forward',10,1)
                return ('created',t.id)
            except ValueError: return ('rejected',None)
    with ThreadPoolExecutor(max_workers=8) as pool: rows=list(pool.map(lambda _:create(),range(8)))
    assert sum(r[0]=='created' for r in rows)==1
    assert sum(r[0]=='rejected' for r in rows)==7
    with Session(engine) as db:
        assert db.query(IperfTask).filter(IperfTask.status.in_(['pending','running'])).count()==1
        t=db.query(IperfTask).one(); t.status='cancelled'; db.commit()
        task_repo.create_iperf(db,None,node_id,'speedtest','forward',10,1)
        assert db.query(IperfTask).filter(IperfTask.status.in_(['pending','running'])).count()==1


def test_exact_multi_interface_percentile_and_bucket_totals(engine):
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    with Session(engine) as db:
        n=Node(name='synthetic',host='127.0.0.1',platform='linux'); db.add(n); db.flush()
        for i in range(100):
            for iface,rx in [('a',i),('b',100-i)]:
                db.add(NodeMetric(node_id=n.id,iface=iface,ts=start+timedelta(seconds=i*5),rx_delta=rx,tx_delta=rx*2))
        db.commit()
        stats=node_repo.get_traffic_stats(db,n.id,None,start,start+timedelta(hours=1))
        assert stats=={'rx_95':100.0,'tx_95':200.0,'rx_max':100.0,'rx_min':100.0,'tx_max':200.0,'tx_min':200.0,'rx_total':10000,'tx_total':20000,'sample_count':100}
        points=node_repo.get_metrics(db,n.id,None,start,start+timedelta(hours=1),5000,30)
        assert sum(p.rx_delta for p in points)==stats['rx_total']
        assert sum(p.tx_delta for p in points)==stats['tx_total']


def test_monitor_bucket_counts_include_all_raw_samples(engine):
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    with Session(engine) as db:
        n=Node(name='synthetic',host='127.0.0.1',platform='linux'); db.add(n); db.flush()
        m=Monitor(name='test',type='ping',target='localhost',node_id=n.id,interval=1,timeout=1); db.add(m); db.flush()
        db.bulk_insert_mappings(MonitorCheck,[{'monitor_id':m.id,'ts':start+timedelta(seconds=i),'success':i!=9999,'latency_ms':10 if i!=9999 else None,'loss_pct':0} for i in range(10000)])
        db.commit()
        points=monitor_repo.list_checks_bucketed(db,m.id,start,start+timedelta(hours=3),3600,24)
        assert sum(p['sample_count'] for p in points)==10000
        assert sum(p['success_count'] for p in points)==9999
        assert sum(p['latency_count'] for p in points)==9999
        assert len(points)==3


def test_stale_task_releases_global_admission(engine):
    from app.services.task import create_iperf
    now=datetime.now(timezone.utc)
    with Session(engine) as db:
        n=Node(name='synthetic',host='127.0.0.1',platform='linux',status='online',installed=True,last_seen_at=now)
        db.add(n);db.flush()
        t=IperfTask(client_node_id=n.id,mode='speedtest',direction='forward',duration=10,parallel=1,status='pending',created_at=now-timedelta(minutes=6))
        db.add(t);db.commit()
        create_iperf(db,None,n.id,'speedtest','forward',10,1)
        assert db.query(IperfTask).filter(IperfTask.status=='failed').count()==1
        assert db.query(IperfTask).filter(IperfTask.status.in_(['pending','running'])).count()==1


def test_concurrent_http_creation_returns_one_201_and_seven_409(engine):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.task import router, current_user, admin_user, get_db
    now=datetime.now(timezone.utc)
    with Session(engine) as db:
        n=Node(name='synthetic',host='127.0.0.1',platform='linux',status='online',installed=True,last_seen_at=now)
        db.add(n);db.commit();node_id=n.id
    app=FastAPI();app.include_router(router)
    app.dependency_overrides[current_user]=lambda: object()
    app.dependency_overrides[admin_user]=lambda: object()
    def private_db():
        with Session(engine) as db: yield db
    app.dependency_overrides[get_db]=private_db
    barrier=Barrier(8)
    with TestClient(app) as client:
        def post():
            barrier.wait(timeout=10)
            return client.post('/iperf-tasks',json={'client_node_id':node_id,'server_node_id':None,'mode':'speedtest'}).status_code
        with ThreadPoolExecutor(max_workers=8) as pool: statuses=list(pool.map(lambda _:post(),range(8)))
    assert sorted(statuses)==[201]+[409]*7
    with Session(engine) as db:
        assert db.query(IperfTask).filter(IperfTask.status.in_(['pending','running'])).count()==1


def test_real_query_timeout_rollback_remains_usable(engine):
    from app.services.node import run_history_query
    from fastapi import HTTPException
    with Session(engine) as db:
        with pytest.raises(HTTPException) as error:
            run_history_query(db,lambda db: db.execute(text('SELECT pg_sleep(6)')))
        assert error.value.status_code==503
        assert db.execute(text('SELECT 1')).scalar()==1
