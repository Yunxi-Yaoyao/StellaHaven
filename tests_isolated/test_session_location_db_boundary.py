"""Real ASGI/DI regressions for the sync DB / async location boundary."""
import asyncio
import threading
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event

from tests_isolated.test_browser_sessions import api, login


@pytest.mark.parametrize('slow_stage', ['select', 'rollback'])
def test_slow_database_does_not_block_http_heartbeat(api, monkeypatch, slow_stage):
    assert login(api).status_code == 200
    with api.factory() as db:
        target = api.AuthSession(user_id=api.uid, refresh_hash='other-owned-session', ip='8.8.4.4')
        db.add(target)
        db.commit()
        sid = target.id
    engine = api.factory.kw['bind']
    sql_threads, rollback_threads, sessions, ticks = [], [], [], []

    def before_cursor(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            sql_threads.append(threading.get_ident())
            if slow_stage == 'select' and sid.hex in parameters:
                time.sleep(0.30)

    def on_rollback(conn):
        rollback_threads.append(threading.get_ident())
        if slow_stage == 'rollback':
            time.sleep(0.30)

    def after_begin(session, transaction, connection):
        sessions.append(session)

    event.listen(engine, 'before_cursor_execute', before_cursor)
    event.listen(engine, 'rollback', on_rollback)
    event.listen(api.factory, 'after_begin', after_begin)
    from app.services import session_location as geo
    loop_thread = None

    async def lookup(ip):
        assert threading.get_ident() == loop_thread
        assert ip == '8.8.4.4'
        assert sessions and all(not session.in_transaction() for session in sessions)
        await asyncio.sleep(0.03)
        return 'TEST-LOCATION'

    monkeypatch.setattr(geo, 'lookup_location', lookup)

    async def run():
        nonlocal loop_thread
        loop_thread = threading.get_ident()
        app = api.client.app

        @app.get('/test-heartbeat')
        async def heartbeat_endpoint():
            return {'ok': True}

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='https://one.test', cookies=api.client.cookies) as client:
            async def heartbeat():
                while True:
                    assert (await client.get('/test-heartbeat')).status_code == 200
                    ticks.append(time.monotonic())
                    await asyncio.sleep(0.01)

            beat = asyncio.create_task(heartbeat())
            try:
                await asyncio.sleep(0.03)
                start = time.monotonic()
                response = await client.get(f'/auth/sessions/{sid}/location')
                elapsed = time.monotonic() - start
                await asyncio.sleep(0.03)
            finally:
                beat.cancel()
                await asyncio.gather(beat, return_exceptions=True)
        assert response.status_code == 200
        assert response.json() == {'ip': '8.8.4.4', 'ip_location': 'TEST-LOCATION'}
        gap = max(b - a for a, b in zip(ticks, ticks[1:]))
        print(f'{slow_stage}: elapsed={elapsed:.3f}s heartbeat_max_gap={gap:.3f}s '
              f'loop_thread={loop_thread} sql_threads={set(sql_threads)} '
              f'rollback_threads={set(rollback_threads)}')
        assert elapsed >= 0.30
        assert gap < 0.15, 'synchronous database work blocked the HTTP event loop'
        assert sql_threads and rollback_threads
        assert loop_thread not in sql_threads + rollback_threads

    try:
        asyncio.run(run())
    finally:
        event.remove(engine, 'before_cursor_execute', before_cursor)
        event.remove(engine, 'rollback', on_rollback)
        event.remove(api.factory, 'after_begin', after_begin)


def test_location_http_authorization_before_lookup(api, monkeypatch):
    assert login(api).status_code == 200
    with api.factory() as db:
        own = db.query(api.AuthSession).one()
        own.ip = '8.8.4.4'
        own_id = own.id
        foreign = api.User(username='foreign-boundary', display_name='Foreign', password_hash='x')
        db.add(foreign)
        db.flush()
        other = api.AuthSession(user_id=foreign.id, refresh_hash='foreign-boundary', ip=own.ip)
        db.add(other)
        db.commit()
        foreign_id = other.id
    from app.services import session_location as geo
    calls = []

    async def lookup(ip):
        calls.append(ip)
        return 'TEST-CACHED'

    monkeypatch.setattr(geo, 'lookup_location', lookup)
    assert api.client.get(f'/auth/sessions/{own_id}/location?ip=1.1.1.1').json() == {
        'ip': '8.8.4.4', 'ip_location': 'TEST-CACHED'}
    assert api.client.get(f'/auth/sessions/{foreign_id}/location').status_code == 404
    assert api.client.get(f'/auth/sessions/{uuid4()}/location').status_code == 404
    assert api.client.get('/auth/sessions/bad/location').status_code == 422
    api.client.cookies.clear()
    assert api.client.get(f'/auth/sessions/{own_id}/location').status_code == 401
    assert calls == ['8.8.4.4']
