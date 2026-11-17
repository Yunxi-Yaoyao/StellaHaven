"""Owned loopback UDP transport plus bounded synthetic failure regressions."""
import importlib.util
import socket
import threading
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    'udp_ipv6_agent', Path(__file__).resolve().parents[1] / 'agent/stella_agent.py')
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)

# The external acceptance runner consults only this process-owned set. No live nodes.
OWNED_SOCKETS = set()


@pytest.mark.parametrize('reply', [True, False])
@pytest.mark.parametrize('family,host', [(socket.AF_INET6, '::1'), (socket.AF_INET, '127.0.0.1')])
def test_real_owned_loopback_roundtrip(monkeypatch, family, host, reply):
    received, replies, opened = [], [], []
    real_socket = socket.socket

    class OwnedSocket(real_socket):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            OWNED_SOCKETS.add(self)
            opened.append(self)

        def recvfrom(self, size, *args):
            value = super().recvfrom(size, *args)
            if self is not listener:
                replies.append(value)
            return value

    monkeypatch.setattr(agent.socket, 'socket', OwnedSocket)
    try:
        listener = OwnedSocket(family, socket.SOCK_DGRAM)
        listener.bind((host, 0))
    except OSError as exc:
        for sock in opened:
            sock.close()
        OWNED_SOCKETS.clear()
        if family == socket.AF_INET6:
            pytest.skip(f'IPv6 loopback unavailable: {exc}')
        raise
    listener.settimeout(.5)
    endpoint = listener.getsockname()

    def echo():
        try:
            payload, peer = listener.recvfrom(1024)
            received.append((payload, peer))
            if reply:
                listener.sendto(b'owned-loopback-reply', peer)
        except OSError:
            pass

    worker = threading.Thread(target=echo)
    worker.start()
    try:
        target = f'[{host}]:{endpoint[1]}' if family == socket.AF_INET6 else f'{host}:{endpoint[1]}'
        timeout = .4 if reply else .08
        result = agent.Agent.__new__(agent.Agent).probe('udp', target, timeout)
        worker.join(1)
        assert not worker.is_alive()
        assert result[0] is reply, (result, received, replies)
        assert (result[1] is not None and result[1] >= 0) if reply else result[1] is None
        assert result[2] is None
        assert received and received[0][0] == b'\x00'
        if reply:
            assert replies == [(b'owned-loopback-reply', endpoint)]
        else:
            assert replies == []
            assert result == (False, None, None)
        assert opened[-1].family == family
        assert opened[-1].fileno() == -1  # helper closes even on success
    finally:
        for sock in opened:
            sock.close()
        worker.join(1)
        OWNED_SOCKETS.clear()


class SyntheticUDP:
    """No real network: controllable elapsed time and precise resource accounting."""
    def __init__(self, monkeypatch, plans, dns_delay=0, dns_error=None):
        self.now = 0.
        self.opened, self.attempts, self.resolutions = [], [], []
        self.addresses = [
            (socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP, '', ('::1', 9999, 0, 0)),
            (socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP, '', ('127.0.0.1', 9999)),
        ]

        def resolve(*args):
            self.resolutions.append(args)
            self.now += dns_delay
            if dns_error:
                raise dns_error
            return self.addresses

        def create(family, socktype, proto=0):
            index = len(self.attempts)
            self.attempts.append((family, socktype, proto))
            plan = plans[index] if index < len(plans) else {}
            if plan.get('error') == 'create':
                raise OSError('synthetic create failure')
            parent = self

            class Sock:
                closed = 0
                sent = None

                def __init__(self):
                    self.timeouts = []

                def settimeout(self, value):
                    self.timeouts.append(value)
                    if plan.get('error') == 'settimeout':
                        raise OSError('synthetic settimeout failure')

                def sendto(self, payload, address):
                    self.sent = (payload, address)
                    parent.now += plan.get('send_cost', 0)
                    if plan.get('error') == 'send':
                        raise OSError('synthetic send failure')
                    return len(payload)

                def recvfrom(self, size):
                    parent.now += plan.get('recv_cost', 0)
                    if plan.get('error') == 'recv':
                        raise OSError('synthetic recv failure')
                    if plan.get('silent'):
                        parent.now += self.timeouts[-1]
                        raise socket.timeout('synthetic no-response')
                    return b'reply', self.sent[1]

                def close(self):
                    self.closed += 1

            sock = Sock()
            self.opened.append(sock)
            return sock

        monkeypatch.setattr(agent.socket, 'getaddrinfo', resolve)
        monkeypatch.setattr(agent.socket, 'socket', create)
        monkeypatch.setattr(agent.time, 'monotonic', lambda: self.now)

    def probe(self, timeout=1):
        return agent.Agent.__new__(agent.Agent)._probe_udp('owned.test:9999', timeout)


