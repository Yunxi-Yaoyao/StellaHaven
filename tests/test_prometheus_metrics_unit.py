"""No application/conftest import or database: run with unittest discovery."""
import importlib.util
import json
from pathlib import Path
import unittest
import httpx

spec = importlib.util.spec_from_file_location('prometheus_pilot', Path(__file__).resolve().parents[1] / 'app/services/prometheus_metrics.py')
assert spec and spec.loader
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


class PrometheusPilotTests(unittest.TestCase):
    def client(self, handler, targets=None, now=1010):
        return pilot.PrometheusMetrics('http://prom.test', allowed_targets=targets or {('job', 'host:9100')}, transport=httpx.MockTransport(handler), clock=lambda: now)

    def response(self, q, rows):
        return httpx.Response(200, json={'status': 'success', 'data': {'resultType': 'matrix' if q.endswith('[5m]') else 'vector', 'result': rows}})

    def test_snapshot_transforms(self):
        def respond(request):
            q = request.url.params['query']
            label = {'mountpoint': '/', 'device': 'eth0', 'fstype': 'ext4'}
            values = {'node_cpu_seconds_total': .8, 'node_memory_MemAvailable_bytes': 25,
                      'node_memory_MemTotal_bytes': 100, 'node_filesystem_size_bytes': 1000,
                      'node_filesystem_free_bytes': 400, 'node_network_receive_bytes_total': 123456789,
                      'node_network_transmit_bytes_total': 987654321, 'up': 1}
            value = next(v for k, v in values.items() if q.startswith(k) or q.startswith('rate('+k))
            if q.startswith('rate(node_network'): value = 12
            row = {'metric': label, 'values': [[1000, str(value)]]} if q.endswith('[5m]') else {'metric': label, 'value': [1010, str(value)]}
            return self.response(q, [row])
        with self.client(respond) as p:
            s = p.snapshot('job', 'host:9100')
        self.assertAlmostEqual(s['cpuPct']['value'], 20)
        self.assertEqual(s['memoryPct']['value'], 75)
        self.assertEqual(s['filesystems'][0]['usedPct']['value'], 60)
        self.assertEqual(s['networks'][0]['receiveBytes']['value'], 123456789)
        self.assertEqual(s['networks'][0]['receiveBytesPerSecond']['value'], 12)
        self.assertEqual(s['freshness'], 'up')
        self.assertEqual(s['scrapeUp']['sampleTimestamp'], 1000)

    def test_empty_down_stale(self):
        for value, ts, expected in [(None, 1000, 'no_sample'), ('0', 1000, 'down'), ('1', 900, 'stale')]:
            def respond(request):
                q = request.url.params['query']
                rows = [{'metric': {}, 'values': [[ts, value]]}] if q.startswith('up{') and value is not None else []
                return self.response(q, rows)
            with self.client(respond) as p:
                snapshot = p.snapshot('job', 'host:9100')
                self.assertEqual(snapshot['freshness'], expected)
                self.assertIsNone(snapshot['cpuPct']['value'])
                self.assertIsNone(snapshot['memoryPct']['value'])

    def test_bounds_mapping_and_escaping(self):
        with self.client(lambda r: self.fail('invalid request reached HTTP'), now=4000000) as p:
            for start, end, step in [(0, 100, 4), (10, 1, 5), (0, 4000001, 5), (float('nan'), 100, 5), (0, 32*86400, 3600), (0, 60000, 5)]:
                with self.assertRaises(ValueError):
                    p.query_range('scrapeUp', 'job', 'host:9100', start=start, end=end, step=step)
            with self.assertRaises(ValueError): p.snapshot('other', 'host:9100')
            with self.assertRaises(ValueError): p.query_range('arbitrary_promql', 'job', 'host:9100', start=0, end=100, step=5)
        job = 'a"\\\nb'
        with self.client(lambda r: None, targets={(job, 'i')}) as p:
            self.assertIn('job='+json.dumps(job), p._expression('scrapeUp', job, 'i'))

    def test_range_nulls_spacing_and_errors(self):
        def respond(request):
            return httpx.Response(200, json={'status': 'success', 'data': {'resultType': 'matrix', 'result': [{'metric': {'device': 'eth0'}, 'values': [[975, '1'], [990, 'NaN'], [1005, '3']]}]}})
        with self.client(respond) as p:
            r = p.query_range('receiveBytes', 'job', 'host:9100', start=975, end=1005, step=15)
            self.assertEqual(r['series'][0]['values'], [[975, 1], [990, None], [1005, 3]])
            self.assertEqual(p.sample_spacing('job', 'host:9100')['spacingSeconds'], [15, 15])
        for response in [httpx.Response(503), httpx.Response(200, json={'status': 'error'}), httpx.Response(200, text='not json')]:
            with self.client(lambda r: response) as p:
                with self.assertRaises(pilot.PrometheusError): p.snapshot('job', 'host:9100')


if __name__ == '__main__':
    unittest.main()
