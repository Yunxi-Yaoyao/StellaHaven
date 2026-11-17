"""Owned loopback PG only; no application startup, agents, mail or external WS."""
import os
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.models import Base
from app.models.alert import AlertRule, AlertState, AlertEvent, Notification
from app.services import alerts

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)

@pytest.fixture()
def db(monkeypatch):
    url = os.environ['ALERT_FEEDBACK_TEST_URL']
    from sqlalchemy.engine import make_url
    u = make_url(url)
    assert (u.host, u.username, u.database) == ('127.0.0.1', 'stella_alert_test', 'alerts_test')
    assert u.port != 5432
    engine = create_engine(url)
    with engine.begin() as c:
        assert c.execute(text("select current_database(),current_user,current_setting('stella.test_isolation')")).one() == ('alerts_test', 'stella_alert_test', 'alerts-feedback-owned')
        Base.metadata.create_all(c)
    monkeypatch.setattr(alerts, '_push_ws', lambda p: None)
    monkeypatch.setattr(alerts, '_send_alert_email', lambda p: pytest.fail('real mail must not be scheduled'))
    with Session(engine) as session:
        yield session
        session.rollback()
    with engine.begin() as c:
        assert c.execute(text("select current_setting('stella.test_isolation')")).scalar_one() == 'alerts-feedback-owned'
        Base.metadata.drop_all(c)
    engine.dispose()


def rule(db):
    return alerts.create_rule(db, 'node_offline', '12', label='HK', link='/status/12', debounce=1, repeat_minutes=1, email=False)


def test_one_episode_owns_reminders_and_recovery_with_actual_evaluation_times(db):
    r = rule(db)
    alerts._evaluate(db, r, True, 'no heartbeat', NOW)
    alerts._evaluate(db, r, True, 'still absent', NOW + timedelta(minutes=2))
    alerts._evaluate(db, r, False, 'online', NOW + timedelta(minutes=3))
    db.flush()
    from app.services.alert_history import list_incidents, incident_detail
    page = list_incidents(db, now=NOW + timedelta(minutes=4))
    assert page['total'] == 1
    incident = page['items'][0]
    assert incident['started_at'] == NOW
    assert incident['resolved_at'] == NOW + timedelta(minutes=3)
    assert incident['duration_seconds'] == 180
    assert incident['status'] == 'resolved'
    detail = incident_detail(db, incident['id'], now=NOW + timedelta(minutes=4))
    assert [n['context']['event'] for n in detail['notifications']] == ['fired', 'remind', 'resolved']
    assert {n['context']['incident_id'] for n in detail['notifications']} == {incident['id']}
    assert db.query(AlertEvent).count() == 2
    alerts.mark_all_read(db)
    assert db.get(AlertState, r.id).state == 'ok'


def test_delete_archives_definition_and_history_without_recovering_and_allows_recreate(db):
    r = rule(db)
    alerts._evaluate(db, r, True, 'absent', NOW)
    event_id = db.query(AlertEvent).one().id
    alerts.delete_rule(db, r.id)
    assert alerts.get_rule(db, r.id) is None
    assert alerts.list_rules(db) == []
    assert db.get(AlertEvent, event_id) is not None
    assert db.get(AlertState, r.id).state == 'firing'
    from app.services.alert_history import list_incidents
    item = list_incidents(db)['items'][0]
    assert item['status'] == 'unresolved' and item['archived'] is True
    assert rule(db).id != r.id
    with pytest.raises(ValueError):
        alerts.update_rule(db, r.id, {'enabled': True})
    alerts.mark_all_read(db)
    assert db.get(AlertState, r.id).state == 'firing'


def test_old_missing_transitions_stay_unknown_and_pair_before_date_filter_and_pagination(db):
    r = rule(db)
    db.add_all([AlertEvent(rule_id=r.id,event='resolved',ts=NOW,message='orphan'),
                AlertEvent(rule_id=r.id,event='fired',ts=NOW+timedelta(minutes=1)),
                AlertEvent(rule_id=r.id,event='fired',ts=NOW+timedelta(minutes=2)),
                AlertEvent(rule_id=r.id,event='resolved',ts=NOW+timedelta(minutes=3))])
    db.flush()
    from app.services.alert_history import list_incidents
    p = list_incidents(db, now=NOW+timedelta(minutes=4),limit=1,offset=0)
    assert p['total'] == 3 and len(p['items']) == 1
    assert p['items'][0]['duration_seconds'] == 60
    old = list_incidents(db,limit=1,offset=2)['items'][0]
    assert old['start_missing'] and old['started_at'] is None and old['duration_seconds'] is None
    incomplete = list_incidents(db,status='incomplete')
    assert incomplete['total'] == 2
    assert all(i['duration_seconds'] is None for i in incomplete['items'])
    p = list_incidents(db,since=NOW+timedelta(minutes=2,seconds=30))
    assert p['total'] == 0  # filter incident start, not its recovery row
    p = list_incidents(db,until=NOW+timedelta(minutes=2,seconds=30))
    assert p['items'][0]['resolved_at'] == NOW+timedelta(minutes=3)


