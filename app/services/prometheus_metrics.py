"""Opt-in read-only Prometheus pilot. No settings, routers, DB or import-time I/O."""
import json
import math
import time
from urllib.parse import urlsplit

import httpx


class PrometheusError(RuntimeError):
    pass


class PrometheusMetrics:
    METRICS = {
        'cpuIdleRate': ('node_cpu_seconds_total', True),
        'memoryAvailable': ('node_memory_MemAvailable_bytes', False),
        'memoryTotal': ('node_memory_MemTotal_bytes', False),
        'filesystemSize': ('node_filesystem_size_bytes', False),
        'filesystemFree': ('node_filesystem_free_bytes', False),
        'receiveBytes': ('node_network_receive_bytes_total', False),
        'transmitBytes': ('node_network_transmit_bytes_total', False),
        'receiveBytesPerSecond': ('node_network_receive_bytes_total', True),
        'transmitBytesPerSecond': ('node_network_transmit_bytes_total', True),
        'scrapeUp': ('up', False),
    }
    MAX_BYTES = 8 * 1024 * 1024
    MAX_SERIES = 256

    def __init__(self, base_url, *, allowed_targets, transport=None, clock=time.time, stale_after=60):
        u = urlsplit(base_url)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError('Admin-configured HTTP(S) URL required; no credentials/query/fragment')
        if not math.isfinite(stale_after) or stale_after <= 0:
            raise ValueError('Invalid freshness threshold')
        self.targets = frozenset(allowed_targets)
        if not self.targets or any(not isinstance(t, tuple) or len(t) != 2 or any(not isinstance(x, str) or not x or len(x) > 512 for x in t) for t in self.targets):
            raise ValueError('Explicit (job, instance) target mapping required')
        self.clock, self.stale_after = clock, stale_after
        self.client = httpx.Client(base_url=base_url.rstrip('/')+'/', timeout=httpx.Timeout(5, connect=2),
                                   limits=httpx.Limits(max_connections=2), follow_redirects=False,
                                   trust_env=False, transport=transport)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def _expression(self, metric, job, instance):
        if (job, instance) not in self.targets:
            raise ValueError('Target not mapped by administrator')
        if metric not in self.METRICS:
            raise ValueError('Unsupported metric')
        name, rate = self.METRICS[metric]
        labels = 'job='+json.dumps(job)+',instance='+json.dumps(instance)
        if metric == 'cpuIdleRate':
            labels += ',mode="idle"'
        expression = name+'{'+labels+'}'
        return 'rate('+expression+'[1m])' if rate else expression

    def _request(self, endpoint, params, result_type):
        try:
            with self.client.stream('GET', 'api/v1/'+endpoint, params={**params, 'timeout': '3s'}) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self.MAX_BYTES:
                        raise PrometheusError('Prometheus response exceeds byte budget')
            payload = json.loads(body)
            if payload.get('status') != 'success' or payload.get('warnings'):
                raise PrometheusError('Prometheus query failed or returned partial warnings')
            data = payload['data']
            if data['resultType'] != result_type or not isinstance(data['result'], list):
                raise PrometheusError('Unexpected Prometheus result')
            if len(data['result']) > self.MAX_SERIES:
                raise PrometheusError('Prometheus series budget exceeded')
            return data['result']
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise PrometheusError('Prometheus request or response failed') from None

    @staticmethod
    def _number(value):
        try:
            value = float(value)
            return value if math.isfinite(value) else None
        except (TypeError, ValueError):
            return None

    def _point(self, value, timestamp, *, evaluation=False, sample_timestamp=None):
        return {'value': self._number(value), 'timestamp': timestamp,
                'sampleTimestamp': sample_timestamp if evaluation else timestamp,
                'timestampKind': 'evaluation' if evaluation else 'sample', 'source': 'prometheus'}

    def snapshot(self, job, instance):
        now = self.clock()
        vectors = {}
        for key, (_, is_rate) in self.METRICS.items():
            expression = self._expression(key, job, instance)
            # Instant vector timestamps are evaluation times, even for raw metrics.
            # A range selector preserves actual scrape timestamps (and reveals stale data).
            rows = self._request('query', {'query': expression if is_rate else expression+'[5m]', 'time': now}, 'vector' if is_rate else 'matrix')
            vectors[key] = rows if is_rate else [{'metric': r['metric'], 'value': r['values'][-1]} for r in rows if r['values']]
        def scalar(key):
            rows = vectors[key]
            return rows[0]['value'] if len(rows) == 1 else (None, None)
        up_ts, up = scalar('scrapeUp')
        up = self._number(up)
        freshness = 'no_sample' if up is None or up_ts is None else ('stale' if now-float(up_ts) > self.stale_after else ('up' if up == 1 else 'down'))
        def ratio(a, b):
            a, b = self._number(a), self._number(b)
            return None if a is None or b is None or b <= 0 else 100*(b-a)/b
        idle = [self._number(row['value'][1]) for row in vectors['cpuIdleRate']]
        cpu = 100*(1-sum(idle)/len(idle)) if idle and all(v is not None for v in idle) else None
        available_ts, available = scalar('memoryAvailable')
        total_ts, total = scalar('memoryTotal')
        result = {'source': 'prometheus', 'job': job, 'instance': instance, 'evaluatedAt': now,
                  'freshness': freshness, 'scrapeUp': self._point(up, up_ts),
                  'cpuPct': self._point(cpu, now, evaluation=True, sample_timestamp=up_ts),
                  'memoryPct': self._point(ratio(available, total), min(available_ts, total_ts) if available_ts is not None and total_ts is not None else None),
                  'filesystems': [], 'networks': []}
        def indexed(key, labels):
            return {tuple(row['metric'].get(k, '') for k in labels): row['value'] for row in vectors[key]}
        sizes = indexed('filesystemSize', ('mountpoint', 'device', 'fstype'))
        frees = indexed('filesystemFree', ('mountpoint', 'device', 'fstype'))
        for labels in sorted(sizes.keys() | frees.keys()):
            ts, size = sizes.get(labels, (None, None))
            free_ts, free = frees.get(labels, (None, None))
            result['filesystems'].append(dict(zip(('mountpoint', 'device', 'fstype'), labels),
                sizeBytes=self._point(size, ts), freeBytes=self._point(free, free_ts),
                usedPct=self._point(ratio(free, size), min(ts, free_ts) if ts is not None and free_ts is not None else None)))
        keys = ('receiveBytes', 'transmitBytes', 'receiveBytesPerSecond', 'transmitBytesPerSecond')
        nets = {key: indexed(key, ('device',)) for key in keys}
        for device in sorted(set().union(*(v.keys() for v in nets.values()))):
            row = {'device': device[0]}
            for key in keys:
                ts, value = nets[key].get(device, (None, None))
                row[key] = self._point(value, ts, evaluation=key.endswith('PerSecond'), sample_timestamp=up_ts)
            result['networks'].append(row)
        return result

    def query_range(self, metric, job, instance, *, start, end, step):
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end, step)):
            raise ValueError('Finite numeric range required')
        if start < 0 or end < start or end > self.clock() or end-start > 31*86400 or step < 5 or math.floor((end-start)/step)+1 > 12000:
            raise ValueError('Range exceeds bounds: 31 days, step >=5s, <=12000 points, no future')
        rows = self._request('query_range', {'query': self._expression(metric, job, instance), 'start': start, 'end': end, 'step': step}, 'matrix')
        if sum(len(row['values']) for row in rows) > 12000:
            raise PrometheusError('Aggregate point budget exceeded')
        return {'source': 'prometheus', 'metric': metric, 'stepSeconds': step,
                'timestampKind': 'evaluation', 'series': [{'labels': row['metric'], 'values': [[ts, self._number(v)] for ts, v in row['values']]} for row in rows]}

    def sample_spacing(self, job, instance):
        """Raw 5-minute up samples, NOT query_range evaluation-grid timestamps."""
        expression = self._expression('scrapeUp', job, instance)+'[5m]'
        rows = self._request('query', {'query': expression, 'time': self.clock()}, 'matrix')
        timestamps = [float(p[0]) for p in rows[0]['values']] if len(rows) == 1 else []
        return {'source': 'prometheus', 'sampleTimestamps': timestamps,
                'spacingSeconds': [b-a for a, b in zip(timestamps, timestamps[1:])]}
