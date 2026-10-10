"""Offline storage/inventory regression probes: no app/database imports."""
import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('storage_refine_agent', ROOT / 'agent/stella_agent.py')
assert spec is not None and spec.loader is not None
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def instance():
    with patch.object(a.Agent, '_check_deps'):
        return a.Agent('http://offline.invalid', 'offline')


def test_windows_get_disk_inventory_and_unique_volume_usage():
    data = {'disks': [
        {'Number': 0, 'FriendlyName': 'KINGSTON SNV2S1000G', 'BusType': 'NVMe', 'Size': 1000},
        {'Number': 1, 'FriendlyName': 'Maxsun 1TB SSD', 'BusType': 'NVMe', 'Size': 1000}],
        'partitions': [{'DiskNumber': 0, 'VolumeId': 'D'},
                       {'DiskNumber': 1, 'VolumeId': 'C'}, {'DiskNumber': 1, 'VolumeId': 'E'},
                       {'DiskNumber': 1, 'VolumeId': None}],
        'volumes': [{'Path': x, 'DriveLetter': x, 'FileSystem': 'NTFS', 'Size': size,
                     'SizeRemaining': free} for x, size, free in [('C', 300, 30), ('D', 1000, 700), ('E', 600, 200)]]}
    data['volumes'].append({'Path': 'hidden', 'DriveLetter': None, 'FileSystem': 'FAT32', 'Size': 100, 'SizeRemaining': 50})
    # Duplicate a volume and leave the reserved partition unmeasured.
    data['volumes'].append(data['volumes'][0])
    with patch.object(a.platform, 'system', return_value='Windows'), \
            patch.object(a, '_map_command', return_value=json.dumps(data)) as cmd:
        result = instance().list_storage()
    disks = [x for x in result if x['kind'] == 'physical']
    volumes = [x for x in result if x['kind'] == 'volume']
    assert len(disks) == 2, 'Windows physical disks must not disappear'
    assert len(volumes) == 3
    assert disks[0]['bus'] == 'NVMe'
    assert disks[0]['volume_mounts'] == ['D:/']
    assert disks[1]['volume_mounts'] == ['C:/', 'E:/']
    assert all(x['used'] is None and x['percent'] is None for x in disks)
    assert sum(x['used'] for x in volumes) == 970
    assert all(x['sampled_at'] for x in result)
    script = base64.b64decode(cmd.call_args.args[0][-1]).decode('utf-16-le')
    assert all(x in script for x in ['Get-Disk', 'Get-Partition', 'Get-Volume'])
    assert 'SerialNumber' not in script
    assert cmd.call_args.kwargs['timeout'] == 5


def test_nvidia_uuid_telemetry_merges_by_bus_without_copying_to_intel():
    obj = instance()
    inventory = [obj._gpu_row('pci:0000:02:00.0', 'Same RTX', 'NVIDIA', 'discrete', 'PCI/sysfs', 'unsupported', '0000:02:00.0'),
                 obj._gpu_row('pci:0000:01:00.0', 'Same RTX', 'NVIDIA', 'discrete', 'PCI/sysfs', 'unsupported', '0000:01:00.0'),
                 obj._gpu_row('pci:0000:00:02.0', 'Intel UHD', 'Intel', 'integrated', 'PCI/sysfs', 'unsupported', '0000:00:02.0')]
    output = ('GPU-a, Same RTX, 60, 2700, 8000, 30, 1024, 8192, 90, 40, 00000000:01:00.0\n'
              'GPU-b, Same RTX, N/A, nan, 8000, 50, 2048, 8192, 100, N/A, 00000000:02:00.0\n')
    with patch.object(obj, '_gpu_static_info', return_value=inventory), patch.object(a, 'psutil', None), \
            patch.object(obj, '_machine_static_info', return_value={'machine': a._classify_machine(), 'physical_inventory': None, 'processors': []}), \
            patch.object(a.platform, 'system', return_value='Linux'), \
            patch.object(a.shutil, 'which', return_value='nvidia-smi'), \
            patch.object(a, '_map_command', return_value=output):
        result = obj._collect_hardware()
    assert len(result['gpus']) == 3
    first, second, intel = result['gpus']
    assert (first['id'], first['utilization_pct']) == ('GPU-b', 50)
    assert (second['id'], second['utilization_pct']) == ('GPU-a', 30)
    assert intel['utilization_pct'] is None and intel['telemetry_status'] == 'unsupported'
    assert result['availability']['gpu'] == 'available'
    assert first['temperature_c'] is None


