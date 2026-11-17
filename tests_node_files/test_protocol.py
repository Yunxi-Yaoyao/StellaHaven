import importlib


def test_dedicated_router_exists():
    router = importlib.import_module('app.routers.node_files')
    assert router.router.prefix == '/node-files'
    assert router.agent_router.prefix == '/agent/files'
