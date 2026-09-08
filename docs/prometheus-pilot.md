# Prometheus read-only pilot (not a production switch)

Only the standalone adapter and isolated tests are added. No router, source default,
DB, node agent, Prometheus configuration or production deployment is changed.
There is no default endpoint or import-time connection. An administrator must supply
the HTTP(S) base URL and an explicit allowlist of `(job, instance)` pairs; future
node-ID mapping belongs in authenticated server configuration, never browser PromQL.
Private endpoint values belong only in the internal pilot artifact/harness.

## Interface and semantics

`PrometheusMetrics(base_url, allowed_targets={(job, instance)})` is a synchronous
context manager; call `snapshot(job, instance)` outside the async event loop (or
use a worker thread in future integration). `query_range(metric, job, instance,
start=..., end=..., step=...)` accepts only adapter metric names, not arbitrary
queries. Selectors escape exact labels using `json.dumps`.

- CPU: `100 * (1 - mean(rate(node_cpu_seconds_total{mode="idle"}[1m])))`.
- Memory: `(MemTotal - MemAvailable) / MemTotal * 100`.
- Filesystems retain mountpoint, device and fstype; used is `(size-free)/size`,
  **not** `(size-avail)/size`. No implicit pseudo-filesystem filtering.
- Networks preserve all device names; counters are bytes, rates bytes/second via
  `rate(...[1m])`, not MB or bits/s. Prometheus handles counter resets in rates.
- Empty/nonfinite/zero-denominator data is null or an empty series, never zero.
- Points carry source, timestamp and sampleTimestamp. Raw values use latest raw
  samples from a five-minute range selector: instant-vector timestamps alone are
  evaluation timestamps and must NOT be presented as scrape timestamps.
  Rates carry evaluation timestamps; their sampleTimestamp is the latest target
  `up` scrape timestamp (a target-level proxy, not an independent rate sample).
- Target freshness: `up`, `down`, `no_sample`, or `stale` (default >60 seconds).
  Old metric samples may remain visible while down/stale; consumers must honor
  freshness rather than treating a non-null historical value as current health.
  Missing metric data stays null even if target `up` is 1.

## Bounds and failure behavior

Read-only GET `/api/v1/query` and `/api/v1/query_range`; no redirects, environment
proxy inheritance, credentials embedded in URLs, or arbitrary query input.
Connect timeout 2s, I/O timeout 5s, Prom query timeout 3s; no retries. At most 256
series and 8 MiB decoded response per request. Ranges require finite epoch seconds,
nonnegative start, ordered start/end, no future end, at most 31 days, step >=5s,
and <=12000 grid points; results additionally enforce <=12000 aggregate points.
HTTP/API/partial-warning errors raise a sanitized `PrometheusError`, not zero data.
This is an opt-in trusted-admin upstream, not a general-purpose URL proxy.

## Isolated verification (no DB or authentication suite)

```sh
python3 -m unittest discover -s tests -p test_prometheus_metrics_unit.py
```

Tests load the adapter by file path to avoid `app.services.__init__` importing DB
services. They use `httpx.MockTransport`, checking real transformations, missing
samples, down/stale states, escaping, bounds, range nulls, errors and raw spacing.
Do not run the repository's DB-backed conftest for this pilot.

## Real pilot evidence

Internal artifact: `/root/.hermes/workspace/stella-prometheus-pilot.json`.
It contains a real snapshot, raw `up{job=...,instance=...}[5m]` scrape timestamps,
spacing deltas, and a bounded network-rate range from the approved LAN Prometheus.
The harness explicitly instantiates the adapter; it is not wired into Stella.

Observed scrape spacing is **15 seconds**. This improves on the old system
sampling interval of 60 seconds, but does **not** match the old traffic interval
of 5 seconds. A 5-second query step merely reevaluates/interpolates a 15-second
source; it cannot manufacture 5-second measurements. One-minute rates also smooth
short spikes. Keep the old traffic source until matching granularity is explicitly
approved or a separate scrape-interval change is authorized. Retention and
historical coverage are not inferred from this five-minute pilot.
