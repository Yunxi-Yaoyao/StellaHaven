"""Own disposable PG only; deliberately outside tests/conftest.py."""
import json
import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from pydantic import ValidationError
from app.models.config import AppConfig
from app.models.user import User,AuthSession
from app.services import integrations as service
from app.services import integrations_sessions as sessions
from app.services.admin_security import STATE_KEY
from fastapi import HTTPException
from datetime import datetime,timezone

@pytest.fixture
def engine():
    url=make_url(os.environ['STELLA_IFRAME_TEST_DSN'])
    assert url.host=='127.0.0.1' and url.port not in {5432,24532,24533,24534}
    assert url.database=='stella_iframe_test' and url.username=='iframe_test' and not url.query
    for key in ('PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGUSER','PGPASSWORD','PGSERVICE','PGSERVICEFILE','PGOPTIONS'):
        assert key not in os.environ
    engine=create_engine(url)
    with engine.connect() as c:
        assert c.execute(text("select current_database(),current_user,current_setting('stella.test_isolation',true)")).one()==('stella_iframe_test','iframe_test','iframe-test-only')
    for table in [User.__table__,AuthSession.__table__,AppConfig.__table__]: table.create(engine)
    try: yield engine
    finally:
        for table in [AppConfig.__table__,AuthSession.__table__,User.__table__]: table.drop(engine)
        engine.dispose()

def test_keep_alive_defaults_off_and_strict_boolean():
    data=dict(name='Test',browser_url='https://cache.test/')
    assert service.ModuleInput(**data).model_dump()['keep_alive'] is False
    for invalid in ['true',1,None,{},[]]:
        with pytest.raises(ValidationError): service.ModuleInput(**data,keep_alive=invalid)

def test_pg_switch_roundtrip_fresh_device_and_legacy_patch(engine):
    actor=uuid4()
    with Session(engine) as db:
        value=service.create_module(db,service.ModuleInput(name='Test',browser_url='https://cache.test/'),actor)
        assert value['keep_alive'] is False
        mid=value['id']
        assert service.patch_module(db,mid,{'keep_alive':True},actor)['keep_alive'] is True
    with Session(engine) as device:
        assert service.present(service.get_module(device,mid))['keep_alive'] is True
        assert service.patch_module(device,mid,{'keep_alive':False},actor)['keep_alive'] is False
        config=service.state(device);del config['modules'][mid]['keep_alive']
        device.get(AppConfig,service.KEY).value=json.dumps(config);device.commit()
    with Session(engine) as device:
        assert service.present(service.get_module(device,mid))['keep_alive'] is False
        assert service.patch_module(device,mid,{'name':'Legacy safe'},actor)['keep_alive'] is False
        assert service.patch_module(device,mid,{'keep_alive':True},actor)['keep_alive'] is True


def test_pg_grant_expiry_is_fixed_reconnect_creates_new_grant_and_revocation_blocks_it(engine,monkeypatch):
    monkeypatch.delenv('STELLA_OWNER_ID',raising=False)
    now=[1000.0];monkeypatch.setattr(sessions.time,'time',lambda:now[0])
    uid,sid=uuid4(),uuid4()
    module={'id':uuid4().hex,'mode':'isolated_proxy','origin':'https://c1.cache.test'}
    with Session(engine) as db:
        db.add(User(id=uid,username='iframe-owner',display_name='Fixture',is_active=True))
        db.flush()
        db.add(AuthSession(id=sid,user_id=uid,refresh_hash='iframe-fixture-only',remember=True,last_seen=datetime.now(timezone.utc)))
        db.add(AppConfig(key=STATE_KEY,value=json.dumps({'owner_id':str(uid)})));db.commit()
        launch=sessions.issue(db,module,str(sid),'https://main.test')
        token=sessions.redeem(db,module['id'],module['origin'],'https://main.test',launch['fields']['ticket'])
        assert sessions.authorize(db,module['id'],module['origin'],token)['expires']==1900.0
    with Session(engine) as other_device:
        now[0]=1899.0
        assert sessions.authorize(other_device,module['id'],module['origin'],token)['expires']==1900.0
        now[0]=1901.0
        with pytest.raises(HTTPException) as rejected:sessions.authorize(other_device,module['id'],module['origin'],token)
        assert rejected.value.status_code==401
        launch=sessions.issue(other_device,module,str(sid),'https://main.test')
        renewed=sessions.redeem(other_device,module['id'],module['origin'],'https://main.test',launch['fields']['ticket'])
        assert renewed!=token
        assert sessions.authorize(other_device,module['id'],module['origin'],renewed)['expires']==2801.0
        other_device.get(AuthSession,sid).revoked=True;other_device.commit()
    with Session(engine) as after_logout:
        with pytest.raises(HTTPException) as rejected:sessions.authorize(after_logout,module['id'],module['origin'],renewed)
        assert rejected.value.status_code==401
        with pytest.raises(HTTPException) as rejected:sessions.issue(after_logout,module,str(sid),'https://main.test')
        assert rejected.value.status_code==401
