"""Collector refresh failures stay visible without shell, network or DB access."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hardware_refresh_agent', ROOT / 'agent/stella_agent.py')
assert spec is not None and spec.loader is not None
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def instance():
    with patch.object(a.Agent, '_check_deps'):
        obj = a.Agent('http://offline.invalid', 'offline')
    obj._os_static_cache = {'kernel': 'fixture', 'cpu_cores': 6, 'cpu_logical_cores': 12}
    return obj


def inline(key, operation):
    operation()
    return True


def os_info(obj):
    with patch.object(a, 'psutil', None), patch.object(a.os, 'getloadavg', side_effect=OSError), \
            patch.object(obj, '_hardware_info', return_value={'cpu': {}}):
        return obj._os_info()


def test_storage_query_failure_is_reported_without_erasing_last_success():
    obj = instance()
    now = [100.0]
    sample = [{'sampled_at': '2026-10-10T00:00:00+00:00', 'used': 0}]
    with patch.object(a.time, 'monotonic', side_effect=lambda: now[0]), \
            patch.object(obj._storage_scheduler, 'submit', side_effect=inline), \
            patch.object(obj, 'list_storage', return_value=sample):
        assert obj._storage_info() is sample
        success = os_info(obj)['storage_status']
        assert success['state'] == 'available'
        assert datetime.fromisoformat(success['sampled_at']).tzinfo == timezone.utc
        assert datetime.fromisoformat(success['attempted_at']).tzinfo == timezone.utc
        now[0] += a.STORAGE_INTERVAL
        with patch.object(obj, 'list_storage', side_effect=RuntimeError('private failure text')):
            assert obj._storage_info() is sample
        failure = os_info(obj)['storage_status']
    assert failure['state'] == 'query_failed'
    assert failure['sampled_at'] == success['sampled_at']
    assert failure['attempted_at'] >= success['attempted_at']
    assert sample[0]['sampled_at'] == '2026-10-10T00:00:00+00:00'
    assert set(failure) == {'state', 'sampled_at', 'attempted_at'}


def collect_gpu(obj, inventory, tool, output):
    from contextlib import ExitStack
    with ExitStack() as stack:
        stack.enter_context(patch.object(a, 'psutil', None))
        stack.enter_context(patch.object(a.platform, 'system', return_value='Linux'))
        stack.enter_context(patch.object(obj, '_gpu_static_info', return_value=inventory))
        stack.enter_context(patch.object(obj, '_linux_gpu_readings', return_value=None))
        stack.enter_context(patch.object(obj, '_machine_static_info', return_value={
            'machine': a._classify_machine(), 'physical_inventory': None, 'processors': []}))
        stack.enter_context(patch.object(a.shutil, 'which', return_value=tool))
        command_patch = (patch.object(a, '_map_command', side_effect=output)
                         if isinstance(output, Exception) else patch.object(a, '_map_command', return_value=output))
        command = stack.enter_context(command_patch)
        return obj._collect_hardware(), command


def test_empty_gpu_inventory_cannot_hide_real_telemetry_query_failure():
    obj = instance()
    for inventory, presence in [(None, 'unknown'), ([], 'none')]:
        for output in [RuntimeError('private failure'), '', 'GPU-a, invalid']:
            hardware, command = collect_gpu(obj, inventory, 'nvidia-smi', output)
            assert hardware['gpus'] == []
            assert hardware['availability']['gpu'] == 'collection_failed'
            assert hardware['availability']['gpu_query'] == 'query_failed'
            assert hardware['availability']['gpu_presence'] == presence
            command.assert_called_once()


def test_nvidia_all_unsupported_values_have_no_measurement_time():
    obj = instance()
    output = 'GPU-a, RTX test, ' + ', '.join(['N/A'] * 8)
    hardware, _ = collect_gpu(obj, None, 'nvidia-smi', output)
    assert hardware['gpus'][0].get('sampled_at') is None
    assert hardware['gpus'][0]['telemetry_status'] == 'unsupported'
    assert hardware['availability']['gpu'] == 'inventory_only'
    assert hardware['availability']['gpu_presence'] == 'present'
    assert hardware['availability']['gpu_query'] == 'available'


def test_storage_initial_failure_has_no_success_time_and_recovery_clears_failure():
    obj = instance()
    assert os_info(obj)['storage_status'] == {
        'state': 'collecting', 'sampled_at': None, 'attempted_at': None}
    with patch.object(obj._storage_scheduler, 'submit', side_effect=inline), \
            patch.object(obj, 'list_storage', side_effect=RuntimeError('offline')):
        assert obj._storage_info() is None
    failure = os_info(obj)['storage_status']
    assert failure['state'] == 'query_failed'
    assert failure['sampled_at'] is None
    assert failure['attempted_at'] is not None
    obj._storage_next_sample = 0
    with patch.object(obj._storage_scheduler, 'submit', side_effect=inline), \
            patch.object(obj, 'list_storage', return_value=[]):
        assert obj._storage_info() == []
    recovered = os_info(obj)['storage_status']
    assert recovered['state'] == 'available'
    assert recovered['sampled_at'] is not None
    assert failure['state'] == 'query_failed', 'earlier report must not mutate'


def test_storage_scheduler_exception_is_failure_but_busy_does_not_start_attempt():
    obj = instance()
    sample = [{'sampled_at': 'original'}]
    prior = {'state': 'available', 'sampled_at': '2026-10-10T00:00:00+00:00',
             'attempted_at': '2026-10-10T00:00:00+00:00'}
    obj._storage_cache, obj._storage_status = sample, prior
    with patch.object(obj._storage_scheduler, 'submit', return_value=False), \
            patch.object(obj, 'list_storage') as collect:
        assert obj._storage_info() is sample
        collect.assert_not_called()
    assert os_info(obj)['storage_status'] == prior
    obj._storage_next_sample = 0
    with patch.object(obj._storage_scheduler, 'submit', side_effect=RuntimeError('cannot start thread')):
        assert obj._storage_info() is sample
    failure = os_info(obj)['storage_status']
    assert failure['state'] == 'query_failed'
    assert failure['sampled_at'] == prior['sampled_at']
    assert failure['attempted_at'] != prior['attempted_at']
    obj._storage_next_sample = 0
    with patch.object(obj._storage_scheduler, 'submit', return_value=False):
        assert obj._storage_info() is sample
    assert os_info(obj)['storage_status'] == failure


def test_storage_none_result_is_failure_without_erasing_old_snapshot():
    obj = instance()
    sample = [{'sampled_at': 'original'}]
    obj._storage_cache = sample
    with patch.object(obj._storage_scheduler, 'submit', side_effect=inline), \
            patch.object(obj, 'list_storage', return_value=None):
        assert obj._storage_info() is sample
    assert os_info(obj)['storage_status']['state'] == 'query_failed'
    assert os_info(obj)['storage_status']['sampled_at'] is None


def test_real_storage_singleflight_reports_collecting_then_failure_while_busy():
    import threading
    obj = instance()
    sample = [{'sampled_at': 'original'}]
    obj._storage_cache = sample
    obj._storage_status = {'state': 'available', 'sampled_at': 'last-success', 'attempted_at': 'previous'}
    started, release = threading.Event(), threading.Event()
    calls, now = [], [100.0]
    def collect():
        calls.append(1)
        started.set()
        assert release.wait(2)
        raise RuntimeError('private failure')
    with patch.object(a.time, 'monotonic', side_effect=lambda: now[0]), \
            patch.object(obj, 'list_storage', side_effect=collect):
        try:
            assert obj._storage_info() is sample
            assert started.wait(1)
            pending = os_info(obj)['storage_status']
            assert pending['state'] == 'collecting'
            assert pending['sampled_at'] == 'last-success'
            now[0] += a.STORAGE_INTERVAL
            assert obj._storage_info() is sample  # busy admission, not query failure
            assert os_info(obj)['storage_status'] == pending
            assert len(calls) == 1
            with obj._storage_scheduler._lock:
                workers = list(obj._storage_scheduler._threads.values())
            release.set()
            for worker in workers:
                worker.join(1)
            assert os_info(obj)['storage_status']['state'] == 'query_failed'
            assert obj._storage_info() is sample
        finally:
            release.set()
            obj._storage_scheduler.close()


def test_regular_report_exposes_storage_failure_by_next_heartbeat():
    obj = instance()
    sample, bodies = [{'sampled_at': 'old-source'}], []
    obj._storage_cache = sample
    with patch.object(a, 'psutil', None), patch.object(a.os, 'getloadavg', side_effect=OSError), \
            patch.object(obj, '_hardware_info', return_value={'cpu': {}}), \
            patch.object(obj, '_check_components', return_value={}), \
            patch.object(obj._storage_scheduler, 'submit', side_effect=inline), \
            patch.object(obj, 'list_storage', side_effect=RuntimeError('offline')), \
            patch.object(obj, '_post', side_effect=lambda path, **kw: bodies.append(kw['json_body']) or {}):
        obj.report([], [])
        obj.report([], [])
    assert bodies[-1]['os_info']['storage_status']['state'] == 'query_failed'
    assert bodies[-1]['os_info']['storage_status']['sampled_at'] is None
    assert all(body['storage'] is sample for body in bodies)


def test_gpu_presence_without_tool_distinguishes_unknown_none_and_inventory():
    obj = instance()
    inventory = [obj._gpu_row('pci:gpu', 'Intel UHD', 'Intel', 'integrated', 'PCI/sysfs', 'unsupported')]
    for rows, availability, presence in [(None, 'unknown', 'unknown'), ([], 'no_gpu', 'none'),
                                         (inventory, 'inventory_only', 'present')]:
        hardware, command = collect_gpu(obj, rows, None, RuntimeError('must not query'))
        assert hardware['availability']['gpu'] == availability
        assert hardware['availability']['gpu_presence'] == presence
        assert hardware['availability'].get('gpu_query') != 'query_failed'
        assert all(gpu.get('sampled_at') is None for gpu in hardware['gpus'])
        command.assert_not_called()


def test_gpu_inventory_query_failure_retains_identity_without_measurement_time():
    obj = instance()
    inventory = [obj._gpu_row('pci:gpu', 'RTX test', 'NVIDIA', 'discrete', 'PCI/sysfs', 'unsupported')]
    hardware, _ = collect_gpu(obj, inventory, 'nvidia-smi', RuntimeError('timeout'))
    assert hardware['gpus'][0]['name'] == 'RTX test'
    assert hardware['gpus'][0]['telemetry_status'] == 'query_failed'
    assert hardware['gpus'][0].get('sampled_at') is None
    assert hardware['availability']['gpu'] == 'inventory_only'
    assert hardware['availability']['gpu_presence'] == 'present'
    assert hardware['availability']['gpu_query'] == 'query_failed'
    assert inventory[0]['telemetry_status'] == 'unsupported'


def test_gpu_sample_time_advances_on_real_dynamic_queries_and_zero_is_measured():
    from datetime import timedelta
    obj = instance()
    ticks = [datetime(2026, 10, 10, tzinfo=timezone.utc)]
    class Clock:
        @staticmethod
        def now(tz):
            ticks[0] += timedelta(seconds=1)
            return ticks[0]
    with patch.object(a, 'datetime', Clock):
        first, _ = collect_gpu(obj, None, 'nvidia-smi', 'GPU-a, RTX test, 0, 0, 0, 0, 0, 0, 0, 0')
        second, _ = collect_gpu(obj, [], 'nvidia-smi', 'GPU-a, RTX test, 0, 0, 0, 0, 0, 0, 0, 0')
    assert first['gpus'][0]['sampled_at'] > first['sampled_at'], 'query completion, not envelope start'
    assert second['gpus'][0]['sampled_at'] > first['gpus'][0]['sampled_at']
    assert second['availability']['gpu'] == 'available'
    assert second['availability']['gpu_presence'] == 'present'
    assert second['gpus'][0]['temperature_c'] == 0


def test_new_and_legacy_agent_reports_accept_optional_nested_status():
    schema_spec = importlib.util.spec_from_file_location('refresh_report_schema', ROOT / 'app/schemas/monitor.py')
    assert schema_spec is not None and schema_spec.loader is not None
    schema = importlib.util.module_from_spec(schema_spec)
    schema_spec.loader.exec_module(schema)
    assert schema.AgentReport().os_info is None
    assert schema.AgentReport(os_info={'cpu_cores': 12}).os_info == {'cpu_cores': 12}
    nested = {'cpu_cores': 6, 'cpu_logical_cores': 12, 'storage_status': {
        'state': 'query_failed', 'sampled_at': None, 'attempted_at': '2026-10-10T00:00:00+00:00'}}
    assert schema.AgentReport(os_info=nested).model_dump()['os_info'] == nested
