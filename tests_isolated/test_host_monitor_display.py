from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
import pytest


@pytest.fixture
def host_db(monkeypatch):
    from app.models.config import AppConfig
    monkeypatch.setenv('STELLA_MAIN_ORIGIN', 'https://host-fixture.test')
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'https://host-fixture.test')
    engine = create_engine('sqlite://')
    AppConfig.__table__.create(engine)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def test_managed_host_uses_node_inventory_not_pod_process(monkeypatch, host_db):
    from app.routers import monitor
    node = SimpleNamespace(id=19, installed=True, os_name='Arch', platform='linux', status='online', last_seen_at=datetime.now(timezone.utc))
    monkeypatch.setattr(monitor.node_svc, 'get_host_node', lambda _: node)
    monkeypatch.setattr(monitor.host_svc, 'is_agent_installed', lambda: False)
    response=monitor.get_host(user=None, db=host_db)
    assert response['installed'] is True
    assert response['node_id']==19
    assert response['installation_url'] == 'https://host-fixture.test'
    assert response['installation']['status'] == 'not_started'


def test_container_does_not_offer_or_execute_local_install(monkeypatch, host_db):
    from app.routers import monitor
    from fastapi import HTTPException
    import pytest
    monkeypatch.setenv('KUBERNETES_SERVICE_HOST','kubernetes')
    monkeypatch.setattr(monitor.node_svc, 'get_host_node', lambda _: None)
    install=Mock();monkeypatch.setattr(monitor.node_svc,'install_host_node',install)
    monkeypatch.setattr(monitor.host_svc, 'detect_os', lambda: 'container Debian')
    response = monitor.get_host(user=None,db=host_db)
    assert response['local_install_supported'] is False
    assert response['os'] == ''
    with pytest.raises(HTTPException) as exc:
        monitor.install_host(user=None,db=host_db)
    assert exc.value.status_code==409
    install.assert_not_called()


def test_monitor_queries_order_by_stable_id():
    from app.repositories import monitor
    from app.models.monitor import Monitor
    db=Mock()
    for call in (lambda:monitor.list_all(db), lambda:monitor.list_for_node(db,19)):
        captured=[]
        class Query:
            def filter(self,*args):return self
            def order_by(self,*args):captured.extend(args);return self
            def offset(self,*args):return self
            def limit(self,*args):return self
            def all(self):return []
        db.query.return_value=Query();call()
        assert [str(x.compile(dialect=postgresql.dialect())) for x in captured]==['monitors.id ASC']
