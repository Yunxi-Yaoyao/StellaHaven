"""Offline async deadline probes; no application/database/config imports."""
import asyncio
import importlib.util
from pathlib import Path
import time

import httpx
import pytest


@pytest.fixture
def geo(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'app/services/session_location.py'
    spec = importlib.util.spec_from_file_location('isolated_session_location', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    real_client = httpx.AsyncClient
    module._test_client = real_client
    def forbidden(*args, **kwargs):
        raise AssertionError('unmocked network request')
    monkeypatch.setattr(real_client, 'get', forbidden)
    monkeypatch.setattr(module.httpx, 'AsyncClient', forbidden)
    monkeypatch.setattr(module.httpx, 'stream', forbidden)
    return module


class Body(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0, eof_delay=0, close_delay=0):
        self.chunks, self.delay = chunks, delay
        self.eof_delay, self.close_delay = eof_delay, close_delay
        self.yielded = 0
        self.closed = False
        self.cancelled = False

    async def __aiter__(self):
        try:
            for chunk in self.chunks:
                await asyncio.sleep(self.delay)
                self.yielded += 1
                yield chunk
            await asyncio.sleep(self.eof_delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aclose(self):
        try:
            await asyncio.sleep(self.close_delay)
        finally:
            self.closed = True


def install_stream(geo, monkeypatch, body, header_delay=0, status=200):
    calls, options = [], []
    async def handler(request):
        calls.append(request)
        await asyncio.sleep(header_delay)
        return httpx.Response(status, stream=body)
    def client(**kwargs):
        options.append(kwargs)
        return geo._test_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(geo.httpx, 'AsyncClient', client)
    return calls, options


def test_slow_drip_expires_closes_stream_and_caches_unknown(geo, monkeypatch):
    body = Body([b'{', b'"country"', b':', b'"US"', b'}'], delay=0.55)
    calls, _ = install_stream(geo, monkeypatch, body)
    async def run():
        start = time.monotonic()
        result = await geo.lookup_location('8.8.4.4')
        elapsed = time.monotonic() - start
        print(f'async slow-drip elapsed={elapsed:.3f}s result={result!r} chunks={body.yielded}')
        assert result is None
        assert 1.8 <= elapsed < 2.35
        assert body.closed and body.cancelled and body.yielded == 3
        assert await geo.lookup_location('8.8.4.4') is None
        assert len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize('stage', ['headers', 'eof', 'close'])
def test_entire_stream_and_cleanup_share_budget(geo, monkeypatch, stage):
    body = Body([b'{"country":"US"}'], eof_delay=3 if stage == 'eof' else 0,
                close_delay=3 if stage == 'close' else 0)
    calls, _ = install_stream(geo, monkeypatch, body, header_delay=3 if stage == 'headers' else 0)
    async def run():
        start = time.monotonic()
        assert await geo.lookup_location('8.8.4.4') is None
        assert 1.8 <= time.monotonic() - start < 2.35
        if stage != 'headers':
            assert body.closed
        assert await geo.lookup_location('8.8.4.4') is None
        assert len(calls) == 1
    asyncio.run(run())


def test_fast_success_request_policy_and_cache(geo, monkeypatch):
    body = Body([b'{"country":" US ","region":"US","city":"Example"}'])
    calls, options = install_stream(geo, monkeypatch, body)
    async def run():
        assert await geo.lookup_location('8.8.4.4') == 'US · Example'
        assert await geo.lookup_location('8.8.4.4') == 'US · Example'
    asyncio.run(run())
    assert body.closed and len(calls) == 1
    assert calls[0].method == 'GET' and str(calls[0].url) == 'https://ipinfo.io/8.8.4.4/json'
    assert options == [{'timeout': 2.0, 'follow_redirects': False, 'trust_env': False}]


@pytest.mark.parametrize('size, expected', [(8192, 'US'), (8193, None)])
def test_byte_cap_including_exact_boundary(geo, monkeypatch, size, expected):
    raw = b'{"country":"US"}'
    body = Body([raw + b' ' * (size - len(raw))])
    calls, _ = install_stream(geo, monkeypatch, body)
    async def run():
        assert await geo.lookup_location('8.8.4.4') == expected
        assert await geo.lookup_location('8.8.4.4') == expected
    asyncio.run(run())
    assert body.closed and len(calls) == 1


@pytest.mark.parametrize('value, expected', [
    ('192.168.1.1', '局域网'), ('127.0.0.1', '局域网'), ('fe80::1', '局域网'),
    ('http://evil.test', None), ('ipinfo.io', None), ('8.8.4.4/path', None), ('100.64.0.1', None),
])
def test_nonpublic_and_invalid_input_never_requests_network(geo, value, expected):
    assert asyncio.run(geo.lookup_location(value)) == expected


@pytest.mark.parametrize('payload,status', [(b'not json', 200), (b'[]', 200), (b'{}', 302)])
def test_failure_and_redirect_are_cached(geo, monkeypatch, payload, status):
    body = Body([payload])
    calls, _ = install_stream(geo, monkeypatch, body, status=status)
    async def run():
        assert await geo.lookup_location('8.8.4.4') is None
        assert await geo.lookup_location('8.8.4.4') is None
    asyncio.run(run())
    assert len(calls) == 1 and body.closed


def test_cache_ttl_and_capacity(geo, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(geo, 'monotonic', lambda: now[0])
    calls, _ = install_stream(geo, monkeypatch, Body([b'{"country":"US"}']))
    async def run():
        assert await geo.lookup_location('8.8.4.4') == 'US'
        now[0] += 3599
        assert await geo.lookup_location('8.8.4.4') == 'US'
        now[0] += 2
        assert await geo.lookup_location('8.8.4.4') == 'US'
        for n in range(513):
            await geo.lookup_location(f'11.0.{n // 256}.{n % 256}')
    asyncio.run(run())
    assert len(calls) == 515 and len(geo._cache) == 512
    assert '8.8.4.4' not in geo._cache


def test_concurrency_admission_and_external_cancellation(geo, monkeypatch):
    body = Body([b'{}'], delay=10)
    calls, _ = install_stream(geo, monkeypatch, body)
    async def run():
        tasks = [asyncio.create_task(geo.lookup_location(f'11.0.0.{n}')) for n in range(16)]
        await asyncio.sleep(0.05)
        assert len(calls) == 16
        assert await geo.lookup_location('11.0.0.0') is None
        assert await geo.lookup_location('12.0.0.1') is None
        assert len(calls) == 16
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        assert not geo._inflight and body.closed
    asyncio.run(run())


def test_real_local_async_server_slow_drip_cancelled(geo, monkeypatch):
    """Only test transport rewrites destination; production still uses fixed HTTPS."""
    async def run():
        disconnected = asyncio.Event()
        handlers = set()
        async def handler(reader, writer):
            task = asyncio.current_task()
            handlers.add(task)
            try:
                await reader.readuntil(b'\r\n\r\n')
                writer.write(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n')
                await writer.drain()
                for chunk in [b'{', b'"country"', b':', b'"US"', b'}']:
                    await asyncio.sleep(0.55)
                    writer.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                    await writer.drain()
                writer.write(b'0\r\n\r\n')
                await writer.drain()
                await reader.read()
            except (ConnectionError, asyncio.IncompleteReadError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionError:
                    pass
                handlers.discard(task)
                disconnected.set()
        server = await asyncio.start_server(handler, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        class LocalTransport(httpx.AsyncBaseTransport):
            def __init__(self):
                self.inner = httpx.AsyncHTTPTransport()
                self.closed = False
                self.calls = 0
            async def handle_async_request(self, request):
                assert str(request.url) == 'https://ipinfo.io/8.8.4.4/json'
                self.calls += 1
                request.url = httpx.URL(f'http://127.0.0.1:{port}/json')
                return await self.inner.handle_async_request(request)
            async def aclose(self):
                await self.inner.aclose()
                self.closed = True
        transport = LocalTransport()
        monkeypatch.setattr(geo.httpx, 'AsyncClient', lambda **kw: geo._test_client(transport=transport, **kw))
        try:
            start = time.monotonic()
            assert await geo.lookup_location('8.8.4.4') is None
            elapsed = time.monotonic() - start
            print(f'local async HTTP slow-drip elapsed={elapsed:.3f}s client_closed={transport.closed}')
            assert 1.8 <= elapsed < 2.35 and transport.closed
            assert await geo.lookup_location('8.8.4.4') is None and transport.calls == 1
            await asyncio.wait_for(disconnected.wait(), 2)
        finally:
            server.close()
            await server.wait_closed()
            for task in list(handlers):
                task.cancel()
            await asyncio.gather(*handlers, return_exceptions=True)
    asyncio.run(run())
