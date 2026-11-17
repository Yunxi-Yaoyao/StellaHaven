import json
from sqlalchemy import text
from sqlalchemy.orm import Session


def notes(engine):
    from app.models.alert import Notification
    with Session(engine) as db:
        return [(n.dedupe_key, n.title, n.body, n.context) for n in db.query(Notification).order_by(Notification.id)]


def test_durable_intent_rollback_commit_retry_and_ws_readback(engine, monkeypatch):
    from app.services import result_notifications as results, alerts
    pushed = []
    def push(payload):
        assert any(n[0] == 'backup:job1' for n in notes(engine))
        pushed.append(payload)
    monkeypatch.setattr(alerts, '_push_ws', push)
    data = dict(source='backup', operation_id='job1', outcome='success', title='备份完成', body='真实持久结果')
    with engine.connect() as conn:
        results.stage_result(conn, **data)
        assert results.deliver_pending(engine) == 0
        conn.rollback()
    assert results.deliver_pending(engine) == 0 and notes(engine) == [] and pushed == []
    with engine.begin() as conn:
        results.stage_result(conn, **data)
    original = results.publish_result
    def fault(*a, **kw):
        original(*a, **kw)
        raise RuntimeError('SQL password=DO_NOT_LEAK')
    monkeypatch.setattr(results, 'publish_result', fault)
    assert results.deliver_pending(engine) == 0
    assert notes(engine) == [] and pushed == []
    monkeypatch.setattr(results, 'publish_result', original)
    assert results.deliver_pending(engine) == 1
    assert len(notes(engine)) == len(pushed) == 1
    with engine.begin() as conn:
        results.stage_result(conn, **data)
    assert results.deliver_pending(engine) == 1
    assert len(notes(engine)) == len(pushed) == 1


def seed_mtr(engine, statuses=('running',), trigger='manual', job_id='manual-job'):
    from app.models.node import Node
    from app.models.task import MtrTask
    with Session(engine) as db:
        rows=[]
        for i, status in enumerate(statuses):
            node=Node(name='fixture', platform='linux', host='192.0.2.1', status='online')
            db.add(node); db.flush()
            row=MtrTask(node_id=node.id, target='example.test', protocol='icmp', trigger=trigger,
                        job_id=job_id, status=status)
            db.add(row);db.flush();rows.append(row.id)
        db.commit()
        return rows


def test_real_mtr_finish_single_and_fanout_waits_all_then_one_safe_summary(engine, monkeypatch):
    from app.services import task, alerts
    from app.models.task import MtrTask
    pushed=[]
    monkeypatch.setattr(alerts, '_push_ws', pushed.append)
    ids=seed_mtr(engine, ('running','running'))
    with Session(engine, autoflush=False) as db:
        task.finish_mtr(db,ids[0],'done',{'hops':[]})
    assert notes(engine)==[] and pushed==[]
    with Session(engine, autoflush=False) as db:
        task.finish_mtr(db,ids[1],'failed',{'error':'SQL password=DO_NOT_LEAK'})
    result=notes(engine)
    assert len(result)==len(pushed)==1
    assert result[0][0]=='manual_test:mtr:manual-job'
    assert result[0][3]['outcome']=='failure' and len(result[0][3]['node_ids'])==2
    assert 'DO_NOT_LEAK' not in str(result)
    with Session(engine) as db:
        task.finish_mtr(db,ids[1],'done',{'hops':[]})
        assert db.get(MtrTask,ids[1]).status=='failed'
    assert len(notes(engine))==1
    single=seed_mtr(engine, job_id='single-job')[0]
    with Session(engine) as db:task.finish_mtr(db,single,'done',{'hops':[]})
    assert notes(engine)[1][3]['outcome']=='success' and len(notes(engine))==2


def test_actual_backup_zip_and_failure_publish_without_status_refresh(engine, tmp_path, monkeypatch):
    from app.services.backup_center import BackupCenter
    from app.services import backup_center as module, alerts
    from contextlib import contextmanager
    from app.services import ha_state
    with engine.begin() as conn: ha_state.metadata.create_all(conn)
    center=BackupCenter(engine,tmp_path,key=b'fixture')
    pushed=[]
    def push(payload):
        with engine.connect() as conn:
            stored=json.loads(conn.execute(text("SELECT value FROM app_config WHERE key='backup_center_v1'")).scalar_one())
        assert stored['job']['state'] in ('succeeded','failed')
        assert any(n[0]==payload['kind'].replace('_result','')+':'+payload['context']['operation_id'] for n in notes(engine))
        pushed.append(payload)
    monkeypatch.setattr(alerts,'_push_ws',push)
    job=center.submit('backup','settings');center.wait()
    assert len(notes(engine))==len(pushed)==1
    assert notes(engine)[0][0]=='backup:'+job['id']
    assert notes(engine)[0][3]['outcome']=='success'
    records=center.store().records()
    assert len(records)==1
    with center.store().open_record(records[0]['id']) as (record,stream):
        import zipfile
        with zipfile.ZipFile(stream) as archive:
            assert archive.testzip() is None and 'manifest.json' in archive.namelist()
    @contextmanager
    def fail(*args):
        raise RuntimeError('SQL password=DO_NOT_LEAK')
        yield
    monkeypatch.setattr(module,'export_settings',fail)
    job=center.submit('backup','settings');center.wait()
    assert len(notes(engine))==len(pushed)==2
    assert notes(engine)[1][3]['outcome']=='failure'
    assert 'operation_failed' in notes(engine)[1][2] and 'DO_NOT_LEAK' not in str(notes(engine))
    assert center.store().records()==records
