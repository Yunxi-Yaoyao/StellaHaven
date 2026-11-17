"""Owned SQLite/ASGI channel tests; no production DB, network or Agent install."""
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import JSON, MetaData, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.models.node import Node
from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember
from app.models.config import AppConfig
from app.models.alert import AlertRule, AlertState
from app.models.user import User, AuthSession


@pytest.fixture
def db():
    # Do not import the policy fixture's process-global JSONB compiler. Copy only
    # this file's reached tables; production mapped types remain PostgreSQL-only.
    metadata = MetaData()
    for model in (Node, Monitor, AppConfig, MonitorGroup, MonitorGroupMember,
                  AlertRule, AlertState, User, AuthSession):
        table = model.__table__.to_metadata(metadata)
        for column in table.c:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def node(db, name='owned', host='192.168.160.3', **kw):
    obj = Node(name=name, host=host, platform='linux', **kw)
    db.add(obj); db.commit()
    return obj

@pytest.fixture
def channels(db, monkeypatch):
    from app.services import agent_channels as svc, entry_registry
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public': 'https://main.test', 'private': 'https://other.test'}})
    monkeypatch.setattr(svc, 'center_id', lambda: 'a' * 64)
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','https://main.test,https://other.test')
    return svc

def test_defaults_are_pending_not_auto_or_put_ack(db, channels):
    n = node(db, token='fixture-token')
    before = channels.read(db)
    assert before['nodes'][0]['mode'] == 'default'
    assert before['nodes'][0]['state'] == 'pending'
    result = channels.update(db, {'revision':0, 'node_ids':[n.id], 'mode':'fixed', 'entry_id':'private'})
    assert result['revision'] == 1
    assert result['nodes'][0]['state'] == 'pending'
    assert result['nodes'][0]['actual_origin'] is None
    cfg = channels.config(db, n)
    assert cfg['selected_entry_id'] == 'private'
    assert cfg['mode'] == 'fixed'
    assert n.token not in json.dumps(result)


def test_bulk_cas_strict_ids_and_same_epoch_does_not_affect_siblings(db, channels):
    a,b = node(db, token='fixture-a'),node(db, token='fixture-b')
    with pytest.raises(HTTPException) as e:
        channels.update(db, {'revision':0,'node_ids':[a.id,9999], 'mode':'auto','entry_id':None})
    assert e.value.status_code == 422
    assert channels.read(db)['revision'] == 0
    channels.update(db, {'revision':0,'node_ids':[a.id], 'mode':'auto','entry_id':None})
    assert [n['mode'] for n in channels.read(db)['nodes']] == ['auto','default']
    with pytest.raises(HTTPException) as e:
        channels.update(db, {'revision':0,'node_ids':[b.id], 'mode':'default','entry_id':None})
    assert e.value.status_code == 409


def test_receipt_nonce_epoch_origin_and_late_failure(db, channels):
    n=node(db,token='receipt-token')
    cfg=channels.config(db,n)
    incoming={k:cfg[k] for k in ('revision','epoch','nonce','center_id')}
    incoming.update(origin='https://main.test',sequence=1,state='applied')
    for altered in ({'nonce':'b'*64},{'origin':'https://other.test'},{'epoch':'old'}):
        with pytest.raises(HTTPException):
            channels.receipt(db,n,incoming|altered,'https://main.test')
    channels.receipt(db,n,incoming,'https://main.test');db.commit()
    assert channels.read(db)['nodes'][0]['state']=='applied'
    with pytest.raises(HTTPException):
        channels.receipt(db,n,incoming|{'state':'failed','error':'probe_failed'},'https://main.test')
    channels.update(db,dict(revision=0,node_ids=[n.id],mode='fixed',entry_id='private'))
    with pytest.raises(HTTPException):
        channels.receipt(db,n,incoming|{'sequence':2},'https://main.test')
    assert channels.read(db)['nodes'][0]['state']=='pending'