def test_gpu_query_failure_preserves_inventory_and_no_gpu_requires_enumeration():
    obj = instance()
    inventory = [obj._gpu_row('gpu', 'RTX test', 'NVIDIA', 'discrete', 'PCI/sysfs', 'unsupported')]
    static = {'machine': a._classify_machine(), 'physical_inventory': None, 'processors': []}
    with patch.object(obj, '_machine_static_info', return_value=static), patch.object(a, 'psutil', None), \
            patch.object(a.platform, 'system', return_value='Linux'), \
            patch.object(a.shutil, 'which', return_value='nvidia-smi'), \
            patch.object(a, '_map_command', side_effect=ValueError('query timeout')), \
            patch.object(obj, '_gpu_static_info', return_value=inventory):
        result = obj._collect_hardware()
    assert len(result['gpus']) == 1
    assert result['gpus'][0]['telemetry_status'] == 'query_failed'
    assert result['availability']['gpu'] == 'inventory_only'
    for rows, expected in [(None, 'unknown'), ([], 'no_gpu')]:
        with patch.object(obj, '_machine_static_info', return_value=static), patch.object(a, 'psutil', None), \
                patch.object(a.shutil, 'which', return_value=None), \
                patch.object(obj, '_gpu_static_info', return_value=rows):
            assert obj._collect_hardware()['availability']['gpu'] == expected


def test_linux_raid_members_never_duplicate_pool_usage_and_root_efi_visible():
    def disk(name, children=()):
        return {'name': name, 'type': 'disk', 'size': 1000, 'model': 'test SSD',
                'tran': 'sata', 'children': list(children)}
    pool = {'name': 'md127', 'type': 'raid5', 'maj:min': '9:127', 'mountpoints': ['/vol1']}
    tree = {'blockdevices': [disk('sda', [pool]), disk('sde', [pool]), disk('sdf', [pool]), disk('sdg', [pool]),
        disk('sdb', [{'name': 'sdb1', 'mountpoints': ['/boot/efi']}, {'name': 'sdb2', 'mountpoints': ['/']},
                     {'name': 'md125', 'type': 'raid1', 'mountpoints': ['/vol2']}]),
        disk('sdc', [{'name': 'md126', 'type': 'raid1', 'mountpoints': ['/vol3']}]), disk('sdd')]}
    parts = [NS(device=dev, mountpoint=mount, fstype='ext4') for dev, mount in
             [('/dev/sdb1', '/boot/efi'), ('/dev/sdb2', '/'), ('/dev/md127', '/vol1'),
              ('/dev/md125', '/vol2'), ('/dev/md126', '/vol3'), ('/dev/md127', '/bind')]]
    fake = NS(disk_partitions=lambda all: parts,
              disk_usage=lambda mount: NS(total=100, used=20, percent=20))
    with patch.object(a.platform, 'system', return_value='Linux'), patch.object(a, 'psutil', fake), \
            patch.object(a, '_map_command', return_value=json.dumps(tree)), \
            patch.object(a.subprocess, 'run', return_value=NS(stdout=json.dumps(tree))), \
            patch.object(a.os, 'stat', side_effect=OSError):
        result = instance().list_storage()
    disks = [x for x in result if x['kind'] == 'physical']
    assert len(disks) == 7
    for row in disks:
        assert row['used'] is None and row['percent'] is None
        assert row['model'] == 'test SSD'
        if row['device'] in ['/dev/sda', '/dev/sde', '/dev/sdf', '/dev/sdg']:
            assert row['usage_scope'] == 'shared_pool'
            assert row['pool_mounts'] == ['/vol1']
        if row['device'] == '/dev/sdd':
            assert row['usage_scope'] == 'unmeasured'
    volumes = [x for x in result if x['kind'] != 'physical']
    assert {x['mount'] for x in volumes} == {'/', '/boot/efi', '/vol1', '/vol2', '/vol3'}
    assert sum(x['used'] for x in volumes) == 100


