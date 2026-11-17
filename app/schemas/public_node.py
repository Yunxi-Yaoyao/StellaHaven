"""Read-only public telemetry projection; never used for agent ingestion.

Missing stays missing, explicit null/invalid scalars become null (not zero).
Source/state/timestamps are retained, not refreshed or inferred. The extension
slot is legacy telemetry, NOT an arbitrary agent envelope or credential store.
"""
from functools import lru_cache
import math
from typing import Annotated, Literal, get_args, get_origin
from pydantic import (BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictInt,
                      StrictStr, TypeAdapter, ValidationError, model_serializer,
                      model_validator)

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Integer = StrictInt
Text = StrictStr
Flag = StrictBool

# Explicit key-based removal only; opaque free-text cannot be proven secret-free.
_PRIVATE_KEYS = frozenset({'token', 'agenttoken', 'accesstoken', 'refreshtoken',
    'password', 'passwd', 'secret', 'clientsecret', 'apikey', 'authorization',
    'credentials', 'command', 'commands', 'cmd', 'installcommand', 'privatekey',
    'sshprivatekey', 'sshpassword', 'serial', 'serialnumber', 'uuid', 'mac', 'macaddress'})


def _private_key(key):
    # Compact spelling covers snake/kebab/camel case without rewriting keys.
    compact = ''.join(char for char in key.lower() if char.isalnum())
    return compact in _PRIVATE_KEYS or compact.endswith(('token', 'password', 'secret', 'privatekey'))


