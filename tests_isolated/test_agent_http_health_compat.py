"""Actual loopback HTTP responses through the candidate Agent, no urlopen mock."""
import importlib.util
import math
from pathlib import Path
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.fixture
def agent():
    spec = importlib.util.spec_from_file_location('health_compat_agent', Path(__file__).parents[1]/'agent/stella_agent.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Agent.__new__(module.Agent)


@pytest.fixture
def http_fixture():
    calls = []
    release = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            if self.path == '/disconnect':
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if self.path == '/timeout':
                release.wait(2)
                return
            status = 302 if self.path == '/redirect' else int(self.path[1:])
            self.send_response(status)
            if status == 302:
                self.send_header('Location', '/403')
            self.send_header('Content-Length', '0')
            self.end_headers()
        def log_message(self, format, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', calls
    finally:
        release.set()
        server.shutdown(); server.server_close(); thread.join(3)
        assert not thread.is_alive()


@pytest.mark.parametrize('status', [200, 204, 401, 403, 404, 429, 500, 503])
def test_real_http_availability_means_status_below_500(agent, http_fixture, status):
    base, calls = http_fixture
    success, latency, loss = agent.probe('http', f'{base}/{status}', 1)
    assert calls == [f'/{status}']
    assert success is (status < 500), (status, success)
    assert math.isfinite(latency) and latency >= 0
    assert loss is None


def test_redirect_to_http_403_keeps_availability_contract(agent, http_fixture):
    base, calls = http_fixture
    success, latency, loss = agent.probe('http', base+'/redirect', 1)
    assert calls == ['/redirect', '/403']
    assert success is True
    assert math.isfinite(latency) and latency >= 0 and loss is None


@pytest.mark.parametrize('failure', ['disconnect', 'timeout'])
def test_real_http_transport_failure_remains_failure(agent, http_fixture, failure):
    base, calls = http_fixture
    success, latency, loss = agent.probe('http', base+'/'+failure, .05)
    assert calls == ['/'+failure]
    assert success is False
    assert math.isfinite(latency) and latency >= 0 and loss is None


def test_refused_owned_loopback_port_remains_failure(agent):
    with socket.socket() as bound_not_listening:
        bound_not_listening.bind(('127.0.0.1', 0))
        url = f'http://127.0.0.1:{bound_not_listening.getsockname()[1]}/'
        success, latency, loss = agent.probe('http', url, .2)
    assert success is False
    assert math.isfinite(latency) and latency >= 0 and loss is None
