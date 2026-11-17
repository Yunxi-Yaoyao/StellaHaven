"""Opt-in PG concurrency on an owned, disposable tmpfs cluster only."""
import os
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.models.node import Node
from app.models.config import AppConfig
from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember

pytestmark=pytest.mark.skipif(not os.getenv('STELLA_MONITOR_V5_PG'),reason='owned disposable PG required')


def test_pg_parallel_create_receipt_and_entry_reconcile(monkeypatch):
    url=make_url(os.environ['STELLA_MONITOR_V5_PG'])
    assert url.host=='127.0.0.1' and url.port not in (25436,24532) and url.database=='monitor_v5'
    engine=create_engine(url)
    try:
        for table in (Node.__table__,Monitor.__table__,MonitorGroup.__table__,MonitorGroupMember.__table__,AppConfig.__table__):table.create(engine)
        from app.services import entry_registry
        from app.services.entry_monitor_groups import reconcile
        from app.services.monitor_groups import create_group
        from app.schemas.monitor import MonitorGroupCreate
        monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':'https://main.example'}})
        with Session(engine) as db:
            n=Node(name='one',host='one.example',platform='linux',token='fixture-one');db.add(n);db.commit();nid=n.id
        data=MonitorGroupCreate(name='atomic',items=[dict(name='one',type='ping',target='one.example',node_id=nid)],request_key='33333333-3333-4333-8333-333333333333')
        def create(_):
            with Session(engine,autoflush=False) as db:return create_group(db,data,session_id='owned-session')['id']
        with ThreadPoolExecutor(max_workers=6) as pool:ids=list(pool.map(create,range(12)))
        assert len(set(ids))==1
        with Session(engine) as db:
            assert db.query(Monitor).count()==1
            n=Node(name='two',host='two.example',platform='linux',token='fixture-two');db.add(n);db.commit();second=n.id
        def sync(nid):
            with Session(engine,autoflush=False) as db:reconcile(db,db.get(Node,nid));db.commit()
        with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(sync,[nid,second]*6))
        with Session(engine) as db:
            assert db.query(Monitor).count()==3 and db.query(MonitorGroup).count()==2
            automatic=db.query(MonitorGroup).filter_by(name='默认入口探测').one()
            assert db.query(MonitorGroupMember).filter_by(group_id=automatic.id).count()==2
            from app.services.monitor_groups import save_group
            assert len(save_group(db,automatic.id,name='renamed entry group')['child_ids'])==2
            assert db.query(AppConfig).filter_by(key='monitor_group.create_receipts.v1').count()==1
    finally:
        engine.dispose()