def test_btrfs_subvolumes_with_different_st_dev_count_one_filesystem():
    obj = instance()
    parts = [NS(device='/dev/mapper/pool', mountpoint=mount, fstype='btrfs') for mount in ['/vol1', '/vol1/subvol']]
    fake = NS(disk_partitions=lambda all: parts, disk_usage=lambda mount: NS(total=100, used=20, percent=20))
    with patch.object(a.platform, 'system', return_value='Linux'), patch.object(a, 'psutil', fake), \
            patch.object(a, '_map_command', return_value='{"blockdevices":[]}'), \
            patch.object(a.os, 'stat', side_effect=lambda p: NS(st_dev=1 if p=='/vol1' else 2)):
        result = obj.list_storage()
    assert len(result) == 1
    assert result[0]['used'] == 20


def test_storage_singleflight_60_second_cache_and_failure_preserves_sample():
    import threading
    obj = instance()
    started, release = threading.Event(), threading.Event()
    now, calls = [100.0], []
    sample = [{'device': 'disk0', 'sampled_at': 'original'}]
    def collect():
        calls.append(1)
        started.set()
        assert release.wait(1)
        return sample
    with patch.object(a.time, 'monotonic', side_effect=lambda: now[0]), \
            patch.object(obj, 'list_storage', collect):
        try:
            assert obj._storage_info() is None
            assert started.wait(1)
            for _ in range(10):
                assert obj._storage_info() is None
            assert len(calls) == 1
            release.set()
            with obj._storage_scheduler._lock:
                workers = list(obj._storage_scheduler._threads.values())
            for worker in workers:
                worker.join(1)
            now[0] = 159.99
            assert obj._storage_info() == sample
            assert len(calls) == 1
            now[0] = 160
            with patch.object(obj, 'list_storage', side_effect=ValueError('offline')):
                assert obj._storage_info() == sample
                with obj._storage_scheduler._lock:
                    workers = list(obj._storage_scheduler._threads.values())
                for worker in workers:
                    worker.join(1)
                assert obj._storage_info() == sample
        finally:
            release.set()
            if hasattr(obj, '_storage_scheduler'):
                obj._storage_scheduler.close()


def test_regular_report_always_carries_latest_cached_storage():
    obj = instance()
    snapshots = [None, [{'sampled_at': 'old-time', 'used': None}]]
    bodies = []
    with patch.object(obj, '_storage_info', side_effect=snapshots, create=True), \
            patch.object(obj, '_os_info', return_value={}), \
            patch.object(obj, '_check_components', return_value={}), \
            patch.object(obj, '_post', side_effect=lambda path, **kw: bodies.append(kw['json_body']) or {}):
        obj.report([], [])
        obj.report([], [])
    assert [x.get('storage', 'missing') for x in bodies] == snapshots


def test_linux_intel_inventory_without_nvidia_is_not_unavailable(tmp_path):
    pci = tmp_path / '0000:00:02.0'
    pci.mkdir()
    for field, value in {'class': '0x030000', 'vendor': '0x8086', 'device': '0x3185'}.items():
        (pci / field).write_text(value + '\n')
    (pci / 'driver').symlink_to(tmp_path / 'i915')
    obj = instance()
    with patch.object(a.shutil, 'which', return_value=None):
        rows = obj._linux_gpu_inventory(str(tmp_path))
    assert len(rows) == 1
    assert rows[0]['name'] == 'Intel UHD Graphics 600'
    assert rows[0]['vendor'] == 'Intel'
    assert rows[0]['kind'] == 'integrated'
    assert rows[0]['telemetry_status'] == 'unsupported'
    assert rows[0]['temperature_c'] is None
    obj._machine_static_cache = (float('inf'), {'machine': a._classify_machine(), 'physical_inventory': None, 'processors': []})
    with patch.object(obj, '_gpu_static_info', return_value=rows, create=True), \
            patch.object(a, 'psutil', None), patch.object(a.platform, 'system', return_value='Linux'), \
            patch.object(a.shutil, 'which', return_value=None):
        result = obj._collect_hardware()
    assert result['gpus'] == rows
    assert result['availability']['gpu'] == 'inventory_only'