def safe_legacy_json(value):
    """Finite JSON only, dropping credential/identity keys at every object level."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [safe_legacy_json(v) for v in value]
    if isinstance(value, dict):
        return {k: safe_legacy_json(v) for k, v in value.items()
                if isinstance(k, str) and not _private_key(k)}
    return None


@lru_cache(maxsize=None)
def _adapter(annotation):
    return TypeAdapter(annotation)


class PublicRecord(BaseModel):
    """Nullable typed known fields, no coercion; unknown fields are discarded.

    This is a read projection, not a claim that historical JSONB was valid.
    Nested serialization omits absent fields for compatibility with old agents.
    """
    model_config = ConfigDict(extra='ignore', populate_by_name=True)

    @model_validator(mode='before')
    @classmethod
    def project(cls, value):
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            return value
        out = {}
        for name, field in cls.model_fields.items():
            key = field.alias if field.alias in value else name
            if key not in value:
                continue
            annotation = Annotated[field.annotation, *field.metadata] if field.metadata else field.annotation
            try:
                out[key] = _adapter(annotation).validate_python(value[key], strict=True)
            except (ValidationError, ValueError, TypeError):
                out[key] = repair_record_collection(annotation, value[key])
        return out

    @model_serializer(mode='wrap')
    def serialize_present(self, handler):
        data = handler(self)
        present = self.model_fields_set | {
            self.__class__.model_fields[name].alias for name in self.model_fields_set}
        return {k: v for k, v in data.items() if k in present}


class Interface(PublicRecord):
    is_default: Flag | None = None
    up: Flag | None = None
    is_physical: Flag | None = None
    docker: Flag | None = None
    ip: Text | None = None


class Component(PublicRecord):
    installed: Flag | None = None
    version: Text | None = None


class DockerComponent(Component):
    running: Flag | None = None


class UfwComponent(Component):
    active: Flag | None = None


class FirewallComponent(PublicRecord):
    ufw: UfwComponent | None = None
    iptables: Component | None = None


class MonitoringCapability(PublicRecord):
    ready: Flag | None = None
    types: list[Literal['tcp','ping']] | None = None
    scope: Literal['container','host'] | None = None
    targets: list[Text] | None = None
    approved_ranges: list[Text] | None = None


class Components(PublicRecord):
    monitoring: MonitoringCapability | None = None
    iperf3: Flag | Component | None = None
    speedtest: Flag | Component | None = None
    mtr: Flag | Component | None = None
    docker: Flag | DockerComponent | None = None
    firewall: FirewallComponent | None = None


class Machine(PublicRecord):
    kind: Literal['physical', 'virtual', 'container', 'unknown'] | None = None
    vendor: Text | None = None
    model: Text | None = None
    virtualization: Text | None = None
    evidence: list[Text] | None = None
    detected_at: Text | None = None


class Board(PublicRecord):
    vendor: Text | None = None
    model: Text | None = None


class Bios(PublicRecord):
    vendor: Text | None = None
    version: Text | None = None


class MemoryModule(PublicRecord):
    slot: Text | None = None
    capacity_bytes: Integer | None = None
    speed_mts: Integer | None = None
    configured_speed_mts: Integer | None = None
    vendor: Text | None = None
    part_number: Text | None = None


class InventoryDisk(PublicRecord):
    name: Text | None = None
    model: Text | None = None
    size_bytes: Integer | None = None
    bus: Text | None = None
    rotational: Flag | None = None


class PhysicalInventory(PublicRecord):
    board: Board | None = None
    bios: Bios | None = None
    memory_modules: list[MemoryModule] | None = None
    disks: list[InventoryDisk] | None = None


class PlatformInventory(PhysicalInventory):
    source: Text | None = None
    scope: Text | None = None
    state: Text | None = None
    sampled_at: Text | None = None


class MemorySample(PublicRecord):
    total_bytes: Integer | None = None
    available_bytes: Integer | None = None
    used_bytes: Integer | None = None
    source: Text | None = None
    scope: Text | None = None
    state: Text | None = None
    sampled_at: Text | None = None
    attempted_at: Text | None = None


class SystemMemory(MemorySample):
    cgroup: MemorySample | None = None


class LegacyTelemetry(PublicRecord):
    legacy_extensions: dict[str, JsonValue] | None = Field(default=None,
        description='Legacy telemetry extensions, finite JSON with private keys removed; no inferred units or provenance.')

    @model_validator(mode='before')
    @classmethod
    def preserve_legacy(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        extra = {k: v for k, v in value.items() if k not in cls.model_fields}
        existing = value.get('legacy_extensions')
        if isinstance(existing, dict):
            extra = {**existing, **extra}
        if extra:
            value['legacy_extensions'] = safe_legacy_json(extra)
        return value


class Cpu(LegacyTelemetry):
    model: Text | None = None
    physical_cores: Integer | None = None
    logical_cores: Integer | None = None
    frequency_mhz: Number | None = None
    max_frequency_mhz: Number | None = None
    base_frequency_mhz: Number | None = None
    base_frequency_source: Text | None = None
    temperature_c: Number | None = None
    temperature_source: Text | None = None
    frequency_source: Text | None = None
    sampled_at: Text | None = None


class Gpu(LegacyTelemetry):
    id: Text | None = None
    name: Text | None = None
    vendor: Text | None = None
    kind: Text | None = None
    source: Text | None = None
    telemetry_status: Text | None = None
    pci_bus: Text | None = None
    sampled_at: Text | None = None
    temperature_c: Number | None = None
    graphics_clock_mhz: Number | None = None
    memory_clock_mhz: Number | None = None
    utilization_pct: Number | None = None
    memory_used_mib: Number | None = None
    memory_total_mib: Number | None = None
    power_w: Number | None = None
    fan_pct: Number | None = None


class Sensor(LegacyTelemetry):
    name: Text | None = None
    kind: Text | None = None
    value: Number | None = None
    unit: Text | None = None
    source: Text | None = None
    scope: Text | None = None


class Availability(PublicRecord):
    cpu_temperature: Text | None = None
    gpu_presence: Text | None = None
    gpu: Text | None = None
    gpu_query: Text | None = None


class Hardware(LegacyTelemetry):
    sampled_at: Text | None = None
    sensors_sampled_at: Text | None = None
    machine: Machine | None = None
    physical_inventory: PhysicalInventory | None = None
    platform_inventory: PlatformInventory | None = None
    memory: SystemMemory | None = None
    cpu: Cpu | None = None
    gpus: list[Gpu] | None = None
    sensors: list[Sensor] | None = None
    availability: Availability | None = None
    @model_validator(mode='before')
    @classmethod
    def scope_inventory(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        machine = value.get('machine')
        physical = isinstance(machine, dict) and machine.get('kind') == 'physical'
        if not physical and 'physical_inventory' in value:
            value['physical_inventory'] = None
        platform = value.get('platform_inventory')
        if isinstance(platform, dict):
            # Source-scoped board/BIOS are not DIMM/disk inventory, even when
            # the host happens to be physical. Do not promote inherited DMI.
            if not isinstance(platform.get('source'), str) or not platform['source'] or platform.get('scope') not in ('host_visible', 'platform_reported'):
                value['platform_inventory'] = None
            else:
                platform = dict(platform)
                for field in ('memory_modules', 'disks'):
                    if field in platform:
                        platform[field] = None
                value['platform_inventory'] = platform
        return value


class Storage(PublicRecord):
    device: Text | None = None
    mount: Text | None = None
    fstype: Text | None = None
    kind: Text | None = None
    total: Integer | None = None
    used: Integer | None = None
    percent: Number | None = None
    model: Text | None = None
    bus: Text | None = None
    volume_mounts: list[Text] | None = None
    pool_mounts: list[Text] | None = None
    usage_scope: Text | None = None
    sampled_at: Text | None = None


class StorageStatus(PublicRecord):
    state: Text | None = None
    sampled_at: Text | None = None
    attempted_at: Text | None = None


class SystemInfo(PublicRecord):
    os_name: Text | None = None
    kernel: Text | None = None
    arch: Text | None = None
    cpu_model: Text | None = None
    cpu_cores: Integer | None = None
    cpu_logical_cores: Integer | None = None
    load1: Number | None = None
    load5: Number | None = None
    load15: Number | None = None
    boot_time: Number | None = None
    hardware: Hardware | None = None
    storage_status: StorageStatus | None = None


def project_optional(annotation, value):
    """Malformed whole slots become unknown; valid empty containers stay empty."""
    try:
        return _adapter(annotation).validate_python(value, strict=True)
    except (ValidationError, ValueError, TypeError):
        return repair_record_collection(annotation, value)


def repair_record_collection(annotation, value):
    """A corrupt row must not erase valid neighboring hardware or hop rows.

    Invalid record entries become empty/unknown records. Never shift indices,
    coerce scalar measurements or fabricate zero. Non-record arrays still fail
    as a whole, e.g. a string array with a numeric element is unknown.
    """
    args = get_args(annotation)
    if type(None) in args:
        remaining = [arg for arg in args if arg is not type(None)]
        if len(remaining) == 1:
            return repair_record_collection(remaining[0], value)
    origin = get_origin(annotation)
    row_type = args[0] if origin is list else args[1] if origin is dict else None
    if not isinstance(row_type, type) or not issubclass(row_type, PublicRecord):
        return None
    def row(item):
        try:
            return _adapter(row_type).validate_python(item, strict=True)
        except (ValidationError, ValueError, TypeError):
            return row_type.model_validate({})
    if origin is list and isinstance(value, list):
        return [row(item) for item in value]
    if origin is dict and isinstance(value, dict):
        return {key: row(item) for key, item in value.items() if isinstance(key, str)}
    return None
