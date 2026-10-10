# Hardware monitoring (Agent 0.6.11)

## Transport and persistence

Agent adds `os_info.hardware` to its existing `/agent/report` payload. The repository
stores that value at `nodes.sys_info.hardware` (existing JSONB column), alongside
`kernel`, `cpu_model`, `cpu_cores`, `load1`, `load5`, `load15`, and `boot_time`.
No schema migration, endpoint, new dependency, or hardware history table is needed.
A legacy report without `hardware` writes `hardware: null`, rather than preserving
old measurements under a new heartbeat. Reports without `os_info` do not replace
`sys_info`. The hardware snapshot is latest-state information, not a time series.

## Contract

```text
hardware = {
  sampled_at: ISO UTC string,
  cpu: {
    model: string|null,
    physical_cores: integer|null,
    logical_cores: integer|null,
    frequency_mhz: number|null,
    max_frequency_mhz: number|null,
    temperature_c: number|null,
    temperature_source: string|null,
    frequency_source: string|null
  },
  gpus: [{
    id: string, name: string,
    temperature_c: number|null,
    graphics_clock_mhz: number|null,
    memory_clock_mhz: number|null,
    utilization_pct: number|null,
    memory_used_mib: number|null,
    memory_total_mib: number|null,
    power_w: number|null,
    fan_pct: number|null,
    source: string
  }],
  sensors: [{
    name: string,
    kind: "temperature"|"fan",
    value: finite number,
    unit: "°C"|"RPM",
    source: string
  }],
  availability: {cpu_temperature: string, gpu: string}
}
```

Missing/unsupported readings are null, **not zero**. A genuine sensor reading of
zero remains zero. Non-finite readings (`NaN`, infinity) never enter the outgoing
JSON. Unknown hardware does not suppress legacy OS/load/system reports.

## Collection and heartbeat isolation

- A dedicated daemon scheduler admits at most **one hardware collection**, with
  no pending queue; hardware cannot occupy the task/probe/map scheduler lanes.
- `_os_info()` schedules collection and immediately returns the cached snapshot.
  Initial values are null with `collecting` availability. It never executes
  PowerShell or `nvidia-smi` synchronously on the heartbeat path.
- Refresh admission uses a monotonic clock and a **30-second** minimum interval.
  Actual refresh cadence depends on when the normal report calls `_os_info()`.
- Both external commands have a **3-second timeout** and a **128 KiB output cap**,
  using the existing bounded command runner, fixed argv and no shell.
- Worker/admission exceptions become a null-valued `collection_failed` snapshot.
  A cache older than 120 seconds is hidden behind a null-valued `stale` snapshot.
  The original measurement timestamp is not refreshed on ordinary cache hits.
- Run-loop shutdown closes the hardware lane. Closing refuses new work; an
  already-running daemon worker is not forcibly interrupted. Native psutil/file
  operations have no portable hard cancellation, but cannot block heartbeat or
  spawn additional hardware workers.

## Linux

Requires psutil for CPU frequency/core inventory and board sensors. Frequency
comes from `psutil.cpu_freq()` and is labelled `psutil.cpu_freq`; nonpositive
frequency/max-frequency sentinels are null. This is a psutil/sysfs reading, not
an assurance of per-core instantaneous boost measurement.

Temperature/fan inventory uses `sensors_temperatures()` and `sensors_fans()`.
The CPU summary is the maximum finite reading from `coretemp`, `k10temp`,
`zenpower`, or explicitly CPU-labelled sensors. ACPI drivers are **never** used
for the CPU summary, even when their label contains CPU. They may remain in the
all-sensors inventory. Sources are `psutil:<driver>`.

## Windows CPU and sensor file

CPU model and core inventory come from a bounded, UTF-16LE `-EncodedCommand`
PowerShell query of `Win32_Processor`. Multiple processor packages have their
core counts summed and model names deduplicated. CPU frequency fallback is the
first processor's `CurrentClockSpeed`, explicitly labelled:

```text
Win32_Processor.CurrentClockSpeed (WMI; not measured boost)
```

