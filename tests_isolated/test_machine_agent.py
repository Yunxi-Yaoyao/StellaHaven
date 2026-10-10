"""Machine classification fixtures: offline, no host probes or database."""
import importlib.util
import json
import pytest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('machine_agent', ROOT / 'agent/stella_agent.py')
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


def test_evidence_classification_handles_physical_vm_vbs_container_and_unknown():
    fixtures = [
        ({'vendor': 'MAXSUN', 'model': 'MS-Terminator B850M PRO', 'windows': True,
          'hypervisor_present': True}, 'physical', None),
        ({'vendor': 'ASUSTeK COMPUTER INC.', 'model': 'ROG STRIX', 'virt_none': True}, 'physical', None),
        ({'vendor': 'Dell Inc.', 'model': 'PowerEdge R740', 'virt_none': True}, 'physical', None),
        ({'vendor': 'VMware, Inc.', 'model': 'VMware Virtual Platform'}, 'virtual', 'vmware'),
        ({'vendor': 'Microsoft Corporation', 'model': 'Virtual Machine'}, 'virtual', 'hyperv'),
        ({'vendor': 'QEMU', 'model': 'Standard PC (Q35 + ICH9, 2009)'}, 'virtual', 'qemu'),
        ({'vendor': 'ASUSTeK COMPUTER INC.', 'model': 'ROG STRIX', 'windows': True,
          'hypervisor_present': True}, 'physical', None),
        ({'vendor': 'LENOVO', 'model': 'ThinkStation P3', 'windows': True}, 'physical', None),
        ({'vendor': 'ASUSTeK COMPUTER INC.', 'model': 'ROG STRIX', 'virt_none': True,
          'container': 'docker', 'vm': 'kvm'}, 'container', 'docker'),
        ({'vendor': 'Dell Inc.', 'model': 'PowerEdge R740', 'vm': 'kvm'}, 'virtual', 'kvm'),
        ({'vendor': 'unknown vendor', 'model': 'made up', 'windows': True}, 'unknown', None),
        ({'vendor': 'ASUS', 'model': None, 'virt_none': True}, 'unknown', None),
        ({}, 'unknown', None),
        ({'vendor': None, 'model': None}, 'unknown', None),
    ]
    for evidence, kind, virtualization in fixtures:
        machine = agent._classify_machine(**evidence)
        assert machine['kind'] == kind, evidence
        assert machine['virtualization'] == virtualization, evidence
        assert set(machine) == {'kind', 'vendor', 'model', 'virtualization', 'evidence', 'detected_at'}
        assert machine['detected_at'].endswith('+00:00')
        assert all(isinstance(item, str) and len(item) <= 128 for item in machine['evidence'])
        assert machine['evidence'], evidence


