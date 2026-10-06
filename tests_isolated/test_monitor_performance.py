"""No DB connection/agent execution: exercise service query contracts."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import pytest
from app.services import node, monitor

@pytest.mark.parametrize('service, repository', [
    (node.get_node_metrics, 'get_metrics'),
    (node.get_node_sys_metrics, 'get_sys_metrics'),
    (node.get_traffic_stats, 'get_traffic_stats'),
])
def test_default_history_is_bounded_to_one_hour(monkeypatch, service, repository):
    capture = Mock(return_value={} if repository == 'get_traffic_stats' else [])
    monkeypatch.setattr(node.repo, repository, capture)
    service(None, 7)
    args = capture.call_args.args
    start, end = (args[3:5] if repository != 'get_sys_metrics' else args[2:4])
    assert isinstance(start, datetime) and isinstance(end, datetime)
    assert end - start == timedelta(hours=1)
    assert start.tzinfo == timezone.utc


@pytest.mark.parametrize('kwargs', [
    {'limit': -1}, {'limit': 0}, {'limit': 5001}, {'step': 0}, {'step': -3},
    {'start': datetime(2026, 1, 2, tzinfo=timezone.utc), 'end': datetime(2026, 1, 1, tzinfo=timezone.utc)},
    {'start': datetime(2026, 1, 1, tzinfo=timezone.utc), 'end': datetime(2026, 3, 1, tzinfo=timezone.utc)},
    {'start': datetime(2026, 1, 1), 'end': datetime(2026, 1, 2)},
])
def test_invalid_query_is_http_422_without_query(monkeypatch, kwargs):
    from fastapi import HTTPException
    capture = Mock(return_value=[])
    monkeypatch.setattr(node.repo, 'get_metrics', capture)
    with pytest.raises(HTTPException) as error:
        node.get_node_metrics(None, 7, **kwargs)
    assert error.value.status_code == 422
    capture.assert_not_called()



def test_default_monitor_series_is_bounded(monkeypatch):
    capture = Mock(return_value=[])
    monkeypatch.setattr(monitor.repo, 'list_checks_range', capture)
    monitor.list_checks_range(None, 7)
    _, _, start, end, _ = capture.call_args.args
    assert end - start == timedelta(hours=1)


def test_monitor_buckets_aggregate_whole_window_before_point_limit(monkeypatch):
    aggregated = [{'ts': datetime(2026, 1, 1, tzinfo=timezone.utc), 'success': True,
                   'latency_ms': 5, 'loss_pct': 0, 'sample_count': 20000,
                   'success_count': 19999, 'latency_count': 19999, 'loss_count': 20000}]
    capture = Mock(return_value=aggregated)
    monkeypatch.setattr(monitor.repo, 'list_checks_bucketed', capture, raising=False)
    monkeypatch.setattr(monitor.repo, 'list_checks_range', Mock(return_value=[]))
    rows = monitor.list_checks_range(None, 7, datetime(2026, 1, 1, tzinfo=timezone.utc),
                                    datetime(2026, 1, 2, tzinfo=timezone.utc), 3600, 200)
    assert rows == aggregated
    capture.assert_called_once()


def test_database_timeout_is_controlled_http503_and_rollback(monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy.exc import OperationalError
    from types import SimpleNamespace
    failure = OperationalError('query', {}, SimpleNamespace(pgcode='57014'))
    monkeypatch.setattr(node.repo, 'get_metrics', Mock(side_effect=failure))
    db=Mock()
    with pytest.raises(HTTPException) as error:
        node.get_node_metrics(db, 7)
    assert error.value.status_code == 503
    assert error.value.detail['code'] == 'monitor_query_timeout'
    db.rollback.assert_called_once()
    assert 'statement_timeout' in str(db.execute.call_args.args[0])


def test_real_router_returns_422_for_bad_budget_and_200_for_default(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.monitor import node_router, current_user, get_db
    capture=Mock(return_value=[])
    monkeypatch.setattr(node.repo, 'get_metrics', capture)
    app=FastAPI(); app.include_router(node_router)
    app.dependency_overrides[current_user]=lambda: object()
    app.dependency_overrides[get_db]=lambda: None
    with TestClient(app) as client:
        assert client.get('/nodes/7/metrics?limit=-1').status_code==422
        assert client.get('/nodes/7/metrics?start=2026-01-02T00:00:00Z&end=2026-01-01T00:00:00Z').status_code==422
        capture.assert_not_called()
        assert client.get('/nodes/7/metrics').status_code==200
        args=capture.call_args.args
        assert args[4]-args[3]==timedelta(hours=1)
