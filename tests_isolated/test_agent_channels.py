"""Real loopback TLS fixtures; never start Agent.run or contact fleet endpoints."""
import importlib.util
from pathlib import Path
import threading
import ssl
import json
import time
import pytest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('channel_agent',Path(__file__).parents[1]/'agent/stella_agent.py')
agent=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(agent)


def obj(url='https://installed.test'):
    a=agent.Agent.__new__(agent.Agent)
    a.url=url;a.token='fixture-channel-token';a._ssl_context=ssl.create_default_context()
    a._channel_init(load_cache=False)
    return a


def policy(origins,mode='default',revision=1):
    return dict(revision=revision,epoch='e'+str(revision),nonce='b'*64,center_id='a'*64,
                token_binding='c'*64,node_id=7,mode=mode,selected_entry_id='public',
                entries=[dict(entry_id=k,origin=v) for k,v in zip(('public','private'),origins)])


def test_legacy_fixed_default_and_explicit_auto_admission():
    a=obj()
    assert a.url=='https://installed.test'
    assert a._channel_policy is None
    a._channel_apply(None)
    assert a.url=='https://installed.test'
    with pytest.raises(ValueError): a._channel_apply(policy(['http://not-tls.test']))
    assert a._channel_policy is None
    a._channel_probe=lambda origin,cfg:dict(ok=True,duration_ms=1,sampled_at='fixture')
    a._channel_save=lambda:None
    a._channel_apply(policy(['https://installed.test','https://other.test']))
    assert a._channel_policy['mode']=='default'
    assert a.url=='https://installed.test'


def test_auto_requires_stable_advantage_and_dwell_and_three_failures():
    a=obj();a._channel_save=lambda:None
    a._channel_probe=lambda origin,cfg:dict(ok=True,duration_ms=100 if origin.endswith('installed.test') else 40,sampled_at='fixture')
    a._channel_apply(policy(['https://installed.test','https://other.test'],'auto'))
    base=a._channel_switched_at
    for i in range(2): a._channel_tick(now=base+61+i*31)
    assert a.url=='https://installed.test'
    a._channel_tick(now=base+123)
    assert a.url=='https://other.test'
    a._channel_probe=lambda origin,cfg:dict(ok=origin.endswith('installed.test'),duration_ms=100,sampled_at='fixture')
    base=a._channel_switched_at
    for i in range(2):a._channel_tick(now=base+61+i*31)
    assert a.url=='https://other.test'
    a._channel_tick(now=base+123)
    assert a.url=='https://installed.test'


def test_three_real_report_failures_can_switch_even_if_readiness_still_works():
    a=obj();a._channel_save=lambda:None
    a._channel_probe=lambda origin,cfg:dict(ok=True,duration_ms=10,sampled_at='fixture')
    a._channel_apply(policy(['https://installed.test','https://other.test'],'auto'))
    a._channel_report_failures=3
    a._channel_tick(now=a._channel_switched_at+61)
    assert a.url=='https://other.test'

@pytest.mark.parametrize('current,candidate',[(100,85),(40,25)])
def test_auto_needs_both_absolute_and_relative_advantage(current,candidate):
    a=obj();a._channel_save=lambda:None
    a._channel_probe=lambda origin,cfg:dict(ok=True,duration_ms=current if origin.endswith('installed.test') else candidate,sampled_at='fixture')
    a._channel_apply(policy(['https://installed.test','https://other.test'],'auto'))
    for i in range(5):a._channel_tick(now=a._channel_switched_at+61+i*31)
    assert a.url=='https://installed.test'


def test_both_unavailable_retain_entry_and_back_off_and_no_implicit_http_upgrade():
    a=obj();a._channel_save=lambda:None
    a._channel_probe=lambda origin,cfg:dict(ok=False,duration_ms=10,sampled_at='fixture')
    a._channel_apply(policy(['https://installed.test','https://other.test'],'auto'))
    now=a._channel_switched_at+61;a._channel_tick(now=now)
    assert a.url=='https://installed.test' and a._channel_next_probe>now+30
    legacy=obj('http://installed.test')
    with pytest.raises(ValueError):legacy._channel_apply(policy(['https://installed.test','https://other.test']))
    assert legacy.url=='http://installed.test' and legacy._channel_policy is None