@pytest.mark.parametrize('error', ['create', 'settimeout', 'send', 'recv'])
def test_candidate_error_closes_then_falls_back_to_other_family(monkeypatch, error):
    io = SyntheticUDP(monkeypatch, [{'error': error}, {}])
    result = io.probe()
    assert result[0] is True and result[2] is None
    assert io.resolutions == [('owned.test', 9999, socket.AF_UNSPEC, socket.SOCK_DGRAM)]
    assert io.attempts == [(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP),
                           (socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)]
    assert io.opened[-1].sent == (b'\x00', ('127.0.0.1', 9999))
    assert all(s.closed == 1 for s in io.opened)


def test_many_a_aaaa_candidates_have_fixed_attempt_cap(monkeypatch):
    io = SyntheticUDP(monkeypatch, [{'error': 'send'}] * 8 + [{}])
    io.addresses *= 20
    assert io.probe() == (False, None, None)
    assert len(io.attempts) == 8
    assert len(io.opened) == 8 and all(s.closed == 1 for s in io.opened)


def test_send_and_receive_and_fallback_share_one_monotonic_budget(monkeypatch):
    io = SyntheticUDP(monkeypatch, [
        {'send_cost': .2, 'recv_cost': .3, 'error': 'recv'},
        {'send_cost': .2, 'silent': True},
    ])
    result = io.probe()
    assert result == (False, None, None)
    assert io.now == pytest.approx(1)
    assert io.opened[0].timeouts == pytest.approx([1, .8])
    assert io.opened[1].timeouts == pytest.approx([.5, .3])
    assert all(s.closed == 1 for s in io.opened)


def test_resolution_elapsed_budget_prevents_socket_creation(monkeypatch):
    io = SyntheticUDP(monkeypatch, [{}], dns_delay=2)
    assert io.probe() == (False, None, None)
    assert io.attempts == []


def test_exhausted_send_budget_never_waits_again(monkeypatch):
    io = SyntheticUDP(monkeypatch, [{'send_cost': 1.1}])
    assert io.probe() == (False, None, None)
    assert len(io.attempts) == 1
    assert io.opened[0].timeouts == [1]
    assert io.opened[0].closed == 1


def test_exhausted_error_budget_never_tries_next_address(monkeypatch):
    io = SyntheticUDP(monkeypatch, [{'send_cost': 1.1, 'error': 'send'}])
    assert io.probe() == (False, None, None)
    assert len(io.attempts) == 1 and io.opened[0].closed == 1


@pytest.mark.parametrize('addresses', [[], [(socket.AF_UNIX, socket.SOCK_DGRAM, 0, '', 'invalid')]])
def test_empty_or_unsupported_resolution_is_failure_without_socket(monkeypatch, addresses):
    io = SyntheticUDP(monkeypatch, [{}])
    io.addresses = addresses
    assert io.probe() == (False, None, None)
    assert io.attempts == []


def test_dns_error_is_failure_without_socket(monkeypatch):
    io = SyntheticUDP(monkeypatch, [{}], dns_error=socket.gaierror('synthetic DNS failure'))
    assert io.probe() == (False, None, None)
    assert io.attempts == []


def test_no_response_never_claims_available_or_measured_latency(monkeypatch):
    io = SyntheticUDP(monkeypatch, [{'silent': True}])
    result = io.probe()
    assert result == (False, None, None)
    assert len(io.attempts) == 1 and io.opened[0].closed == 1
