"""Memory-only isolated probes: never construct an agent or access production."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('memory_agent', ROOT / 'agent/stella_agent.py')
assert spec is not None and spec.loader is not None
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

class SystemMemoryTests(unittest.TestCase):
    def test_os_visible_capacity_independent_of_machine_classification(self):
        for kind in ('physical', 'virtual', 'unknown', None, 'container'):
            obj = object.__new__(agent.Agent)
            obj._os_static_cache = {}
            obj._storage_status = {}
            hw = {'machine': {'kind': kind}, 'cpu': {}}
            with patch.object(obj, '_hardware_info', return_value=hw), patch.object(agent, '_hardware_read', return_value=None), patch.object(agent, 'psutil', SimpleNamespace(boot_time=lambda: 1, virtual_memory=lambda: SimpleNamespace(total=8192, available=0, used=7000))):
                memory = obj._os_info()['hardware'].get('memory')
            self.assertIsNotNone(memory)
            self.assertEqual(memory['total_bytes'], 8192)
            self.assertEqual(memory['available_bytes'], 0)
            self.assertEqual(memory['used_bytes'], 7000)  # preserve psutil semantics, not total-available
            self.assertEqual(memory['source'], 'psutil.virtual_memory')
            self.assertEqual(memory['scope'], 'host_visible' if kind == 'container' else 'os_visible')
            self.assertEqual(memory['state'], 'available')
            self.assertIsNotNone(memory['sampled_at'])

    def test_proc_fallback_is_bounded_and_does_not_invent_available(self):
        for text, available in [('MemTotal: 8 kB\nMemAvailable: 0 kB\n', 0), ('MemTotal: 8 kB\nMemFree: 4 kB\n', None)]:
            obj = object.__new__(agent.Agent)
            with patch.object(agent, 'psutil', None), patch.object(agent.platform, 'system', return_value='Linux'), patch.object(agent, '_hardware_read', return_value=text) as read:
                m = obj._system_memory('unknown')
            self.assertEqual(m['total_bytes'], 8192)
            self.assertEqual(m['available_bytes'], available)
            self.assertEqual(m['used_bytes'], 8192 if available == 0 else None)
            self.assertEqual(m['source'], '/proc/meminfo')
            read.assert_called_once_with('/proc/meminfo', limit=32768)

    def test_invalid_values_and_failure_retain_true_source_time(self):
        obj = object.__new__(agent.Agent)
        for total in (None, -1, 0, True, float('nan'), float('inf')):
            with patch.object(agent, 'psutil', SimpleNamespace(virtual_memory=lambda: SimpleNamespace(total=total, available=0, used=0))), patch.object(agent, '_hardware_read', return_value=None):
                m = obj._system_memory('unknown')
            self.assertIsNone(m['total_bytes'])
            self.assertIsNone(m['sampled_at'])
            self.assertEqual(m['state'], 'query_failed')
        with patch.object(agent, 'psutil', SimpleNamespace(virtual_memory=lambda: SimpleNamespace(total=8192, available=0, used=4096))):
            success = obj._system_memory('virtual')
        with patch.object(agent, 'psutil', None), patch.object(agent, '_hardware_read', return_value=None):
            failed = obj._system_memory('virtual')
        self.assertEqual(failed['total_bytes'], 8192)
        self.assertEqual(failed['sampled_at'], success['sampled_at'])
        self.assertEqual(failed['source'], success['source'])
        self.assertEqual(failed['state'], 'query_failed')
        self.assertNotEqual(failed['attempted_at'], success['attempted_at'])

    def test_windows_psutil_and_partial_invalid_measurements(self):
        obj = object.__new__(agent.Agent)
        with patch.object(agent.platform, 'system', return_value='Windows'), patch.object(agent, 'psutil', SimpleNamespace(virtual_memory=lambda: SimpleNamespace(total=8192, available=True, used=float('inf')))):
            m = obj._system_memory('virtual')
        self.assertEqual(m['total_bytes'], 8192)
        self.assertIsNone(m['available_bytes'])
        self.assertIsNone(m['used_bytes'])

    def test_cgroup_limit_is_independent_with_own_failure_cache(self):
        for version in (1, 2):
            obj = object.__new__(agent.Agent)
            root = '/sys/fs/cgroup' if version == 2 else '/sys/fs/cgroup/memory'
            files = {'/proc/self/cgroup': '0::/job\n' if version == 2 else '4:memory:/job\n',
                     '/proc/self/mountinfo': f'1 0 0:1 / {root} rw - ' + ('cgroup2 cgroup rw\n' if version == 2 else 'cgroup cgroup rw,memory\n'),
                     root + '/job/' + ('memory.max' if version == 2 else 'memory.limit_in_bytes'): '1024',
                     root + '/job/' + ('memory.current' if version == 2 else 'memory.usage_in_bytes'): '0',
                     root + '/' + ('memory.max' if version == 2 else 'memory.limit_in_bytes'): 'max' if version == 2 else '9223372036854771712'}
            with patch.object(agent, '_hardware_read', side_effect=lambda path, limit=8192: files.get(path)), patch.object(agent, 'psutil', SimpleNamespace(virtual_memory=lambda: SimpleNamespace(total=8192, available=4096, used=4096))):
                m = obj._system_memory('container')
                self.assertEqual(m['total_bytes'], 8192)
                c = m.get('cgroup')
                self.assertIsNotNone(c)
                self.assertEqual((c['total_bytes'], c['used_bytes'], c['available_bytes']), (1024, 0, 1024))
                self.assertEqual(c['scope'], 'cgroup')
                files.clear()
                failed = obj._system_memory('container')['cgroup']
                self.assertEqual(failed['state'], 'query_failed')
                self.assertEqual(failed['sampled_at'], c['sampled_at'])
                self.assertEqual(failed['total_bytes'], 1024)

    def test_cgroup_unlimited_and_unknown_are_not_zero_capacity(self):
        obj = object.__new__(agent.Agent)
        files = {'/proc/self/cgroup': '0::/\n', '/proc/self/mountinfo': '1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n', '/sys/fs/cgroup/memory.max': 'max'}
        with patch.object(agent, '_hardware_read', side_effect=lambda path, limit=8192: files.get(path)):
            m = obj._cgroup_memory()
            self.assertEqual(m['state'], 'unlimited')
            self.assertIsNone(m['total_bytes'])
            files.clear()
            self.assertEqual(obj._cgroup_memory()['state'], 'query_failed')

    def test_unknown_public_platform_does_not_become_physical(self):
        obj = object.__new__(agent.Agent)
        files = {'/sys/class/dmi/id/sys_vendor': 'Default string', '/sys/class/dmi/id/product_name': 'Default string',
                 '/sys/class/dmi/id/board_vendor': 'Default string', '/sys/class/dmi/id/board_name': 'Default string',
                 '/sys/class/dmi/id/bios_vendor': 'American Megatrends Inc.', '/sys/class/dmi/id/bios_version': '5.13'}
        with patch.object(agent, '_hardware_read', side_effect=lambda path, limit=8192: files.get(path)), patch.object(agent.os.path, 'exists', return_value=False), patch.object(agent.shutil, 'which', return_value=None):
            static = obj._linux_machine_static()
        self.assertEqual(static['machine']['kind'], 'unknown')
        self.assertIsNone(static['physical_inventory'])
        public = static.get('platform_inventory')
        self.assertIsNotNone(public)
        self.assertEqual(public['scope'], 'platform_reported')
        self.assertEqual(public['source'], 'sysfs.dmi')
        self.assertEqual(public['bios']['version'], '5.13')
        self.assertIsNone(public['memory_modules'])
        self.assertIsNone(public['disks'])

    def test_sensor_scope_and_platform_capability_reach_hardware(self):
        obj = object.__new__(agent.Agent)
        obj._os_static_cache = {}
        public = {'bios': {'version': '5.13'}, 'source': 'sysfs.dmi', 'scope': 'platform_reported'}
        for kind in ('unknown', 'container', 'virtual', 'physical'):
            static = {'machine': {'kind': kind}, 'physical_inventory': None, 'processors': [], 'platform_inventory': public}
            with patch.object(obj, '_machine_static_info', return_value=static), patch.object(obj, '_gpu_static_info', return_value=[]), patch.object(agent.shutil, 'which', return_value=None), patch.object(agent.platform, 'system', return_value='Linux'), patch.object(agent, 'psutil', SimpleNamespace(sensors_temperatures=lambda: {'nct': [SimpleNamespace(label='System', current=35)]})):
                hw = obj._collect_hardware()
            self.assertEqual(hw['platform_inventory'], public)
            self.assertEqual(hw['sensors'][0].get('scope'), 'host_visible' if kind == 'container' else 'os_visible')

    def test_cgroup_ancestor_limit_uses_matching_group_usage_and_rejects_escape(self):
        obj = object.__new__(agent.Agent)
        files = {'/proc/self/cgroup': '0::/jobs/leaf', '/proc/self/mountinfo': '1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw',
                 '/sys/fs/cgroup/jobs/leaf/memory.max': 'max', '/sys/fs/cgroup/jobs/memory.max': '4096',
                 '/sys/fs/cgroup/jobs/memory.current': '1024', '/sys/fs/cgroup/memory.max': 'max'}
        with patch.object(agent, '_hardware_read', side_effect=lambda path, limit=8192: files.get(path)) as read:
            sample = obj._cgroup_memory()
            self.assertEqual((sample['total_bytes'], sample['used_bytes'], sample['available_bytes']), (4096, 1024, 3072))
            files['/proc/self/cgroup'] = '0::/../../etc'
            self.assertEqual(obj._cgroup_memory()['state'], 'query_failed')
            self.assertFalse(any('..' in call.args[0] for call in read.call_args_list))
            files['/proc/self/cgroup'] = '0::/jobs/leaf'
            files.pop('/sys/fs/cgroup/jobs/memory.max')
            self.assertEqual(obj._cgroup_memory()['state'], 'query_failed')

    def test_psutil_exception_falls_back_and_partial_bytes_never_exceed_total(self):
        obj = object.__new__(agent.Agent)
        with patch.object(agent, 'psutil', SimpleNamespace(virtual_memory=lambda: (_ for _ in ()).throw(OSError()))), patch.object(agent.platform, 'system', return_value='Linux'), patch.object(agent, '_hardware_read', return_value='MemTotal: 8 kB\nMemAvailable: 9 kB\n'):
            m = obj._system_memory('unknown')
        self.assertEqual(m['total_bytes'], 8192)
        self.assertIsNone(m['available_bytes'])
        self.assertIsNone(m['used_bytes'])
        self.assertEqual(m['source'], '/proc/meminfo')

if __name__ == '__main__':
    unittest.main()
