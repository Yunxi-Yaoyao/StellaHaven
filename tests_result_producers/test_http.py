"""Actual agent task authorization and bell read routes on owned PG."""
from sqlalchemy.orm import Session
from tests_result_producers.test_results import notes, seed_mtr


def test_actual_agent_result_router_ownership_terminal_replay_and_bell_get(engine):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.task import agent_task_router
    from app.routers.alerts import router as alerts_router
    from app.routers.auth import current_user
    from app.database import get_db
    from app.models.node import Node
    from app.models.task import MtrTask
    from app.models.alert import Notification
    ids=seed_mtr(engine,('running','running'))
    with Session(engine) as db:
        for i in ids:db.get(Node,db.get(MtrTask,i).node_id).token='fixture-'+str(i)
        db.commit()
    app=FastAPI();app.include_router(agent_task_router);app.include_router(alerts_router)
    def get_owned_db():
        with Session(engine,autoflush=False) as db:yield db
    app.dependency_overrides[get_db]=get_owned_db
    app.dependency_overrides[current_user]=lambda:object()  # bell read auth-boundary stub only
    with TestClient(app) as client:
        def finish(i,token):
            return client.post(f'/agent/mtr-tasks/{i}/result',params={'token':token,'status':'done'},json={'hops':[]})
        assert finish(ids[0],'invalid').status_code==401
        assert finish(ids[0],'fixture-'+str(ids[1])).status_code==403
        assert notes(engine)==[]
        assert finish(ids[0],'fixture-'+str(ids[0])).status_code==200 and notes(engine)==[]
        assert finish(ids[1],'fixture-'+str(ids[1])).status_code==200
        assert finish(ids[1],'fixture-'+str(ids[1])).status_code==409
        with Session(engine) as db:note_id=db.query(Notification).one().id
        response=client.get(f'/notifications/{note_id}')
        assert response.status_code==200
        assert response.json()['context']['source']=='manual_test' and response.json()['context']['outcome']=='success'
    assert len(notes(engine))==1
