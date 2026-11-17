"""Opt-in real PG concurrency; only a disposable stella_policy_* database."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.models.node import Node
from app.models.monitor import Monitor
from app.models.config import AppConfig

@pytest.mark.skipif(not os.getenv('STELLA_POLICY_TEST_DATABASE_URL'),reason='dedicated policy PG required')
def test_concurrent_reconciliation_is_one_durable_monitor():
    url=make_url(os.environ['STELLA_POLICY_TEST_DATABASE_URL'])
    assert url.host=='127.0.0.1' and url.port==25436
    assert url.database.startswith('stella_policy_') and url.database!='stella_preview_20261018'
    engine=create_engine(url)
    with engine.connect() as c:
        assert c.scalar(text('SELECT system_identifier::text FROM pg_control_system()'))=='7698041980212371498'
    for table in (Node.__table__,Monitor.__table__,AppConfig.__table__):table.create(engine)
    from app.services import node_monitor_policy as p
    with Session(engine) as db:
        source=Node(name='explicit source',host='192.168.160.2',platform='linux',status='online',last_seen_at=datetime.now(timezone.utc),components={'monitoring':{'ready':True,'types':['ping']}})
        db.add(source);db.flush()
        target=Node(name='owned target',host='192.168.160.3',platform='linux',status='pending')
        db.add(target);db.commit()
        p.update(db,{'revision':0,'enabled':False,'source_node_id':source.id,'host_node_id':None,'interval':60})
        # Enable without eager reconciliation, then race independent sessions.
        row=db.get(AppConfig,p.KEY)
        import json
        state=json.loads(row.value);state['enabled']=True;row.value=json.dumps(state);db.commit()
    def reconcile(_):
        with Session(engine) as db:p.reconcile(db)
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(reconcile,range(16)))
    with Session(engine) as db:
        assert db.query(Monitor).count()==1
        record=p.read(db)['managed'][0]
        assert record['exists'] is True
        db.delete(db.get(Monitor,record['monitor_id']));db.commit()
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(reconcile,range(16)))
    with Session(engine) as db:
        assert db.query(Monitor).count()==0
        assert p.read(db)['managed'][0]['exists'] is False
    engine.dispose()
