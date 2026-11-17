import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
def test_agent_real_interval_and_clock_rejection():
    tree=ast.parse((ROOT/'agent/stella_agent.py').read_text())
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='collect_metrics')
    ns={'datetime':datetime,'timezone':timezone,'time':SimpleNamespace(monotonic=lambda:clock[0])}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'collector','exec'),ns)
    clock=[10.0]
    counters={'eth0':(100,200)}
    collector=SimpleNamespace(last_net=None,read_net_bytes=lambda:dict(counters))
    assert ns['collect_metrics'](collector)==[]
    clock[0]=22.0; counters['eth0']=(1300,2600)
    # Simulate 12 seconds wall time as well as monotonic time.
    collector.last_net_wall=collector.last_net_wall.replace(microsecond=0)
    from datetime import timedelta
    collector.last_net_wall=datetime.now(timezone.utc)-timedelta(seconds=12)
    p=ns['collect_metrics'](collector)[0]
    assert p['elapsed_seconds']==12 and p['quality']=='valid'
    assert p['rx_delta']==1200
    assert p['interval_start']
    clock[0]=23.0; counters['eth0']=(1400,2800)
    collector.last_net_wall=datetime.now(timezone.utc)+timedelta(seconds=20)
    assert ns['collect_metrics'](collector)[0]['quality']=='clock_skew'

def test_legacy_schema_accepts_missing_metadata_but_preserves_new():
    import importlib.util
    spec=importlib.util.spec_from_file_location('_monitor_schema',ROOT/'app/schemas/monitor.py')
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    now=datetime.now(timezone.utc)
    p=m.MetricPoint(iface='eth0',ts=now,rx_delta=1,tx_delta=2,interval_start=now,elapsed_seconds=12,quality='valid')
    assert p.model_dump()['elapsed_seconds']==12
    old=m.MetricPoint(iface='eth0',ts=now,rx_delta=1,tx_delta=2)
    assert old.interval_start is None
