"""Owned PG → real alert router → browser harness, with explicit auth boundary stub.
No main import/startup, real agents, SMTP, WS server or production inventory.
"""
import json, os, socket
from datetime import datetime,timedelta,timezone
from fastapi import FastAPI,Depends
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from sqlalchemy.engine import make_url
from app.models import Base
from app.models.node import Node
from app.models.alert import AlertRule,AlertEvent,AlertState,Notification
from app.services import alerts
from app.database import get_db
from app.routers.auth import current_user,admin_user
from app.routers.alerts import router
import uvicorn

url=os.environ['ALERT_FEEDBACK_TEST_URL'];u=make_url(url)
assert (u.host,u.username,u.database)==('127.0.0.1','stella_alert_test','alerts_test') and u.port!=5432
engine=create_engine(url)
def guard(c):
    assert c.execute(text("select current_database(),current_user,current_setting('stella.test_isolation')")).one()==('alerts_test','stella_alert_test','alerts-feedback-owned')
with engine.begin() as c:guard(c);Base.metadata.create_all(c)
alerts._push_ws=lambda p:None
alerts._send_alert_email=lambda p:(_ for _ in ()).throw(AssertionError('email prohibited'))
now=datetime.now(timezone.utc)
with Session(engine) as db:
    node=Node(name='HK 边缘节点',platform='linux',host='192.0.2.12',interfaces={'eth0':{}},status='online',last_seen_at=now)
    db.add(node);db.flush();node_id=node.id
    r=alerts.create_rule(db,'node_offline',str(node_id),label=node.name,link=f'/status/{node_id}',debounce=1,repeat_minutes=1,email=False)
    alerts._evaluate(db,r,True,'心跳中断，请检查节点连通性',now-timedelta(minutes=12))
    alerts._evaluate(db,r,True,'心跳仍未恢复',now-timedelta(minutes=5))
    unresolved=db.query(AlertEvent).filter_by(rule_id=r.id,event='fired').one().id
    r2=AlertRule(kind='node_metric',target=str(node_id),schema_version=2,condition={'metric':'cpu','threshold':'80'},label='HK CPU 使用率',debounce=1,repeat_minutes=0,email=False,enabled=True,link=f'/status/{node_id}')
    db.add(r2);db.flush()
    alerts._evaluate(db,r2,True,'CPU 92%，阈值 80%',now-timedelta(hours=2))
    alerts._evaluate(db,r2,False,'CPU 已回落',now-timedelta(hours=1,minutes=50))
    db.commit()
app=FastAPI();app.include_router(router)
def session():
    with Session(engine) as db:yield db
app.dependency_overrides[get_db]=session
app.dependency_overrides[current_user]=lambda:object()
app.dependency_overrides[admin_user]=lambda:object()
@app.get('/nodes/map-topology')
def topology():return {'nodes':[],'links':[]}
@app.get('/nodes/')
def nodes(db:Session=Depends(session)):
    return [dict(id=n.id,name=n.name,status=n.status,host=n.host,interfaces=n.interfaces) for n in db.query(Node).all()]
@app.get('/monitors/')
def monitors():return []
@app.post('/__fixture/cleanup')
def cleanup():
    with engine.begin() as c:
        guard(c);Base.metadata.drop_all(c)
        count=c.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")).scalar_one()
    return {'remaining_tables':count}

@app.get('/__fixture/receipt')
def receipt(db:Session=Depends(session)):
    return {'events':db.query(AlertEvent).count(),'notifications':db.query(Notification).count(),
            'unread':db.query(Notification).filter_by(read=False).count(),'open_state':db.get(AlertState,1).state}
sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
print(json.dumps({'port':port,'node_id':node_id,'incident_id':unresolved}),flush=True)
try:
    uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning')).run(sockets=[sock])
finally:
    with engine.begin() as c:guard(c);Base.metadata.drop_all(c)
    engine.dispose()
