import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_secondary_and_unknown_block_http_and_websocket():
    from app.services.ha_readiness import PrimaryOnlyMiddleware
    for state in (False, None):
        calls=[]
        async def ready():return state
        app=FastAPI()
        @app.post('/save')
        def save():calls.append('write');return {'ok':True}
        @app.get('/live')
        def live():return {'alive':True}
        @app.websocket('/ws')
        async def ws(socket):
            await socket.accept();await socket.send_text('opened');await socket.close()
        app.add_middleware(PrimaryOnlyMiddleware, enabled=True, checker=ready)
        with TestClient(app) as c:
            assert c.post('/save').status_code==503
            assert c.get('/live').status_code==200
            assert c.get('/ready-primary').status_code==503
            with pytest.raises(Exception):
                with c.websocket_connect('/ws') as socket:socket.receive_text()
        assert calls==[]


def test_primary_allows_requests_but_does_not_elect():
    from app.services.ha_readiness import PrimaryOnlyMiddleware
    async def ready():return True
    app=FastAPI()
    @app.post('/save')
    def save():return {'ok':True}
    app.add_middleware(PrimaryOnlyMiddleware,enabled=True,checker=ready)
    with TestClient(app) as c:
        assert c.post('/save').status_code==200
        assert c.get('/ready-primary').status_code==200


def test_legacy_disabled_and_checker_error_is_closed():
    from app.services.ha_readiness import PrimaryOnlyMiddleware
    async def broken():raise OSError('no lease evidence')
    for enabled,status in [(True,503),(False,200)]:
        app=FastAPI()
        @app.get('/test')
        def route():return {'ok':True}
        app.add_middleware(PrimaryOnlyMiddleware,enabled=enabled,checker=broken)
        with TestClient(app) as c:assert c.get('/test').status_code==status
