"""Read-only map collector contract; run with pytest --noconftest."""
import base64
import hashlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('map_agent', Path(__file__).parents[1] / 'agent/stella_agent.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
LOCAL = base64.b64encode(b'l' * 32).decode()
PEER = base64.b64encode(b'p' * 32).decode()


def sample():
    return {'public-key': f'wg-real\t{LOCAL}\n', 'peers': f'wg-real\t{PEER}\n',
            'endpoints': f'wg-real\t{PEER}\t[2001:4860::1]:51820\n',
            'allowed-ips': f'wg-real\t{PEER}\t10.0.0.0/24 ::/0\n',
            'latest-handshakes': f'wg-real\t{PEER}\t0\n',
            'transfer': f'wg-real\t{PEER}\t12\t34\n'}


class WireGuardTests(unittest.TestCase):
    def test_legacy_endpoints_continuation_rows(self):
        data=sample();second=base64.b64encode(b's'*32).decode()
        data['peers']+=f'wg-real\t{second}\n'
        data['endpoints']+=f'{second}\t8.8.8.8:51820\n'
        data['allowed-ips']+=f'wg-real\t{second}\t10.2.0.0/24\n'
        data['latest-handshakes']+=f'wg-real\t{second}\t0\n'
        data['transfer']+=f'wg-real\t{second}\t0\t0\n'
        self.assertEqual(len(a._parse_map_wireguard(data,{})['interfaces'][0]['peers']),2)

    def test_safe_ipv6_snapshot_hashes_keys(self):
        result = a._parse_map_wireguard(sample(), {'wg-real': ['10.0.0.1/24']})
        iface = result['interfaces'][0]
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(iface['public_key_id'], hashlib.sha256(LOCAL.encode()).hexdigest())
        self.assertEqual(iface['peers'][0]['latest_handshake_at'], 0)
        self.assertEqual(iface['peers'][0]['allowed_ips'], ['10.0.0.0/24', '::/0'])
        self.assertNotIn(PEER, str(result))
        self.assertNotIn(LOCAL, str(result))


class CollectorTests(unittest.TestCase):
    def test_wg_only_safe_commands_and_permission(self):
        calls = []
        def run(cmd, **kw):
            calls.append(cmd)
            return sample()[cmd[-1]]
        with patch.object(a.shutil, 'which', return_value='/usr/bin/wg'), patch.object(a, '_map_command', side_effect=run), patch.object(a, '_map_addresses', return_value={}):
            self.assertEqual(a._collect_map_wireguard()['status'], 'ok')
        self.assertEqual([c[1:] for c in calls], [['show', 'all', f] for f in a._MAP_WG_FIELDS])
        with patch.object(a.shutil, 'which', return_value='/usr/bin/wg'), patch.object(a, '_map_command', side_effect=PermissionError):
            self.assertEqual(a._collect_map_wireguard(), {'status': 'permission_denied', 'interfaces': []})

    def test_unprivileged_wg_uses_only_fixed_read_commands(self):
        calls=[]
        def run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] != '/usr/bin/sudo': raise PermissionError('denied')
            return sample()[cmd[-1]]
        with patch.object(a.shutil,'which',side_effect=lambda x: '/usr/bin/'+x if x in ('wg','sudo') else None), patch.object(a.platform,'system',return_value='Linux'), patch.object(a,'_map_command',side_effect=run), patch.object(a,'_map_addresses',return_value={}):
            self.assertEqual(a._collect_map_wireguard()['status'],'ok')
        self.assertTrue(all(cmd[-1] in a._MAP_WG_FIELDS for cmd in calls))
        self.assertTrue(all(cmd[1:4]==['-n','/usr/bin/wg','show'] for cmd in calls if cmd[0].endswith('/sudo')))

    def test_nat_requires_binding_and_valid_public_coordinates(self):
        with patch.object(a, '_map_physical_iface', return_value='eth0'), patch.object(a, '_map_addresses', return_value={'eth0': ['192.168.1.2/24']}), patch.object(a.shutil, 'which', return_value='/usr/bin/curl'), patch.object(a, '_map_command', return_value='{"ip":"8.8.8.8","latitude":12,"longitude":34,"city_name":"City"}\n192.168.1.2') as run:
            self.assertEqual(a._collect_map_location()['status'], 'located')
            args = run.call_args.args[0]
            self.assertIn('if!eth0', args)
            self.assertIn('--noproxy', args)
            self.assertEqual(args[-1], 'https://api.ip2location.io/')
            self.assertEqual(a._collect_map_location()['provider'], 'ip2location')
            run.return_value = '{"ip":"127.0.0.1","latitude":12,"longitude":34}\n192.168.1.2'
            self.assertEqual(a._collect_map_location()['status'], 'unknown')
            run.return_value = '{"ip":"8.8.8.8","latitude":NaN,"longitude":34}\n192.168.1.2'
            self.assertEqual(a._collect_map_location()['status'], 'unknown')

    def test_ip2location_error_is_unknown_without_fallback(self):
        with patch.object(a, '_map_physical_iface', return_value='eth0'), patch.object(a, '_map_addresses', return_value={'eth0': ['192.168.1.2/24']}), patch.object(a.shutil, 'which', return_value='/usr/bin/curl'), patch.object(a, '_map_command', return_value='{"error":{"error_code":104,"error_message":"quota"}}\n192.168.1.2') as run:
            self.assertEqual(a._collect_map_location()['status'],'unknown')
            self.assertEqual(run.call_count,1)

    def test_cache_and_separate_report(self):
        agent = a.Agent('https://unused.invalid', 'test-token')
        with patch.object(a, '_collect_map_location', return_value={'status': 'located'}) as loc, patch.object(a, '_collect_map_wireguard', return_value={'status': 'ok', 'interfaces': []}) as wg, patch.object(a.time, 'monotonic', side_effect=[0, 60, 901]), patch.object(agent, '_post') as post:
            for _ in range(3):
                agent._report_map_snapshot()
            self.assertEqual(loc.call_count, 2)
            self.assertEqual(wg.call_count, 3)
            body = post.call_args.kwargs['json_body']
            self.assertEqual(set(body), {'metrics', 'map_snapshot'})
            self.assertEqual(body['metrics'], [])

    def test_physical_default_ignores_tun_and_rejects_ambiguity(self):
        import json
        routes = [{'dev': 'tun0', 'gateway': '198.18.0.1', 'metric': 0},
                  {'dev': 'eth0', 'gateway': '192.168.1.1', 'metric': 100}]
        with patch.object(a.platform, 'system', return_value='Linux'), patch.object(a.shutil, 'which', return_value='/sbin/ip'), patch.object(a.os.path, 'exists', side_effect=lambda p: 'tun0' not in p), patch.object(a, '_map_command', side_effect=lambda cmd: json.dumps(routes)):
            self.assertEqual(a._map_physical_iface(), 'eth0')
            routes.append({'dev': 'eth1', 'gateway': '192.168.2.1', 'metric': 100})
            with self.assertRaises(ValueError):
                a._map_physical_iface()
            routes[:] = routes[:1]
            with self.assertRaises(ValueError):
                a._map_physical_iface()

    def test_unsupported_and_no_interfaces_are_distinct(self):
        with patch.object(a.shutil, 'which', return_value=None):
            self.assertEqual(a._collect_map_wireguard()['status'], 'unavailable')
        with patch.object(a.shutil, 'which', return_value='/usr/bin/wg'), patch.object(a, '_map_command', return_value=''), patch.object(a, '_map_addresses', return_value={}):
            self.assertEqual(a._collect_map_wireguard(), {'status': 'ok', 'interfaces': []})

    def test_windows_wg_exe_uses_same_whitelist(self):
        with patch.object(a.platform, 'system', return_value='Windows'), patch.object(a.shutil, 'which', side_effect=lambda name: 'wg.exe' if name == 'wg.exe' else None), patch.object(a, '_map_command', side_effect=lambda cmd: sample()[cmd[-1]]) as run, patch.object(a, '_map_addresses', return_value={}):
            self.assertEqual(a._collect_map_wireguard()['status'], 'ok')
            self.assertTrue(all(call.args[0][0] == 'wg.exe' for call in run.call_args_list))

    def test_endpoint_none_and_oversized_fail_closed(self):
        data = sample()
        data['endpoints'] = f'wg-real\t{PEER}\t(none)\n'
        result = a._parse_map_wireguard(data, {})
        self.assertIsNone(result['interfaces'][0]['peers'][0]['endpoint'])
        data['peers'] = 'x' * (a._MAP_OUTPUT_LIMIT + 1)
        with self.assertRaises(ValueError):
            a._parse_map_wireguard(data, {})

    def test_unknown_retries_after_one_minute(self):
        agent = a.Agent('https://unused.invalid', '')
        with patch.object(a, '_collect_map_location', return_value={'status': 'unknown'}) as loc, patch.object(a, '_collect_map_wireguard', return_value={'status': 'unavailable', 'interfaces': []}), patch.object(a.time, 'monotonic', side_effect=[0, 59, 60]):
            for _ in range(3):
                agent.collect_map_snapshot()
            self.assertEqual(loc.call_count, 2)

    def test_command_limits_and_proxy_environment(self):
        import sys
        with patch.dict(a.os.environ, {'HTTP_PROXY': 'do-not-use', 'all_proxy': 'do-not-use'}):
            output = a._map_command([sys.executable, '-c', 'import os; print(any(k.lower().endswith("_proxy") for k in os.environ))'])
            self.assertEqual(output.strip(), 'False')
        with self.assertRaises(ValueError):
            a._map_command([sys.executable, '-c', 'print("x" * 200000)'])
        with self.assertRaises(ValueError):
            a._map_command([sys.executable, '-c', 'import time; time.sleep(1)'], timeout=0.01)
        with self.assertRaises(PermissionError):
            a._map_command([sys.executable, '-c', 'import sys; print("Operation not permitted"); sys.exit(1)'])

    def test_duplicate_and_missing_handshake_fail_closed(self):
        for field in ('peers', 'latest-handshakes'):
            data = sample()
            data[field] += data[field]
            with self.assertRaises(ValueError):
                a._parse_map_wireguard(data, {})
        data = sample()
        data['latest-handshakes'] = ''
        with self.assertRaises(ValueError):
            a._parse_map_wireguard(data, {})


if __name__ == '__main__':
    unittest.main()