`MaxClockSpeed` is WMI metadata, not a measured peak. WMI fallback must not be
presented as live boost. A valid LibreHardwareMonitor dynamic frequency takes
precedence. The legacy `cpu_model` field also picks up the asynchronously
collected Windows model on subsequent reports.

An external, separately deployed LibreHardwareMonitor producer writes:

```text
C:/stella-agent/hardware-sensors.json
```

Override with the **agent process environment variable**
`STELLA_HARDWARE_SENSORS_FILE`. This change does not install or start the producer.
The input is UTF-8 (BOM accepted), with this contract:

```text
{
  sampled_at: ISO timestamp with timezone (UTC recommended),
  cpu_temperature_c: finite number|null,
  cpu_frequency_mhz: finite number|null,
  cpu_temperature_source?: string,
  cpu_frequency_source?: string,
  sensors: [{name, kind, value, unit, source}]
}
```

The optional sources are preserved (maximum 256 characters), defaulting to
`LibreHardwareMonitor`. For example, a producer can label CPU temperature as
`LibreHardwareMonitor:Core (Tctl/Tdie)` and dynamic frequency as
`LibreHardwareMonitor:Cores (Average)`.

Only regular files at most **128 KiB** are accepted; reads are capped too. Both
file mtime and `sampled_at` must be within **120 seconds** of now; more than
30 seconds in the future is rejected. Missing, stale, malformed, oversized,
unreadable and timezone-naive files are ignored with
`sensors_file_unavailable`. Invalid/non-finite CPU readings are ignored; invalid
sensor entries (including numeric strings/booleans and kind/unit mismatches)
are skipped. Names are limited to 128 characters. A valid file without CPU
temperature leaves CPU temperature unavailable; WMI frequency can still work.
The producer should use atomic file replacement and refresh more often than
120 seconds. A file can become stale between cache refreshes; the agent only
checks it during collection, so displayed data can lag by one cache interval.

## NVIDIA GPU inventory (Linux and Windows)

`nvidia-smi` is discovered through PATH. One CSV query enumerates **all GPUs**,
using UUID as ID, not just GPU 0. The query requests temperature, graphics and
memory clocks, utilisation, memory used/total, power and fan speed. Values use
MHz, MiB, watts and percent; source is `nvidia-smi`. `N/A`, unsupported and
non-finite numeric cells are null. Invalid CSV/failing commands discard the
GPU batch, without discarding CPU/board data. No AMD/Intel GPU collector is
implemented; missing `nvidia-smi` must not be interpreted as proof of no GPU.

Availability values:

- CPU: `available`, `unavailable`, `sensors_file_unavailable`.
- GPU: `available`, `nvidia_smi_missing`, `no_nvidia_gpu`, `nvidia_smi_failed`.
- Both during scheduler lifecycle: `collecting`, `collection_failed`, `stale`.

Consumers must also check `sampled_at` age for disconnected nodes or queued
reports. Availability means the source worked, not that every optional cell is
supported. CPU maximum frequency retains its platform-specific provenance.

## Offline verification

New tests live in `tests_isolated/test_hardware_agent.py` and
`tests_isolated/test_hardware_repository.py`. They replace external I/O and do
not import the app's database module. Repository tests execute the real
heartbeat function isolated from database bootstrap. Do **not** run the main
`tests/conftest.py` fixture against production.

```sh
env -i PATH=/usr/bin:/bin \
  HOME=/root/.hermes/cache/scratch/hardware-backend \
  TMPDIR=/root/.hermes/cache/scratch \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  /opt/Yunxi-workstation/Stella/.venv/bin/python -m pytest \
  -c /dev/null --confcutdir=tests_isolated \
  tests_isolated/test_hardware_agent.py \
  tests_isolated/test_hardware_repository.py -q
```

RED/GREEN and regression outputs are retained under
`/root/.hermes/cache/scratch/hardware-backend/`. These tests validate collection,
null/source semantics, bounded background scheduling and repository assignment;
they do not claim physical Windows driver, production PostgreSQL or deployment
validation. Existing tests with hard-coded Agent 0.6.10/update-to-0.6.11
expectations need their fixtures advanced separately when the release lands.
