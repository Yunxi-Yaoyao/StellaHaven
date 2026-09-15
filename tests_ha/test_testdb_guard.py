"""Offline guard tests: never import application/conftest or connect to PG."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

HELPER = Path(__file__).with_name("testdb_guard.py")


def load_guard():
    assert HELPER.exists(), "test database guard is missing"
    spec = importlib.util.spec_from_file_location("testdb_guard", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_production_is_rejected_before_engine_creation():
    guard = load_guard()
    factory = Mock(side_effect=AssertionError("must not create/connect engine"))
    with pytest.raises(ValueError, match="test database"):
        guard.build_test_engine("postgresql://stalla:secret@localhost:5432/stella", {}, factory)
    factory.assert_not_called()


@pytest.mark.parametrize("dsn,env", [
    ("postgresql://poc:x@172.25.0.2:5432/stella_ha_integration", {}),
    ("postgresql://stalla:x@postgres:5432/stella", {"CI": "true"}),
    ("postgresql://poc:x@172.25.0.2:5432/stella_test_ha_integration", {}),
])
def test_exact_allowed_targets(dsn, env):
    url = load_guard().select_test_url(dsn, env)
    assert url.database in {"stella_test_ha_integration", "stella_test"}


@pytest.mark.parametrize("dsn,env", [
    ("postgresql://stalla:x@localhost:30432/stella", {}),
    ("postgresql://stalla:x@127.0.0.1:5432/stella_test", {}),
    ("postgresql://poc:x@172.25.0.2:5432/stella", {}),
    ("postgresql://poc:x@172.25.0.2:5432/stella_ha_integration_backup", {}),
    ("postgresql://poc:x@172.25.0.2:5432/stella_test_ha_integration?hostaddr=127.0.0.1", {}),
    ("postgresql://poc:x@172.25.0.2:5432/stella_test_ha_integration?service=prod", {}),
    ("postgresql://poc:x@172.25.0.2:5432/stella_test_ha_integration", {"PGSERVICE": "prod"}),
    ("postgresql://poc:x@172.25.0.2:5432/stella_test_ha_integration", {"PGHOSTADDR": "127.0.0.1"}),
    ("postgresql://poc:x@172.25.0.2:5432/stella_test_ha_integration", {"PGOPTIONS": "-c role=admin"}),
    ("postgresql://stalla:x@postgres:5432/stella_test", {}),
    ("postgresql://stalla:x@postgres:5432/stella_test", {"CI": "false"}),
    ("postgresql://poc:x@172.25.0.2:5432/stella_test_ha_integration", {"STELLA_TEST_DATABASE_URL": "postgresql://poc:x@172.25.0.2:5432/stella_ha_integration"}),
])
def test_unsafe_targets_never_create_engine(dsn, env):
    factory = Mock(side_effect=AssertionError("NoConnect"))
    with pytest.raises(ValueError, match="test database"):
        load_guard().build_test_engine(dsn, env, factory)
    factory.assert_not_called()


@pytest.mark.parametrize("row", [
    ("stella", "poc", "172.25.0.2", 5432, "ha-integration-test-only"),
    ("stella_test_ha_integration", "poc", "127.0.0.1", 5432, "ha-integration-test-only"),
    ("stella_test_ha_integration", "poc", "172.25.0.2", 30432, "ha-integration-test-only"),
    ("stella_test_ha_integration", "poc", "172.25.0.2", 5432, None),
])
def test_connection_identity_fail_closed(row):
    guard = load_guard()
    url = guard.select_test_url("postgresql://poc:x@172.25.0.2:5432/stella_test_ha_integration", {})
    with pytest.raises(ValueError):
        guard.verify_identity(row, url, "172.25.0.2")


def test_connection_identity_allowed():
    guard = load_guard()
    url = guard.select_test_url("postgresql://poc:x@172.25.0.2:5432/stella_test_ha_integration", {})
    guard.verify_identity((url.database, url.username, url.host, 5432, "ha-integration-test-only"), url, url.host)


@pytest.mark.parametrize("operation", ["create_all", "drop_all"])
@pytest.mark.parametrize("valid", [True, False])
def test_ddl_checks_identity_on_same_connection(operation, valid):
    from unittest.mock import MagicMock
    guard = load_guard()
    url = guard.select_test_url("postgresql://poc:x@172.25.0.2:5432/stella_test_ha_integration", {})
    engine = MagicMock()
    revalidate = Mock()
    engine._stella_test_identity = (url, url.host, revalidate)
    connection = engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.one.return_value = (
        url.database if valid else "stella", url.username, url.host, 5432, guard.MARKER
    )
    metadata = Mock()
    if valid:
        guard.guarded_metadata(engine, metadata, operation)
        getattr(metadata, operation).assert_called_once_with(bind=connection)
    else:
        with pytest.raises(ValueError):
            guard.guarded_metadata(engine, metadata, operation)
        getattr(metadata, operation).assert_not_called()
    revalidate.assert_called_once()


def test_allowed_engine_is_lazy_and_environment_rechecked():
    guard = load_guard()
    env = {}
    engine = guard.build_test_engine("postgresql://poc:x@172.25.0.2:5432/stella_test_ha_integration", env)
    try:
        env["PGSERVICE"] = "production"
        # A patched driver proves rejection occurs before *any* network connection.
        from unittest.mock import patch
        with patch.object(engine.dialect, "connect", side_effect=AssertionError("NoConnect")) as connect:
            with pytest.raises(ValueError):
                engine.connect()
            connect.assert_not_called()
    finally:
        engine.dispose()


def test_conftest_rejects_production_before_importing_app(monkeypatch):
    import runpy
    import sys
    import types
    from unittest.mock import patch
    config = types.ModuleType("app.config")
    config.settings = types.SimpleNamespace(database_url="postgresql://stalla:x@localhost:5432/stella")
    monkeypatch.setitem(sys.modules, "app.config", config)
    with patch("sqlalchemy.create_engine", side_effect=AssertionError("NoConnect")) as create:
        with pytest.raises(ValueError, match="test database"):
            runpy.run_path(str(HELPER.parents[1] / "tests" / "conftest.py"))
        create.assert_not_called()
