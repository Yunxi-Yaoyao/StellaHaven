"""Real config -> Agent helpers, with all socket I/O intercepted; not a live probe."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_node_monitor_policy import db, node
from app.database import get_db
from app.models.monitor import Monitor
from app.routers.monitor import agent_router, monitor_router
from app.routers.auth import current_user, admin_user
from app.services import monitor as monitor_svc


SPEC = importlib.util.spec_from_file_location(
    'ipv6_wire_agent', Path(__file__).resolve().parents[1] / 'agent/stella_agent.py')
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


@pytest.fixture
def http(db):
    app = FastAPI()
    app.include_router(agent_router)
    app.include_router(monitor_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: object()
    app.dependency_overrides[admin_user] = lambda: object()
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize('kind', ['tcp', 'udp'])
@pytest.mark.parametrize('target,host,port', [
    ('[2001:db8::1]:443', '2001:db8::1', 443),
    ('[::1]:53', '::1', 53),
    ('[::ffff:192.0.2.1]:65535', '::ffff:192.0.2.1', 65535),
    ('192.0.2.1:8443', '192.0.2.1', 8443),
    ('nas:53', 'nas', 53),
])
def test_real_config_to_socket_boundary(db, http, monkeypatch, kind, target, host, port):
    source = node(db, token='synthetic-ipv6-wire-token', status='online', last_seen_at=datetime.now(timezone.utc))
    created = http.post('/monitors/', json={
        'name': 'wire', 'node_id': source.id, 'type': kind,
        'target': target, 'interval': 60, 'timeout': 2,
    })
    assert created.status_code == 201, created.text
    mid = created.json()['id']
    response = http.get('/agent/config', headers={'Authorization': f'Bearer {source.token}'})
    assert response.status_code == 200, response.text
    wire = next(m for m in response.json()['monitors'] if m['id'] == mid)
    assert wire['target'] == target == db.get(Monitor, mid).target
    assert (wire['mtr_host'], wire['mtr_proto'], wire['mtr_port']) == (
        host, kind, port)
    assert monitor_svc.mtr_spec(kind, target) == (host, kind, port)

    calls = []

    class SocketSpy:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, timeout):
            calls.append(('timeout', timeout))

        def sendto(self, payload, address):
            calls.append(('sendto', payload, address))

        def recvfrom(self, size):
            raise agent.socket.timeout('synthetic no-response')

        def close(self):
            calls.append(('close',))

    def connect(address, timeout):
        calls.append(('connect', address, timeout))
        return SocketSpy()

    def datagram(family, socktype, proto):
        calls.append(('socket', family, socktype, proto))
        return SocketSpy()

    family = agent.socket.AF_INET6 if ':' in host else agent.socket.AF_INET
    sockaddr = (host, port, 0, 0) if family == agent.socket.AF_INET6 else (
        ('192.0.2.55', port) if host == 'nas' else (host, port))

    def resolve(*args):
        calls.append(('getaddrinfo', *args))
        return [(family, agent.socket.SOCK_DGRAM, agent.socket.IPPROTO_UDP, '', sockaddr)]

    with monkeypatch.context() as boundary:
        boundary.setattr(agent.socket, 'create_connection', connect)
        boundary.setattr(agent.socket, 'socket', datagram)
        boundary.setattr(agent.socket, 'getaddrinfo', resolve)
        boundary.setattr(agent.time, 'monotonic', lambda: 10.)
        instance = agent.Agent.__new__(agent.Agent)
        result = instance.probe(wire['type'], wire['target'], wire['timeout'])
    # This is only the helper's result under synthetic I/O, never network evidence.
    assert result[0] is True
    if kind == 'tcp':
        assert calls == [('connect', (host, port), 2)]
    else:
        assert calls == [('getaddrinfo', host, port, agent.socket.AF_UNSPEC, agent.socket.SOCK_DGRAM),
                         ('socket', family, agent.socket.SOCK_DGRAM, agent.socket.IPPROTO_UDP),
                         ('timeout', 2), ('sendto', b'\x00', sockaddr),
                         ('timeout', 2), ('close',)]
        assert result[2] is None  # Silence is not measured packet loss.


@pytest.mark.parametrize('target,expected', [
    ('nas', ('nas', 80)), ('192.0.2.1', ('192.0.2.1', 80)),
    (' nas：8443 ', ('nas', 8443)), (' [2001:db8::1]：443 ', ('2001:db8::1', 443)),
])
def test_legacy_default_and_normalization(target, expected):
    assert agent.Agent._split_host_port(target) == expected


@pytest.mark.parametrize('target', [
    '[2001:db8::1:443', '[2001:db8::1]]:443', '[2001:db8::1]extra:443',
    '[not-ipv6]:443', '[192.0.2.1]:443', '[2001:::1]:443',
    '[2001:db8::1]:0', '[2001:db8::1]:65536', '[2001:db8::1]:-1',
    '[2001:db8::1]:', '[2001:db8::1]:abc', '[2001:db8::1]:443:80',
])
def test_malformed_bracket_ipv6_never_reaches_socket(monkeypatch, target):
    def forbidden(*args, **kwargs):
        pytest.fail('invalid target reached a socket')
    monkeypatch.setattr(agent.socket, 'create_connection', forbidden)
    monkeypatch.setattr(agent.socket, 'socket', forbidden)
    with pytest.raises(ValueError):
        agent.Agent._split_host_port(target)
    instance = agent.Agent.__new__(agent.Agent)
    for kind in ('tcp', 'udp'):
        assert instance.probe(kind, target, 2) == (False, None, None)


@pytest.mark.parametrize('kind', ['tcp', 'udp'])
@pytest.mark.parametrize('target', [
    '2001:db8::1:443', '::1:443',
    '[2001:db8::1]:0', '[2001:db8::1]:65536', '[2001:::1]:443', '1:1',
])
def test_public_http_still_rejects_bad_syntax(db, http, kind, target):
    source = node(db)
    before = db.query(Monitor).count()
    response = http.post('/monitors/', json={
        'name': 'negative', 'node_id': source.id, 'type': kind, 'target': target,
    })
    assert response.status_code == 422, response.text
    assert db.query(Monitor).count() == before


def test_served_artifact_manifest_matches_exact_bytes(http, monkeypatch):
    import hashlib
    monkeypatch.delenv('STELLA_AGENT_ROLLOUT_VERSION', raising=False)
    body = (Path(__file__).resolve().parents[1] / 'agent/stella_agent.py').read_bytes()
    script = http.get('/agent/script')
    assert script.status_code == 200 and script.content == body
    version = http.get('/agent/version')
    assert version.status_code == 200
    assert version.json()['sha256'] == hashlib.sha256(body).hexdigest()
    assert version.json()['size'] == len(body)