def test_linux_physical_inventory_is_privacy_allowlisted_and_cached_300_seconds():
    obj = agent.Agent('http://offline.invalid', 'offline')
    now = [100.0]
    files = {'/sys/class/dmi/id/sys_vendor': 'Dell Inc.',
             '/sys/class/dmi/id/product_name': 'PowerEdge R740',
             '/sys/class/dmi/id/board_vendor': 'Dell Inc.',
             '/sys/class/dmi/id/board_name': 'Test Board',
             '/sys/class/dmi/id/bios_vendor': 'American Megatrends',
             '/sys/class/dmi/id/bios_version': '1.2'}
    dmi = ('Memory Device\n\tSize: 16 GB\n\tLocator: DIMM_A1\n\tSpeed: 4800 MT/s\n'
           '\tConfigured Memory Speed: 4800 MT/s\n\tManufacturer: MAXSUN\n'
           '\tPart Number: MAXSUN16G6400\n\tSerial Number: SECRET\n'
           'Memory Device\n\tSize: No Module Installed\n')
    def command(args, **kwargs):
        assert kwargs['timeout'] <= 3
        assert not any('sudo' in arg for arg in args)
        if '--container' in args or '--vm' in args:
            assert kwargs['allowed_returncodes'] == (0, 1)
            return 'none\n'
        if '-J' in args:
            assert '-d' in args and '-b' in args
            assert not any('SERIAL' in arg.upper() or 'UUID' in arg.upper() for arg in args)
            return json.dumps({'blockdevices': [{'name': 'sda', 'model': 'Test SSD',
                               'size': 1000000, 'tran': 'scsi', 'rota': False, 'serial': 'SECRET'}]})
        if '--type' in args:
            return dmi
        raise AssertionError(args)
    with patch.object(agent.platform, 'system', return_value='Linux'), \
            patch.object(agent.shutil, 'which', side_effect=lambda name: '/bin/' + name), \
            patch.object(agent.os.path, 'exists', return_value=False), \
            patch.object(agent, '_hardware_read', side_effect=lambda path, limit=8192: files.get(path), create=True), \
            patch.object(agent, '_map_command', side_effect=command) as runner, \
            patch.object(agent.time, 'monotonic', side_effect=lambda: now[0]):
        first = obj._machine_static_info()
        count = runner.call_count
        now[0] = 399.99
        assert obj._machine_static_info() == first
        assert runner.call_count == count
        now[0] = 400
        obj._machine_static_info()
        assert runner.call_count == count * 2
    assert first['machine']['kind'] == 'physical'
    physical = first['physical_inventory']
    assert physical['board'] == {'vendor': 'Dell Inc.', 'model': 'Test Board'}
    assert physical['bios']['version'] == '1.2'
    assert physical['memory_modules'] == [{'slot': 'DIMM_A1', 'capacity_bytes': 17179869184,
        'speed_mts': 4800, 'configured_speed_mts': 4800, 'vendor': 'MAXSUN', 'part_number': 'MAXSUN16G6400'}]
    assert physical['disks'] == [{'name': 'sda', 'model': 'Test SSD', 'size_bytes': 1000000,
                                 'bus': 'scsi', 'rotational': False}]
    assert 'SECRET' not in json.dumps(first)


def windows_fixture(model='MS-Terminator B850M PRO', vendor='MAXSUN'):
    return {'computer_system': {'Manufacturer': vendor, 'Model': model, 'HypervisorPresent': True},
            'processors': [{'Name': 'Ryzen test', 'CurrentClockSpeed': 3900, 'MaxClockSpeed': 3900,
                            'NumberOfCores': 8, 'NumberOfLogicalProcessors': 16}],
            'board': {'Manufacturer': 'MAXSUN', 'Product': 'MS-Terminator B850M PRO', 'SerialNumber': 'SECRET'},
            'bios': {'Manufacturer': 'American Megatrends International LLC', 'SMBIOSBIOSVersion': 'B1.7D'},
            'memory': [{'DeviceLocator': 'DIMM_A1', 'Capacity': 17179869184, 'Speed': 4800,
                        'ConfiguredClockSpeed': 4800, 'Manufacturer': 'MAXSUN', 'PartNumber': 'MAXSUN16G6400',
                        'SerialNumber': 'SECRET'},
                       {'DeviceLocator': 'DIMM_B1', 'Capacity': 17179869184, 'Speed': 4800,
                        'ConfiguredClockSpeed': 4800, 'Manufacturer': 'MAXSUN', 'PartNumber': 'MSD516G64AX5-D40M0'}],
            'disks': [{'Name': 'disk0', 'Model': 'Kingston SNV2S1000G', 'Size': 1000000000000,
                       'InterfaceType': 'SCSI', 'SerialNumber': 'SECRET'}], 'container': False}