def test_http_contract_has_real_registered_routes_and_closed_fields(db, channels):
    from fastapi import FastAPI,Request
    from fastapi.testclient import TestClient
    from app.routers.monitor import node_router,agent_router
    from app.routers.auth import current_user,admin_user
    from app.database import get_db
    n=node(db,token='http-fixture-token')
    app=FastAPI();app.include_router(node_router);app.include_router(agent_router)
    app.dependency_overrides[get_db]=lambda:db
    with TestClient(app,base_url='https://main.test') as c:
        assert c.get('/nodes/report-channels').status_code==401
        assert c.get('/agent/entry-probe').status_code==401
        from datetime import datetime,timezone
        from uuid import uuid4
        from app.services import admin_security
        owner_id, foreign_id, sid = uuid4(), uuid4(), uuid4()
        session = AuthSession(id=sid, user_id=foreign_id, refresh_hash='synthetic-unused',
                              revoked=False, remember=False, last_seen=datetime.now(timezone.utc))
        db.add_all([User(id=owner_id, username='owner', display_name='Owner'),
                    User(id=foreign_id, username='foreign', display_name='Foreign'), session,
                    AppConfig(key=admin_security.STATE_KEY, value=json.dumps({'owner_id': str(owner_id)}))])
        db.commit()
        def authenticated(request:Request):
            request.state.auth_session=session
            return object()
        app.dependency_overrides[current_user]=authenticated
        denied=c.put('/nodes/report-channels',json=dict(revision=0,node_ids=[n.id],mode='auto'))
        assert denied.status_code==403
        assert channels.read(db)['revision']==0
        app.dependency_overrides[admin_user]=lambda:object()
        r=c.get('/nodes/report-channels'); assert r.status_code==200
        assert c.put('/nodes/report-channels',json=dict(revision=0,node_ids=[n.id],mode='default',secret='forbidden')).status_code==422
        assert c.put('/nodes/report-channels',json=dict(revision=0,node_ids=[n.id],mode='auto')).status_code==200
        probe=c.get('/agent/entry-probe',headers={'Authorization':'Bearer '+n.token})
        assert probe.status_code==200
        assert probe.json()==dict(center_id='a'*64,node_id=n.id,token_binding=channels._proof(n,'binding'),origin='https://main.test')
        cfg=c.get('/agent/config',headers={'Authorization':'Bearer '+n.token})
        assert cfg.status_code==200 and cfg.json()['report_channel']['mode']=='auto'


def test_host_trust_does_not_infer_443_from_legacy_25451(db,channels,monkeypatch):
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','https://main.test:25451,https://other.test')
    with pytest.raises(HTTPException) as exc:channels.read(db)
    assert exc.value.status_code==503
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','https://main.test:25451,https://main.test,https://other.test')
    assert channels.read(db)['entries'][0]['origin']=='https://main.test'


def test_real_report_receipt_persisted_and_read_back(db,channels):
    from datetime import datetime,timezone
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.monitor import agent_router
    from app.database import get_db

    n=node(db,token='real-receipt-fixture',status='online',last_seen_at=datetime.now(timezone.utc))
    cfg=channels.config(db,n)
    value={k:cfg[k] for k in ('revision','epoch','nonce','center_id')}
    value.update(sequence=1,origin='https://main.test',state='applied',error=None)
    app=FastAPI();app.include_router(agent_router);app.dependency_overrides[get_db]=lambda:db
    with TestClient(app,base_url='https://main.test') as c:
        response=c.post('/agent/report',headers={'Authorization':'Bearer '+n.token},json={'channel_receipt':value})
        assert response.status_code==200,response.text
        db.expire_all()
        assert channels.read(db)['nodes'][0]['actual_origin']=='https://main.test'
        late=c.post('/agent/report',headers={'Authorization':'Bearer '+n.token},json={'channel_receipt':value|{'state':'failed','error':'probe_failed'}})
        assert late.status_code==409
        assert channels.read(db)['nodes'][0]['state']=='applied'


@pytest.mark.parametrize('ids',[[True],['1'],[1,1],[],[-1]])
def test_write_ids_are_strict_and_unique(ids):
    from pydantic import ValidationError
    from app.schemas.channel import ChannelWrite
    with pytest.raises(ValidationError):ChannelWrite(revision=0,node_ids=ids,mode='default')


def test_exact_candidate_release_bytes_and_old_rollout_pins(monkeypatch):
    from app.routers.monitor import agent_version,agent_script
    import hashlib
    monkeypatch.delenv('STELLA_AGENT_ROLLOUT_VERSION',raising=False)
    body=agent_script().body
    assert agent_version()==dict(version='0.6.20',sha256=hashlib.sha256(body).hexdigest(),size=len(body))
    for version in ('0.6.16','0.6.17'):
        monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION',version)
        assert agent_version()=={'version':version}


def test_registry_change_invalidates_old_policy_confirmation(db,channels,monkeypatch):
    from app.services import entry_registry
    n=node(db,token='registry-fixture')
    channels.update(db,dict(revision=0,node_ids=[n.id],mode='auto',entry_id=None))
    cfg=channels.config(db,n)
    incoming={k:cfg[k] for k in ('revision','epoch','nonce','center_id')}
    incoming.update(origin='https://other.test',sequence=1,state='applied')
    channels.receipt(db,n,incoming,'https://other.test');db.commit()
    monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':'https://newmain.test','private':'https://other.test'}})
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','https://newmain.test,https://other.test')
    assert channels.read(db)['nodes'][0]['state']=='pending'
    with pytest.raises(HTTPException):channels.receipt(db,n,incoming|{'sequence':2},'https://other.test')
