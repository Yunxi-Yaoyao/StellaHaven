"""Real v6 routes/owner auth with file-owned memory DB and network fences.
Standalone with pytest --noconftest; no external runtime runner or live PG.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import JSON, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from tests_website_settings.test_website_settings import upstream

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = json.loads((ROOT/'app/api_response_v6_integration.json').read_text())
DAILY = 'daily-fixture-password'


@pytest.fixture(scope='module', autouse=True)
def runtime_boundary():
    """Own the old runner's prerequisites, before importing real app bodies.

    Only database wiring/package re-exports are synthetic; routes, security,
    ORM models and services remain the on-disk implementation. The audit hook
    is active only during this module and also fences native SQLite aliases.
    """
    import importlib.abc
    import ipaddress
    import socket
    import sys
    import types
    import sqlalchemy
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import DeclarativeBase, sessionmaker

    forbidden = {'main', 'app.main', 'app.config'}
    assert not forbidden.intersection(sys.modules), 'Bootstrap preceded isolated fixture'
    assert 'app.database' not in sys.modules, 'Database preceded isolated fixture'
    previous_modules = set(sys.modules)
    owned = {}
    active = True
    real_listen = socket.socket.listen
    real_close = socket.socket.close
    real_engine = sqlalchemy.create_engine

    def listen(sock, *args, **kwargs):
        result = real_listen(sock, *args, **kwargs)
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host, port = sock.getsockname()[:2]
            if ipaddress.ip_address(host).is_loopback:
                owned[sock] = (host, port)
        return result

    def close(sock, *args, **kwargs):
        # Accepted connections share the listener's local address, not ownership.
        owned.pop(sock, None)
        return real_close(sock, *args, **kwargs)

    def audit(event, args):
        if not active:
            return
        if event == 'socket.connect':
            sock, address = args
            if sock.family in (socket.AF_INET, socket.AF_INET6) and address[:2] not in owned.values():
                raise AssertionError('Only current-process fixture listeners permitted')
        if event == 'socket.getaddrinfo':
            try:
                safe = ipaddress.ip_address(args[0]).is_loopback
            except ValueError:
                safe = False
            if not safe:
                raise AssertionError('No external DNS permitted')
        if event == 'sqlite3.connect' and str(args[0]) != ':memory:':
            raise AssertionError('Only memory SQLite permitted')

    class Deny(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname in forbidden:
                raise AssertionError('Forbidden bootstrap/config ' + fullname)

    def memory_engine(url, *args, **kwargs):
        value = make_url(url)
        if value.drivername != 'sqlite' or value.database not in (None, '', ':memory:'):
            raise AssertionError('Only memory SQLite permitted')
        return real_engine(url, *args, **kwargs)

    class Base(DeclarativeBase):
        pass

    db = types.ModuleType('app.database')
    db.Base = Base
    db.engine = memory_engine('sqlite://')
    def get_db():
        raise AssertionError('Fixture must override get_db')
    get_db.__module__ = 'app.database'
    get_db.__qualname__ = 'get_db'
    db.get_db = get_db
    db.sessionLocal = db.SessionLocal = sessionmaker(bind=db.engine)
    fence = Deny()
    sys.addaudithook(audit)
    sys.meta_path.insert(0, fence)
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(socket.socket, 'listen', listen)
            patch.setattr(socket.socket, 'close', close)
            patch.setattr(sqlalchemy, 'create_engine', memory_engine)
            patch.setitem(sys.modules, 'app.database', db)
            for name in ('app.services', 'app.routers'):
                package = types.ModuleType(name)
                package.__path__ = [str(ROOT.joinpath(*name.split('.')))]
                patch.setitem(sys.modules, name, package)
            patch.setenv('STELLA_SECRET_KEY', 'v6-contract-synthetic-signing-key-00000000')
            patch.setenv('STELLA_COOKIE_SECURE', 'false')
            patch.setenv('STELLA_MAIN_ORIGIN', 'https://main.test')
            yield db
    finally:
        active = False
        sys.meta_path.remove(fence)
        db.engine.dispose()
        # No model/router imported against the synthetic Base may leak onward.
        for name in set(sys.modules) - previous_modules:
            if name == 'app' or name.startswith('app.') or name == 'test_owner_admin_security':
                sys.modules.pop(name, None)


@pytest.fixture
def auth_env(runtime_boundary, monkeypatch):
    from test_owner_admin_security import auth_env as shared_auth_env
    yield from shared_auth_env.__wrapped__(monkeypatch)


def owner(client):
    from test_owner_admin_security import owner as register_owner
    return register_owner(client)


@pytest.fixture
def installed(auth_env, monkeypatch):
    from app.models.node import Node
    from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember
    from app.routers.monitor import monitor_router, node_router, agent_router
    from app.routers.website_settings import router as website_router
    from app.routers.integrations import router as integration_router
    from app.services import entry_registry
    from app.openapi_contract import install_openapi_contract
    c, db, app = auth_env
    c.base_url = 'https://main.test'
    from fastapi.exceptions import RequestValidationError
    from app.validation_errors import validation_exception_handler
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    # Adapt only private table copies; never register a global JSONB compiler.
    metadata = MetaData()
    for table in Node.metadata.tables.values():
        table.to_metadata(metadata)
    for table in metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    for model in (Node, Monitor, MonitorGroup, MonitorGroupMember):
        metadata.tables[model.__tablename__].create(db.get_bind())
    for router in (monitor_router, node_router, agent_router, website_router, integration_router):
        app.include_router(router)
    monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':'https://main.test','private':'https://other.test'}})
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS','https://main.test,https://other.test')
    # Reject mail if an unrelated call accidentally reaches this transport.
    from app.routers import admin_email
    def no_mail(*args, **kwargs): raise AssertionError('No email transport in contract integration')
    monkeypatch.setattr(admin_email, '_send', no_mail)
    install_openapi_contract(app)
    return c, db, app


def validate(method, path, response):
    from app.api_response_contracts import DECLARATIONS
    schema = DECLARATIONS[method,path]['responses'][str(response.status_code)]['content']['application/json']['schema']
    Draft202012Validator(schema).validate(response.json())


def test_runtime_fences_reject_live_db_dns_and_main(runtime_boundary):
    import importlib
    import socket
    import sqlite3
    import sys
    import sqlalchemy
    assert not {'main','app.main','app.config'}.intersection(sys.modules)
    assert str(runtime_boundary.engine.url) == 'sqlite://'
    with pytest.raises(AssertionError, match='Fixture must override get_db'):
        runtime_boundary.get_db()
    for url in ('postgresql://fixture@127.0.0.1:25436/never-connect', 'sqlite:///never-open.sqlite'):
        with pytest.raises(AssertionError, match='Only memory SQLite'):
            sqlalchemy.create_engine(url)
    with pytest.raises(AssertionError, match='Only memory SQLite|PREFLIGHT_GUARD non-memory sqlite'):
        sqlite3.connect('never-open.sqlite')
    with pytest.raises(AssertionError, match='No external DNS|PREFLIGHT_GUARD DNS'):
        socket.getaddrinfo('contract-do-not-resolve.invalid', 443)
    with socket.socket() as probe:
        with pytest.raises(AssertionError, match='fixture listeners|PREFLIGHT_GUARD non-owned network'):
            probe.connect(('127.0.0.1', 24532))
    # Positive and lifecycle controls: only a live, process-owned listener works.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        address = listener.getsockname()
        with socket.create_connection(address):
            pass
    with socket.socket() as probe:
        with pytest.raises(AssertionError, match='fixture listeners|PREFLIGHT_GUARD non-owned network'):
            probe.connect(address)
    for name in ('main', 'app.main', 'app.config'):
        with pytest.raises(AssertionError, match='Forbidden bootstrap|PREFLIGHT_GUARD production bootstrap'):
            importlib.import_module(name)


@pytest.mark.parametrize('boundary', ['anonymous','owner','wrong_owner'])
def test_actual_retirement_and_normal_owner_boundaries(installed, boundary):
    from app.models.user import User, AuthSession
    from app.models.config import AppConfig
    from app.security import hash_password, make_access_token
    from app.services.admin_security import STATE_KEY
    c, db, app = installed
    if boundary != 'anonymous':owner(c)
    if boundary == 'wrong_owner':
        foreign=User(username='foreign',display_name='foreign',password_hash=hash_password(DAILY),is_admin=True)
        db.add(foreign);db.flush()
        session=AuthSession(user_id=foreign.id,refresh_hash='contract-foreign',remember=True)
        db.add(session);db.commit();c.cookies.clear()
        c.cookies.set('stella_at',make_access_token(str(foreign.id),str(session.id)))
    state=db.get(AppConfig,STATE_KEY); before=state.value if state is not None else None
    rows=[('PUT','/auth/security',{'enabled':False}),('POST','/auth/admin/password',{'current_password':DAILY,'new_password':DAILY+'2'}),('POST','/auth/admin/setup',{'user_password':DAILY,'new_password':DAILY+'2'}),('POST','/auth/admin/unlock',{'password':DAILY}),('POST','/auth/admin/lock',{})]
    document=c.get('/openapi.json').json()
    for method,path,payload in rows:
        operation=document['paths'][path][method.lower()]
        assert {'401','403','410'} <= set(operation['responses']) and '200' not in operation['responses']
        assert operation['security']==[{'StellaAccessCookie':[]}]
        assert operation['x-stella-elevation']=='none'
        response=c.request(method,path,json=payload)
        assert response.status_code=={'anonymous':401,'wrong_owner':403,'owner':410}[boundary]
        validate(method,path,response)
    assert c.get('/monitors/').status_code=={'anonymous':401,'wrong_owner':403,'owner':200}[boundary]
    assert c.post('/danger').status_code=={'anonymous':401,'wrong_owner':403,'owner':200}[boundary]
    after=db.get(AppConfig,STATE_KEY)
    assert (after.value if after is not None else None)==before


def test_native_website_request_schema_preserves_new_and_old_constraints(installed):
    from app.openapi_contract import install_openapi_contract, validate_contract
    c, db, app = installed
    # Original routes/signatures, not the source-shaped offline request harness.
    native_app=FastAPI()
    native_app.router.routes.extend(route for route in app.router.routes if getattr(route,'path',None) not in {'/danger','/openapi.json','/docs','/docs/oauth2-redirect','/redoc'})
    native=native_app.openapi()
    for key, expected in OVERLAY['request_signatures'].items():
        method,path=key.split(' ',1)
        request=native['paths'][path][method.lower()]['requestBody']
        name=request['content']['application/json']['schema']['$ref'].rsplit('/',1)[-1]
        actual=native['components']['schemas'][name]
        from private_remediation_evidence_fixture import review as v22_review
        current=v22_review()['request_signatures'].get(key)
        if current is None:
            assert actual==expected['schema']
        else:
            assert actual==current['schema']
            # The only approved WebsiteInput extension; freeze every old field.
            from copy import deepcopy
            legacy=deepcopy(actual)
            legacy['properties'].pop('expected_revision')
            assert legacy==expected['schema']
    install_openapi_contract(native_app)
    native_app.openapi_schema=None
    decorated=validate_contract(native_app)
    for key in OVERLAY['request_signatures']:
        method,path=key.split(' ',1)
        assert decorated['paths'][path][method.lower()]['requestBody']==native['paths'][path][method.lower()]['requestBody']
    owner(c)
    for payload in ({'address':'x'*2049},{'address':'http://127.0.0.1','alternate_address':''},
                    {'address':'http://127.0.0.1','address_mode':'wildcard'},
                    {'address':'http://127.0.0.1','extra_internal':True}):
        response=c.post('/website-settings/check',json=payload)
        assert response.status_code==422,response.text
        validate('POST','/website-settings/check',response)
        assert all(set(item)=={'loc','type','msg'} for item in response.json()['detail'])


@pytest.mark.parametrize('edit', ['omitted','null','alternate'])
def test_actual_website_mapping_responses_single_list_and_nested_checks(installed, upstream, edit):
    c, db, app = installed; owner(c)
    origin, _, seen = upstream
    first=origin+'/first?q=a%2Fb#one';second=origin+'/second?q=c%2Fd#two'
    body={'address':first,'address_mode':'ip','alternate_address':second,
          'connection':{'transport':'auto'},'name':'contract site','idempotency_key':'contract-site-'+edit}
    created=c.post('/website-settings',json=body)
    assert created.status_code==201,created.text
    validate('POST','/website-settings',created)
    mid=created.json()['id']
    check=c.post('/website-settings/check',json={'address':first,'address_mode':'ip','alternate_address':second,'connection':{'transport':'auto'}})
    assert check.status_code==200,check.text
    validate('POST','/website-settings/check',check)
    assert check.json()['alternate_normalized_url'] == second
    patch={'address':first,'name':'changed only'}
    if edit=='null':patch.update(address_mode=None,alternate_address=None)
    elif edit=='alternate':patch.update(address_mode='ip',alternate_address=origin+'/third#three')
    updated=c.patch('/website-settings/'+mid,json=patch)
    assert updated.status_code==200,updated.text
    validate('PATCH','/website-settings/{mid}',updated)
    read=c.get('/external-modules/'+mid);validate('GET','/external-modules/{mid}',read)
    listing=c.get('/external-modules');validate('GET','/external-modules',listing)
    expected={'omitted':second,'null':None,'alternate':origin+'/third#three'}[edit]
    for item in (updated.json(),read.json(),next(v for v in listing.json() if v['id']==mid)):
        assert item['alternate_address']==expected and item['mapping_configured'] is True
        assert item['address_mode']==(None if edit=='null' else 'ip')
    assert seen and any(path=='/second?q=c%2Fd' for path,_ in seen)
    if edit == 'omitted':
        # Real failed write carries the same DTO nested inside an HTTP error.
        rejected=c.patch('/website-settings/'+mid,json={'address':'http://169.254.169.254/latest'})
        assert rejected.status_code==422,rejected.text
        assert rejected.json()['detail']['code']=='website_check_failed'
        validate('PATCH','/website-settings/{mid}',rejected)
        assert c.get('/external-modules/'+mid).json()==read.json()


def test_actual_monitor_object_list_and_agent_artifact_are_current(installed):
    from app.models.node import Node
    from app.models.monitor import Monitor
    c, db, app = installed;owner(c)
    n=Node(name='contract node',host='192.0.2.7',platform='linux',token='contract-fixture-agent-token',status='online',last_seen_at=datetime.now(timezone.utc))
    db.add(n);db.flush()
    m=Monitor(name='1',node_id=n.id,type='tcp',target='1:1',interval=60,timeout=5)
    db.add(m);db.commit()
    read=c.get('/monitors/');assert read.status_code==200;validate('GET','/monitors/',read)
    assert read.json()[0]['status_reason']=='invalid_target'
    patched=c.patch('/monitors/'+str(m.id),json={'target':'nas:80'})
    assert patched.status_code==200;validate('PATCH','/monitors/{monitor_id}',patched)
    assert patched.json()['status_reason']=='pending'
    created=c.post('/monitors/',json={'name':'new','node_id':n.id,'type':'tcp','target':'nas:80'})
    assert created.status_code==201,created.text
    validate('POST','/monitors/',created)
    group=c.post('/monitors/groups',json={'name':'contract group','items':[{'name':'one','node_id':n.id,'type':'tcp','target':'nas:80'}],'request_key':'12345678-1234-4234-8234-123456789abc'})
    assert group.status_code==201,group.text
    child=c.post('/monitors/groups/'+str(group.json()['id'])+'/children',json={'name':'child','node_id':n.id,'type':'tcp','target':'nas:81'})
    assert child.status_code==201,child.text
    validate('POST','/monitors/groups/{group_id}/children',child)
    from nav_files_evidence_fixture import current_agent
    historical_artifact,previous=current_agent()
    artifact=(ROOT/'agent/stella_agent.py').read_bytes()
    assert historical_artifact!=artifact
    from servers_audit_evidence_fixture import frozen, review
    assert hashlib.sha256(frozen('agent/stella_agent.py')).hexdigest()=='e95bcb5fc05920e580d5687f277a9f3833bde8d354a923b8faad63e2c90f0aa5'
    assert {s['sha256'] for s in review()['sources'].values() if s['file']=='agent/stella_agent.py'} == {hashlib.sha256(artifact).hexdigest()}
    # Reviewed 7497d50 HTTPError availability fix atop the 4462964 artifact.
    # Keep the historical blob/ledger frozen; pin today's served source exactly.
    assert hashlib.sha256(previous).hexdigest()=='25bc5e8c4f8e6ec262b89118098ea6d7b796f0bf3e75d8b10bd9a0aab070208b'
    assert len(previous)==232703
    assert c.get('/agent/script').content==artifact
    manifest=c.get('/agent/version');validate('GET','/agent/version',manifest)
    assert manifest.status_code==200
    assert manifest.json()=={
        'version':'0.6.21',
        'sha256':hashlib.sha256(artifact).hexdigest(),
        'size':len(artifact),
    }