def test_windows_vbs_machine_inventory_and_cpu_use_one_bounded_cached_query():
    import base64
    obj = agent.Agent('http://offline.invalid', 'offline')
    obj._os_static_cache = {'cpu_model': 'legacy CPU'}
    output = windows_fixture()
    with patch.object(agent.platform, 'system', return_value='Windows'), \
            patch.object(agent, 'psutil', None), \
            patch.object(agent.shutil, 'which', side_effect=lambda name: 'powershell.exe' if name == 'powershell' else None), \
            patch.object(agent.os, 'stat', side_effect=FileNotFoundError()), \
            patch.object(agent, '_map_command', return_value=json.dumps(output)) as runner, \
            patch.object(agent.time, 'monotonic', return_value=100):
        first = obj._collect_hardware()
        second = obj._collect_hardware()
    assert first['machine']['kind'] == 'physical'
    assert second['machine']['detected_at'] == first['machine']['detected_at']
    runner.assert_called_once()
    args, kwargs = runner.call_args
    assert kwargs['timeout'] == 3
    script = base64.b64decode(args[0][-1]).decode('utf-16-le')
    for name in ('Win32_ComputerSystem', 'Win32_BaseBoard', 'Win32_BIOS',
                 'Win32_PhysicalMemory', 'Win32_DiskDrive', 'Win32_Container', 'Win32_Processor'):
        assert name in script
    assert "$ProgressPreference='SilentlyContinue'" in script
    assert '$ProgressPreference=0' in script
    assert 'UTF8' in script
    for forbidden in ('SerialNumber', 'UUID', 'MACAddress'):
        assert forbidden not in script
        assert forbidden not in json.dumps(first['physical_inventory'])
    assert 'SECRET' not in json.dumps(first)
    assert first['cpu']['model'] == 'Ryzen test'
    assert first['cpu']['frequency_mhz'] == 3900
    assert first['cpu']['max_frequency_mhz'] is None
    assert first['cpu']['base_frequency_mhz'] == 3900
    assert first['cpu']['base_frequency_source'] == 'Win32_Processor.MaxClockSpeed (WMI nominal metadata; not measured base/boost)'
    modules = first['physical_inventory']['memory_modules']
    assert len(modules) == 2
    assert all(m['speed_mts'] == 4800 and m['configured_speed_mts'] == 4800 for m in modules)
    assert modules[0]['part_number'] == 'MAXSUN16G6400'
    assert first['physical_inventory']['disks'][0]['bus'] == 'SCSI'
    assert first['physical_inventory']['disks'][0]['rotational'] is None


def test_lhm_119_second_sample_preserves_source_time_and_expires_on_cache_hit(tmp_path):
    from datetime import datetime, timedelta, timezone
    obj = agent.Agent('http://offline.invalid', 'offline')
    obj._os_static_cache = {'cpu_model': 'legacy'}
    now = datetime.now(timezone.utc)
    timestamp = (now - timedelta(seconds=119)).isoformat()
    path = tmp_path / 'sensors.json'
    path.write_text(json.dumps({'sampled_at': timestamp, 'cpu_temperature_c': 62,
        'cpu_frequency_mhz': 5400, 'sensors': [{'name': 'CPU Fan', 'kind': 'fan',
        'value': 1100, 'unit': 'RPM', 'source': 'LHM'}]}))
    with patch.object(agent.platform, 'system', return_value='Windows'), \
            patch.object(agent, 'psutil', None), \
            patch.object(agent.shutil, 'which', return_value=None), \
            patch.dict(agent.os.environ, {'STELLA_HARDWARE_SENSORS_FILE': str(path)}), \
            patch.object(agent, '_map_command', return_value=json.dumps(windows_fixture())), \
            patch.object(agent.time, 'monotonic', return_value=100):
        sample = obj._collect_hardware()
        assert sample['cpu']['sampled_at'] == timestamp
        assert sample['sensors_sampled_at'] == timestamp
        assert sample['sampled_at'] != timestamp  # envelope is collection, not LHM measurement
        obj._hardware_cache = sample
        obj._hardware_cached_at = 100
        obj._hardware_next_sample = 130
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now + timedelta(seconds=2)
        with patch.object(agent, 'datetime', Clock):
            expired = obj._hardware_info()
        assert expired['cpu']['temperature_c'] is None
        assert expired['cpu']['frequency_mhz'] is None
        assert expired['sensors'] == []
        assert expired['availability']['cpu_temperature'] == 'sensors_file_stale'
        assert expired['cpu']['sampled_at'] == timestamp  # no fake new measurement
        assert expired['sensors_sampled_at'] == timestamp
        assert sample['cpu']['temperature_c'] == 62  # immutable cached sample


