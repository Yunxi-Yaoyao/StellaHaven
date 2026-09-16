"""Bounded map snapshots in AppConfig; GET assembly is strictly local/read-only.

WG fingerprints identify interfaces, never cities. A recent handshake is evidence
of a handshake only, NOT a guarantee of data-plane connectivity.
"""
from datetime import datetime, timezone
from ipaddress import ip_address, ip_interface, ip_network
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from app.services.server_status import node_status

TTL = 180
Label = Annotated[str, Field(strict=True, max_length=256)]
Fingerprint = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Latitude = Annotated[float, Field(strict=True, ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, Field(strict=True, ge=-180, le=180, allow_inf_nan=False)]
Counter = Annotated[int, Field(strict=True, ge=0, le=2**64 - 1)]
Prefix = Annotated[str, Field(strict=True, max_length=64)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MapLocationUpdate(StrictModel):
    latitude: Latitude | None
    longitude: Longitude | None
    label: Label | None = None

    @model_validator(mode="after")
    def paired(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must both be set or both be null")
        return self


class Location(StrictModel):
    status: Literal["located", "unknown"]
    source: Literal["nat", "unknown"]
    public_ip: Annotated[str, Field(strict=True, max_length=64)] | None = None
    label: Label | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    reason: Label | None = None


class Peer(StrictModel):
    public_key_id: Fingerprint
    endpoint: Label | None = None
    allowed_ips: Annotated[list[Prefix], Field(max_length=128)] = []
    latest_handshake_at: Annotated[int, Field(strict=True, ge=0, le=253402300799)]
    rx_bytes: Counter
    tx_bytes: Counter

    @field_validator("allowed_ips")
    @classmethod
    def valid_prefixes(cls, value):
        for item in value:
            ip_network(item, strict=False)
        return value


class Interface(StrictModel):
    name: Annotated[str, Field(strict=True, min_length=1, max_length=64)]
    public_key_id: Fingerprint
    addresses: Annotated[list[Prefix], Field(max_length=64)] = []
    peers: Annotated[list[Peer], Field(max_length=256)] = []

    @field_validator("addresses")
    @classmethod
    def valid_addresses(cls, value):
        for item in value:
            ip_interface(item)
        return value


class WireGuard(StrictModel):
    status: Literal["ok", "unavailable", "permission_denied"]
    interfaces: Annotated[list[Interface], Field(max_length=64)] = []

    @model_validator(mode="after")
    def bounded_peers(self):
        if sum(len(i.peers) for i in self.interfaces) > 1024:
            raise ValueError("too many WireGuard peers")
        return self


class Snapshot(StrictModel):
    observed_at: datetime
    location: Location
    wireguard: WireGuard

    @field_validator("observed_at", mode="before")
    @classmethod
    def utc_timestamp(cls, value):
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError("observed_at must be an ISO UTC string")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("observed_at must be UTC")
        return parsed


def validate_snapshot(value):
    """Shared by report validation, persistence and defensive cache reads."""
    import json
    clean = Snapshot.model_validate(value).model_dump(mode="json")
    # The persistence reader is bounded too; never accept a report it would
    # later discard silently. Limit bytes as well as per-list item counts.
    if len(json.dumps(clean, ensure_ascii=False, allow_nan=False).encode()) > 262144:
        raise ValueError("map snapshot exceeds storage limit")
    return clean


def _safe_snapshot(value):
    try:
        return validate_snapshot(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _global_ip(value):
    try:
        ip = ip_address(value)
        return ip if ip.is_global and not ip.is_multicast and not ip.is_unspecified else None
    except (ValueError, TypeError):
        return None


def _node_location(node, snapshot, manual, now):
    location = snapshot["location"] if snapshot else {}
    manual_ip = getattr(node, "public_ip_source", None) == "manual"
    result = dict(id=node.id, name=node.name, status=node_status(node, now),
        latitude=None, longitude=None, location_label=None, location_source="unknown",
        location_reason="no_snapshot", location_observed_at=snapshot["observed_at"] if snapshot else None,
        public_ip=node.public_ip if manual_ip else location.get("public_ip"),
        wireguard_status=snapshot["wireguard"]["status"] if snapshot else "unavailable")
    try:
        manual = MapLocationUpdate.model_validate(manual) if manual else None
    except ValidationError:
        manual = None
    if manual and manual.latitude is not None:
        result.update(latitude=manual.latitude, longitude=manual.longitude,
            location_label=manual.label, location_source="manual", location_reason=None,
            location_observed_at=None)
        return result
    if node.net_type != "public":
        result["location_reason"] = "internal_requires_manual_location"
    elif manual_ip and (not _global_ip(node.public_ip) or
                         _global_ip(node.public_ip) != _global_ip(location.get("public_ip"))):
        result["location_reason"] = "manual_ip_requires_location"
    elif (location.get("status") == "located" and location.get("source") == "nat"
          and _global_ip(location.get("public_ip")) and location.get("latitude") is not None
          and location.get("longitude") is not None):
        result.update(latitude=location["latitude"], longitude=location["longitude"],
            location_label=location.get("label"), location_source="nat", location_reason=None)
    elif snapshot:
        result["location_reason"] = location.get("reason") or "nat_location_unavailable"
    return result


def build_topology(nodes, snapshots, manuals, *, now=None):
    now = now or datetime.now(timezone.utc)
    nodes = [n for n in nodes if n.status != "removed"]
    snapshots = {n.id: _safe_snapshot(snapshots.get(n.id)) for n in nodes}
    result = [_node_location(n, snapshots[n.id], manuals.get(n.id), now) for n in nodes]
    located = sum(n["latitude"] is not None for n in result)
    links = _links(nodes, snapshots, now)
    return dict(generated_at=now.isoformat(), nodes=result, links=links,
                stats=dict(located=located, unknown=len(result) - located, links=len(links)))


def _fresh(node, snapshot, now):
    return bool(snapshot and node_status(node, now) == "online"
        and snapshot["wireguard"]["status"] == "ok"
        and 0 <= (now - datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))).total_seconds() <= TTL)


def _links(nodes, snapshots, now):
    import hashlib
    index = {}
    for node in nodes:
        snapshot = snapshots[node.id]
        if snapshot and snapshot["wireguard"]["status"] == "ok":
            for iface in snapshot["wireguard"]["interfaces"]:
                index.setdefault(iface["public_key_id"], []).append((node, iface))
    links = {}
    for node in sorted(nodes, key=lambda n: n.id):
        snapshot = snapshots[node.id]
        if not snapshot or snapshot["wireguard"]["status"] != "ok":
            continue
        for iface in snapshot["wireguard"]["interfaces"]:
            for peer in iface["peers"]:
                matches = index.get(peer["public_key_id"], [])
                target, target_iface = matches[0] if len(matches) == 1 else (None, None)
                reason = None if target else ("ambiguous_peer_key" if matches else "unmatched_peer")
                if target and target.id == node.id:
                    target, target_iface, reason = None, None, "self_peer"
                local = f'{node.id}:{iface["name"]}:{iface["public_key_id"]}'
                remote = (f'{target.id}:{target_iface["name"]}:{target_iface["public_key_id"]}'
                          if target else f'peer:{peer["public_key_id"]}')
                identity = "|".join(sorted((local, remote)))
                link_id = hashlib.sha256(identity.encode()).hexdigest()
                handshake = peer["latest_handshake_at"]
                if not _fresh(node, snapshot, now) or (target and not _fresh(target, snapshots[target.id], now)):
                    state, state_reason = "unknown", "offline_or_expired_report"
                elif handshake > now.timestamp():
                    state, state_reason = "unknown", "future_handshake"
                else:
                    state = "never" if handshake == 0 else ("recent" if now.timestamp() - handshake <= TTL else "stale")
                    state_reason = None
                link = dict(id=link_id, source=node.id, target=target.id if target else None,
                    source_interface=iface["name"], target_interface=target_iface["name"] if target_iface else None,
                    state=state, latest_handshake_at=handshake, rx_bytes=peer["rx_bytes"], tx_bytes=peer["tx_bytes"],
                    peer_label=target.name if target else f'peer {peer["public_key_id"][:12]}',
                    reason=reason or state_reason)
                if link_id not in links:
                    links[link_id] = link
                elif state == "unknown":
                    # Keep the deterministic source direction and its counters;
                    # a bad reverse observation must not turn into green health.
                    links[link_id].update(state="unknown", reason=state_reason or reason)
    return list(links.values())


# Separate keys prevent a concurrent agent report from replacing manual settings.
# These functions use the existing AppConfig table; no schema migration needed.
def save_snapshot(db, node_id, value):
    import json
    from app.repositories import config as config_repo
    clean = validate_snapshot(value) if value is not None else None
    config_repo.put(db, f"node_map_snapshot:{node_id}", json.dumps(clean, ensure_ascii=False, allow_nan=False))


def _decode(value):
    import json
    try:
        return json.loads(value) if value and len(value) <= 262144 else None
    except (ValueError, TypeError):
        return None


def set_manual_location(db, node_id, data: MapLocationUpdate):
    import json
    from app.repositories import config as config_repo, node as node_repo
    node = node_repo.get_by_id(db, node_id)
    if node is None or node.status == "removed":
        raise ValueError("node not found")
    value = data.model_dump() if data.latitude is not None else None
    config_repo.put(db, f"node_map_manual:{node_id}", json.dumps(value, allow_nan=False))
    snapshot = _safe_snapshot(_decode(config_repo.get(db, f"node_map_snapshot:{node_id}")))
    return _node_location(node, snapshot, value, datetime.now(timezone.utc))


def get_topology(db):
    from app.models.config import AppConfig
    from app.repositories import node as node_repo
    # Same global authenticated node visibility as the existing list route.
    # Page through all visible nodes rather than silently truncating at 100.
    nodes, snapshots, manuals = [], {}, {}
    while True:
        batch = node_repo.list_all(db, skip=len(nodes), limit=100)
        if not batch:
            break
        nodes.extend(batch)
        keys = [f"node_map_{kind}:{n.id}" for n in batch for kind in ("snapshot", "manual")]
        for row in db.query(AppConfig).filter(AppConfig.key.in_(keys)).all():
            prefix, node_id = row.key.split(":", 1)
            target = snapshots if prefix == "node_map_snapshot" else manuals
            target[int(node_id)] = _decode(row.value)
        if len(batch) < 100:
            break
    return build_topology(nodes, snapshots, manuals)
