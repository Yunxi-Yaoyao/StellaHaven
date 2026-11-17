"""Real heartbeat + JSON/JSONB commit/readback + response schema, no app bootstrap.

PostgreSQL opt-in is restricted to a disposable Unix socket under our scratch.
The HTTP route is an isolated schema harness, not the production auth/router.
"""
import importlib.util
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from sqlalchemy import JSON, Integer, String, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column, Session
from test_hardware_repository import heartbeat_function
from test_system_memory import agent, ROOT

spec = importlib.util.spec_from_file_location('memory_schemas', ROOT / 'app/schemas/monitor.py')
assert spec and spec.loader
schemas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schemas)

from contextlib import ExitStack
from qa.isolated_legacy_backends.owned_target import owned_target


def legacy_memory_engine():
    socket = os.environ.get('MEMORY_QA_PG_SOCKET')
    if not socket:
        pytest.skip('disposable PostgreSQL socket not provided')
    assert Path(socket).resolve().parent == Path('/root/.hermes/cache/scratch')
    assert Path(socket).name.startswith('memory-qa-')
    return create_engine('postgresql+psycopg2://postgres@/memory_qa', connect_args={'host': socket, 'connect_timeout': 3})


@pytest.mark.parametrize('database', ['sqlite', 'postgres'])
def test_memory_report_repository_schema_http_roundtrip(database, owned_target):
    with ExitStack() as resources:
        if database == 'postgres':
            engine = legacy_memory_engine() if owned_target is None else resources.enter_context(owned_target.scope())
        else:
            engine = create_engine('sqlite://')
        _memory_roundtrip(database, engine)


def _memory_roundtrip(database, engine):
    class Base(DeclarativeBase):
        pass
    class Node(Base):
        __tablename__ = 'memory_roundtrip_qa'
        id = mapped_column(Integer, primary_key=True)
        status = mapped_column(String)
        sys_info = mapped_column(JSONB if database == 'postgres' else JSON)
    output = {}
    Base.metadata.create_all(engine)
    try:
        for index, kind in enumerate(('physical', 'virtual', 'container', 'unknown', 'legacy'), 1):
            obj = object.__new__(agent.Agent)
            obj._os_static_cache, obj._storage_status = {}, {}
            hw = {'cpu': {}, 'gpus': [], 'sensors': [], 'availability': {}, 'machine': {'kind': kind}}
            with patch.object(obj, '_hardware_info', return_value=hw), patch.object(agent, '_hardware_read', return_value=None), patch.object(agent, 'psutil', SimpleNamespace(boot_time=lambda: 1, virtual_memory=lambda: SimpleNamespace(total=8157769728, available=0, used=4096))):
                info = obj._os_info()
            if kind == 'legacy':
                del info['hardware']['memory']
                del info['hardware']['machine']
            report = schemas.AgentReport.model_validate_json(json.dumps({'os_info': info}))
            with Session(engine) as db:
                node = Node(id=index, status='online', sys_info={})
                node.installed, node.arch, node.uninstall_status = True, None, None
                db.add(node); db.commit()
                heartbeat = heartbeat_function()
                heartbeat.__globals__['get_by_id'] = lambda session, node_id: session.get(Node, node_id)
                heartbeat(db, index, os_info=report.os_info)
            with Session(engine) as db:
                saved = db.scalar(select(Node).where(Node.id == index)).sys_info
            assert saved['hardware'] == info['hardware']
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            app = FastAPI()
            @app.get('/memory-qa', response_model=schemas.NodeDetail)
            def response():
                return dict(id=index, name='Generic fixture', platform='linux', host='offline.invalid',
                            status='online', created_at=datetime.now(timezone.utc), sys_info=saved)
            with TestClient(app) as client:
                http_response = client.get('/memory-qa')
                assert http_response.status_code == 200
                body = http_response.json()
            assert body['sys_info']['hardware'] == info['hardware']
            output[kind] = body
        if database == 'postgres' and os.environ.get('MEMORY_QA_OUTPUT'):
            Path(os.environ['MEMORY_QA_OUTPUT']).write_text(json.dumps(output, indent=2))
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_real_service_uid_memory_postgres_public_http(owned_target):
    """Opt-in real read-only collector evidence, never a synthetic NAS substitute."""
    sample_path = os.environ.get('HARDWARE_REAL_SAMPLE')
    if not sample_path:
        pytest.skip('service-UID collector evidence not provided')
    assert sample_path is not None
    evidence = json.loads(Path(sample_path).read_text())
    assert evidence['uid'] != 0 and evidence['uid'] == evidence['service_uids'][0]
    assert evidence['gid'] == evidence['service_gids'][0]
    assert all(evidence['namespace_matches'].values())
    assert evidence['service_before'] == evidence['service_after']
    hardware = evidence['hardware']
    assert hardware['memory']['state'] == 'available'
    assert hardware['memory']['total_bytes'] == evidence['proc_fallback']['total_bytes']
    with ExitStack() as resources:
        engine = legacy_memory_engine() if owned_target is None else resources.enter_context(owned_target.scope())
        class Base(DeclarativeBase):
            pass
        class Node(Base):
            __tablename__ = 'service_uid_memory_qa'
            id = mapped_column(Integer, primary_key=True)
            status = mapped_column(String)
            sys_info = mapped_column(JSONB)
        Base.metadata.create_all(engine)
        try:
            report = schemas.AgentReport.model_validate_json(json.dumps({'os_info': {'hardware': hardware}}))
            with Session(engine) as db:
                node = Node(id=1, status='online', sys_info={})
                node.installed, node.arch, node.uninstall_status = True, None, None
                db.add(node); db.commit()
                heartbeat = heartbeat_function()
                heartbeat.__globals__['get_by_id'] = lambda session, node_id: session.get(Node, node_id)
                heartbeat(db, 1, os_info=report.os_info)
            with Session(engine) as db:
                saved = db.get(Node, 1).sys_info
            assert saved['hardware'] == hardware
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            app = FastAPI()
            @app.get('/service-uid-memory', response_model=schemas.NodeDetail, response_model_exclude_unset=True)
            def response():
                return dict(id=1, name='NAS service-UID evidence', platform='linux', host='redacted.invalid',
                            status='online', created_at=datetime.now(timezone.utc), sys_info=saved)
            with TestClient(app) as client:
                result = client.get('/service-uid-memory')
                assert result.status_code == 200
                body = result.json()
            assert body['sys_info']['hardware'] == hardware
            assert body['sys_info']['hardware']['machine']['kind'] == hardware['machine']['kind']
            # Read-only public projection cannot alter stored evidence.
            with Session(engine) as db:
                assert db.get(Node, 1).sys_info == saved
            if os.environ.get('HARDWARE_REAL_READBACK'):
                Path(os.environ['HARDWARE_REAL_READBACK']).write_text(json.dumps(body, indent=2))
        finally:
            Base.metadata.drop_all(engine)
            engine.dispose()
