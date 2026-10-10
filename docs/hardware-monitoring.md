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
  sampled_at: ISO UTC string|null,  // collection envelope, not all sources' measurement time
  sensors_sampled_at: ISO UTC string|null,
  machine: {
    kind: "physical"|"virtual"|"container"|"unknown",
    vendor: string|null, model: string|null, virtualization: string|null,
    evidence: [short public strings], detected_at: ISO UTC string|null
  },
  physical_inventory: null|{
    board: {vendor: string|null, model: string|null},
    bios: {vendor: string|null, version: string|null},
    memory_modules: null|[{
      slot: string|null, capacity_bytes: integer|null,
      speed_mts: integer|null, configured_speed_mts: integer|null,
      vendor: string|null, part_number: string|null
    }],
    disks: null|[{
      name: string|null, model: string|null, size_bytes: integer|null,
      bus: string|null, rotational: boolean|null
    }]
  },
  cpu: {
    sampled_at: ISO UTC string|null,
    model: string|null,
    physical_cores: integer|null,
    logical_cores: integer|null,
    frequency_mhz: number|null,
    max_frequency_mhz: number|null,
    base_frequency_mhz: number|null,  // historical field name: WMI nominal metadata only
    base_frequency_source: string|null,
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

## Machine labels and physical inventory (every node)

Machine detection is evidence-driven and independent of GPU model, temperature,
CPU frequency, or the presence of sensors. Consumers map `kind` to 真机 / 虚拟机 /
容器 / 未知; an old agent with no `machine` is **unknown**, never physical.
`physical_inventory` is collected/stored only for `kind: physical`; it is null for
virtual/container/unknown nodes. Basic readable CPU/GPU reporting remains enabled
for all types. Pending detection has `detected_at: null`; subsequent detection,
including unknown results, records actual UTC detection time.

Linux checks bounded `systemd-detect-virt --container` and `--vm` separately
(return codes 0 and 1 are normal). `/.dockerenv`, `/run/.containerenv`, and bounded
cgroup marker checks override guest/physical-looking passed-through DMI. Known
VM products in `/sys/class/dmi/id/{sys_vendor,product_name}` are strong VM evidence.
A successful `--container` and `--vm` result of `none` plus a recognized real vendor and non-placeholder
model is required for physical; unavailable/ambiguous evidence stays unknown.
No raw cgroup path, container ID, exception output, serial, UUID or MAC is sent
in machine evidence or the physical inventory.

Linux board/BIOS product fields are read directly from sysfs. DIMM information
uses bounded `dmidecode --type 17` **with existing process permissions only**;
there is no sudo, capability change, or new privilege grant. Missing/unreadable
DIMM information is `memory_modules: null` (unknown), not zero installed RAM.
Disk collection uses `lsblk -d -b -J -o NAME,MODEL,SIZE,TRAN,ROTA`, never partitions
or serials. Unknown per-field metadata is null. Capacity is bytes; reported
memory speed is MT/s (historical dmidecode MHz output is accepted as the reported
numeric rate). Part numbers are product metadata, not a source of measured speed.

Windows uses one UTF-16LE `-EncodedCommand` query, suppresses progress in both
supported preference forms, emits UTF-8, and has one **3-second process budget**
for all CIM branches. `Win32_ComputerSystem` manufacturer/model, known VM products,
and `Win32_Container` / boolean container environment markers determine type.
`HypervisorPresent: true` **alone is not VM evidence**: ASUS/Lenovo/MAXSUN physical
products can host Hyper-V/VBS. Unrecognized manufacturers or missing products
stay unknown. A failing overall PowerShell query returns unknown without exposing
host diagnostics. Board/BIOS/DIMM/disk queries run only for physical-looking
recognized products; Python applies the final physical gate again.

Windows disk `bus` preserves `Win32_DiskDrive.InterfaceType`, for example `SCSI`;
this does **not** prove SATA/NVMe, and rotational remains null when not measured.
Memory `Speed` / `ConfiguredClockSpeed` are reported numeric rates: a MAXSUN16G6400
part number does not convert a reported 4800 MT/s into 6400 MT/s.

All static detection/inventory, Windows CPU CIM metadata, and failures are cached
for **300 seconds**, on the existing single-flight background hardware lane.
They are not re-read with every 30-second dynamic sample. No detection, WMI,
dmidecode or lsblk command runs synchronously on the heartbeat path.

## Collection and heartbeat isolation

- A dedicated daemon scheduler admits at most **one hardware collection**, with
  no pending queue; hardware cannot occupy the task/probe/map scheduler lanes.
- `_os_info()` schedules collection and immediately returns the cached snapshot.
  Initial values are null with `collecting` availability. It never executes
  PowerShell or `nvidia-smi` synchronously on the heartbeat path.
- Refresh admission uses a monotonic clock and a **30-second** minimum interval.
  Actual refresh cadence depends on when the normal report calls `_os_info()`.
- External commands each have a **3-second timeout** and a **128 KiB output cap**,
  using the existing bounded command runner, fixed argv and no shell. Windows
  shares one process deadline across all CIM branches; Linux static commands are
  independently bounded, run only on the worker, and are cached for 300 seconds.
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

`MaxClockSpeed` is WMI nominal metadata, **not a measured base or peak**. Windows
`max_frequency_mhz` is always null. The compatibility field `base_frequency_mhz`
stores positive WMI `MaxClockSpeed` with this visible provenance:

```text
Win32_Processor.MaxClockSpeed (WMI nominal metadata; not measured base/boost)
```

Do not label that field “最高” or “实测基准频率”; label it “WMI 标称频率”. Zero,
negative, boolean and non-finite WMI values become null. A valid
LibreHardwareMonitor dynamic frequency takes precedence over `CurrentClockSpeed`.
The cached WMI fallback carries its actual query time and is hidden after 120
seconds, even while the static inventory remains cached for 300 seconds.
The legacy `cpu_model` also picks up the asynchronously collected Windows model.

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
unreadable and timezone-naive files are ignored with specific public reasons:
`sensors_file_missing`, `sensors_file_permission_denied`, `sensors_file_stale`,
`sensors_file_invalid`, or fallback `sensors_file_unavailable`. Invalid/non-finite
CPU readings are ignored; invalid sensor entries (including numeric strings/
booleans and kind/unit mismatches) are skipped. Names are limited to 128
characters. A valid file without CPU temperature leaves CPU temperature
unavailable; WMI frequency can still work.

`hardware.sampled_at` is the collection envelope timestamp, **not** proof every
measurement was just taken. LHM supplies `cpu.sampled_at` and
`sensors_sampled_at` from its validated JSON sample, normalized to UTC. A sample
119 seconds old stays 119 seconds old even under a new envelope. Source-age
checks run on every cache read without I/O; values over 120 seconds are cleared
and their original timestamp is retained, not advanced. A pending/failed/stale
empty snapshot uses `sampled_at: null`, `cpu.sampled_at: null`, and
`sensors_sampled_at: null`. Cached machine/physical metadata can survive a failed
dynamic sample independently; `machine.detected_at` is not a sensor timestamp.
The producer should use atomic file replacement and refresh more often than
120 seconds. Consumers must use the source timestamps for CPU/board freshness.

## NVIDIA GPU inventory (Linux and Windows)

`nvidia-smi` is discovered through PATH. One CSV query enumerates **all GPUs**,
using UUID as ID, not just GPU 0. The query requests temperature, graphics and
memory clocks, utilisation, memory used/total, power and fan speed. Values use
MHz, MiB, watts and percent; source is `nvidia-smi`. `N/A`, unsupported and
non-finite numeric cells are null. Invalid CSV/failing commands discard the
GPU batch, without discarding CPU/board data. No AMD/Intel GPU collector is
implemented; missing `nvidia-smi` must not be interpreted as proof of no GPU.

Availability values:

- CPU: `available`, `unavailable`, `sensors_file_missing`,
  `sensors_file_permission_denied`, `sensors_file_invalid`, `sensors_file_stale`,
  `sensors_file_unavailable`.
- GPU: `available`, `nvidia_smi_missing`, `no_nvidia_gpu`, `nvidia_smi_failed`.
- Both during scheduler lifecycle: `collecting`, `collection_failed`, `stale`.

Consumers must also check `sampled_at` age for disconnected nodes or queued
reports. Availability means the source worked, not that every optional cell is
supported. CPU maximum frequency retains its platform-specific provenance.

## Offline verification

New tests live in `tests_isolated/test_hardware_agent.py`,
`tests_isolated/test_machine_agent.py`, and
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
  -c /dev/null --noconftest \
  --basetemp=/root/.hermes/cache/scratch/hardware-backend/pytest \
  tests_isolated/test_machine_agent.py \
  tests_isolated/test_hardware_agent.py \
  tests_isolated/test_hardware_repository.py -q
```

RED/GREEN and regression outputs are retained under
`/root/.hermes/cache/scratch/hardware-backend/`. These tests validate collection,
null/source semantics, bounded background scheduling and repository assignment;
they do not claim physical Windows driver, production PostgreSQL or deployment
validation. Existing tests with hard-coded Agent 0.6.10/update-to-0.6.11
expectations need their fixtures advanced separately when the release lands.
