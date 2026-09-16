"""Isolated AppConfig SQLite only + FastAPI dependency overrides. No app lifespan."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models.config import AppConfig
from app.repositories import config as config_repo
from app.schemas.monitor import AgentReport
from app.services import node as node_svc
from app.services import server_map
from test_server_map import node, snapshot, NOW


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    AppConfig.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_report_persistence_is_separate_from_manual_and_clear(db, monkeypatch):
    assert hasattr(server_map, "save_snapshot")
    n = node()
    monkeypatch.setattr(node_svc.repo, "get_by_token", lambda *a: n)
    monkeypatch.setattr(node_svc.repo, "get_by_id", lambda *a: n)
    monkeypatch.setattr(node_svc.repo, "heartbeat", lambda *a, **kw: None)
    server_map.set_manual_location(db, 1, server_map.MapLocationUpdate(latitude=0, longitude=0, label="Origin"))
    node_svc.handle_report(db, "token", AgentReport(map_snapshot=snapshot()))
    assert json.loads(config_repo.get(db, "node_map_snapshot:1"))["location"]["latitude"] == 35
    assert json.loads(config_repo.get(db, "node_map_manual:1"))["latitude"] == 0
    server_map.set_manual_location(db, 1, server_map.MapLocationUpdate(latitude=None, longitude=None))
    assert json.loads(config_repo.get(db, "node_map_manual:1")) is None
    assert json.loads(config_repo.get(db, "node_map_snapshot:1")) is not None
    node_svc.handle_report(db, "token", AgentReport())
    # Map collection is scheduled independently; ordinary metric reports omit it.
    assert json.loads(config_repo.get(db, "node_map_snapshot:1")) is not None
    node_svc.handle_report(db, "token", AgentReport(map_snapshot=None))
    assert json.loads(config_repo.get(db, "node_map_snapshot:1")) is None


def test_agent_targets_require_valid_nonremoved_token(db, monkeypatch):
    from app.routers import monitor
    from test_wg_probes import pair
    assert hasattr(server_map, 'get_probe_targets')
    nodes = [node(), node(2)]
    monkeypatch.setattr(node_svc.repo, 'get_by_token', lambda db, token: nodes[0] if token == 'good' else None)
    monkeypatch.setattr(node_svc.repo, 'list_all', lambda db, skip=0, limit=100: nodes if skip == 0 else [])
    for ident, snap in pair().items():
        server_map.save_snapshot(db, ident, snap)
    assert server_map.get_probe_targets(db, 'good', now=NOW) == [dict(interface='wg0', peer_key_id='b'*64, target='10.0.0.2')]
    assert any(r.path == '/agent/map-targets' for r in monitor.agent_router.routes)
    for token in ('bad', 'good'):
        if token == 'good':
            nodes[0].status = 'removed'
        with pytest.raises(ValueError):
            server_map.get_probe_targets(db, token, now=NOW)


def test_legacy_ip_report_cannot_overwrite_manual_ip(db, monkeypatch):
    n = node(public_ip="1.1.1.1", public_ip_source="manual")
    monkeypatch.setattr(node_svc.repo, "get_by_id", lambda *a: n)
    node_svc.apply_public_ip_info(db, 1, dict(public_ip="8.8.8.8", region="Wrong city"))
    assert (n.public_ip, n.public_ip_source) == ("1.1.1.1", "manual")


def test_get_topology_reads_only_and_routes_auth(db, monkeypatch):
    from app.routers import monitor, auth
    from app.database import get_db
    assert any(r.path == "/nodes/map-topology" for r in monitor.node_router.routes)
    n = node()
    monkeypatch.setattr(node_svc.repo, "get_by_id", lambda *a: n)
    monkeypatch.setattr(node_svc.repo, "list_all", lambda db, skip=0, limit=100: [n] if skip == 0 else [])
    server_map.save_snapshot(db, 1, snapshot())
    before = config_repo.get(db, "node_map_snapshot:1")
    network = Mock(side_effect=AssertionError("GET must not geolocate"))
    monkeypatch.setattr(node_svc, "lookup_ip_region", network)
    app = FastAPI()
    app.include_router(monitor.node_router)
    app.dependency_overrides[get_db] = lambda: db
    user = SimpleNamespace(is_admin=False)
    app.dependency_overrides[auth.current_user] = lambda: user
    # SQLite connection stays on this thread for the read-only service exercise.
    result = server_map.get_topology(db)
    assert result["nodes"][0]["location_source"] == "nat"
    assert config_repo.get(db, "node_map_snapshot:1") == before
    network.assert_not_called()
    # Route boundary tests stub only persistence, retaining actual auth/validation.
    monkeypatch.setattr(server_map, "get_topology", lambda db: result)
    save = Mock(return_value=result["nodes"][0])
    monkeypatch.setattr(server_map, "set_manual_location", save)
    client = TestClient(app)
    assert client.get("/nodes/map-topology").status_code == 200
    body = dict(latitude=0, longitude=0, label="Origin")
    assert client.patch("/nodes/1/map-location", json=body).status_code == 403
    save.assert_not_called()
    user.is_admin = True
    assert client.patch("/nodes/1/map-location", json=body).status_code == 200
    assert client.patch("/nodes/1/map-location", json=dict(latitude=0, longitude=None)).status_code == 422
    def deny():
        raise HTTPException(401, "not logged in")
    app.dependency_overrides[auth.current_user] = deny
    assert client.get("/nodes/map-topology").status_code == 401
    assert client.patch("/nodes/1/map-location", json=body).status_code == 401