def test_windows_inventory_filters_virtual_adapters_and_classifies_actual_gpus():
    rows = [{'Name': name, 'PNPDeviceID': pnp, 'ConfigManagerErrorCode': error} for name, pnp, error in [
        ('Zako Display Adapter', 'ROOT\\ZAKO', 0), ('Todesk Virtual Display Adapter', 'ROOT\\TOD', 0),
        ('NVIDIA GeForce RTX 5060 Ti', 'PCI\\VEN_10DE&DEV_2D04', 0),
        ('AMD Radeon(TM) Graphics', 'PCI\\VEN_1002&DEV_13C0', 0),
        ('Unknown Display', 'PCI\\VEN_1234&DEV_5678', 28)]]
    obj = instance()
    with patch.object(a, '_map_command', return_value=json.dumps(rows)) as cmd:
        result = obj._windows_gpu_inventory()
    assert len(result) == 3
    assert [x['kind'] for x in result] == ['discrete', 'integrated', 'unknown']
    assert [x['vendor'] for x in result] == ['NVIDIA', 'AMD', 'Unknown']
    assert result[-1]['telemetry_status'] == 'driver_missing'
    script = base64.b64decode(cmd.call_args.args[0][-1]).decode('utf-16-le')
    assert 'Win32_VideoController' in script and 'PNPDeviceID' in script
    assert 'SerialNumber' not in script


def test_linux_drm_finite_readings_are_measured_without_nvidia(tmp_path):
    obj = instance()
    pci = tmp_path / '0000:00:02.0'
    pci.mkdir()
    drm = tmp_path / 'drm'
    card = drm / 'card0'
    card.mkdir(parents=True)
    (card / 'device').symlink_to(pci)
    (card / 'gt_cur_freq_mhz').write_text('450')
    inventory = [obj._gpu_row('pci:0000:00:02.0', 'Intel UHD', 'Intel', 'integrated', 'PCI/sysfs', 'unsupported', '0000:00:02.0')]
    obj._linux_gpu_readings(inventory, str(drm))
    assert inventory[0]['graphics_clock_mhz'] == 450
    assert inventory[0]['telemetry_status'] == 'available'
    assert inventory[0]['source'] == 'DRM/sysfs'
    assert inventory[0]['sampled_at']
    (card / 'gt_cur_freq_mhz').write_text('nan')
    inventory[0]['graphics_clock_mhz'] = None
    obj._linux_gpu_readings(inventory, str(drm))
    assert inventory[0]['graphics_clock_mhz'] is None


def test_os_cpu_cores_means_physical_and_keeps_logical_separate():
    obj = instance()
    with patch.object(a, 'psutil', NS(cpu_count=lambda logical: 12 if logical else 6, boot_time=lambda: 1)), \
            patch.object(a.platform, 'system', return_value='Windows'), \
            patch.object(obj, '_hardware_info', return_value={'cpu': {'physical_cores': 6, 'logical_cores': 12}}):
        info = obj._os_info()
    assert info['cpu_cores'] == 6
    assert info['cpu_logical_cores'] == 12


def test_agent_release_version_is_0612():
    assert a.AGENT_VERSION == '0.6.12'


def test_pending_and_stale_gpu_availability_is_unknown_not_no_gpu():
    obj = instance()
    assert obj._empty_hardware('collecting')['availability']['gpu'] == 'unknown'
    assert obj._empty_hardware('stale')['availability']['gpu'] == 'unknown'
    assert obj._empty_hardware('collection_failed')['availability']['gpu'] == 'collection_failed'


