"""Concurrent result transactions, crash retry and no-fake-terminal guards."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import time

import pytest
from sqlalchemy import text, event
from sqlalchemy.orm import Session

from tests_result_producers.test_results import notes, seed_mtr


def test_eight_authorized_fanout_finishes_one_summary_with_cached_siblings(engine, monkeypatch):
    from app.services import task, alerts
    from app.models.node import Node
    from app.models.task import MtrTask
    ids=seed_mtr(engine, ('running',)*8)
    with Session(engine) as db:
        for i in ids:
            row=db.get(MtrTask,i);db.get(Node,row.node_id).token='fixture-'+str(i)
        db.commit()
    barrier=threading.Barrier(8)
    pushed=[];monkeypatch.setattr(alerts,'_push_ws',pushed.append)
    def finish(i):
        with Session(engine,autoflush=False) as db:
            cached=db.query(MtrTask).all()  # retain stale identity-map observations
            task.authorize_agent_task(db,'fixture-'+str(i),'mtr',i,status='done')
            barrier.wait(timeout=5)
            task.finish_mtr(db,i,'done',{'hops':[]})
            assert cached
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(finish,ids))
    result=notes(engine)
    assert len(result)==len(pushed)==1
    assert result[0][3]['outcome']=='success' and len(result[0][3]['node_ids'])==8


def test_finish_commit_failure_rolls_back_result_intent_and_ws_then_retry(engine, monkeypatch):
    from app.services import task, alerts
    from app.models.task import MtrTask
    ids=seed_mtr(engine)
    pushed=[];monkeypatch.setattr(alerts,'_push_ws',pushed.append)
    # Real PG deferred constraint failure occurs only at actual COMMIT.
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE commit_guard (id int PRIMARY KEY, task_id int REFERENCES mtr_tasks(id) DEFERRABLE INITIALLY DEFERRED)'))
    with Session(engine) as db:
        db.execute(text('INSERT INTO commit_guard VALUES (1,-99999)'))
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):task.finish_mtr(db,ids[0],'done',{'hops':[]})
        db.rollback()
    with Session(engine) as db:
        assert db.get(MtrTask,ids[0]).status=='running'
        assert db.execute(text("SELECT count(*) FROM app_config WHERE key LIKE 'result_notice_v1:%'")).scalar_one()==0
    assert notes(engine)==[] and pushed==[]
    with Session(engine) as db:task.finish_mtr(db,ids[0],'done',{'hops':[]})
    assert len(notes(engine))==len(pushed)==1


def test_delivery_failure_keeps_committed_mtr_then_existing_off_timer_retries(engine,tmp_path,monkeypatch,caplog):
    from app.services import task, result_notifications as results
    from app.services.backup_center import BackupCenter
    from app.models.task import MtrTask
    ids=seed_mtr(engine)
    original=results.publish_result
    def fail(*a,**kw):raise RuntimeError('SQL password=DO_NOT_LEAK')
    monkeypatch.setattr(results,'publish_result',fail)
    with Session(engine) as db:task.finish_mtr(db,ids[0],'done',{'hops':[]})
    with Session(engine) as db:assert db.get(MtrTask,ids[0]).status=='done'
    assert notes(engine)==[] and 'DO_NOT_LEAK' not in caplog.text
    monkeypatch.setattr(results,'publish_result',original)
    restarted=BackupCenter(engine,tmp_path/'absent',key=b'fixture')
    restarted.start(interval=.02)
    try:
        deadline=time.monotonic()+3
        while not notes(engine) and time.monotonic()<deadline:time.sleep(.02)
    finally:restarted.stop()
    assert len(notes(engine))==1 and not (tmp_path/'absent').exists()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM app_config WHERE key='backup_center_v1'")).scalar_one()==0


def test_scheduled_mtr_live_partial_unknown_and_ordinary_patch_do_not_notify(engine,tmp_path):
    from app.services import task
    from app.services.backup_center import BackupCenter
    ids=seed_mtr(engine, trigger='scheduled')
    with Session(engine) as db:task.finish_mtr(db,ids[0],'done',{'hops':[]})
    ids=seed_mtr(engine, ('running','unknown'), job_id='unknown')
    unclaimed=seed_mtr(engine, ('pending',), job_id='unclaimed')[0]
    with Session(engine) as db:task.finish_mtr(db,unclaimed,'done',{'hops':[]})
    with Session(engine) as db:
        task.update_mtr_live(db,ids[0],{'hops':[]})
        task.finish_mtr(db,ids[0],'done',{'hops':[]})
    center=BackupCenter(engine,tmp_path/'absent',key=b'fixture')
    center.patch({'expected_revision':0,'time':'04:00'})
    center.status()
    assert notes(engine)==[] and not (tmp_path/'absent').exists()


def test_lost_backup_ownership_and_interruption_never_publish_fake_terminal(engine,tmp_path,monkeypatch):
    from app.services import backup_center as module
    from app.services.backup_center import BackupCenter
    from app.services import ha_state
    with engine.begin() as conn:ha_state.metadata.create_all(conn)
    center=BackupCenter(engine,tmp_path,key=b'fixture')
    original=module.export_settings
    @contextmanager
    def lost(*args):
        with original(*args) as payload:
            def demoted(conn):raise RuntimeError('SQL password=DO_NOT_LEAK')
            monkeypatch.setattr(center,'_primary',demoted)
            yield payload
    monkeypatch.setattr(module,'export_settings',lost)
    center.submit('backup','settings');center.wait()
    assert notes(engine)==[] and center.store().records()==[]
    restarted=BackupCenter(engine,tmp_path,key=b'fixture');restarted.recover()
    assert restarted.status()['job']['state']=='interrupted' and notes(engine)==[]


def test_backup_notification_fault_cannot_rewrite_success_and_timer_recovers(engine,tmp_path,monkeypatch,caplog):
    from app.services import result_notifications as results
    from app.services.backup_center import BackupCenter, EXEC_LOCK
    from app.services import ha_state
    with engine.begin() as conn:ha_state.metadata.create_all(conn)
    original=results.publish_result
    def fault(*a,**kw):raise RuntimeError('SQL password=DO_NOT_LEAK')
    monkeypatch.setattr(results,'publish_result',fault)
    center=BackupCenter(engine,tmp_path,key=b'fixture')
    job=center.submit('backup','settings');center.wait()
    assert center.status()['job']['state']=='succeeded' and len(center.store().records())==1
    assert notes(engine)==[] and 'DO_NOT_LEAK' not in caplog.text
    monkeypatch.setattr(results,'publish_result',original)
    with engine.connect() as conn:
        conn.execute(text('SELECT pg_advisory_lock(:key)'),{'key':EXEC_LOCK});conn.commit()
        try:center._job(conn,job['id'],state='failed',stage='failed')
        finally:
            conn.rollback();conn.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':EXEC_LOCK});conn.commit()
    assert center.status()['job']['state']=='succeeded'
    restarted=BackupCenter(engine,tmp_path,key=b'fixture');restarted.start(interval=.02)
    try:
        deadline=time.monotonic()+3
        while not notes(engine) and time.monotonic()<deadline:time.sleep(.02)
    finally:restarted.stop()
    assert len(notes(engine))==1 and notes(engine)[0][3]['outcome']=='success'


def test_backup_terminal_commit_failure_never_emits_success(engine,tmp_path,monkeypatch):
    from app.services import result_notifications as results, ha_state, alerts
    from app.services.backup_center import BackupCenter
    with engine.begin() as conn:
        ha_state.metadata.create_all(conn)
        conn.execute(text('CREATE TABLE commit_guard (id int PRIMARY KEY, task_id int REFERENCES mtr_tasks(id) DEFERRABLE INITIALLY DEFERRED)'))
    original=results.stage_result
    injected=[];pushed=[];monkeypatch.setattr(alerts,'_push_ws',pushed.append)
    def fail_commit(conn,**data):
        original(conn,**data)
        if data['outcome']=='success':
            injected.append(True)
            conn.execute(text('INSERT INTO commit_guard VALUES (1,-99999)'))
    monkeypatch.setattr(results,'stage_result',fail_commit)
    center=BackupCenter(engine,tmp_path,key=b'fixture')
    center.submit('backup','settings');center.wait()
    job=center.status()['job']
    assert injected==[True] and job['state']=='failed' and job['reason_code']=='database_unavailable'
    assert len(notes(engine))==len(pushed)==1 and notes(engine)[0][3]['outcome']=='failure'


def test_notification_actual_commit_failure_retains_intent_and_never_pushes(engine,monkeypatch):
    from app.services import result_notifications as results, alerts
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE commit_guard (id int PRIMARY KEY, task_id int REFERENCES mtr_tasks(id) DEFERRABLE INITIALLY DEFERRED)'))
        results.stage_result(conn,source='backup',operation_id='commit-fault',outcome='success',title='完成',body='持久结果')
    original=results.publish_result;pushed=[];monkeypatch.setattr(alerts,'_push_ws',pushed.append)
    def fail_commit(db,**data):
        note=original(db,**data)
        db.execute(text('INSERT INTO commit_guard VALUES (1,-99999)'))
        return note
    monkeypatch.setattr(results,'publish_result',fail_commit)
    assert results.deliver_pending(engine)==0 and notes(engine)==[] and pushed==[]
    monkeypatch.setattr(results,'publish_result',original)
    assert results.deliver_pending(engine)==1 and len(notes(engine))==len(pushed)==1


def test_concurrent_delivery_is_duplicate_safe_and_each_batch_bounded(engine,monkeypatch):
    from app.services import result_notifications as results, alerts
    pushed=[];monkeypatch.setattr(alerts,'_push_ws',pushed.append)
    with engine.begin() as conn:
        for i in range(20):
            results.stage_result(conn,source='backup',operation_id='batch-'+str(i),outcome='success',title='完成',body='持久结果')
    assert results.deliver_pending(engine)==16 and len(notes(engine))==16
    with ThreadPoolExecutor(max_workers=8) as pool:
        counts=list(pool.map(lambda _:results.deliver_pending(engine),range(8)))
    assert sum(counts)==4 and len(notes(engine))==len(pushed)==20
    assert len({n[0] for n in notes(engine)})==20


def test_stale_cached_replay_cannot_replace_persisted_terminal(engine):
    from app.services import task
    from app.models.task import MtrTask
    row_id=seed_mtr(engine)[0]
    with Session(engine,autoflush=False) as stale:
        cached=stale.get(MtrTask,row_id)
        with Session(engine) as fresh:task.finish_mtr(fresh,row_id,'done',{'hops':[]})
        assert cached.status=='running'
        task.finish_mtr(stale,row_id,'failed',{'error':'late reply'})
    with Session(engine) as fresh:assert fresh.get(MtrTask,row_id).status=='done'
    assert len(notes(engine))==1 and notes(engine)[0][3]['outcome']=='success'
