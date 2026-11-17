"""Manual WG contracts: synthetic discovery only, never real network or DB."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import importlib.util
from pathlib import Path
import pytest
from app.services import server_map as m

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)

def source():
    return SimpleNamespace(id=1, name='fixture', status='online', last_seen_at=NOW)

def snapshot():
    return dict(observed_at=NOW.isoformat(), location=dict(status='unknown', source='unknown'),
        wireguard=dict(status='ok', manual_probe_version=1, interfaces=[dict(name='wg0', public_key_id='a'*64,
            addresses=['10.0.0.1/24'], peers=[dict(public_key_id='b'*64,
                allowed_ips=['10.0.0.0/24'], latest_handshake_at=0, rx_bytes=0, tx_bytes=0)])]))

def intent(**change):
    return dict(node_id=1, interface='wg0', target='10.0.0.9') | change

def binding():
    return m.bind_manual_probe(intent(), [source()], {1:snapshot()}, now=NOW)

def load_agent():
    spec=importlib.util.spec_from_file_location('wg_manual_agent',Path(__file__).parents[1]/'agent/stella_agent.py')
    agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)
    return agent

def test_manual_agent_keeps_automatic_probe_separate_and_verifies_kernel_route(monkeypatch):
    a=load_agent();wg=snapshot()['wireguard'];calls=[]
    monkeypatch.setattr(a.shutil,'which',lambda name:'/usr/bin/'+name)
    monkeypatch.setattr(a.platform,'system',lambda:'Linux')
    def run(cmd,**kwargs):
        calls.append((cmd,kwargs))
        if cmd[0].endswith('/ip'):
            return '[{"dev":"wg0","prefsrc":"10.0.0.1","type":"unicast"}]'
        return '5 packets transmitted, 5 received, 0% packet loss'
    monkeypatch.setattr(a,'_map_command',run)
    automatic=dict(interface='wg0',peer_key_id='b'*64,target='10.0.0.2')
    manual=automatic|dict(target='10.0.0.9',manual=True,interface_key_id='a'*64)
    a._probe_map_targets(wg,[automatic,manual])
    peer=wg['interfaces'][0]['peers'][0]
    assert peer['probe']['target']=='10.0.0.2'
    assert peer.get('manual_probes') and peer['manual_probes'][0]['target']=='10.0.0.9'
    assert peer['manual_probes'][0]['status']=='ok'
    assert ['/usr/bin/ip','-j','-4','route','get','10.0.0.9'] in [c[0] for c in calls]
    assert all(0<c[1]['timeout']<=5 for c in calls)
    assert all('sudo' not in c[0] and 'shell' not in c[1] for c in calls)
    m.validate_snapshot(snapshot()|{'wireguard':wg})

def manual_service():
    assert importlib.util.find_spec('app.services.wg_manual') is not None, 'manual WG data path is missing'
    from app.services import wg_manual
    return wg_manual

def test_manual_targets_and_health_match_exact_binding_without_topology_replacement():
    w=manual_service();b=binding()
    r=SimpleNamespace(target=w.target_id(b),condition={'wg_manual':b},enabled=True,archived=False)
    assert w.probe_targets([r],1,[source()],{1:snapshot()},now=NOW)==[
        dict(interface='wg0',interface_key_id='a'*64,peer_key_id='b'*64,target='10.0.0.9',manual=True)]
    s=snapshot();p=s['wireguard']['interfaces'][0]['peers'][0]
    p['manual_probes']=[dict(checked_at=NOW.isoformat(),status='failed',sent=5,received=0,
        loss_pct=100.0,rtt_ms=None,target='10.0.0.9',reason='icmp_no_response')]
    assert w.health(r,[source()],{1:s},now=NOW)['health']=='failed'
    r.created_at=NOW+timedelta(seconds=1)
    assert w.health(r,[source()],{1:s},now=NOW)['health']=='unknown'
    r.created_at=None
    p['manual_probes'][0]['target']='10.0.0.8'
    assert w.health(r,[source()],{1:s},now=NOW)['health']=='unknown'
    assert w.health(r,[source()],{},now=NOW)['health']=='unknown'
    s=snapshot();s['wireguard']['interfaces'][0]['public_key_id']='c'*64
    assert w.probe_targets([r],1,[source()],{1:s},now=NOW)==[]
    assert w.health(r,[source()],{1:s},now=NOW)['health']=='unknown'
    assert m.build_topology([source()],{1:snapshot()},{},now=NOW)['links'][0]['target'] is None

@pytest.mark.parametrize('route',[[],[{'dev':'eth0','prefsrc':'10.0.0.1'}],
    [{'dev':'wg0','prefsrc':'192.168.1.1'}],[{'dev':'wg0','prefsrc':'10.0.0.1','type':'local'}]])
def test_manual_agent_route_rejection_is_unknown_and_sends_no_ping(monkeypatch,route):
    import json
    a=load_agent();wg=snapshot()['wireguard'];calls=[]
    monkeypatch.setattr(a.shutil,'which',lambda name:'/usr/bin/'+name)
    monkeypatch.setattr(a.platform,'system',lambda:'Linux')
    def run(cmd,**kwargs):calls.append(cmd);return json.dumps(route)
    monkeypatch.setattr(a,'_map_command',run)
    a._probe_map_targets(wg,[dict(interface='wg0',interface_key_id='a'*64,peer_key_id='b'*64,target='10.0.0.9',manual=True)])
    assert len(calls)==1 and calls[0][0]=='/usr/bin/ip'
    assert wg['interfaces'][0]['peers'][0]['manual_probes'][0]['status']=='unknown'

@pytest.mark.parametrize('change',[dict(interface='wg0;id'),dict(interface_key_id='c'*64),
    dict(peer_key_id='c'*64),dict(target='169.254.169.254'),dict(target='10.0.0.1'),
    dict(target='10.0.0.255'),dict(command='id'),dict(target='8.8.8.8'),dict(manual='true')])
def test_manual_agent_rejects_unsafe_configuration_before_any_command(monkeypatch,change):
    a=load_agent();wg=snapshot()['wireguard'];calls=[]
    monkeypatch.setattr(a,'_map_command',lambda *args,**kw:calls.append(args))
    a._probe_map_targets(wg,[dict(interface='wg0',interface_key_id='a'*64,peer_key_id='b'*64,target='10.0.0.9',manual=True)|change])
    assert calls==[]

def test_old_agent_without_route_validation_capability_gets_no_manual_target():
    w=manual_service();b=binding()
    r=SimpleNamespace(target=w.target_id(b),condition={'wg_manual':b},enabled=True,archived=False)
    s=snapshot();s['wireguard'].pop('manual_probe_version',None)
    assert w.probe_targets([r],1,[source()],{1:s},now=NOW)==[]

def test_manual_configuration_binds_discovered_identity_without_remote_node():
    assert hasattr(m, 'bind_manual_probe'), 'manual configuration must bind actual discovered WG identity'
    bound = m.bind_manual_probe(intent(), [source()], {1:snapshot()}, now=NOW)
    assert bound == intent() | {'interface_key_id':'a'*64, 'peer_key_id':'b'*64}
    assert snapshot()['wireguard']['interfaces'][0]['peers'][0].get('probe') is None

@pytest.mark.parametrize('change', [dict(interface='wg0;id'),dict(interface='-x'),dict(target='host.invalid'),
    dict(target='127.0.0.1'),dict(target='169.254.169.254'),dict(target='8.8.8.8'),
    dict(target='10.0.0.1'),dict(target='10.0.0.255'),dict(target='10.0.0.0'),dict(target='::1'),
    dict(target='10.0.0.9;id'),dict(node_id=True),dict(command='id')])
def test_manual_configuration_rejects_unsafe_or_unowned_input(change):
    assert hasattr(m, 'bind_manual_probe')
    with pytest.raises(ValueError):
        m.bind_manual_probe(intent(**change), [source()], {1:snapshot()}, now=NOW)

def test_manual_configuration_requires_fresh_unique_real_interface_and_peer():
    assert hasattr(m, 'bind_manual_probe')
    for mutate in ('expired','missing','ambiguous','no_address'):
        s=snapshot()
        if mutate=='expired':s['observed_at']=(NOW-timedelta(seconds=181)).isoformat()
        if mutate=='missing':s['wireguard']['interfaces']=[]
        if mutate=='ambiguous':s['wireguard']['interfaces'][0]['peers']*=2
        if mutate=='no_address':s['wireguard']['interfaces'][0]['addresses']=[]
        with pytest.raises(ValueError):m.bind_manual_probe(intent(),[source()],{1:s},now=NOW)
