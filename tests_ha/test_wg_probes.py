"""Pure WG probe contracts; no production database or network."""
from copy import deepcopy
import pytest
from test_server_map import node, NOW, wg_snapshot, svc


def pair():
    a, b = wg_snapshot('a', 'b'), wg_snapshot('b', 'a')
    b['wireguard']['interfaces'][0]['addresses'] = ['10.0.0.2/24']
    return {1: a, 2: b}


def probe(received=5):
    return dict(checked_at=NOW.isoformat(), status='ok' if received == 5 else ('degraded' if received else 'failed'),
                sent=5, received=received, loss_pct=(5-received)*20.0, rtt_ms=1.2 if received else None,
                target='10.0.0.2', reason=None)


def test_health_requires_both_fresh_directions_and_preserves_counts():
    snapshots = pair()
    snapshots[1]['wireguard']['interfaces'][0]['peers'][0]['probe'] = probe()
    result = svc().build_topology([node(), node(2)], snapshots, {}, now=NOW)
    assert len(result['links']) == 1
    assert result['links'][0]['health'] == 'unknown'
    snapshots[2]['wireguard']['interfaces'][0]['peers'][0]['probe'] = probe(3) | {'target':'10.0.0.1'}
    result = svc().build_topology([node(), node(2)], snapshots, {}, now=NOW)
    link = result['links'][0]
    assert link['health'] == 'degraded'
    assert [o['probe']['received'] for o in link['observations']] == [5, 3]
    assert result['stats']['node_pairs'] == result['stats']['matched_tunnels'] == 1
    assert result['stats']['unmatched_peers'] == 0
    snapshots[2]['wireguard']['interfaces'][0]['peers'][0]['probe']['checked_at'] = '2020-01-01T00:00:00Z'
    assert svc().build_topology([node(), node(2)], snapshots, {}, now=NOW)['links'][0]['health'] == 'unknown'


@pytest.mark.parametrize('change', [dict(sent=6), dict(received=6), dict(sent=True), dict(rtt_ms=float('nan')), dict(loss_pct=101), dict(checked_at='2026-01-01T00:00:00'), dict(status='ok', received=0)])
def test_probe_validation(change):
    from pydantic import ValidationError
    assert hasattr(svc(), 'Probe')
    with pytest.raises(ValidationError):
        svc().Probe.model_validate(probe() | change)


def test_agent_ping_is_bounded_and_parsed(monkeypatch):
    from test_agent_map import a
    assert hasattr(a, '_probe_map_targets')
    wg = pair()[1]['wireguard']
    calls = []
    monkeypatch.setattr(a.shutil, 'which', lambda _: '/usr/bin/ping')
    def run(args, **kw):
        calls.append((args, kw))
        return '5 packets transmitted, 3 received, 40% packet loss, time 800ms\nrtt min/avg/max/mdev = 1.000/2.000/3.000/0.100 ms\n'
    monkeypatch.setattr(a, '_map_command', run)
    targets = [dict(interface='wg0', peer_key_id='b'*64, target='10.0.0.2')]
    a._probe_map_targets(wg, targets)
    p = wg['interfaces'][0]['peers'][0]['probe']
    assert (p['status'], p['sent'], p['received'], p['rtt_ms']) == ('degraded', 5, 3, 2.0)
    assert calls[0][0][1:] == ['-n', '-I', 'wg0', '-c', '5', '-i', '0.2', '-W', '1', '10.0.0.2']
    assert calls[0][1]['timeout'] <= 5
    calls.clear()
    for target in ['1.1.1.1', ';id', '::1']:
        a._probe_map_targets(wg, [targets[0] | {'target': target}])
    a._probe_map_targets(wg, [targets[0] | {'interface': '-evil'}])
    assert calls == []
    monkeypatch.setattr(a.shutil, 'which', lambda _: None)
    a._probe_map_targets(wg, targets)
    assert wg['interfaces'][0]['peers'][0]['probe']['status'] == 'unknown'


