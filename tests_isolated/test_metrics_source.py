"""Run with pytest --confcutdir=tests_isolated; never uses shared test DB."""
import importlib.util
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@compiles(JSONB, 'sqlite')
def jsonb_sqlite(type_, compiler, **kw):
    return 'JSON'


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    import httpx
    def blocked(*args, **kwargs):
        raise AssertionError('Live HTTP forbidden in isolated tests')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', blocked)


@pytest.fixture
def api():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    # Import-time default engine is replaced before app.database can construct it.
    with patch('sqlalchemy.create_engine', return_value=engine):
        assert importlib.util.find_spec('app.routers.metrics_source'), 'comparison/config router not implemented'
        from app.routers import metrics_source as routes
        from app.routers.auth import current_user
        from app.models import Node, NodeSysMetric, AppConfig
    for table in (Node.__table__, NodeSysMetric.__table__, AppConfig.__table__):
        table.create(engine)
    with Session(engine) as db:
        db.add(Node(id=7, name='private-test', platform='linux', host='192.0.2.7'))
        db.commit()
    def private_db():
        with Session(engine) as db:
            yield db
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_db] = private_db
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(is_admin=True)
    with TestClient(app) as client:
        yield client, app, engine, routes, current_user
    engine.dispose()


def test_config_opt_in_roundtrip(api):
    client, _, engine, _, _ = api
    assert client.get('/config/prometheus').json() == {'enabled': False, 'url': None, 'nodes': {}}
    data = {'enabled': True, 'url': 'http://192.0.2.10:9090', 'nodes': {'7': {'job': 'node', 'instance': '192.0.2.7:9100'}}}
    assert client.put('/config/prometheus', json=data).status_code == 200
    assert client.get('/config/prometheus').json() == data
    from app.models import AppConfig
    with Session(engine) as db:
        assert db.query(AppConfig).count() == 1
        assert db.get(AppConfig, 'prometheus_connection') is not None


def test_comparison_is_readonly_and_reports_raw_cadence(api):
    import threading
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    from app.models import NodeSysMetric, AppConfig
    client, _, engine, routes, _ = api
    data = {'enabled': True, 'url': 'http://192.0.2.10:9090', 'nodes': {'7': {'job': 'node', 'instance': '192.0.2.7:9100'}}}
    client.put('/config/prometheus', json=data)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add_all([NodeSysMetric(id=1, node_id=7, ts=now-timedelta(seconds=60), cpu_pct=20), NodeSysMetric(id=2, node_id=7, ts=now, cpu_pct=30)])
        db.commit()
    adapter = MagicMock()
    def snapshot(*args):
        import asyncio
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return {'source': 'prometheus', 'evaluatedAt': 1000, 'freshness': 'up', 'cpuPct': {'value': 40, 'timestamp': 1000, 'sampleTimestamp': 990}}
    adapter.snapshot.side_effect = snapshot
    adapter.sample_spacing.return_value = {'source': 'prometheus', 'sampleTimestamps': [960, 975, 990], 'spacingSeconds': [15, 15]}
    with patch.object(routes, 'PrometheusMetrics', create=True) as factory, patch.object(routes, 'PinnedTransport', create=True):
        factory.return_value.__enter__.return_value = adapter
        response = client.get('/nodes/7/metrics-comparison')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['nodeId'] == 7
    assert result['legacy']['latestSys']['cpuPct'] == 30
    assert result['legacy']['sysSampleSpacingSeconds'] == 60
    assert result['prometheus']['sampleSpacing']['spacingSeconds'] == [15, 15]
    assert result['equivalence']['status'] == 'not_equivalent'
    assert result['equivalence']['reason'] == 'sample_spacing_not_5s'
    adapter.snapshot.assert_called_once_with('node', '192.0.2.7:9100')
    adapter.sample_spacing.assert_called_once_with('node', '192.0.2.7:9100')
    with Session(engine) as db:
        assert db.query(NodeSysMetric).count() == 2
        assert db.query(AppConfig).count() == 1


@pytest.mark.parametrize('path', ['/config/prometheus', '/nodes/7/metrics-comparison'])
def test_admin_only(api, path):
    client, app, _, _, current_user = api
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(is_admin=False)
    assert client.get(path).status_code == 403
    if path == '/config/prometheus':
        assert client.put(path, json={'enabled': False}).status_code == 403
    app.dependency_overrides.pop(current_user)
    assert client.get(path).status_code == 401


def test_disabled_missing_node_and_missing_mapping_never_contact_prometheus(api):
    client, _, _, routes, _ = api
    with patch.object(routes, 'PrometheusMetrics', create=True) as factory:
        assert client.get('/nodes/7/metrics-comparison').status_code == 409
        assert client.get('/nodes/999/metrics-comparison').status_code == 404
        assert client.get('/nodes/not-an-id/metrics-comparison').status_code == 422
        factory.assert_not_called()


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'http://user:secret@example.com', 'http://example.com?q=1',
    'http://example.com/#x', 'http://127.0.0.1:9090', 'http://localhost:9090',
    'http://169.254.169.254', 'http://[::ffff:127.0.0.1]:9090', 'http://0.0.0.0',
    'http://example.com:99999', 'http://example.com:0', 'http://example.com/../admin',
    'http://example.com/%2e%2e', 'http://metadata.google.internal',
])
def test_unsafe_url_rejected_without_writes(api, url):
    client, _, engine, _, _ = api
    assert client.put('/config/prometheus', json={'url': url}).status_code == 422
    from app.models import AppConfig
    with Session(engine) as db:
        assert db.query(AppConfig).count() == 0