def test_real_run_keeps_heartbeats_while_storage_worker_is_blocked():
    import threading
    obj = instance()
    started, release, reported, stop = (threading.Event() for _ in range(4))
    bodies, errors = [], []
    def storage():
        started.set()
        release.wait(3)
        return [{'sampled_at': 'original'}]
    def post(path, **kw):
        if kw['json_body'].get('metrics'):
            bodies.append(kw['json_body'])
            if len(bodies) >= 2:
                reported.set()
        return {}
    replacements = {'list_storage': storage, '_post': post, '_os_info': lambda: {},
        'list_interfaces': lambda: {}, '_check_components': lambda: {}, '_probe_public_ip': lambda: {},
        '_report_map_snapshot': lambda: None, 'refresh_config': lambda: None, 'check_update': lambda: None,
        'run_due_probes': lambda: None, 'poll_and_execute': lambda: None,
        'collect_sys': lambda: {}, 'collect_metrics': lambda: [{'ts': 'offline'}]}
    def run():
        try:
            obj.run(stop)
        except Exception as exc:
            errors.append(exc)
    with patch.multiple(obj, **replacements), patch.object(a, 'POLL_INTERVAL', .005), patch.object(a, 'REPORT_INTERVAL', .01):
        thread = threading.Thread(target=run)
        thread.start()
        try:
            assert started.wait(1)
            assert reported.wait(1), 'storage blocks heartbeat'
            assert all(x['storage'] is None for x in bodies)
        finally:
            stop.set()
            release.set()
            thread.join(2)
    assert errors == []
    assert not thread.is_alive()
    assert not obj._storage_scheduler.submit('storage', lambda: None)


def test_storage_none_and_admission_failure_never_replace_previous_snapshot():
    obj = instance()
    sample = [{'sampled_at': 'old-source-time'}]
    obj._storage_cache = sample
    with patch.object(obj._storage_scheduler, 'submit', side_effect=RuntimeError('closed')):
        assert obj._storage_info() is sample
    obj._storage_next_sample = 0
    def synchronous(key, operation):
        operation()
        return True
    with patch.object(obj._storage_scheduler, 'submit', side_effect=synchronous), patch.object(obj, 'list_storage', return_value=None):
        assert obj._storage_info() is sample


def test_windows_gpu_inventory_shares_one_cached_machine_query():
    obj = instance()
    fixture = {'computer_system': {'Manufacturer': 'MAXSUN', 'Model': 'MS-Terminator B850M PRO'},
               'processors': [{'Name': '9600X', 'NumberOfCores': 6, 'NumberOfLogicalProcessors': 12}],
               'gpus': [{'Name': 'AMD Radeon(TM) Graphics', 'PNPDeviceID': 'PCI\\VEN_1002&DEV_13C0', 'ConfigManagerErrorCode': 0}]}
    with patch.object(a.platform, 'system', return_value='Windows'), patch.object(a, 'psutil', None), \
            patch.object(a.shutil, 'which', return_value=None), \
            patch.object(a, '_map_command', return_value=json.dumps(fixture)) as command:
        first = obj._collect_hardware()
        second = obj._collect_hardware()
    assert len(first['gpus']) == len(second['gpus']) == 1
    command.assert_called_once()
    assert command.call_args.kwargs['timeout'] == 3


def test_gpu_inventory_failure_is_unknown_and_cache_is_300_seconds():
    obj = instance()
    now = [100]
    with patch.object(a.time, 'monotonic', side_effect=lambda: now[0]), \
            patch.object(a.platform, 'system', return_value='Linux'), \
            patch.object(obj, '_linux_gpu_inventory', side_effect=PermissionError) as collect:
        assert obj._gpu_static_info() is None
        now[0] = 399
        assert obj._gpu_static_info() is None
        assert collect.call_count == 1
        now[0] = 400
        assert obj._gpu_static_info() is None
        assert collect.call_count == 2
