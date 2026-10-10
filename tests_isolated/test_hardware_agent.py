"""Offline hardware contract tests. No HTTP, real shell or database."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('hardware_agent', ROOT / 'agent/stella_agent.py')
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


def sensor(label, current):
    return SimpleNamespace(label=label, current=current)


def linux_psutil(temperatures=None):
    return SimpleNamespace(cpu_count=lambda logical: 16 if logical else 8,
                           cpu_freq=lambda: SimpleNamespace(current=4250, max=5100),
                           sensors_temperatures=lambda: temperatures or {},
                           sensors_fans=lambda: {'nct': [sensor('CPU Fan', 900)]})


def instance():
    obj = agent.Agent('http://offline.invalid', 'offline')
    obj._os_static_cache = {'cpu_model': 'AMD test CPU', 'cpu_cores': 16,
                            'os_name': 'Test Linux', 'kernel': 'test', 'arch': 'x86_64'}
    return obj


class HardwareAgentTests(unittest.TestCase):
    def test_linux_frequency_cpu_temperature_and_all_sensors(self):
        temperatures = {'acpitz': [sensor('', 99)],
                        'k10temp': [sensor('Tctl', 64), sensor('Tdie', 62)],
                        'nvme': [sensor('Composite', 43)]}
        with patch.object(agent.platform, 'system', return_value='Linux'), \
                patch.object(agent, 'psutil', linux_psutil(temperatures)), \
                patch.object(agent.shutil, 'which', return_value=None):
            hardware = instance()._collect_hardware()
        self.assertEqual(hardware['cpu'], {
            'model': 'AMD test CPU', 'physical_cores': 8, 'logical_cores': 16,
            'frequency_mhz': 4250.0, 'max_frequency_mhz': 5100.0,
            'temperature_c': 64.0, 'temperature_source': 'psutil:k10temp',
            'frequency_source': 'psutil.cpu_freq'})
        self.assertEqual(len(hardware['sensors']), 5)
        self.assertEqual(hardware['gpus'], [])
        self.assertEqual(hardware['availability']['cpu_temperature'], 'available')
        self.assertEqual(hardware['availability']['gpu'], 'nvidia_smi_missing')
        self.assertTrue(hardware['sampled_at'].endswith('+00:00'))


    def test_nvidia_single_bounded_query_preserves_every_gpu_and_nulls(self):
        output = ('GPU-a, "NVIDIA, test", 61, 2700, 9000, 55, 1000, 8192, 100.5, 30\n'
                  'GPU-b, Second GPU, N/A, [Not Supported], nan, inf, N/A, 16384, N/A, N/A\n')
        # UUID + name + 8 numeric measurements = 10 columns.
        with patch.object(agent.platform, 'system', return_value='Linux'), \
                patch.object(agent, 'psutil', linux_psutil()), \
                patch.object(agent.shutil, 'which', return_value='/bin/nvidia-smi'), \
                patch.object(agent, '_map_command', return_value=output) as command:
            hardware = instance()._collect_hardware()
        self.assertEqual(len(hardware['gpus']), 2)
        first, second = hardware['gpus']
        self.assertEqual(first['id'], 'GPU-a')
        self.assertEqual(first['name'], 'NVIDIA, test')
        self.assertEqual(first['temperature_c'], 61.0)
        self.assertEqual(first['graphics_clock_mhz'], 2700.0)
        self.assertEqual(first['power_w'], 100.5)
        self.assertEqual(second['id'], 'GPU-b')
        self.assertIsNone(second['temperature_c'])
        self.assertIsNone(second['graphics_clock_mhz'])
        self.assertIsNone(second['memory_clock_mhz'])
        self.assertIsNone(second['utilization_pct'])
        self.assertEqual(second['memory_total_mib'], 16384.0)
        self.assertEqual(second['source'], 'nvidia-smi')
        self.assertEqual(hardware['availability']['gpu'], 'available')
        command.assert_called_once()
        args, kwargs = command.call_args
        self.assertIn('--format=csv,noheader,nounits', args[0])
        self.assertEqual(kwargs['timeout'], 3)


    def test_windows_cpu_inventory_uses_encoded_wmi_with_explicit_frequency_source(self):
        import base64
        import json
        output = json.dumps({'Name': 'AMD Ryzen 9 actual model', 'NumberOfCores': 12,
                             'NumberOfLogicalProcessors': 24, 'CurrentClockSpeed': 3900,
                             'MaxClockSpeed': 5600})
        with patch.object(agent.platform, 'system', return_value='Windows'), \
                patch.object(agent, 'psutil', None), \
                patch.object(agent.shutil, 'which', side_effect=lambda name: 'powershell.exe' if name == 'powershell' else None), \
                patch.object(agent, '_map_command', return_value=output) as command:
            hardware = instance()._collect_hardware()
        self.assertEqual(hardware['cpu']['model'], 'AMD Ryzen 9 actual model')
        self.assertEqual(hardware['cpu']['physical_cores'], 12)
        self.assertEqual(hardware['cpu']['logical_cores'], 24)
        self.assertEqual(hardware['cpu']['frequency_mhz'], 3900.0)
        self.assertEqual(hardware['cpu']['frequency_source'], 'Win32_Processor.CurrentClockSpeed (WMI; not measured boost)')
        args, kwargs = command.call_args
        self.assertIn('-EncodedCommand', args[0])
        script = base64.b64decode(args[0][-1]).decode('utf-16-le')
        self.assertIn('Win32_Processor', script)
        self.assertIn("$ProgressPreference='SilentlyContinue'", script)
        self.assertEqual(kwargs['timeout'], 3)


    def test_windows_lhm_file_overrides_wmi_frequency_with_dynamic_sources(self):
        import json
        import os
        import tempfile
        from datetime import datetime, timezone
        data = {'sampled_at': datetime.now(timezone.utc).isoformat(), 'cpu_temperature_c': 62,
                'cpu_frequency_mhz': 5408,
                'cpu_temperature_source': 'LibreHardwareMonitor:Core (Tctl/Tdie)',
                'cpu_frequency_source': 'LibreHardwareMonitor:Cores (Average)',
                'sensors': [{'name': 'CPU Fan', 'kind': 'fan', 'value': 1100, 'unit': 'RPM',
                             'source': 'LibreHardwareMonitor'}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'hardware-sensors.json'
            path.write_text(json.dumps(data), encoding='utf-8-sig')
            with patch.dict(os.environ, {'STELLA_HARDWARE_SENSORS_FILE': str(path)}), \
                    patch.object(agent.platform, 'system', return_value='Windows'), \
                    patch.object(agent, 'psutil', None), \
                    patch.object(agent.shutil, 'which', return_value=None), \
                    patch.object(agent, '_map_command', return_value='{"CurrentClockSpeed":3900}'):
                hardware = instance()._collect_hardware()
        self.assertEqual(hardware['cpu']['temperature_c'], 62.0)
        self.assertEqual(hardware['cpu']['frequency_mhz'], 5408.0)
        self.assertEqual(hardware['cpu']['temperature_source'], data['cpu_temperature_source'])
        self.assertEqual(hardware['cpu']['frequency_source'], data['cpu_frequency_source'])
        self.assertEqual(hardware['sensors'], data['sensors'])
        self.assertEqual(hardware['availability']['cpu_temperature'], 'available')


    def test_windows_rejects_stale_oversized_and_invalid_sensor_files(self):
        import json
        import os
        import tempfile
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        good = {'sampled_at': now.isoformat(), 'cpu_temperature_c': 62,
                'cpu_frequency_mhz': 5408, 'sensors': []}
        cases = [('old_sample', {**good, 'sampled_at': (now - timedelta(seconds=121)).isoformat()}, None),
                 ('old_mtime', good, now.timestamp() - 121),
                 ('future_sample', {**good, 'sampled_at': (now + timedelta(seconds=60)).isoformat()}, None),
                 ('naive_timestamp', {**good, 'sampled_at': now.replace(tzinfo=None).isoformat()}, None),
                 ('oversized', {**good, 'padding': 'x' * 131073}, None),
                 ('malformed', '{broken', None)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'hardware-sensors.json'
            for name, data, mtime in cases:
                with self.subTest(name=name):
                    path.write_text(data if isinstance(data, str) else json.dumps(data))
                    if mtime is not None:
                        os.utime(path, (mtime, mtime))
                    with patch.dict(os.environ, {'STELLA_HARDWARE_SENSORS_FILE': str(path)}), \
                            patch.object(agent.platform, 'system', return_value='Windows'), \
                            patch.object(agent, 'psutil', None), \
                            patch.object(agent.shutil, 'which', return_value=None), \
                            patch.object(agent, '_map_command', side_effect=ValueError('offline WMI')):
                        hardware = instance()._collect_hardware()
                    self.assertIsNone(hardware['cpu']['temperature_c'])
                    self.assertIsNone(hardware['cpu']['frequency_mhz'])
                    self.assertEqual(hardware['sensors'], [])
                    self.assertNotEqual(hardware['availability']['cpu_temperature'], 'available')

    def test_windows_file_sanitizes_nonfinite_numbers_and_invalid_sensor_shapes(self):
        import json
        import os
        import tempfile
        from datetime import datetime, timezone
        data = {'sampled_at': datetime.now(timezone.utc).isoformat(), 'cpu_temperature_c': float('nan'),
                'cpu_frequency_mhz': float('inf'), 'sensors': [
                    {'name': 'valid', 'kind': 'temperature', 'value': 0, 'unit': '°C', 'source': 'LHM'},
                    {'name': 'nan', 'kind': 'temperature', 'value': float('nan'), 'unit': '°C'},
                    {'name': 'bad-unit', 'kind': 'fan', 'value': 1000, 'unit': '°C'},
                    {'name': 'boolean', 'kind': 'temperature', 'value': True, 'unit': '°C'},
                    {'name': 'string', 'kind': 'temperature', 'value': '62', 'unit': '°C'}, None]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'hardware-sensors.json'
            path.write_text(json.dumps(data))
            with patch.dict(os.environ, {'STELLA_HARDWARE_SENSORS_FILE': str(path)}), \
                    patch.object(agent.platform, 'system', return_value='Windows'), \
                    patch.object(agent, 'psutil', None), \
                    patch.object(agent.shutil, 'which', return_value=None), \
                    patch.object(agent, '_map_command', side_effect=ValueError('offline WMI')):
                hardware = instance()._collect_hardware()
        self.assertEqual(hardware['sensors'], [data['sensors'][0]])
        self.assertIsNone(hardware['cpu']['temperature_c'])
        self.assertIsNone(hardware['cpu']['frequency_mhz'])
        json.dumps(hardware, allow_nan=False)


    def test_os_info_uses_single_flight_background_hardware_cache_without_blocking(self):
        import threading
        obj = instance()
        started, release = threading.Event(), threading.Event()
        calls = []
        def collect():
            calls.append(1)
            started.set()
            release.wait(2)
            return {'sampled_at': '2026-10-10T00:00:00+00:00', 'cpu': {'model': 'WMI model'},
                    'gpus': [], 'sensors': [], 'availability': {'cpu_temperature': 'unavailable', 'gpu': 'unavailable'}}
        with patch.object(obj, '_collect_hardware', collect), \
                patch.object(agent.time, 'monotonic', return_value=100):
            try:
                initial = obj._os_info()
                self.assertIn('hardware', initial)
                self.assertTrue(started.wait(1))
                for _ in range(10):
                    pending = obj._os_info()
                    self.assertEqual(pending['kernel'], 'test')
                    self.assertEqual(pending['hardware']['availability']['gpu'], 'collecting')
                self.assertEqual(len(calls), 1)
            finally:
                release.set()
                if hasattr(obj, '_hardware_scheduler'):
                    obj._hardware_scheduler.close()
            refreshed = obj._os_info()
            self.assertEqual(refreshed['hardware']['cpu']['model'], 'WMI model')
            self.assertEqual(refreshed['cpu_model'], 'WMI model')
            self.assertEqual(len(calls), 1)


    def test_linux_never_uses_acpi_cpu_labels_and_unmeasured_zero_frequency(self):
        readings = {'acpitz': [sensor('CPU', 99)], 'acpi_thermal': [sensor('CPU temperature', 98)],
                    'nvme': [sensor('', float('nan'))]}
        fake_psutil = linux_psutil(readings)
        fake_psutil.cpu_freq = lambda: SimpleNamespace(current=0, max=0)
        with patch.object(agent.platform, 'system', return_value='Linux'), \
                patch.object(agent, 'psutil', fake_psutil), \
                patch.object(agent.shutil, 'which', return_value=None):
            hardware = instance()._collect_hardware()
        self.assertIsNone(hardware['cpu']['temperature_c'])
        self.assertIsNone(hardware['cpu']['temperature_source'])
        self.assertIsNone(hardware['cpu']['frequency_mhz'])
        self.assertIsNone(hardware['cpu']['max_frequency_mhz'])
        self.assertIsNone(hardware['cpu']['frequency_source'])
        self.assertEqual(len(hardware['sensors']), 3)

    def test_cache_hides_stale_readings_when_a_later_worker_is_stuck(self):
        import threading
        obj = instance()
        release = threading.Event()
        now = [100.0]
        sample = obj._empty_hardware('available')
        sample['cpu']['temperature_c'] = 62.0
        def collect():
            if now[0] > 100:
                release.wait(2)
            return sample
        def join_workers():
            with obj._hardware_scheduler._lock:
                threads = list(obj._hardware_scheduler._threads.values())
            for thread in threads:
                thread.join(1)
        with patch.object(agent.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(obj, '_collect_hardware', collect):
            try:
                obj._hardware_info()
                join_workers()
                now[0] = 129
                self.assertEqual(obj._hardware_info()['cpu']['temperature_c'], 62.0)
                now[0] = 130
                obj._hardware_info()
                now[0] = 221
                stale = obj._hardware_info()
                self.assertIsNone(stale['cpu']['temperature_c'])
                self.assertEqual(stale['availability']['cpu_temperature'], 'stale')
            finally:
                release.set()
                obj._hardware_scheduler.close()


    def test_scheduler_admission_error_cannot_break_legacy_os_heartbeat(self):
        obj = instance()
        with patch.object(obj._hardware_scheduler, 'submit', side_effect=RuntimeError('thread unavailable')):
            info = obj._os_info()
        self.assertEqual(info['kernel'], 'test')
        self.assertEqual(info['hardware']['availability']['gpu'], 'collection_failed')
        self.assertIsNone(info['hardware']['cpu']['temperature_c'])


    def test_collection_failure_is_cached_and_retried_after_30_seconds(self):
        obj = instance()
        now = [100.0]
        def join_workers():
            with obj._hardware_scheduler._lock:
                threads = list(obj._hardware_scheduler._threads.values())
            for thread in threads:
                thread.join(1)
        with patch.object(agent.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(obj, '_collect_hardware', side_effect=ValueError('unavailable')) as collect:
            try:
                obj._hardware_info()
                join_workers()
                self.assertEqual(obj._hardware_info()['availability']['gpu'], 'collection_failed')
                now[0] = 129.99
                obj._hardware_info()
                self.assertEqual(collect.call_count, 1)
                now[0] = 130
                obj._hardware_info()
                join_workers()
                self.assertEqual(collect.call_count, 2)
            finally:
                obj._hardware_scheduler.close()

    def test_nvidia_failure_preserves_cpu_and_board_sensor_report(self):
        for output in (ValueError('timeout'), 'GPU-a, bad row\n', ''):
            command_patch = (patch.object(agent, '_map_command', side_effect=output)
                             if isinstance(output, Exception)
                             else patch.object(agent, '_map_command', return_value=output))
            with self.subTest(output=repr(output)), \
                    patch.object(agent.platform, 'system', return_value='Linux'), \
                    patch.object(agent, 'psutil', linux_psutil({'coretemp': [sensor('Package', 65)]})), \
                    patch.object(agent.shutil, 'which', return_value='/bin/nvidia-smi'), command_patch:
                hardware = instance()._collect_hardware()
                self.assertEqual(hardware['gpus'], [])
                self.assertEqual(hardware['cpu']['temperature_c'], 65.0)
                self.assertEqual(len(hardware['sensors']), 2)
                self.assertNotEqual(hardware['availability']['gpu'], 'available')

    def test_missing_psutil_returns_complete_null_contract(self):
        with patch.object(agent.platform, 'system', return_value='Linux'), \
                patch.object(agent, 'psutil', None), \
                patch.object(agent.shutil, 'which', return_value=None):
            hardware = instance()._collect_hardware()
        self.assertEqual(set(hardware['cpu']), {'model', 'physical_cores', 'logical_cores',
                         'frequency_mhz', 'max_frequency_mhz', 'temperature_c',
                         'temperature_source', 'frequency_source'})
        self.assertIsNone(hardware['cpu']['physical_cores'])
        self.assertEqual(hardware['sensors'], [])
        self.assertEqual(hardware['availability']['cpu_temperature'], 'unavailable')

    def test_real_run_loop_reports_while_hardware_worker_is_blocked(self):
        import threading
        obj = instance()
        started, release, reported, stop = (threading.Event() for _ in range(4))
        bodies, errors = [], []
        def collect():
            started.set()
            release.wait(3)
            return obj._empty_hardware('unavailable')
        def post(path, **kwargs):
            if started.is_set() and not release.is_set() and kwargs.get('json_body', {}).get('metrics'):
                bodies.append(kwargs['json_body'])
                if len(bodies) >= 2:
                    reported.set()
            return {}
        replacements = {'_collect_hardware': collect, '_post': post,
                        'list_interfaces': lambda: {}, 'list_storage': lambda: [],
                        '_check_components': lambda: {}, '_probe_public_ip': lambda: {},
                        '_report_map_snapshot': lambda: None, 'refresh_config': lambda: None,
                        'check_update': lambda: None, 'run_due_probes': lambda: None,
                        'poll_and_execute': lambda: None, 'collect_sys': lambda: {},
                        'collect_metrics': lambda: [{'ts': 'offline'}]}
        with patch.multiple(obj, **replacements), patch.object(agent, 'psutil', None), \
                patch.object(agent, 'POLL_INTERVAL', .005), patch.object(agent, 'REPORT_INTERVAL', .01):
            def run():
                try:
                    obj.run(stop)
                except Exception as error:
                    errors.append(error)
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(started.wait(1))
                self.assertTrue(reported.wait(1), 'heartbeats blocked behind hardware')
                self.assertEqual(bodies[0]['os_info']['hardware']['availability']['gpu'], 'collecting')
                self.assertEqual(bodies[0]['os_info']['kernel'], 'test')
            finally:
                stop.set()
                release.set()
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertFalse(obj._hardware_scheduler.submit('hardware', lambda: None))

    def test_command_runner_enforces_real_process_timeout_and_output_limit(self):
        import sys
        with self.assertRaisesRegex(ValueError, 'command timeout'):
            agent._map_command([sys.executable, '-c', 'import time; time.sleep(2)'], timeout=.05)
        with self.assertRaisesRegex(ValueError, 'output limit'):
            agent._map_command([sys.executable, '-c', 'print("x" * 131073)'], timeout=1)


    def test_release_version_refuses_same_version_update_and_accepts_newer(self):
        self.assertEqual(agent.AGENT_VERSION, '0.6.11')
        obj = instance()
        with patch.object(obj, '_get', return_value={'version': '0.6.11'}), \
                patch.object(obj, '_download_and_restart') as download:
            obj.check_update()
            download.assert_not_called()
        with patch.object(obj, '_get', return_value={'version': '0.6.12'}), \
                patch.object(obj, '_download_and_restart') as download:
            obj.check_update()
            download.assert_called_once()


if __name__ == '__main__':
    unittest.main()