@pytest.mark.parametrize('received,status', [(0, 'failed'), (5, 'ok')])
def test_ping_loss_status_and_local_longest_prefix(monkeypatch, received, status):
    from test_agent_map import a
    wg = pair()[1]['wireguard']
    target = dict(interface='wg0', peer_key_id='b'*64, target='10.0.0.2')
    monkeypatch.setattr(a.shutil, 'which', lambda _: '/usr/bin/ping')
    calls = []
    def run(*args, **kw):
        calls.append(args)
        return f'5 packets transmitted, {received} received, 0% packet loss'
    monkeypatch.setattr(a, '_map_command', run)
    a._probe_map_targets(wg, [target])
    assert wg['interfaces'][0]['peers'][0]['probe']['status'] == status
    competitor = deepcopy(wg['interfaces'][0]['peers'][0])
    competitor.update(public_key_id='c'*64, allowed_ips=['10.0.0.2/32'])
    wg['interfaces'][0]['peers'].append(competitor)
    calls.clear()
    a._probe_map_targets(wg, [target])
    assert calls == []


def test_agent_probe_budget_and_concurrency(monkeypatch):
    import threading
    import time
    from test_agent_map import a
    wg = pair()[1]['wireguard']
    template = wg['interfaces'][0]
    wg['interfaces'] = [deepcopy(template) | {'name': f'wg{i}'} for i in range(10)]
    targets = [dict(interface=f'wg{i}', peer_key_id='b'*64, target='10.0.0.2') for i in range(10)]
    monkeypatch.setattr(a.shutil, 'which', lambda _: '/usr/bin/ping')
    lock = threading.Lock()
    counts = dict(active=0, peak=0, calls=0)
    def run(*args, **kw):
        with lock:
            counts['active'] += 1
            counts['calls'] += 1
            counts['peak'] = max(counts['peak'], counts['active'])
        time.sleep(.005)
        with lock:
            counts['active'] -= 1
        return '5 packets transmitted, 5 received, 0% packet loss'
    monkeypatch.setattr(a, '_map_command', run)
    a._probe_map_targets(wg, targets)
    assert counts['calls'] == 8 and counts['peak'] <= 2
    counts['calls'] = 0
    a._probe_map_targets(wg, targets, deadline=time.monotonic()-1)
    assert counts['calls'] == 0
    assert wg['interfaces'][0]['peers'][0]['probe']['reason'] == 'probe_budget_exhausted'


def test_report_keeps_wg_on_target_or_location_failure(monkeypatch):
    from test_agent_map import a
    agent = a.Agent('https://unused.invalid', 'secret')
    assert hasattr(agent, '_get_map_targets')
    monkeypatch.setattr(a, '_collect_map_wireguard', lambda: pair()[1]['wireguard'])
    monkeypatch.setattr(a, '_collect_map_location', lambda: (_ for _ in ()).throw(ValueError()))
    monkeypatch.setattr(agent, '_get_map_targets', lambda: (_ for _ in ()).throw(ValueError()))
    posted = []
    monkeypatch.setattr(agent, '_post', lambda *args, **kwargs: posted.append(kwargs))
    agent._report_map_snapshot()
    assert posted[0]['json_body']['map_snapshot']['wireguard']['status'] == 'ok'


def test_targets_are_exact_key_unique_longest_prefix():
    snapshots = pair()
    s = svc()
    assert hasattr(s, 'build_probe_targets')
    expected = [dict(interface='wg0', peer_key_id='b'*64, target='10.0.0.2')]
    assert s.build_probe_targets(1, [node(), node(2)], snapshots, now=NOW) == expected
    iface = snapshots[1]['wireguard']['interfaces'][0]
    competitor = deepcopy(iface['peers'][0])
    competitor['public_key_id'] = 'c'*64
    iface['peers'].append(competitor)
    assert s.build_probe_targets(1, [node(), node(2)], snapshots, now=NOW) == []
    iface['peers'][0]['allowed_ips'] = ['10.0.0.2/32']
    assert s.build_probe_targets(1, [node(), node(2)], snapshots, now=NOW) == expected
    assert s.build_probe_targets(1, [node(status='removed'), node(2)], snapshots, now=NOW) == []
    assert s.build_probe_targets(1, [node(), node(2), node(3)], snapshots | {3: snapshots[2]}, now=NOW) == []


def test_misdirected_probe_does_not_mark_tunnel_healthy():
    snapshots=pair()
    snapshots[1]['wireguard']['interfaces'][0]['peers'][0]['probe']=probe() | {'target':'8.8.8.8'}
    snapshots[2]['wireguard']['interfaces'][0]['peers'][0]['probe']=probe() | {'target':'10.0.0.1'}
    link=svc().build_topology([node(),node(2)],snapshots,{},now=NOW)['links'][0]
    assert link['health']=='unknown'
