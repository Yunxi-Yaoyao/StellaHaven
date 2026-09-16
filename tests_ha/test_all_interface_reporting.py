"""Agent interface selections are display preferences, never collection filters."""
import importlib.util
from pathlib import Path
from collections import deque
import pytest

spec=importlib.util.spec_from_file_location('all_iface_agent',Path(__file__).parents[1]/'agent/stella_agent.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.mark.parametrize('selection',[None,{}, {'eno1':{}}, {'wlan0':{}}])
def test_collect_and_report_all_interfaces_regardless_of_display_selection(selection):
    a=m.Agent.__new__(m.Agent);a.monitored_ifaces=selection;a.last_net=None
    first={'eno1':(0,0),'wlan0':(100,200),'wg0':(20,40),'lo':(50,50),'veth-test':(3,4)}
    a.read_net_bytes=lambda:first
    assert a.collect_metrics()==[]
    a.read_net_bytes=lambda:{name:(rx+10,tx+20) for name,(rx,tx) in first.items()}
    points=a.collect_metrics()
    assert {p['iface'] for p in points}==set(first)
    assert all(p['rx_delta']==10 and p['tx_delta']==20 for p in points)
    a.queue=deque();a.token='test-only';a.monitors_version=0
    a._check_components=lambda:{};a._os_info=lambda:{}
    posted=[];a._post=lambda *args,**kw:posted.append(kw['json_body']) or {}
    a.report(points,[])
    assert posted[0]['metrics']==points
    assert not a.queue
    assert a.monitored_ifaces==selection

def test_new_reset_removed_and_reappearing_interfaces_use_real_baselines():
    a=m.Agent.__new__(m.Agent);a.monitored_ifaces={'eno1':{}};a.last_net={'eno1':(100,100),'wg0':(100,100)}
    a.read_net_bytes=lambda:{'eno1':(120,130),'wg0':(1,2),'wlan0':(900,800)}
    points=a.collect_metrics()
    assert [p['iface'] for p in points]==['eno1']
    a.read_net_bytes=lambda:{'wg0':(11,12),'wlan0':(910,820)}
    points=a.collect_metrics()
    assert {(p['iface'],p['rx_delta'],p['tx_delta']) for p in points}=={('wg0',10,10),('wlan0',10,20)}
    a.read_net_bytes=lambda:{'eno1':(200,200),'wlan0':(920,830)}
    assert [p['iface'] for p in a.collect_metrics()]==['wlan0']