@pytest.mark.parametrize('data', [
    {'enabled': True}, {'nodes': {'999': {'job': 'node', 'instance': 'host:9100'}}},
    {'nodes': {'07': {'job': 'node', 'instance': 'host:9100'}}},
    {'nodes': {'7': {'job': '', 'instance': 'host:9100'}}},
    {'nodes': {'7': {'job': 'node', 'instance': 'host:9100', 'query': 'up'}}},
    {'query': 'up'},
])
def test_invalid_config_rejected(api, data):
    assert api[0].put('/config/prometheus', json=data).status_code == 422


def test_pinned_transport_keeps_host_sni_rejects_dns_metadata(api):
    import httpx
    import socket
    routes = api[3]
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.10', 9090))]
    with patch.object(routes.socket, 'getaddrinfo', return_value=answers), patch.object(routes.httpx, 'HTTPTransport') as inner:
        transport = routes.PinnedTransport('https://prom.example:9090')
        request = httpx.Request('GET', 'https://prom.example:9090/api/v1/query', extensions={'timeout': {'read': 5}})
        transport.handle_request(request)
        sent = inner.return_value.handle_request.call_args.args[0]
        assert sent.url.host == '192.0.2.10'
        assert sent.headers['host'] == 'prom.example:9090'
        assert sent.extensions['sni_hostname'] == 'prom.example'
        assert sent.extensions['timeout']['read'] == 5
        with pytest.raises(ValueError):
            transport.handle_request(httpx.Request('GET', 'https://evil.example:9090'))
        transport.close()
        inner.return_value.close.assert_called_once()
    answers.append((socket.AF_INET, socket.SOCK_STREAM, 6, '', ('169.254.169.254', 9090)))
    with patch.object(routes.socket, 'getaddrinfo', return_value=answers):
        with pytest.raises(ValueError):
            routes.PinnedTransport('http://prom.example:9090')


@pytest.mark.parametrize('intervals,freshness,reason', [
    ([], 'up', 'insufficient_raw_samples'), ([5, 5], 'up', 'rate_window_and_metric_semantics_differ'),
    ([5, 5], 'stale', 'prometheus_not_fresh'), ([5.01], 'up', 'sample_spacing_not_5s'),
])
def test_cadence_does_not_claim_equivalence(api, intervals, freshness, reason):
    client, _, _, routes, _ = api
    client.put('/config/prometheus', json={'enabled': True, 'url': 'http://192.0.2.10:9090', 'nodes': {'7': {'job': 'node', 'instance': 'host:9100'}}})
    with patch.object(routes, 'PrometheusMetrics') as factory, patch.object(routes, 'PinnedTransport'):
        adapter = factory.return_value.__enter__.return_value
        adapter.snapshot.return_value = {'freshness': freshness}
        adapter.sample_spacing.return_value = {'sampleTimestamps': [], 'spacingSeconds': intervals}
        result = client.get('/nodes/7/metrics-comparison').json()
        assert result['legacy']['latestSys'] is None
        assert result['equivalence']['reason'] == reason
        assert result['equivalence']['status'] == 'not_equivalent'


def test_upstream_failure_is_sanitized_and_no_write(api):
    client, _, engine, routes, _ = api
    client.put('/config/prometheus', json={'enabled': True, 'url': 'http://192.0.2.10:9090', 'nodes': {'7': {'job': 'node', 'instance': 'host:9100'}}})
    with patch.object(routes, 'PrometheusMetrics') as factory, patch.object(routes, 'PinnedTransport'):
        factory.return_value.__enter__.return_value.snapshot.side_effect = routes.PrometheusError('secret upstream body')
        response = client.get('/nodes/7/metrics-comparison')
        assert response.status_code == 502
        assert 'secret' not in response.text
    from app.models import AppConfig
    with Session(engine) as db:
        assert db.query(AppConfig).count() == 1


def test_unmapped_node_and_corrupt_config_fail_closed(api):
    from app.models import Node, AppConfig
    client, _, engine, routes, _ = api
    client.put('/config/prometheus', json={'enabled': True, 'url': 'http://192.0.2.10:9090', 'nodes': {'7': {'job': 'node', 'instance': 'host:9100'}}})
    with Session(engine) as db:
        db.add(Node(id=8, name='unmapped', platform='linux', host='192.0.2.8'))
        db.commit()
    with patch.object(routes, 'PrometheusMetrics') as factory:
        assert client.get('/nodes/8/metrics-comparison').status_code == 409
        with Session(engine) as db:
            db.get(AppConfig, 'prometheus_connection').value = 'broken'
            db.commit()
        assert client.get('/config/prometheus').status_code == 409
        assert client.get('/nodes/7/metrics-comparison').status_code == 409
        factory.assert_not_called()


def test_main_registers_router_without_importing_app():
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).parents[1] / 'main.py').read_text())
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == 'include_router' and node.args
               and isinstance(node.args[0], ast.Name) and node.args[0].id == 'metrics_source_router'
               for node in ast.walk(tree))