def test_empty_failed_and_stale_contracts_never_claim_a_new_measurement():
    obj = agent.Agent('http://offline.invalid', 'offline')
    obj._os_static_cache = {'cpu_model': 'legacy'}
    for reason in ('collecting', 'collection_failed', 'stale'):
        sample = obj._empty_hardware(reason)
        assert sample['sampled_at'] is None
        assert sample['cpu']['sampled_at'] is None
        assert sample['sensors_sampled_at'] is None
        assert sample['machine']['kind'] == 'unknown'
        assert sample['physical_inventory'] is None


@pytest.mark.parametrize('error,expected', [
    (FileNotFoundError(), 'sensors_file_missing'),
    (PermissionError(), 'sensors_file_permission_denied'),
    (OSError(), 'sensors_file_unavailable'),
])
def test_sensor_file_os_errors_have_public_specific_reasons(error, expected):
    obj = agent.Agent('http://offline.invalid', 'offline')
    obj._os_static_cache = {'cpu_model': 'legacy'}
    with patch.object(agent.platform, 'system', return_value='Windows'), \
            patch.object(agent, 'psutil', None), patch.object(agent.shutil, 'which', return_value=None), \
            patch.object(agent.os, 'stat', side_effect=error), \
            patch.object(agent, '_map_command', side_effect=ValueError('SECRET host diagnostic')):
        sample = obj._collect_hardware()
    assert sample['availability']['cpu_temperature'] == expected
    assert sample['machine']['kind'] == 'unknown'
    assert sample['physical_inventory'] is None
    assert sample['cpu']['sampled_at'] is None
    assert 'SECRET' not in json.dumps(sample)


@pytest.mark.parametrize('content,expected', [
    ('{broken', 'sensors_file_invalid'),
    ('[]', 'sensors_file_invalid'),
    ('{"sampled_at":"2020-01-01T00:00:00Z"}', 'sensors_file_stale'),
    ('{"sampled_at":"2026-01-01T00:00:00"}', 'sensors_file_invalid'),
])
def test_sensor_file_invalid_and_stale_have_distinct_reasons(tmp_path, content, expected):
    path = tmp_path / 'sensors.json'
    path.write_text(content)
    obj = agent.Agent('http://offline.invalid', 'offline')
    obj._os_static_cache = {'cpu_model': 'legacy'}
    with patch.object(agent.platform, 'system', return_value='Windows'), \
            patch.object(agent, 'psutil', None), patch.object(agent.shutil, 'which', return_value=None), \
            patch.dict(agent.os.environ, {'STELLA_HARDWARE_SENSORS_FILE': str(path)}), \
            patch.object(agent, '_map_command', side_effect=ValueError('offline')):
        sample = obj._collect_hardware()
    assert sample['availability']['cpu_temperature'] == expected
    assert sample['cpu']['sampled_at'] is None
    assert sample['sensors_sampled_at'] is None


