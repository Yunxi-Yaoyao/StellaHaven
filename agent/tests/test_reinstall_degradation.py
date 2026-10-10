"""Offline regression: a stopped/reinstalling bridge cannot break GPU/WMI metrics.
Run: python -m unittest discover -s agent/tests -p 'test_*.py' -v
No network, shell, DB or production sensor paths are accessed.
"""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location('reinstall_agent', Path(__file__).parents[1] / 'stella_agent.py')
assert _SPEC is not None and _SPEC.loader is not None
agent = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(agent)


class ReinstallDegradationTests(unittest.TestCase):
    def test_bridge_gap_and_failures_preserve_gpu_and_explicit_wmi_fallback(self):
        now = datetime.now(timezone.utc)
        machine = {'machine': {'detected_at': now.isoformat()}, 'physical_inventory': None,
                   'processors': [{'Name': 'fixture CPU', 'NumberOfCores': 6,
                                   'NumberOfLogicalProcessors': 12, 'CurrentClockSpeed': 3900,
                                   'MaxClockSpeed': 5500}]}
        valid = {'sampled_at': now.isoformat(), 'cpu_temperature_c': 62,
                 'cpu_frequency_mhz': 5408, 'sensors': [{'name': 'fixture fan', 'kind': 'fan',
                  'value': 900, 'unit': 'RPM', 'source': 'LibreHardwareMonitor'}]}
        with tempfile.TemporaryDirectory(prefix='stella-reinstall-degraded-') as root:
            path = Path(root) / 'sensors.json'
            with patch.dict(os.environ, {'STELLA_HARDWARE_SENSORS_FILE': str(path)}), \
                 patch.object(agent.platform, 'system', return_value='Windows'), \
                 patch.object(agent, 'psutil', None), \
                 patch.object(agent.shutil, 'which', side_effect=lambda name: 'fixture-nvidia' if name == 'nvidia-smi' else None), \
                 patch.object(agent.subprocess, 'run', side_effect=AssertionError('No real shell permitted')), \
                 patch.object(agent, '_map_command', return_value='GPU-fixture, Fixture NVIDIA, 55, 2700, 9000, 20, 1000, 16384, 90, 30') as command:
                obj = agent.Agent('http://offline.invalid', 'offline-never-sent')
                with patch.object(obj, '_machine_static_info', return_value=machine):
                    for failure in ('missing', 'stale', 'malformed', 'permission'):
                        with self.subTest(failure=failure):
                            # First publish a valid dynamic sample, then lose the bridge.
                            path.write_text(json.dumps(valid))
                            good = obj._collect_hardware()
                            self.assertEqual(good['cpu']['temperature_c'], 62)
                            self.assertEqual(good['cpu']['frequency_mhz'], 5408)
                            if failure == 'missing':
                                path.unlink()
                            elif failure == 'stale':
                                path.write_text(json.dumps({**valid, 'sampled_at': (now - timedelta(minutes=5)).isoformat()}))
                            elif failure == 'malformed':
                                path.write_text('{interrupted-install')
                            if failure == 'permission':
                                with patch.object(agent.os, 'stat', side_effect=PermissionError('fixture denied')):
                                    sample = obj._collect_hardware()
                            else:
                                sample = obj._collect_hardware()
                            self.assertIsNone(sample['cpu']['temperature_c'])
                            self.assertEqual(sample['cpu']['frequency_mhz'], 3900)
                            self.assertIn('WMI; not measured boost', sample['cpu']['frequency_source'])
                            self.assertEqual(sample['sensors'], [])
                            self.assertNotEqual(sample['availability']['cpu_temperature'], 'available')
                            self.assertEqual(sample['gpus'][0]['id'], 'GPU-fixture')
                            self.assertEqual(sample['gpus'][0]['memory_total_mib'], 16384)
                            self.assertEqual(sample['availability']['gpu'], 'available')
                            json.dumps(sample, allow_nan=False)
                self.assertEqual(command.call_count, 8)
                for args, kwargs in command.call_args_list:
                    self.assertEqual(args[0][0], 'fixture-nvidia')
                    self.assertEqual(kwargs['timeout'], 3)


if __name__ == '__main__':
    unittest.main()