def test_result_notification_is_terminal_only_idempotent_and_dispatched_after_commit(db,monkeypatch):
    from app.services.notifications import publish_result
    pushed=[]
    monkeypatch.setattr(alerts,'_push_ws',pushed.append)
    with pytest.raises(ValueError):
        publish_result(db,source='backup',operation_id='job-1',outcome='running',title='test',body='test')
    a=publish_result(db,source='backup',operation_id='job-1',outcome='failure',title='备份失败',body='旧备份保留')
    b=publish_result(db,source='backup',operation_id='job-1',outcome='failure',title='备份失败',body='旧备份保留')
    assert a.id==b.id and db.query(Notification).count()==1 and pushed==[]
    db.commit()
    assert len(pushed)==1 and pushed[0]['kind']=='backup_result'
    publish_result(db,source='manual_test',operation_id='job-2',outcome='success',title='手测完成',body='真实结果')
    db.rollback()
    assert len(pushed)==1 and db.query(Notification).count()==1


def test_v2_archive_retains_conditions_and_allows_a_new_identical_rule(db):
    from app.services import alert_metrics
    from app.models.node import Node
    n=Node(name='synthetic',platform='linux',host='192.0.2.1',status='online');db.add(n);db.flush()
    data={'node_id':n.id,'label':'CPU','condition':{'metric':'cpu','threshold':'80'},'email':False,'debounce':1}
    r=alert_metrics.save(db,data,now=NOW);old_condition=dict(r.condition)
    alerts._evaluate(db,r,True,'high',NOW+timedelta(seconds=1))
    alerts.delete_rule(db,r.id)
    assert alert_metrics.list_rules(db)==[] and r.condition==old_condition
    replacement=alert_metrics.save(db,data,now=NOW+timedelta(seconds=2))
    assert replacement.id!=r.id
    with pytest.raises(ValueError,match='不存在'):
        alert_metrics.save(db,data,rule_id=r.id,revision=r.revision,now=NOW+timedelta(seconds=3))
    assert db.query(AlertEvent).filter_by(rule_id=r.id).count()==1


def test_current_network_incident_uses_metric_freshness_not_generic_three_minutes(db):
    r=AlertRule(kind='node_metric',target='12',schema_version=2,label='network',condition={'metric':'network.rate','threshold':'1','interface':'eth0','direction':'out'},debounce=1,email=False,enabled=True)
    db.add(r);db.flush();alerts._evaluate(db,r,True,'high',NOW)
    s=db.get(AlertState,r.id);s.evaluated_at=NOW;s.watermark=NOW;s.preview={'quality':'valid','bad':True};db.flush()
    from app.services.alert_history import list_incidents
    assert list_incidents(db,now=NOW+timedelta(seconds=44))['items'][0]['observation']=='recent'
    assert list_incidents(db,now=NOW+timedelta(seconds=46))['items'][0]['observation']=='unknown'


def test_snapshots_do_not_follow_later_rule_edits(db):
    r=rule(db);alerts._evaluate(db,r,True,'absent',NOW)
    alerts.update_rule(db,r.id,{'label':'new name','severity':'critical'})
    from app.services.alert_history import list_incidents
    old=list_incidents(db)['items'][0]
    assert old['label']=='HK' and old['severity']=='warning'


def test_firing_state_without_start_evidence_is_not_a_healthy_empty_list(db):
    r=rule(db)
    s=db.get(AlertState,r.id);s.state='firing';s.last_change_at=NOW;db.flush()
    from app.services.alert_history import list_incidents
    p=list_incidents(db,status='unresolved')
    assert p['total']==0
    assert p['untracked']==[{'rule_id':r.id,'label':'HK','message':'起始事件记录缺失；未确认恢复'}]


def test_http_incidents_details_notification_read_and_safe_missing_node(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.alerts import router
    from app.routers.auth import current_user,admin_user
    from app.database import get_db
    app=FastAPI();app.include_router(router)
    # Deliberate auth-boundary stub; no claim of full-app auth acceptance.
    app.dependency_overrides[current_user]=lambda: object()
    app.dependency_overrides[admin_user]=lambda: object()
    app.dependency_overrides[get_db]=lambda: db
    r=rule(db);alerts._evaluate(db,r,True,'absent',NOW);db.flush()
    with TestClient(app) as c:
        response=c.get('/alerts/incidents?status=unresolved&node_id=12&limit=1')
        assert response.status_code==200,response.text
        incident=response.json()['items'][0]
        assert incident['resolved_at'] is None
        detail=c.get('/alerts/incidents/'+str(incident['id']))
        assert detail.status_code==200 and len(detail.json()['timeline'])==1
        note=c.get('/notifications').json()[0]
        detail=c.get('/notifications/'+str(note['id']))
        assert detail.status_code==200
        assert detail.json()['entities']==[{'type':'node','id':12,'label':'HK','available':False}]
        assert c.post('/notifications/'+str(note['id'])+'/read').status_code==200
        assert c.get('/notifications/'+str(note['id'])).json()['read'] is True
        assert c.get('/alerts/incidents/'+str(incident['id'])).json()['status']=='unresolved'
        assert c.get('/alerts/incidents?limit=0').status_code==422
        assert c.get('/alerts/incidents?status=healthy').status_code==422
        assert c.get('/notifications/999999').status_code==404