@pytest.mark.parametrize('systemd_container,systemd_vm,file_marker,cgroup,expected,engine', [
    ('none', 'none', '/.dockerenv', '', 'container', 'docker'),
    ('none', 'none', '/run/.containerenv', '', 'container', 'podman'),
    ('none', 'none', None, '0::/kubepods/secret-id', 'container', 'kubernetes'),
    ('docker', 'kvm', None, '', 'container', 'docker'),
    ('none', 'kvm', None, '', 'virtual', 'kvm'),
    (None, None, None, '', 'unknown', None),
    (None, 'none', None, '', 'unknown', None),
])
def test_linux_container_guards_prevent_passthrough_dmi_physical_inventory(
        systemd_container, systemd_vm, file_marker, cgroup, expected, engine):
    obj = agent.Agent('http://offline.invalid', 'offline')
    files = {'/sys/class/dmi/id/sys_vendor': 'MAXSUN',
             '/sys/class/dmi/id/product_name': 'MS-Terminator B850M PRO',
             '/proc/1/cgroup': cgroup}
    def command(args, **kwargs):
        if '--container' in args:
            value = systemd_container
        elif '--vm' in args:
            value = systemd_vm
        else:
            raise AssertionError('physical inventory collected on non-physical node')
        if value is None:
            raise ValueError('offline systemd')
        return value
    def read_metadata(path, limit=8192):
        assert not any(field in path for field in ('board_', 'bios_'))
        return files.get(path)
    with patch.object(agent.platform, 'system', return_value='Linux'), \
            patch.object(agent.shutil, 'which', side_effect=lambda name: '/bin/' + name), \
            patch.object(agent.os.path, 'exists', side_effect=lambda path: path == file_marker), \
            patch.object(agent, '_hardware_read', side_effect=read_metadata), \
            patch.object(agent, '_map_command', side_effect=command) as runner:
        sample = obj._machine_static_info()
    assert sample['machine']['kind'] == expected
    assert sample['machine']['virtualization'] == engine
    assert sample['physical_inventory'] is None
    assert runner.call_count == 2
    assert 'secret-id' not in json.dumps(sample)


@pytest.mark.parametrize('vendor,model,container,kind', [
    ('VMware, Inc.', 'VMware Virtual Platform', False, 'virtual'),
    ('Microsoft Corporation', 'Virtual Machine', False, 'virtual'),
    ('QEMU', 'Standard PC', False, 'virtual'),
    ('innotek GmbH', 'VirtualBox', False, 'virtual'),
    ('Xen', 'HVM domU', False, 'virtual'),
    ('MAXSUN', 'MS-Terminator B850M PRO', True, 'container'),
    ('unrecognized', 'unrecognized', False, 'unknown'),
    (None, None, False, 'unknown'),
])
def test_windows_nonphysical_drops_even_injected_physical_inventory(vendor, model, container, kind):
    data = windows_fixture(vendor=vendor, model=model)
    data['container'] = container
    obj = agent.Agent('http://offline.invalid', 'offline')
    with patch.object(agent.platform, 'system', return_value='Windows'), \
            patch.object(agent.shutil, 'which', return_value='powershell.exe'), \
            patch.object(agent, '_map_command', return_value=json.dumps(data)):
        sample = obj._machine_static_info()
    assert sample['machine']['kind'] == kind
    assert sample['physical_inventory'] is None
    assert sample['processors'][0]['Name'] == 'Ryzen test'


def test_linux_unreadable_dimms_and_disk_failures_are_unknown_without_sudo():
    obj = agent.Agent('http://offline.invalid', 'offline')
    def command(args, **kwargs):
        assert not any('sudo' in arg for arg in args)
        if '--container' in args or '--vm' in args:
            return 'none'
        raise PermissionError('SECRET permission detail')
    files = {'/sys/class/dmi/id/sys_vendor': 'MAXSUN',
             '/sys/class/dmi/id/product_name': 'MS-Terminator B850M PRO'}
    with patch.object(agent.platform, 'system', return_value='Linux'), \
            patch.object(agent.shutil, 'which', side_effect=lambda name: '/bin/' + name), \
            patch.object(agent.os.path, 'exists', return_value=False), \
            patch.object(agent, '_hardware_read', side_effect=lambda path, limit=8192: files.get(path)), \
            patch.object(agent, '_map_command', side_effect=command):
        sample = obj._machine_static_info()
    assert sample['machine']['kind'] == 'physical'
    physical = sample['physical_inventory']
    assert physical['memory_modules'] is None
    assert physical['disks'] is None
    assert physical['board'] == {'vendor': None, 'model': None}
    assert physical['bios'] == {'vendor': None, 'version': None}
    assert 'SECRET' not in json.dumps(sample)


