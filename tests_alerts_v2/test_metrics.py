"""Offline, no application/database imports. Run with --noconftest."""
import importlib.util
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
import pytest

ROOT = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

@pytest.fixture
def core():
    path = ROOT / 'app/alert_metrics.py'
    assert path.exists(), 'metric evaluator is not implemented'
    return load('_alert_core', 'app/alert_metrics.py')

NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)
def condition(**kw):
    return dict(metric='network.rate', interface='eth0', direction='in', threshold='80000000', **kw)
def sample(seconds=10, rx=125000000, tx=25000000, end=NOW):
    return dict(ts=end, interval_start=end-timedelta(seconds=seconds), elapsed_seconds=seconds,
                rx_delta=rx, tx_delta=tx, quality='valid')

@pytest.mark.parametrize('direction,value', [('in',100000000),('out',20000000),('total',120000000)])
def test_real_elapsed_rate(core,direction,value):
    c=condition(); c['direction']=direction
    result=core.evaluate(core.Condition.model_validate(c), [sample()], NOW)
    assert float(result['value']) == value
    assert result['quality']=='valid'

@pytest.mark.parametrize('direction,expected', [('in',80),('out',80),('any',80)])
def test_asymmetric_capacity(core,direction,expected):
    c=condition(); c.update(metric='network.utilization',direction=direction,threshold='80',
        capacity={'mode':'independent','in_bps':100000000,'out_bps':10000000})
    assert float(core.evaluate(core.Condition.model_validate(c), [sample(rx=100000000,tx=10000000)],NOW)['value'])==expected

def test_shared_total_and_independent_total_rejected(core):
    c=condition(); c.update(metric='network.utilization',direction='total',threshold='80',capacity={'mode':'shared','shared_bps':100000000})
    assert float(core.evaluate(core.Condition.model_validate(c),[sample(rx=75000000,tx=37500000)],NOW)['value'])==90
    c['capacity']={'mode':'independent','in_bps':100000000,'out_bps':10000000}
    with pytest.raises(ValueError,match='独立双向'):
        core.Condition.model_validate(c)

@pytest.mark.parametrize('change', [{'interface':''},{'threshold':'NaN'},{'threshold':'-1'},{'direction':'any'}, {'capacity':{'mode':'shared','shared_bps':0}}, {'surprise':1}])
def test_invalid_contract(core,change):
    c=condition(); c.update(change)
    with pytest.raises(ValueError): core.Condition.model_validate(c)

@pytest.mark.parametrize('points,reason', [([], 'history_missing'),([{'ts':NOW,'rx_delta':100,'tx_delta':0}], 'legacy_interval'),([sample(end=NOW-timedelta(minutes=5))], 'stale')])
def test_missing_is_not_zero(core,points,reason):
    r=core.evaluate(core.Condition.model_validate(condition()),points,NOW)
    assert r['value'] is None and r['bad'] is None and r['reason']==reason

def test_fixed_strict_bounds_and_missing_coverage(core):
    c=condition(); c.update(metric='network.volume',threshold='1000', window={'kind':'fixed','start':NOW-timedelta(seconds=20),'end':NOW,'timezone':'UTC'})
    points=[sample(seconds=10,rx=200,end=NOW-timedelta(seconds=15)),sample(seconds=15,rx=900)]
    r=core.evaluate(core.Condition.model_validate(c),points,NOW)
    assert (r['lower'],r['upper'],r['bad'])==('900','1100',None)
    c['threshold']='800'
    assert core.evaluate(core.Condition.model_validate(c),points,NOW)['bad'] is True
    c['threshold']='1200'
    assert core.evaluate(core.Condition.model_validate(c),points,NOW)['bad'] is False
    r=core.evaluate(core.Condition.model_validate(c),points[1:],NOW)
    assert r['upper'] is None and r['bad'] is None

def test_future_fixed_and_large_integer(core):
    c=condition(); c.update(metric='network.volume',threshold='9007199254740993',window={'kind':'fixed','start':NOW+timedelta(days=1),'end':NOW+timedelta(days=2),'timezone':'Asia/Shanghai'})
    r=core.evaluate(core.Condition.model_validate(c),[],NOW)
    assert r['reason']=='scheduled' and r['value'] is None
    assert core.Condition.model_validate(c).threshold=='9007199254740993'

@pytest.mark.parametrize('field,value', [('timezone','Invalid/Zone'),('start','2026-10-15T00:00:00'),('end',NOW-timedelta(days=50))])
def test_fixed_validation(core,field,value):
    c=condition(); c.update(metric='network.volume',window={'kind':'fixed','start':NOW-timedelta(days=1),'end':NOW,'timezone':'UTC'})
    c['window'][field]=value
    with pytest.raises(ValueError): core.Condition.model_validate(c)

@pytest.mark.parametrize('metric,field', [('cpu','cpu_pct'),('memory','mem_pct'),('root_disk','disk_pct')])
def test_system_metrics_null_unknown(core,metric,field):
    c=core.Condition.model_validate({'metric':metric,'threshold':'80'})
    assert core.evaluate(c,[{'ts':NOW,field:85}],NOW)['bad'] is True
    assert core.evaluate(c,[{'ts':NOW,field:None}],NOW)['bad'] is None


def test_canonical_threshold_and_exponent_budget(core):
    c=condition();c['threshold']='80.00'
    assert core.Condition.model_validate(c).threshold=='80'
    c['threshold']='1e100000'
    with pytest.raises(ValueError):core.Condition.model_validate(c)