@pytest.mark.parametrize('frequency', [0, -1, None, True, 'nan'])
def test_windows_wmi_frequency_sentinels_are_null(frequency):
    data = windows_fixture()
    data['processors'][0].update(CurrentClockSpeed=frequency, MaxClockSpeed=frequency)
    obj = agent.Agent('http://offline.invalid', 'offline')
    obj._os_static_cache = {'cpu_model': 'legacy'}
    with patch.object(agent.platform, 'system', return_value='Windows'), \
            patch.object(agent, 'psutil', None), patch.object(agent.shutil, 'which', return_value=None), \
            patch.object(agent.os, 'stat', side_effect=FileNotFoundError()), \
            patch.object(agent, '_map_command', return_value=json.dumps(data)):
        sample = obj._collect_hardware()
    assert sample['cpu']['frequency_mhz'] is None
    assert sample['cpu']['max_frequency_mhz'] is None
    assert sample['cpu']['base_frequency_mhz'] is None
    assert sample['cpu']['base_frequency_source'] is None
    assert sample['cpu']['sampled_at'] is None


def test_cached_wmi_frequency_cannot_borrow_fresh_lhm_temperature_timestamp():
    from datetime import datetime, timedelta, timezone
    obj = agent.Agent('http://offline.invalid', 'offline')
    obj._os_static_cache = {'cpu_model': 'legacy'}
    now = datetime.now(timezone.utc)
    sample = obj._empty_hardware('available')
    sample['sampled_at'] = now.isoformat()
    sample['cpu'].update(sampled_at=now.isoformat(), frequency_mhz=3900, temperature_c=62,
        frequency_source='Win32_Processor.CurrentClockSpeed (WMI; not measured boost)',
        temperature_source='LibreHardwareMonitor')
    sample['machine']['detected_at'] = (now - timedelta(seconds=121)).isoformat()
    with patch.object(agent.platform, 'system', return_value='Windows'):
        result = obj._expire_hardware_readings(sample)
    assert result['cpu']['frequency_mhz'] is None
    assert result['cpu']['frequency_source'] is None
    assert result['cpu']['temperature_c'] == 62
    assert result['cpu']['sampled_at'] == now.isoformat()
    assert result['availability']['cpu_temperature'] == 'available'


def test_static_failure_cache_is_300_seconds_from_completion_not_command_start():
    obj = agent.Agent('http://offline.invalid', 'offline')
    now = [100.0]
    def command(*args, **kwargs):
        now[0] += 3
        raise ValueError('SECRET timed out')
    with patch.object(agent.platform, 'system', return_value='Windows'), \
            patch.object(agent.shutil, 'which', return_value='powershell.exe'), \
            patch.object(agent, '_map_command', side_effect=command) as runner, \
            patch.object(agent.time, 'monotonic', side_effect=lambda: now[0]):
        first = obj._machine_static_info()
        assert first['machine']['kind'] == 'unknown'
        now[0] = 400
        assert obj._machine_static_info() == first
        assert runner.call_count == 1
        now[0] = 403
        obj._machine_static_info()
        assert runner.call_count == 2
    assert 'SECRET' not in json.dumps(first)


def test_local_metadata_reader_enforces_limit_and_missing_file(tmp_path):
    path = tmp_path / 'metadata'
    path.write_bytes(b'ASUS')
    assert agent._hardware_read(str(path), limit=4) == 'ASUS'
    assert agent._hardware_read(str(path), limit=3) is None
    assert agent._hardware_read(str(path) + '.missing') is None
    assert agent._memory_devices('Memory Device\n\tSize: Unknown\n\tSpeed: Unknown\n') == [
        {'slot': None, 'capacity_bytes': None, 'speed_mts': None, 'configured_speed_mts': None,
         'vendor': None, 'part_number': None}]
